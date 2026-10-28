"""Run checks with explicit integrations; fail if configured prerequisites are absent."""

import os
import subprocess
from pathlib import Path

from ontology_platform.config import get_settings

root = Path(__file__).resolve().parents[1]
if not os.environ.get("TEST_DATABASE_URL"):
    os.environ["TEST_DATABASE_URL"] = get_settings().database_url.get_secret_value()
binary = Path(os.environ.get("OPEN_ONTOLOGIES_BIN", root / ".external/open-ontologies"))
if not binary.is_file():
    raise SystemExit("NOT RUN: install the pinned engine with scripts/install_semantic_engine.py")
os.environ["OPEN_ONTOLOGIES_BIN"] = str(binary.resolve())
checks = [
    ["uv", "run", "ruff", "check", "."],
    ["uv", "run", "ruff", "format", "--check", "."],
    ["uv", "run", "mypy"],
    ["uv", "run", "alembic", "check"],
    ["uv", "run", "pytest", "-ra", "--tb=short"],
]
for command in checks:
    subprocess.run(command, cwd=root, check=True)
