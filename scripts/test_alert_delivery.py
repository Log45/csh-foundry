"""Real Prometheus rule evaluation and Alertmanager delivery to a disposable local receiver."""

import json
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

PROMETHEUS = (
    "prom/prometheus@sha256:49214755b6153f90a597adcbff0252cc61069f8ab69ce8411285cd4a560e8038"
)
ALERTMANAGER = (
    "prom/alertmanager@sha256:27c475db5fb156cab31d5c18a4251ac7ed567746a2483ff264516437a39b15ba"
)


def main() -> None:
    events: list[dict] = []
    healthy = False

    class Receiver(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200 if healthy else 503)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.end_headers()
            self.wfile.write(b"# local metrics target\n")

        def do_POST(self) -> None:
            events.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args) -> None:
            pass

    receiver = ThreadingHTTPServer(("0.0.0.0", 0), Receiver)
    threading.Thread(target=receiver.serve_forever, daemon=True).start()
    port = receiver.server_address[1]
    containers: list[str] = []
    evidence = Path("docs/architecture/evidence/phase-10-closure/alerts.json")
    with tempfile.TemporaryDirectory(prefix="foundry-alerts-") as directory:
        root = Path(directory)
        root.chmod(0o755)
        (root / "rules.yaml").write_bytes(
            Path("infrastructure/monitoring/alerts.yaml").read_bytes()
        )
        (root / "alertmanager.yaml").write_text(f"""global:
  resolve_timeout: 5s
route:
  receiver: local
  group_wait: 1s
  group_interval: 1s
  repeat_interval: 10m
receivers:
  - name: local
    webhook_configs:
      - url: http://host.docker.internal:{port}/alerts
        send_resolved: true
""")
        success = False
        try:

            def start(image: str, container_port: str, args: list[str]) -> tuple[str, str]:
                container = subprocess.check_output(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "-d",
                        "-p",
                        f"127.0.0.1::{container_port}",
                        *(
                            ["--add-host=host.docker.internal:host-gateway"]
                            if sys.platform != "darwin"
                            else []
                        ),
                        "-v",
                        f"{root}:/config:ro",
                        image,
                        *args,
                    ],
                    text=True,
                ).strip()
                containers.append(container)
                binding = subprocess.check_output(
                    ["docker", "port", container, container_port], text=True
                )
                return container, binding.strip().rsplit(":", 1)[1]

            _, alert_port = start(ALERTMANAGER, "9093", ["--config.file=/config/alertmanager.yaml"])
            (root / "prometheus.yaml").write_text(f"""global:
  scrape_interval: 1s
  evaluation_interval: 1s
rule_files: [/config/rules.yaml]
alerting:
  alertmanagers:
    - static_configs:
        - targets: [host.docker.internal:{alert_port}]
scrape_configs:
  - job_name: foundry-api
    static_configs:
      - targets: [host.docker.internal:{port}]
""")
            subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--entrypoint=/bin/promtool",
                    "-v",
                    f"{root}:/config:ro",
                    PROMETHEUS,
                    "check",
                    "rules",
                    "/config/rules.yaml",
                ],
                check=True,
            )
            _, prom_port = start(PROMETHEUS, "9090", ["--config.file=/config/prometheus.yaml"])
            deadline = time.monotonic() + 210
            while not any(e["status"] == "firing" for e in events):
                if time.monotonic() > deadline:
                    raise RuntimeError("No firing webhook within 210 seconds")
                time.sleep(2)
            rules = httpx.get(f"http://127.0.0.1:{prom_port}/api/v1/rules", timeout=5).json()
            assert any(
                r.get("state") == "firing" for g in rules["data"]["groups"] for r in g["rules"]
            )
            healthy = True
            deadline = time.monotonic() + 150
            while not any(e["status"] == "resolved" for e in events):
                if time.monotonic() > deadline:
                    raise RuntimeError("No resolved webhook within 150 seconds")
                time.sleep(2)
            evidence.write_text(
                json.dumps(
                    {
                        "result": "PASS",
                        "rule": "FoundryAPIUnavailable",
                        "rules": "infrastructure/monitoring/alerts.yaml (unchanged)",
                        "prometheus": PROMETHEUS,
                        "alertmanager": ALERTMANAGER,
                        "events": events,
                        "production_delivery": (
                            "NOT RUN; approved receiver and operational owner unavailable"
                        ),
                        "scope": (
                            "Real 2-minute production rule; local simulated unavailable "
                            "scrape target; no deployed API target or host/WAL/backup alerts"
                        ),
                    },
                    indent=2,
                )
                + "\n"
            )
            success = True
            print("PASS rule evaluation, firing, local webhook delivery and resolution")
        finally:
            if not locals().get("success", False):
                diagnostics = {}
                if "prom_port" in locals():
                    for endpoint in ("targets", "rules"):
                        try:
                            diagnostics[endpoint] = httpx.get(
                                f"http://127.0.0.1:{prom_port}/api/v1/{endpoint}", timeout=5
                            ).json()
                        except httpx.HTTPError:
                            pass
                evidence.write_text(
                    json.dumps(
                        {
                            "result": "FAIL",
                            "events": events,
                            "diagnostics": diagnostics,
                            "production_delivery": "NOT RUN",
                        },
                        indent=2,
                    )
                    + "\n"
                )
            receiver.shutdown()
            for container in reversed(containers):
                subprocess.run(["docker", "stop", container], capture_output=True, check=True)


if __name__ == "__main__":
    main()
