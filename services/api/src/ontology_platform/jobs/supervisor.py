"""One bounded child at a time. Leases/fencing remain owned by existing job services."""

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

log = logging.getLogger("foundry.worker")


def run_child(command: list[str], stop: threading.Event, deadline: float = 120) -> int:
    import time

    process = subprocess.Popen(command, start_new_session=True)
    started = time.monotonic()
    try:
        while process.poll() is None:
            if stop.wait(0.25) or time.monotonic() - started >= deadline:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                return 124
        return process.returncode
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("ingestion", "semantic", "outbox"), required=True)
    parser.add_argument("--ontology", required=True)
    parser.add_argument("--deadline", type=float, default=120)
    args = parser.parse_args()
    if not 1 <= args.deadline <= 600:
        parser.error("Deadline must be 1–600 seconds")
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    failures = 0
    module = "ontology_platform." + (args.kind if args.kind != "outbox" else "jobs.outbox")
    while not stop.is_set():
        code = run_child(
            [sys.executable, "-m", module, "--ontology", args.ontology], stop, args.deadline
        )
        failures = min(failures + 1, 6) if code else 0
        # Liveness is local process progress, never an assertion of successful authorization.
        Path("/tmp/foundry-worker-heartbeat").touch()
        log.info(
            json.dumps(
                {
                    "event": "worker_cycle",
                    "kind": args.kind,
                    "status": code,
                    "consecutive_failures": failures,
                }
            )
        )
        stop.wait(min(60, 2**failures) if failures else 2)


if __name__ == "__main__":
    main()
