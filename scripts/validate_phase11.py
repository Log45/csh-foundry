"""Full Phase 11 regression in a disposable schema; never migrate developer data."""

import os
import subprocess
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from ontology_platform.config import get_settings
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parents[1]
url = os.environ.get("TEST_DATABASE_URL") or get_settings().database_url.get_secret_value()
schema = "test_phase11_suite_" + uuid4().hex
admin = create_engine(url)
with admin.begin() as connection:
    connection.execute(text(f'CREATE SCHEMA "{schema}"'))
isolated = make_url(url).update_query_dict({"options": f"-csearch_path={schema}"})
env = os.environ | {
    "TEST_DATABASE_URL": isolated.render_as_string(hide_password=False),
    "FOUNDRY_DATABASE_SCHEMA": schema,
}
binary = Path(env.get("OPEN_ONTOLOGIES_BIN", root / ".external/open-ontologies"))
if binary.is_file():
    env["OPEN_ONTOLOGIES_BIN"] = str(binary.resolve())
engine = create_engine(isolated)
try:
    config = Config(str(root / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        command.check(config)
    subprocess.run(["uv", "run", "pytest", "-ra", "--tb=short"], cwd=root, env=env, check=True)
finally:
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()
