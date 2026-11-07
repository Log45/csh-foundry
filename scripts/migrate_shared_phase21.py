"""Controlled development migration using the existing root Alembic configuration.

Requires the recorded logical backup/restore rehearsal and stopped Foundry API/worker writers.
Does not implement another migration runner or automatically perform recovery.
"""

import hashlib
import json
import subprocess
from pathlib import Path

from alembic import command
from alembic.config import Config
from ontology_platform.config import get_settings
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "artifacts/phase21"
assert json.loads((EVIDENCE / "backup-restore.json").read_text())["result"] == "PASS"
url = make_url(get_settings().database_url.get_secret_value())
assert url.database == "foundry" and url.username == "foundry"
assert url.host in {"127.0.0.1", "localhost"} and url.port == 55432
assert get_settings().database_schema == "public"
for name in ["csh-foundry-api-1", "csh-foundry-worker-1"]:
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", name],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0 or result.stdout.strip() == "false", (
        "Stop only Foundry writers first"
    )
engine = create_engine(url, hide_parameters=True)
TABLES = [
    "projects",
    "project_members",
    "folders",
    "platform_resources",
    "resource_shares",
    "artifact_versions",
    "dataset_versions",
    "pipeline_definitions",
    "execution_jobs",
    "ontologies",
    "ontology_versions",
    "objects",
    "object_links",
    "application_versions",
    "action_audit_events",
    "authorization_audit",
    "materialization_records",
]


def snapshot(connection):
    result = {}
    for table in TABLES:
        if not connection.scalar(text("SELECT to_regclass(:table)"), {"table": "public." + table}):
            continue
        # Fixed allowlisted identifiers; streaming hashes, no user data in evidence or memory.
        digest = hashlib.sha256()
        count = 0
        for row in connection.execute(
            text(f"SELECT to_jsonb(t)::text FROM public.{table} t ORDER BY to_jsonb(t)::text")
        ):
            digest.update(row[0].encode())
            digest.update(b"\n")
            count += 1
        result[table] = {"rows": count, "sha256": digest.hexdigest()}
    return result


try:
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL search_path=public"))
        assert connection.scalar(text("SELECT current_database()")) == "foundry"
        current = connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert current == "0026_pipeline_dag", "Unexpected revision; repeat preflight"
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM execution_jobs WHERE "
                    "state IN ('QUEUED','ADMITTED','RUNNING','CANCELLING')"
                )
            )
            == 0
        )
        before = snapshot(connection)
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["connection"] = connection
        command.upgrade(config, "0027_lineage_observability")
        command.check(config)
        assert snapshot(connection) == before, (
            "Canonical data changed; migration transaction will roll back"
        )
        final = connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert final == "0027_lineage_observability"
    (EVIDENCE / "shared-migration.json").write_text(
        json.dumps(
            {
                "before_revision": current,
                "after_revision": final,
                "target": {
                    "host": url.host,
                    "port": url.port,
                    "database": url.database,
                    "user": url.username,
                    "schema": "public",
                },
                "preserved_tables": before,
                "drift": "PASS",
                "backup_restore": "PASS",
                "result": "PASS",
            },
            indent=2,
        )
    )
    print("PASS exact shared forward migration, canonical data fingerprints and migration drift")
finally:
    engine.dispose()
