"""Complete local Phase 18 validation; disposable schemas and private MinIO only."""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/development/evidence/phase-18/final"
EVIDENCE.mkdir(parents=True, exist_ok=True)

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
    (
        "focused-real-services",
        [
            "uv",
            "run",
            "python",
            "scripts/validate_phase15.py",
            "--pytest-file",
            "services/api/tests/test_pipeline_graphs.py",
        ],
    ),
    (
        "full-platform-browser",
        ["uv", "run", "python", "scripts/validate_phase15.py", "--full", "--browser"],
    ),
]

results: dict[str, dict[str, object]] = {}
for label, command in checks:
    environment = os.environ.copy()
    environment["PATH"] = "/Users/log/.nvm/versions/node/v26.7.0/bin:" + environment["PATH"]
    if label == "full-platform-browser":
        environment["STUDIO_E2E_DIRECTORY"] = str(ROOT / "artifacts/phase18-final-browser")
    path = EVIDENCE / f"{label}.txt"
    if path.exists():
        raise RuntimeError(f"Evidence already exists: {path}")
    print(f"RUN {label}", flush=True)
    with path.open("w") as log:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    results[label] = {
        "result": "PASS" if result.returncode == 0 else "FAIL",
        "exit_code": result.returncode,
        "command": command,
    }
    (EVIDENCE / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(f"{results[label]['result']} {label}", flush=True)

raise SystemExit(0 if all(item["result"] == "PASS" for item in results.values()) else 1)
