"""Phase 21 validation with recorded host/PostgreSQL clocks and process-scoped idle prevention.

No timeout, lease, assertion, TLS/signature check or system clock is changed. All integration work
uses existing disposable-schema/MinIO harnesses. Never treats skipped or interrupted work as PASS.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from ontology_platform.config import get_settings
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=["focused", "full", "large", "browser", "quality"])
parser.add_argument("--evidence", required=True)
args = parser.parse_args()
directory = ROOT / args.evidence
directory.mkdir(parents=True, exist_ok=True)
log = directory / (args.mode + ".txt")
if log.exists():
    raise SystemExit("Refusing to overwrite validation evidence")
command = ["uv", "run", "python", "scripts/validate_phase15.py"]
if args.mode == "full":
    command += ["--full"]
elif args.mode == "browser":
    command += ["--browser-only"]
elif args.mode == "large":
    command += ["--pytest-file", "services/api/tests/test_pipeline_dag_large.py"]
elif args.mode == "quality":
    command = [
        "uv",
        "run",
        "python",
        "scripts/validate_phase19.py",
        "--quality-only",
        "--evidence",
        str(directory / "quality"),
    ]
else:
    for name in [
        "test_observability",
        "test_pipeline_dag",
        "test_pipeline_graphs",
        "test_applications",
        "test_mappings",
        "test_media_functions_automations",
        "test_security_workflows",
    ]:
        command += ["--pytest-file", f"services/api/tests/{name}.py"]
stop = threading.Event()
clock_log = directory / (args.mode + "-clocks.jsonl")
engine = create_engine(get_settings().database_url.get_secret_value(), hide_parameters=True)


def observe() -> None:
    with clock_log.open("x") as output:
        while not stop.is_set():
            before = datetime.now(UTC)
            try:
                with engine.connect() as connection:
                    server = connection.scalar(text("SELECT clock_timestamp()"))
                after = datetime.now(UTC)
                midpoint = before + (after - before) / 2
                entry = {
                    "host": midpoint.isoformat(),
                    "database": server.isoformat(),
                    "offset_seconds": (midpoint - server).total_seconds(),
                }
            except Exception:
                entry = {"host": before.isoformat(), "database": "UNAVAILABLE"}
            output.write(json.dumps(entry) + "\n")
            output.flush()
            stop.wait(5)


awake = (
    subprocess.Popen(["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())])
    if sys.platform == "darwin"
    else None
)
thread = threading.Thread(target=observe, daemon=True)
thread.start()
try:
    started = time.monotonic()
    env = os.environ | {"PYTEST_ADDOPTS": "-s"} if args.mode == "large" else os.environ.copy()
    with log.open("x") as output:
        process = subprocess.Popen(
            command, cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT
        )
        try:
            code = process.wait()
        except BaseException:
            process.send_signal(signal.SIGINT)
            process.wait(timeout=45)
            raise
    result = {
        "mode": args.mode,
        "command": command,
        "result": "PASS" if code == 0 else "FAIL",
        "exit_code": code,
        "seconds": time.monotonic() - started,
        "evidence": str(log),
    }
    (directory / (args.mode + "-result.json")).write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
finally:
    stop.set()
    thread.join(timeout=10)
    engine.dispose()
    if awake is not None:
        awake.terminate()
        awake.wait(timeout=5)
raise SystemExit(code)
