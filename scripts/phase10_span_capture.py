"""Retain bounded, allowlisted spans before disposable replica recreation deletes logs."""

import argparse
import json
import re
import subprocess
import threading
from pathlib import Path

ALLOWED = {
    "event",
    "timestamp",
    "trace_id",
    "span_id",
    "route",
    "method",
    "status",
    "duration_seconds",
    "timings",
    "duration_ms",
    "stages",
    "duration",
    "epoch",
    "upstream_connect",
    "upstream_header",
    "upstream_response",
}


class SpanCapture:
    def __init__(self, containers: list[str], output: Path):
        self.output = output.open("w")
        self.lock = threading.Lock()
        self.count = 0
        self.processes = []
        self.threads = []
        for container in containers:
            process = subprocess.Popen(
                ["docker", "logs", "--follow", container],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.processes.append(process)
            thread = threading.Thread(target=self.consume, args=(process,), daemon=True)
            thread.start()
            self.threads.append(thread)

    def consume(self, process):
        for line in process.stdout:
            try:
                record = json.loads(line[line.index("{") :])
            except (ValueError, json.JSONDecodeError):
                continue
            if record.get("event") not in {"request_span", "bff_span", "ingress_status"}:
                continue
            with self.lock:
                if self.count >= 20000:
                    continue
                self.output.write(
                    json.dumps({k: v for k, v in record.items() if k in ALLOWED}) + "\n"
                )
                self.output.flush()
                self.count += 1

    def close(self):
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
        for thread in self.threads:
            thread.join(timeout=5)
        self.output.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"foundry-accept-[0-9a-f]{8}", args.project):
        raise ValueError("Disposable acceptance project required")
    containers = subprocess.check_output(
        [
            "docker",
            "ps",
            "-q",
            "--filter",
            "label=com.docker.compose.project=" + args.project,
        ],
        text=True,
    ).split()
    if not containers:
        raise ValueError("No owned containers")
    capture = SpanCapture(containers, args.output)
    try:
        for process in capture.processes:
            process.wait()
    finally:
        capture.close()


if __name__ == "__main__":
    main()
