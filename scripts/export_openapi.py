"""Export actual FastAPI contracts for Studio; no live service or credentials required."""

import argparse
import json
import os
from pathlib import Path

from ontology_platform.config import Settings
from ontology_platform.main import create_app
from pydantic import SecretStr

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, default=root / "apps/studio/lib/openapi.json")
args = parser.parse_args()
# Schema construction never enters the application's lifespan or connects to this URL.
# Use explicit offline settings rather than requiring a developer .env on clean runners.
os.environ["FOUNDRY_ARTIFACT_BACKEND"] = "disabled"
os.environ.pop("FOUNDRY_SECRETS_DIRECTORY", None)
settings = Settings(
    database_url=SecretStr("postgresql+psycopg://schema@127.0.0.1:1/schema"),
    environment="development",
    auth_mode="disabled",
    _env_file=None,
    _secrets_dir=None,
)
args.output.write_text(json.dumps(create_app(settings).openapi(), indent=2) + "\n")
