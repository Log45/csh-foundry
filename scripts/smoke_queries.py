"""Actual Uvicorn/HTTP Phase 2 smoke against a disposable migrated PostgreSQL schema."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api/tests"))
from ontology_platform.config import get_settings  # noqa: E402
from test_phase1 import active, database, make_world  # noqa: E402
from test_queries import load_manufacturing  # noqa: E402

os.environ.setdefault("TEST_DATABASE_URL", get_settings().database_url.get_secret_value())
fixture = database.__wrapped__()
engine, sessions, url = next(fixture)
try:
    world = make_world((engine, sessions, url))
    active(world)
    load_manufacturing(world)
    with engine.connect() as connection:
        schema = connection.exec_driver_sql("SELECT current_schema()").scalar()
    with socket.socket() as address:
        address.bind(("127.0.0.1", 0))
        port = address.getsockname()[1]
    environment = dict(os.environ)
    environment.update(
        FOUNDRY_DATABASE_URL=url,
        FOUNDRY_TRUSTED_LOCAL_IDENTITY="true",
        FOUNDRY_LOCAL_TENANT_ID=str(world.actor.tenant_id),
        FOUNDRY_LOCAL_PRINCIPAL_ID=world.actor.principal_id,
        SMOKE_SCHEMA=schema,
    )
    with tempfile.TemporaryDirectory(prefix="csh-query-smoke-") as directory:
        Path(directory, "query_smoke.py").write_text("""
import os,re
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from ontology_platform.main import create_app
from ontology_platform.config import get_settings

def create():
    schema=os.environ["SMOKE_SCHEMA"]
    assert re.fullmatch(r"test_phase1_[a-f0-9]{32}",schema)
    app=create_app()
    engine=create_engine(get_settings().database_url.get_secret_value(),
        connect_args={"options":f"-c search_path={schema} -c statement_timeout=3000"})
    app.state.sessions=sessionmaker(engine,expire_on_commit=False)
    return app
""")
        process = subprocess.Popen(
            [
                "uv",
                "run",
                "uvicorn",
                "query_smoke:create",
                "--factory",
                "--app-dir",
                directory,
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        checks = []

        def call(path, payload=None):
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}" + path,
                data=json.dumps(payload).encode() if payload is not None else None,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                assert response.status == 200
                return json.load(response)

        try:
            for _ in range(80):
                if process.poll() is not None:
                    raise RuntimeError("Uvicorn did not start")
                try:
                    if call("/api/v1/tenant")["id"] == str(world.actor.tenant_id):
                        break
                except (OSError, urllib.error.HTTPError):
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("Matching smoke server unavailable")
            assert call("/health/live")["status"] == "ok"
            assert call("/health/ready")["status"] == "ready"
            assert (
                "/api/v1/ontologies/{ontology_id}/aggregate"
                in call("/api/v1/openapi.json")["paths"]
            )
            checks.append("PASS host Uvicorn liveness/readiness/OpenAPI and trusted tenant")
            base = f"/api/v1/ontologies/{world.definition.id}"
            body = {"object_type": "Machine", "select": ["machineId"], "limit": 1}
            first = call(base + "/objects/Machine/query", body)
            second = call(base + "/objects/Machine/query", body | {"cursor": first["next_cursor"]})
            assert (
                first["items"][0]["object_id"] == "MCH-001"
                and second["items"][0]["object_id"] == "MCH-002"
            )
            checks.append("PASS POST query / signed cursor continuation")
            assert call(base + "/object-sets/query", body)["items"][0]["object_id"] == "MCH-001"
            traversal = call(
                base + "/traverse",
                {
                    "object_type": "Factory",
                    "filter": {"property": "factoryId", "operator": "eq", "value": "FAC-001"},
                    "traverse": [{"link": "containsMachine"}],
                },
            )
            assert len(traversal["items"]) == 4
            checks.append("PASS POST object-set and inverse traversal")
            aggregate = call(
                base + "/aggregate",
                {"object_type": "Machine", "metrics": [{"name": "n", "operator": "count"}]},
            )
            assert aggregate["groups"][0]["values"]["n"]["value"] == 20
            checks.append("PASS POST aggregate count")
        finally:
            process.terminate()
            output = process.communicate(timeout=10)[0]
            path = ROOT / "docs/architecture/evidence/phase-2/http-smoke.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(checks) + "\n" + output)
            print("\n".join(checks))
finally:
    try:
        next(fixture)
    except StopIteration:
        pass
