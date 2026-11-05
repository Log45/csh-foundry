"""Complete local Phase 16 regression; owned schemas/MinIO only, no shared migrations.

Requires built-in local services, pinned semantic engine, Node and browser dependencies.
Run with Node >= dependencies' engine requirements on PATH. No checks are silently skipped.
"""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/development/evidence/phase-16"
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
        "full-platform-browser",
        ["uv", "run", "python", "scripts/validate_phase15.py", "--full", "--browser"],
    ),
    ("example-browser", ["uv", "run", "python", "scripts/validate_phase15.py", "--browser-only"]),
]
results = {}
for label, command in checks:
    env = os.environ.copy()
    if label == "example-browser":
        env.update(
            {
                "STUDIO_E2E_APP": "apps/sdk-example",
                "STUDIO_E2E_PORT": "3200",
                "STUDIO_E2E_DURABLE": "false",
                "STUDIO_E2E_DIRECTORY": str(ROOT / "artifacts/phase16-example-final"),
            }
        )
    # Preserve earlier evidence: choose a new invocation directory for another complete run.
    path = EVIDENCE / (label + ".txt")
    if path.exists():
        raise RuntimeError(f"Evidence already exists: {path}; archive it before an explicit rerun")
    print(f"RUN {label}", flush=True)
    with path.open("w") as log:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    results[label] = {
        "result": "PASS" if result.returncode == 0 else "FAIL",
        "exit_code": result.returncode,
        "command": command,
    }
    (EVIDENCE / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(f"{results[label]['result']} {label}", flush=True)
raise SystemExit(0 if all(r["result"] == "PASS" for r in results.values()) else 1)
