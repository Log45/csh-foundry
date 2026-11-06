"""Reproducible Phase 20 checks; existing disposable-schema/MinIO/browser harnesses only."""

import argparse
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=["focused", "large", "full", "browser", "quality"])
parser.add_argument("--evidence", default="docs/development/evidence/phase-20/recheck")
args = parser.parse_args()
evidence = ROOT / args.evidence
evidence.mkdir(parents=True, exist_ok=True)
log = evidence / (args.mode + ".txt")
if log.exists():
    raise RuntimeError(f"Refusing to overwrite evidence: {log}")
command = ["uv", "run", "python", "scripts/validate_phase15.py"]
environment = os.environ.copy()
if args.mode == "quality":
    command = [
        "uv",
        "run",
        "python",
        "scripts/validate_phase19.py",
        "--quality-only",
        "--evidence",
        str(evidence / "quality"),
    ]
elif args.mode == "full":
    command += ["--full"]
elif args.mode == "browser":
    command += ["--browser-only"]
elif args.mode == "large":
    command += ["--pytest-file", "services/api/tests/test_pipeline_dag_large.py"]
    environment["PYTEST_ADDOPTS"] = "-s"
else:
    for file in ["test_pipeline_dag.py", "test_pipeline_graphs.py", "test_execution.py"]:
        command += ["--pytest-file", "services/api/tests/" + file]
with log.open("w") as output:
    result = subprocess.run(
        command, cwd=ROOT, env=environment, stdout=output, stderr=subprocess.STDOUT
    )
print(("PASS" if result.returncode == 0 else "FAIL") + ": " + str(log))
raise SystemExit(result.returncode)
