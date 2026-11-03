"""Bounded correlated diagnostics for an already-owned disposable acceptance project."""

import json
import subprocess
import threading
import time

import httpx
from sqlalchemy import text


class Sampler:
    def __init__(self, acceptance):
        self.acceptance = acceptance
        self.stop = threading.Event()
        self.threads = []
        self.samples = []
        self.errors = []
        self.events = None

    def __enter__(self):
        a = self.acceptance
        self.containers = a.dc("ps", "-q").split()
        identities = json.loads(a.run(["docker", "inspect", *self.containers]))
        self.names = {item["Id"]: item["Name"] for item in identities}
        context = json.loads(a.run(["docker", "context", "inspect"]))[0]
        self.socket = context["Endpoints"]["docker"]["Host"].removeprefix("unix://")
        # Strict label selection means only this run's resources can enter the event stream.
        from phase10_span_capture import SpanCapture

        self.capture = SpanCapture(self.containers, a.output / "request-spans.jsonl")
        self.event_file = (a.output / "container-events.jsonl").open("w")
        self.events = subprocess.Popen(
            [
                "docker",
                "events",
                "--filter",
                "label=com.docker.compose.project=" + a.project,
                "--format",
                "{{json .}}",
            ],
            stdout=self.event_file,
            stderr=subprocess.DEVNULL,
        )
        for target in (self.container_samples, self.database_samples, self.host_samples):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self.threads.append(thread)
        return self

    def container_samples(self):
        with httpx.Client(transport=httpx.HTTPTransport(uds=self.socket), timeout=3) as client:
            while not self.stop.is_set() and len(self.samples) < 50000:
                started = time.monotonic()
                for container in self.containers:
                    try:
                        response = client.get(
                            f"http://docker/containers/{container}/stats?stream=false&one-shot=true"
                        )
                        response.raise_for_status()
                        raw = response.json()
                        self.samples.append(
                            {
                                "kind": "container",
                                "epoch": time.time(),
                                "name": self.names[container],
                                "container_id": container,
                                "http_status": response.status_code,
                                "read": raw.get("read"),
                                "cpu": raw.get("cpu_stats"),
                                "memory": raw.get("memory_stats"),
                                "pids": raw.get("pids_stats"),
                            }
                        )
                    except Exception as error:
                        self.errors.append(type(error).__name__)
                self.stop.wait(max(0, 0.25 - (time.monotonic() - started)))

    def host_samples(self):
        while not self.stop.is_set() and len(self.samples) < 50000:
            try:
                result = subprocess.run(
                    ["memory_pressure", "-Q"], capture_output=True, text=True, timeout=2
                )
                # Aggregate macOS pressure only; no process names, paths or page contents.
                self.samples.append(
                    {
                        "kind": "host_memory_pressure",
                        "epoch": time.time(),
                        "exit_code": result.returncode,
                        "summary": result.stdout,
                    }
                )
            except Exception as error:
                self.errors.append(type(error).__name__)
            self.stop.wait(1)

    def database_samples(self):
        with self.acceptance.engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as sql:
            while not self.stop.is_set() and len(self.samples) < 50000:
                try:
                    row = (
                        sql.execute(
                            text("""
                        SELECT clock_timestamp() AS database_time,
                          (SELECT count(*) FROM pg_stat_activity) AS total_connections,
                          (SELECT count(*) FROM pg_stat_activity WHERE state='active') AS active,
                          (SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock')
                            AS lock_waiters,
                          (SELECT coalesce(max(extract(epoch FROM clock_timestamp()-query_start)),0)
                            FROM pg_stat_activity WHERE state='active' AND pid<>pg_backend_pid())
                            AS longest_active_seconds,
                          (SELECT wal_bytes FROM pg_stat_wal) AS wal_bytes,
                          pg_database_size(current_database()) AS database_bytes,
                          (SELECT coalesce(max(extract(epoch FROM clock_timestamp()-created_at)),0)
                           FROM (SELECT created_at FROM ingestion_runs WHERE status='PENDING'
                             UNION ALL SELECT created_at FROM semantic_jobs
                             WHERE status='PENDING') q)
                            AS oldest_pending_seconds
                    """)
                        )
                        .mappings()
                        .one()
                    )
                    self.samples.append({"kind": "database", "epoch": time.time(), **dict(row)})
                except Exception as error:
                    self.errors.append(type(error).__name__)
                self.stop.wait(0.1)

    def __exit__(self, *args):
        self.stop.set()
        for thread in self.threads:
            thread.join(timeout=10)
        self.events.terminate()
        self.events.wait(timeout=10)
        self.event_file.close()
        self.capture.close()
        (self.acceptance.output / "resource-samples.json").write_text(
            json.dumps(
                {
                    "container_interval_seconds": 0.25,
                    "database_interval_seconds": 0.1,
                    "samples": self.samples,
                    "errors": self.errors,
                    "scope": "Docker VM counters; macOS memory pressure not represented",
                },
                indent=2,
                default=str,
            )
            + "\n"
        )


def correlate(acceptance):
    """Join allowlisted log records by trace ID, preserving every failed/slow sample."""
    a = acceptance
    logs = a.dc("logs", "--no-color", "api", "studio", "ingress")
    retained = a.output / "request-spans.jsonl"
    if retained.exists():
        logs += "\n" + retained.read_text()
    spans = {}
    seen = set()
    for line in logs.splitlines():
        try:
            record = json.loads(line[line.index("{") :])
        except (ValueError, json.JSONDecodeError):
            continue
        if record.get("event") not in {"request_span", "bff_span", "ingress_status"}:
            continue
        trace = record.get("trace_id")
        if trace and trace.startswith("00-"):
            trace = trace.split("-")[1]
        if not trace:
            continue
        identity = (trace, json.dumps(record, sort_keys=True))
        if identity in seen:
            continue
        seen.add(identity)
        spans.setdefault(trace, []).append(record)
    joined = []
    for file in a.output.glob("*.json"):
        data = json.loads(file.read_text())
        if not isinstance(data, dict):
            continue
        for measurement in data.get("measurements", []):
            for sample in measurement["samples"]:
                joined.append(
                    {
                        "run": file.name,
                        "concurrency": measurement["concurrency"],
                        **sample,
                        "spans": spans.get(sample.get("trace_id"), []),
                    }
                )
    (a.output / "correlated-requests.json").write_text(
        json.dumps(
            {
                "diagnostic_threshold_ms": 250,
                "requests": joined,
                "slow_requests": sum(s["seconds"] >= 0.25 for s in joined),
                "limitations": [
                    "SQL durations include server waits and network",
                    "BFF fetch stages end at headers",
                    "No per-request GC, lock wait attribution or macOS scheduler trace",
                ],
            },
            indent=2,
        )
        + "\n"
    )
