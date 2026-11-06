"""Phase 19 local acceptance runner; only disposable integration environments."""

import argparse
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--evidence", default="docs/development/evidence/phase-19/final")
parser.add_argument("--quality-only", action="store_true")
args = parser.parse_args()
node_version = subprocess.check_output(["node", "--version"], text=True).strip()
if int(node_version.removeprefix("v").split(".")[0]) < 22:
    raise RuntimeError("Node >=22 is required; select a supported runtime before validation")
evidence = ROOT / args.evidence
evidence.mkdir(parents=True, exist_ok=True)
checks = [
    ("python-quality", ["uv", "run", "ruff", "check", "."]),
    ("python-format", ["uv", "run", "ruff", "format", "--check", "."]),
    ("mypy", ["uv", "run", "mypy"]),
    ("openapi-export", ["uv", "run", "python", "scripts/export_openapi.py"]),
    ("generated", ["npm", "run", "check:generated"]),
    ("sdk-format", ["npm", "run", "format:check"]),
    ("sdk-build", ["npm", "run", "build"]),
    ("sdk-typecheck", ["npm", "run", "typecheck"]),
    ("sdk-tests", ["npm", "test"]),
    ("sdk-consumer", ["npm", "run", "test:consumer"]),
    ("studio-format", ["npm", "run", "format:check", "--prefix", "apps/studio"]),
    ("studio-typecheck", ["npm", "run", "typecheck", "--prefix", "apps/studio"]),
    ("studio-tests", ["npm", "test", "--prefix", "apps/studio"]),
    ("studio-build", ["npm", "run", "build", "--prefix", "apps/studio"]),
]
if not args.quality_only:
    checks.append(
        (
            "full-platform-browser",
            ["uv", "run", "python", "scripts/validate_phase15.py", "--full", "--browser"],
        )
    )
results = {}
environment = os.environ.copy()
# Use a supported Node already supplied by the operator, never silently install a runtime.
for label, command in checks:
    path = evidence / f"{label}.txt"
    if path.exists():
        raise RuntimeError(f"Refusing to overwrite evidence: {path}")
    print(f"RUN {label}", flush=True)
    with path.open("w") as log:
        outcome = subprocess.run(
            command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT
        )
    results[label] = {
        "command": command,
        "exit_code": outcome.returncode,
        "result": "PASS" if outcome.returncode == 0 else "FAIL",
    }
    (evidence / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(f"{results[label]['result']} {label}", flush=True)
raise SystemExit(0 if all(v["result"] == "PASS" for v in results.values()) else 1)
