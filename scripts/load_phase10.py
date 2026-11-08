"""Authenticated local HTTP workload on isolated PostgreSQL; provisional SLO sample only."""

import json
import os
import platform
import resource
import secrets
import socket
import statistics
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import uvicorn
from cryptography.fernet import Fernet
from ontology_platform.config import Settings, get_settings
from ontology_platform.main import create_app
from ontology_platform.queries.ast import QueryRequest
from ontology_platform.security.bootstrap import bootstrap
from ontology_platform.security.identity import resolve
from ontology_platform.security.service import PlatformAuthorizer
from ontology_platform.semantic.contracts import CompileInput, ExportInput
from ontology_platform.semantic.service import SemanticService
from pydantic import SecretStr
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api/tests"))
from test_ingestion import setup  # noqa: E402
from test_phase1 import database  # noqa: E402
from test_security_oidc import ISSUER, idp, token  # noqa: E402


def main() -> None:
    os.environ.setdefault("TEST_DATABASE_URL", get_settings().database_url.get_secret_value())
    fixture, identity = database.__wrapped__(None), idp.__wrapped__()
    server = None
    runtime_role = None
    with tempfile.TemporaryDirectory(prefix="foundry-load-") as directory:
        try:
            world, ingestion, worker = setup(next(fixture), Path(directory))
            from ontology_platform.ingestion.contracts import MappingRef, RunInput

            mappings = [
                MappingRef(id=k, version=1)
                for k in ("Factory", "Machine", "Employee", "MaintenanceTask")
            ]
            ingestion.submit(
                world.actor, "manufacturing", RunInput(idempotency_key="seed", mappings=mappings)
            )
            worker.run_one(world.actor, "manufacturing")
            with world.sessions.begin() as sql:
                bootstrap(sql, world.actor.tenant_id, ISSUER, "alice", "Load test")
            auth = PlatformAuthorizer(world.sessions)
            actor = resolve(
                world.sessions,
                ISSUER,
                "alice",
                world.actor.tenant_id,
                method="oidc",
                expires_at=datetime.now(UTC) + timedelta(minutes=30),
            )
            private, _, verifier = next(identity)
            from sqlalchemy.engine import make_url

            owner_runtime = get_settings().allow_owner_runtime_role
            if owner_runtime:
                with world.engine.connect() as connection:
                    schema = connection.scalar(text("SELECT current_schema()"))
                runtime_url = make_url(world.settings.database_url.get_secret_value())
            else:
                runtime_role = "load_runtime_" + secrets.token_hex(8)
                runtime_password = secrets.token_hex(32)
                with world.engine.begin() as connection:
                    schema = connection.scalar(text("SELECT current_schema()"))
                    connection.exec_driver_sql(
                        f"CREATE ROLE {runtime_role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        f"PASSWORD '{runtime_password}'"
                    )
                    connection.exec_driver_sql(
                        f'GRANT USAGE ON SCHEMA "{schema}" TO {runtime_role}'
                    )
                    connection.exec_driver_sql(
                        f'GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA "{schema}" '
                        f"TO {runtime_role}"
                    )
                runtime_url = make_url(world.settings.database_url.get_secret_value()).set(
                    username=runtime_role, password=runtime_password
                )
            settings = Settings(
                database_url=SecretStr(runtime_url.render_as_string(hide_password=False)),
                database_schema=schema,
                allow_owner_runtime_role=owner_runtime,
                auth_mode="oidc",
                environment="production",
                public_origin="https://studio.example",
                allowed_hosts=("127.0.0.1",),
                oidc_providers=verifier.providers,
                query_cursor_secret=SecretStr("q" * 43),
                browser_state_secret=SecretStr("s" * 43),
                browser_state_keys=SecretStr(Fernet.generate_key().decode()),
                request_limit_per_minute=10000,
                _env_file=None,
            )
            app = create_app(settings)
            app.state.oidc.client.close()
            app.state.oidc = verifier
            app.state.ingestion_catalog = ingestion.catalog
            semantic = SemanticService(world.sessions, auth)
            artifacts = semantic.compile(
                actor, "manufacturing", CompileInput(schema_version=world.definition.version)
            )
            asserted = semantic.export(
                actor,
                "manufacturing",
                ExportInput(
                    schema_version=world.definition.version,
                    selections=[QueryRequest(object_type="Machine")],
                ),
            )
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
            thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
            thread.start()
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.05)
            base = f"http://127.0.0.1:{listener.getsockname()[1]}"
            headers = {
                "Authorization": "Bearer " + token(private),
                "X-Tenant-ID": str(actor.tenant_id),
            }
            prefix = "/api/v1/ontologies/manufacturing"
            with httpx.Client(
                base_url=base, headers=headers, timeout=30, trust_env=False
            ) as client:

                def request(method, path, body=None):
                    response = client.request(method, path, json=body)
                    response.raise_for_status()
                    return response.json()

                source = request("POST", prefix + "/branches", {"name": "load-source"})
                target = request("POST", prefix + "/branches", {"name": "load-target"})
                sdk = request(
                    "POST",
                    prefix + "/sdk/generate",
                    {"version": world.definition.version, "language": "python"},
                )
                parameters = {"machineId": "MCH-001", "newStatus": "STOPPED", "expectedRevision": 1}
                execute = {"parameters": parameters, "idempotency_key": "load-replay"}
                request("POST", prefix + "/actions/UpdateMachineStatus/execute", execute)
                asserted = semantic.export(
                    actor,
                    "manufacturing",
                    ExportInput(
                        schema_version=world.definition.version,
                        selections=[QueryRequest(object_type="Machine")],
                    ),
                )
                cases = [
                    ("tenants", "GET", "/api/v1/security/tenants", None),
                    ("membership", "GET", "/api/v1/security/me", None),
                    (
                        "query",
                        "POST",
                        prefix + "/objects/Machine/query",
                        {"object_type": "Machine"},
                    ),
                    (
                        "object_set",
                        "POST",
                        prefix + "/object-sets/query",
                        {"object_type": "Machine"},
                    ),
                    (
                        "traversal",
                        "POST",
                        prefix + "/traverse",
                        {"object_type": "Machine", "traverse": [{"link": "locatedInFactory"}]},
                    ),
                    (
                        "preview",
                        "POST",
                        prefix + "/actions/UpdateMachineStatus/preview",
                        {"parameters": parameters | {"expectedRevision": 2}},
                    ),
                    (
                        "execute_replay",
                        "POST",
                        prefix + "/actions/UpdateMachineStatus/execute",
                        execute,
                    ),
                    ("comparison", "POST", prefix + f"/branches/{source['id']}/compare", {}),
                    (
                        "merge_preview",
                        "POST",
                        prefix + f"/branches/{target['id']}/merge-preview",
                        {"source_branch": source["id"], "source_revision": 1, "target_revision": 1},
                    ),
                    (
                        "sdk_python",
                        "POST",
                        prefix + "/sdk/generate",
                        {"version": world.definition.version, "language": "python"},
                    ),
                    (
                        "sdk_typescript",
                        "POST",
                        prefix + "/sdk/generate",
                        {"version": world.definition.version, "language": "typescript"},
                    ),
                    ("artifact", "GET", prefix + f"/sdk/artifacts/{sdk['id']}/download", None),
                    (
                        "ingestion_submit",
                        "POST",
                        prefix + "/ingestion/runs",
                        {
                            "idempotency_key": "load-submit",
                            "mappings": [{"id": "Factory", "version": 1}],
                        },
                    ),
                    (
                        "semantic_submit",
                        "POST",
                        prefix + "/semantic/jobs",
                        {
                            "operation": "validation",
                            "primary_artifact": str(asserted),
                            "secondary_artifact": str(artifacts[1]),
                        },
                    ),
                ]

                def sample(index):
                    name, method, path, body = cases[index % len(cases)]
                    start = time.perf_counter()
                    response = client.request(method, path, json=body)
                    return name, time.perf_counter() - start, response.status_code

                cpu = time.process_time()
                start = time.perf_counter()
                with ThreadPoolExecutor(8) as pool:
                    results = list(pool.map(sample, range(len(cases) * 5)))
                elapsed = time.perf_counter() - start
                measurements = {}
                for name, *_ in cases:
                    samples = sorted(v for n, v, _ in results if n == name)
                    measurements[name] = {
                        "count": len(samples),
                        "p50_ms": round(statistics.median(samples) * 1000, 3),
                        "p95_ms": round(samples[-1] * 1000, 3),
                        "p99_ms": round(samples[-1] * 1000, 3),
                        "statuses": [s for n, _, s in results if n == name],
                    }
                with world.sessions() as sql:
                    database_stats = dict(
                        sql.execute(
                            text(
                                "SELECT numbackends,xact_commit,xact_rollback,blks_read,blks_hit "
                                "FROM pg_stat_database WHERE datname=current_database()"
                            )
                        )
                        .mappings()
                        .one()
                    )
                    locks = sql.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE datname=current_database() "
                            "AND wait_event_type='Lock'"
                        )
                    )
                report = {
                    "environment": platform.platform(),
                    "concurrency": 8,
                    "requests": len(results),
                    "throughput_per_second": round(len(results) / elapsed, 2),
                    "error_rate": sum(s >= 400 for _, _, s in results) / len(results),
                    "cpu_seconds": round(time.process_time() - cpu, 3),
                    "max_rss_platform_units": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                    "database_shared_stats": database_stats,
                    "lock_waiters_at_end": locks,
                    "pool_checked_out": world.engine.pool.checkedout(),
                    "measurements": measurements,
                    "scope": (
                        "Local 63-object/70-link fixture, 5 samples per operation, "
                        "real HTTP/PostgreSQL and signed controlled OIDC. "
                        "Conservative nearest-rank percentiles; not production capacity."
                    ),
                    "provisional_targets": (
                        "p95 read 500ms, write 2000ms, errors 0%; proposed only; "
                        "inspect measurements, not business-approved SLOs."
                    ),
                }
                destination = ROOT / "docs/architecture/evidence/phase-10/load.json"
                destination.write_text(json.dumps(report, indent=2) + "\n")
                if report["error_rate"]:
                    raise RuntimeError("Load operations failed; inspect load.json status codes")
                print(
                    "PASS authenticated HTTP workload; measurements in "
                    "docs/architecture/evidence/phase-10/load.json"
                )
        finally:
            if server:
                server.should_exit = True
                thread.join(timeout=30)
            identity.close()
            if runtime_role:
                with world.engine.begin() as connection:
                    connection.exec_driver_sql(f"DROP OWNED BY {runtime_role}")
                    connection.exec_driver_sql(f"DROP ROLE {runtime_role}")
            fixture.close()


if __name__ == "__main__":
    main()
