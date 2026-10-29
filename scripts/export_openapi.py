"""Export actual FastAPI contracts for Studio; no live service or credentials required."""

import json
from pathlib import Path

from ontology_platform.main import create_app

root = Path(__file__).resolve().parents[1]
(root / "apps/studio/lib/openapi.json").write_text(
    json.dumps(create_app().openapi(), indent=2) + "\n"
)
