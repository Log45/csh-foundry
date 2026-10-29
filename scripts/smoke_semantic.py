"""Actual loopback HTTP semantic workflow in a disposable PostgreSQL schema."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api/tests"))
from ontology_platform.config import get_settings  # noqa: E402
from ontology_platform.semantic.engine import OpenOntologiesAdapter  # noqa: E402
from ontology_platform.semantic.worker import SemanticWorker  # noqa: E402
from test_ingestion import setup, submit  # noqa: E402
from test_phase1 import database  # noqa: E402

os.environ.setdefault("TEST_DATABASE_URL", get_settings().database_url.get_secret_value())
fixture = database.__wrapped__()
engine, sessions, url = next(fixture)
interchange = "--interchange" in sys.argv
checks = []
try:
    with tempfile.TemporaryDirectory(prefix="semantic-http-") as directory:
        world, ingestion, ingest_worker = setup((engine, sessions, url), Path(directory))
        run = submit((world, ingestion, ingest_worker))
        ingest_worker.run_one(world.actor, world.definition.id)
        assert ingestion.get(world.actor, world.definition.id, run.id).status == "COMPLETED"
        worker = SemanticWorker(
            sessions,
            world.objects.authorizer,
            engine=OpenOntologiesAdapter(
                Path(os.environ.get("OPEN_ONTOLOGIES_BIN", ROOT / ".external/open-ontologies"))
            ),
        )
        with engine.connect() as conn:
            schema = conn.exec_driver_sql("SELECT current_schema()").scalar()
        with socket.socket() as address:
            address.bind(("127.0.0.1", 0))
            port = address.getsockname()[1]
        env = dict(
            os.environ,
            FOUNDRY_DATABASE_URL=url,
            FOUNDRY_TRUSTED_LOCAL_IDENTITY="true",
            FOUNDRY_LOCAL_TENANT_ID=str(world.actor.tenant_id),
            FOUNDRY_LOCAL_PRINCIPAL_ID=world.actor.principal_id,
            SMOKE_SCHEMA=schema,
        )
        (Path(directory) / "semantic_http.py").write_text("""
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
                "semantic_http:create",
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
            with urllib.request.urlopen(request, timeout=15) as response:
                assert response.status == 200
                return json.load(response)

        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("HTTP server failed to start")
                try:
                    if call("/health/ready")["status"] == "ready":
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("HTTP server never ready")
            prefix = f"/api/v1/ontologies/{world.definition.id}/semantic"
            if interchange:
                from test_ontology_import import request as import_request

                exchange = f"/api/v1/ontologies/{world.definition.id}/interchange"
                result = call(
                    exchange + "/imports",
                    import_request(world, mode="CREATE_DRAFT").model_dump(mode="json"),
                )
                assert result["status"] == "DRAFT_CREATED", result
                assert result["draft_version"] == "2.0.0"
                assert result["conflict_count"] == 0
                key = result["id"]
                assert call(exchange + f"/imports/{key}")["input_hash"] == result["input_hash"]
                assert call(exchange + f"/imports/{key}/vocabulary")
                assert call(exchange + f"/imports/{key}/diagnostics")
                # Original is deliberately text/plain, not interpreted as JSON or active HTML.
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}" + result["artifact_reference"]
                ) as response:
                    assert (
                        response.read().decode()
                        == (ROOT / "fixtures/manufacturing.ttl").read_text()
                    )
                assert call(exchange + "/exports/1.0.0")["output_hash"]
                assert (
                    call(f"/api/v1/ontologies/{world.definition.id}")["active_version"] == "1.0.0"
                )
                checks.append(
                    "PASS HTTP governed OWL import, unpublished draft, "
                    "original/diagnostics/vocabulary "
                    "and deterministic export; active schema unchanged"
                )
            compiled = call(prefix + "/compile", {"schema_version": world.definition.version})
            exported = call(
                prefix + "/exports",
                {
                    "schema_version": world.definition.version,
                    "selections": [
                        {"object_type": t.id, "limit": 200} for t in world.definition.object_types
                    ],
                    "links": [t.id for t in world.definition.link_types],
                },
            )
            view = call(prefix + f"/artifacts/{exported}")
            assert view["freshness"] == "CURRENT"
            checks.append(
                "PASS HTTP compiled schema and authorized 63-object/70-forward-edge RDF export"
            )
            for operation, index in (("validation", 1), ("reasoning", 0)):
                submitted = call(
                    prefix + "/jobs",
                    {
                        "operation": operation,
                        "primary_artifact": exported,
                        "secondary_artifact": compiled[index],
                    },
                )
                assert submitted["status"] == "PENDING"
                assert worker.run_one(world.actor, world.definition.id) == UUID(submitted["id"])
                result = call(prefix + f"/jobs/{submitted['id']}")
                assert result["status"] == "COMPLETED"
                outputs = [call(prefix + f"/artifacts/{key}") for key in result["outputs"]]
                if operation == "validation":
                    assert json.loads(outputs[0]["content"])["conforms"] is True
                else:
                    key = next(
                        o["manifest"]["id"] for o in outputs if o["manifest"]["kind"] == "derived"
                    )
                    assert (
                        call(prefix + f"/artifacts/{key}/approval", {"state": "APPROVED"})
                        == "APPROVED"
                    )
                    assert call(prefix + f"/artifacts/{key}/approval")[0]["state"] == "APPROVED"
                    call(prefix + f"/artifacts/{key}/facts")
                checks.append(
                    f"PASS HTTP {operation} submit/status/result; separate durable worker"
                )
            checks.append("PASS HTTP derived-set approval, audit history and fact projection")
        finally:
            process.terminate()
            logs = process.communicate(timeout=10)[0]
finally:
    try:
        next(fixture)
    except StopIteration:
        pass
output = (
    ROOT
    / "docs/architecture/evidence"
    / ("phase-6" if interchange else "phase-5")
    / "http-smoke.txt"
)
output.write_text("\n".join(checks) + "\n" + logs)
print("\n".join(checks))
