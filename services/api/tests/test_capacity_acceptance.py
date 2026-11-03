"""Real PostgreSQL race, rollback and tenant accounting acceptance checks."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from ontology_platform.config import Settings
from ontology_platform.db.models import IngestionRun, SemanticJob, TenantResourceUsage
from ontology_platform.db.session import make_engine
from ontology_platform.errors import ApplicationError
from ontology_platform.main import create_app
from ontology_platform.queries.ast import QueryRequest
from ontology_platform.security.bootstrap import bootstrap
from ontology_platform.security.identity import resolve
from ontology_platform.security.service import PlatformAuthorizer
from ontology_platform.semantic.contracts import CompileInput, ExportInput, NativeInput
from ontology_platform.semantic.service import SemanticService
from sqlalchemy import func, select, text
from sqlalchemy.exc import TimeoutError
from test_ingestion import setup
from test_phase1 import database  # noqa: F401

ISSUER = "https://capacity.example/realm"


@pytest.fixture
def tenants(database, tmp_path):  # noqa: F811
    worlds = []
    with ExitStack() as stack:
        for subject in ("alpha", "beta"):
            folder = tmp_path / subject
            folder.mkdir()
            world, ingestion, _ = setup(database, folder)
            with world.sessions.begin() as sql:
                bootstrap(sql, world.actor.tenant_id, ISSUER, subject, subject)
                schema = sql.scalar(text("SELECT current_schema()"))
            actor = resolve(
                world.sessions,
                ISSUER,
                subject,
                world.actor.tenant_id,
                method="oidc",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
            settings = Settings(
                database_url=world.settings.database_url,
                database_schema=schema,
                tenant_pending_job_limit=4,
                auth_mode="test",
                test_issuer=ISSUER,
                test_subject=subject,
                request_limit_per_minute=10000,
                _env_file=None,
            )
            app = create_app(settings)
            app.state.ingestion_catalog = ingestion.catalog
            client = stack.enter_context(TestClient(app))
            client.headers["x-tenant-id"] = str(actor.tenant_id)
            semantic = SemanticService(world.sessions, PlatformAuthorizer(world.sessions))
            shapes = semantic.compile(actor, "manufacturing", CompileInput(schema_version="1.0.0"))[
                1
            ]
            exports = [
                semantic.export(
                    actor,
                    "manufacturing",
                    ExportInput(
                        schema_version="1.0.0",
                        selections=[QueryRequest(object_type="Factory", limit=n)],
                    ),
                )
                for n in (1, 2, 3)
            ]
            worlds.append((world, actor, semantic, client, shapes, exports))
        yield worlds


def active_jobs(world, tenant):
    with world.sessions() as sql:
        return sum(
            sql.scalar(
                select(func.count())
                .select_from(model)
                .where(model.tenant_id == tenant, model.status.in_(("PENDING", "RUNNING")))
            )
            for model in (IngestionRun, SemanticJob)
        )


@pytest.mark.parametrize("concurrency", [2, 8, 12])
def test_cross_tenant_mixed_http_admission_and_cancel(tenants, concurrency):
    prefix = "/api/v1/ontologies/manufacturing"

    def submit(pair):
        tenant, index = pair
        world, actor, _, client, shapes, exports = tenants[tenant]
        kind = "semantic/jobs" if index < 3 else "ingestion/runs"
        body = (
            {
                "operation": "validation",
                "primary_artifact": str(exports[index]),
                "secondary_artifact": str(shapes),
            }
            if index < 3
            else {"idempotency_key": f"race-{index}", "mappings": [{"id": "Factory", "version": 1}]}
        )
        response = client.post(prefix + "/" + kind, json=body)
        assert response.status_code in (202, 200, 409), response.text
        if response.status_code == 409:
            assert response.json()["error"]["code"] == "constraint_conflict"
        return tenant, kind, body, response

    with ThreadPoolExecutor(concurrency) as pool:
        results = list(pool.map(submit, [(t, i) for i in range(12) for t in range(2)]))
    for tenant, (world, actor, _, client, _, _) in enumerate(tenants):
        accepted = [
            (kind, body, r.json()["id"])
            for t, kind, body, r in results
            if t == tenant and r.status_code < 300
        ]
        assert len(accepted) == 4
        assert active_jobs(world, actor.tenant_id) == 4
        for kind, body, key in accepted:
            # Replay under saturation must not charge again.
            assert client.post(prefix + "/" + kind, json=body).json()["id"] == key
            for _ in range(2):
                r = client.post(prefix + "/" + kind + "/" + key + "/cancel", json={})
                assert r.status_code == 200 and r.json()["status"] == "CANCELLED"
        assert active_jobs(world, actor.tenant_id) == 0
        response = client.post(
            prefix + "/ingestion/runs",
            json={"idempotency_key": "reused", "mappings": [{"id": "Factory", "version": 1}]},
        )
        assert response.status_code == 200
        client.post(prefix + "/ingestion/runs/" + response.json()["id"] + "/cancel", json={})
        foreign = tenants[1 - tenant][1].tenant_id
        foreign_before = active_jobs(world, foreign)
        for kind, body in [
            (
                "ingestion/runs",
                {"idempotency_key": "denied", "mappings": [{"id": "Factory", "version": 1}]},
            ),
            (
                "semantic/jobs",
                {
                    "operation": "validation",
                    "primary_artifact": str(tenants[1 - tenant][5][0]),
                    "secondary_artifact": str(tenants[1 - tenant][4]),
                },
            ),
        ]:
            assert (
                client.post(
                    prefix + "/" + kind, json=body, headers={"x-tenant-id": str(foreign)}
                ).status_code
                == 403
            )
        assert active_jobs(world, actor.tenant_id) == 0
        assert active_jobs(world, foreign) == foreign_before


def usage(world, tenant):
    with world.sessions() as sql:
        row = sql.get(TenantResourceUsage, tenant)
        return row.bytes_used if row else 0


def test_logical_byte_concurrency_abort_retry_and_tenant_isolation(tenants):
    world, actor, service, _, _, _ = tenants[0]
    other, other_actor, other_service, *_ = tenants[1]
    before = usage(world, actor.tenant_id)
    other_before = usage(other, other_actor.tenant_id)
    sample = NativeInput(
        schema_version="1.0.0",
        kind="ontology",
        content='<urn:capacity:s> <urn:capacity:p> "' + "x" * 3000 + '" .',
    )
    service.native(actor, "manufacturing", sample)
    delta = usage(world, actor.tenant_id) - before
    assert delta > 3000
    # Enough space for exactly one more comparable immutable artifact.
    capacity = before + delta * 2 + 100

    def create(index, *, abort=False):
        body = sample.model_copy(
            update={
                "content": sample.content.replace("urn:capacity:s", "urn:capacity:" + str(index))
            }
        )
        try:
            with world.sessions.begin() as sql:
                sql.execute(
                    text("SELECT set_config('foundry.storage_limit', :n, true)"),
                    {"n": str(capacity)},
                )
                scoped = SemanticService(world.sessions, service.authorizer, session=sql)
                key = scoped.native(actor, "manufacturing", body)
                if abort:
                    raise RuntimeError("abort accepted upload")
            return key
        except ApplicationError as error:
            assert error.status_code == 409
            return None

    with pytest.raises(RuntimeError):
        create(99, abort=True)
    assert usage(world, actor.tenant_id) == before + delta
    with ThreadPoolExecutor(8) as pool:
        accepted = list(pool.map(create, range(8)))
    assert sum(k is not None for k in accepted) == 1
    used = usage(world, actor.tenant_id)
    assert before + delta < used <= capacity
    service.native(actor, "manufacturing", sample)  # Idempotent retry at saturation.
    assert usage(world, actor.tenant_id) == used
    other_service.native(other_actor, "manufacturing", sample)
    assert usage(other, other_actor.tenant_id) > other_before
    assert usage(world, actor.tenant_id) == used
    # Rejected malformed upload never reserves bytes.
    with pytest.raises(ApplicationError):
        service.native(actor, "manufacturing", sample.model_copy(update={"content": "invalid ttl"}))
    assert usage(world, actor.tenant_id) == used


def test_bounded_ordinary_and_audit_pool_exhaustion_recovery(tenants):
    world, *_ = tenants[0]
    with world.sessions() as sql:
        schema = sql.scalar(text("SELECT current_schema()"))
    settings = Settings(
        database_url=world.settings.database_url,
        database_schema=schema,
        database_pool_size=1,
        database_pool_overflow=0,
        _env_file=None,
    )
    for audit, limit in ((False, 1), (True, 2)):
        engine = make_engine(settings, audit=audit)
        held = []
        try:
            held = [engine.connect() for _ in range(limit)]
            with pytest.raises(TimeoutError):
                engine.connect()
            assert engine.pool.checkedout() == limit
        finally:
            for connection in held:
                connection.close()
        with engine.connect() as sql:
            assert sql.scalar(text("SELECT 1")) == 1
        assert engine.pool.checkedout() == 0
        engine.dispose()
        assert engine.pool.checkedout() == 0


def test_staging_quota_failure_rollback_cancel_cleanup_and_recovery(tenants):
    from ontology_platform.db.models import IngestionStage
    from ontology_platform.ingestion.contracts import MappingRef, RunInput
    from ontology_platform.ingestion.service import IngestionService
    from ontology_platform.ingestion.worker import IngestionWorker

    world, actor, semantic, client, *_ = tenants[0]
    catalog = client.app.state.ingestion_catalog
    service = IngestionService(world.sessions, semantic.authorizer, catalog)
    worker = IngestionWorker(world.sessions, semantic.authorizer, catalog)
    before = usage(world, actor.tenant_id)
    body = RunInput(
        idempotency_key="staging-limited",
        batch_size=1,
        mappings=[MappingRef(id="Factory", version=1)],
    )
    run = service.submit(actor, "manufacturing", body)
    key, token = worker.claim(actor, "manufacturing")
    assert key == run.id
    with pytest.raises(ApplicationError), world.sessions.begin() as sql:
        sql.execute(
            text("SELECT set_config('foundry.storage_limit', :n, true)"), {"n": str(before + 1)}
        )
        scoped = IngestionWorker(world.sessions, semantic.authorizer, catalog, session=sql)
        scoped.step(actor, "manufacturing", key, token)
    assert usage(world, actor.tenant_id) == before
    with world.sessions() as sql:
        assert sql.scalar(select(func.count()).select_from(IngestionStage)) == 0
        row = sql.get(IngestionRun, (actor.tenant_id, "manufacturing", key))
        assert row.checkpoint == 0
    worker.fail(actor, "manufacturing", key, token, "constraint_conflict")
    assert active_jobs(world, actor.tenant_id) == 0
    retry = service.submit(
        actor, "manufacturing", body.model_copy(update={"idempotency_key": "staging-retry"})
    )
    key, token = worker.claim(actor, "manufacturing")
    assert key == retry.id
    worker.step(actor, "manufacturing", key, token)
    staged = usage(world, actor.tenant_id)
    assert staged > before
    service.cancel(actor, "manufacturing", key)
    assert active_jobs(world, actor.tenant_id) == 0
    # Cancellation retains staging for the documented seven-day retention interval.
    assert usage(world, actor.tenant_id) == staged
    with world.sessions.begin() as sql:
        sql.execute(
            text(
                "UPDATE ingestion_runs SET completed_at=clock_timestamp()-interval '8 days' "
                "WHERE tenant_id=:tenant AND id=:id"
            ),
            {"tenant": actor.tenant_id, "id": key},
        )
    assert service.cleanup(actor, "manufacturing") >= 1
    assert usage(world, actor.tenant_id) == before
    world.engine.dispose()  # Reconnect: authoritative accounting remains consistent.
    assert usage(world, actor.tenant_id) == before
