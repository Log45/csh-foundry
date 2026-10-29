"""Actual host HTTP source/mapping/run/query/action/reconciliation smoke."""

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
from ontology_platform.db.models import IngestionMapping  # noqa: E402
from test_ingestion import FILES, setup  # noqa: E402
from test_phase1 import database  # noqa: E402

os.environ.setdefault("TEST_DATABASE_URL", get_settings().database_url.get_secret_value())
fixture = database.__wrapped__()
engine, sessions, url = next(fixture)
checks = []
try:
    with tempfile.TemporaryDirectory(prefix="ingestion-http-") as directory:
        root = Path(directory)
        world, service, worker = setup((engine, sessions, url), root)
        with engine.connect() as connection:
            schema = connection.exec_driver_sql("SELECT current_schema()").scalar()
        with socket.socket() as address:
            address.bind(("127.0.0.1", 0))
            port = address.getsockname()[1]
        env = dict(
            os.environ,
            FOUNDRY_DATABASE_URL=url,
            FOUNDRY_TRUSTED_LOCAL_IDENTITY="true",
            FOUNDRY_LOCAL_TENANT_ID=str(world.actor.tenant_id),
            FOUNDRY_LOCAL_PRINCIPAL_ID=world.actor.principal_id,
            FOUNDRY_INGESTION_CATALOG_JSON=json.dumps(
                [b.model_dump(mode="json") for b in worker.catalog.bindings.values()]
            ),
            SMOKE_SCHEMA=schema,
        )
        (root / "ingestion_http.py").write_text("""
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
                "ingestion_http:create",
                "--factory",
                "--app-dir",
                directory,
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        def call(path, body=None):
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}" + path,
                data=json.dumps(body).encode() if body is not None else None,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                assert response.status == 200
                return json.load(response)

        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("Smoke server failed to start")
                try:
                    if call("/api/v1/tenant")["id"] == str(world.actor.tenant_id):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Smoke server unavailable")
            assert call("/health/ready")["status"] == "ready"
            assert (
                "/api/v1/ontologies/{ontology_id}/ingestion/runs"
                in call("/api/v1/openapi.json")["paths"]
            )
            checks.append("PASS host startup/readiness/OpenAPI/trusted tenant")
            base = "/api/v1/ontologies/manufacturing"
            for name in FILES:
                source = call(base + "/sources/" + name)["definition"]
                assert "url" not in source and "root" not in source
                source["version"] = 2
                assert call(base + "/sources", source)["version"] == 2
                with sessions() as session:
                    definition = json.loads(
                        session.get(
                            IngestionMapping, (world.actor.tenant_id, "manufacturing", name, 1)
                        ).definition_json
                    )
                definition.update(version=2, source_version=2)
                assert call(base + "/mappings", definition)["version"] == 2
            checks.append("PASS HTTP immutable source and mapping publication")

            def ingest(key):
                run = call(
                    base + "/ingestion/runs",
                    {
                        "idempotency_key": key,
                        "mappings": [{"id": name, "version": 2} for name in FILES],
                    },
                )
                assert run["status"] == "PENDING"
                assert worker.run_one(world.actor, "manufacturing") == __import__("uuid").UUID(
                    run["id"]
                )
                result = call(base + "/ingestion/runs/" + run["id"])
                assert result["status"] == "COMPLETED", result
                assert call(base + "/ingestion/runs/" + run["id"] + "/diagnostics") == []
                return result

            first = ingest("http-first")
            assert first["created"] == 63 and first["links_created"] == 70
            for kind, count in [
                ("Factory", 6),
                ("Machine", 20),
                ("Employee", 12),
                ("MaintenanceTask", 25),
            ]:
                aggregate = call(
                    base + "/aggregate",
                    {"object_type": kind, "metrics": [{"name": "n", "operator": "count"}]},
                )
                assert aggregate["groups"][0]["values"]["n"]["value"] == count
            traversal = call(
                base + "/traverse",
                {
                    "object_type": "Factory",
                    "filter": {"property": "factoryId", "operator": "eq", "value": "FAC-001"},
                    "traverse": [{"link": "containsMachine"}],
                },
            )
            assert len(traversal["items"]) == 4
            checks.append(
                "PASS HTTP async ingestion: 63 objects/70 links, aggregate counts and traversal"
            )
            repeated = ingest("http-repeat")
            assert repeated["created"] == repeated["updated"] == repeated["links_created"] == 0
            call(
                base + "/actions/UpdateMachineStatus/execute",
                {
                    "idempotency_key": "http-edit",
                    "parameters": {
                        "machineId": "MCH-001",
                        "newStatus": "MAINTENANCE",
                        "expectedRevision": 1,
                    },
                },
            )
            machines = root / "machines.csv"
            machines.write_text(
                machines.read_text().replace(
                    "MCH-001,CNC Mill 01,RUNNING,73.9", "MCH-001,Source Rename,STOPPED,73.9"
                )
            )
            changed = ingest("http-change")
            assert changed["updated"] == 1
            row = call(
                base + "/objects/Machine/query",
                {
                    "object_type": "Machine",
                    "filter": {"property": "machineId", "operator": "eq", "value": "MCH-001"},
                },
            )["items"][0]
            assert (
                row["properties"]["operationalStatus"] == "MAINTENANCE"
                and row["properties"]["machineName"] == "Source Rename"
            )
            checks.append("PASS repeat idempotency and source refresh preserves HTTP action edit")
        finally:
            process.terminate()
            output = process.communicate(timeout=10)[0]
            evidence = ROOT / "docs/architecture/evidence/phase-4/http-smoke.txt"
            evidence.write_text("\n".join(checks) + "\n" + output)
            print("\n".join(checks))
finally:
    try:
        next(fixture)
    except StopIteration:
        pass
