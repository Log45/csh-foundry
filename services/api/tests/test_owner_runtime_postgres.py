# ruff: noqa: F811
"""Production startup and governed jobs with the same non-superuser migration/table owner."""

import json
import os
import runpy
import signal
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from ontology_platform.config import Settings
from ontology_platform.db.models import JobExecutionGrant
from ontology_platform.db.session import require_runtime_role
from ontology_platform.errors import ApplicationError
from ontology_platform.functions.contracts import Invoke
from ontology_platform.main import create_app
from ontology_platform.queries.ast import QueryRequest
from ontology_platform.security.oidc import OIDCVerifier
from ontology_platform.security.workers import worker_context
from ontology_platform.semantic.contracts import CompileInput, ExportInput, JobInput
from ontology_platform.semantic.service import SemanticService
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from test_job_execution import function_world, shared, submit  # noqa: F401
from test_owner_runtime_override import production
from test_phase1 import database  # noqa: F401
from test_security_oidc import idp, token  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def owner_environment(shared, idp, monkeypatch):
    w, auth, admin, owner, alice, bob, actor, svc = shared
    with w.sessions() as s:
        privileged = s.scalar(
            text(
                "SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication "
                "FROM pg_roles WHERE rolname=current_user"
            )
        )
        schema = s.scalar(text("SELECT current_schema()"))
    if privileged:
        if os.environ.get("FOUNDRY_OWNER_RUNTIME_TEST") == "true":
            pytest.fail("Owner test harness must use an account without elevated role flags")
        pytest.skip("NOT RUN: use scripts/validate_owner_runtime.py for a non-superuser owner")
    private, state, original = idp
    providers = tuple(
        p.model_copy(update={"clients": ("studio", "worker")}) for p in original.providers
    )

    def factory(providers, **kwargs):
        def respond(request):
            body = (
                state["metadata"]
                if request.url.path.endswith("openid-configuration")
                else {"keys": state["keys"]}
            )
            return httpx.Response(200, stream=httpx.ByteStream(json.dumps(body).encode()))

        return OIDCVerifier(providers, client=httpx.Client(transport=httpx.MockTransport(respond)))

    monkeypatch.setattr("ontology_platform.security.workers.OIDCVerifier", factory)
    monkeypatch.setattr("ontology_platform.main.OIDCVerifier", factory)
    settings = Settings(
        **(
            production(True).model_dump()
            | {
                "database_url": w.settings.database_url,
                "database_schema": schema,
                "oidc_providers": providers,
                "worker_tenant_id": alice.tenant_id,
                "worker_access_token": token(
                    private, claims={"sub": "pool", "client_id": "worker"}
                ),
                "ingestion_catalog_json": json.dumps(
                    [b.model_dump(mode="json") for b in svc.catalog.bindings.values()]
                ),
            }
        )
    )
    return shared, settings, private


def test_same_owner_migrates_0028_and_owner_opt_in_is_required(owner_environment):
    shared, settings, _ = owner_environment
    w, _, _, _, _, _, _, _ = shared
    with w.sessions() as s:
        assert (
            s.scalar(text("SELECT version_num FROM alembic_version")) == "0028_job_execution_grants"
        )
        assert s.scalar(
            text(
                "SELECT c.relowner = (SELECT oid FROM pg_roles WHERE rolname=current_user) "
                "FROM pg_class c WHERE c.oid='job_execution_grants'::regclass"
            )
        )
    with pytest.raises(ApplicationError):
        require_runtime_role(w.sessions)
    require_runtime_role(w.sessions, allow_owner_runtime_role=settings.allow_owner_runtime_role)


def test_production_api_owner_startup_and_live_authorization(owner_environment):
    shared, settings, private = owner_environment
    _, _, _, _, alice, _, _, _ = shared
    app = create_app(settings)
    headers = {
        "host": "api",
        "X-Tenant-ID": str(alice.tenant_id),
        "Authorization": "Bearer " + token(private),
    }
    with TestClient(app) as client:
        assert client.get("/health/ready", headers={"host": "api"}).status_code == 200
        assert client.get("/api/v1/security/me", headers={"host": "api"}).status_code == 401
        assert client.get("/api/v1/security/me", headers=headers).status_code == 200
        assert (
            client.get(
                "/api/v1/security/me",
                headers=headers | {"X-Tenant-ID": str(uuid4())},
            ).status_code
            == 403
        )
    disabled = settings.model_copy(update={"allow_owner_runtime_role": False})
    with pytest.raises(ApplicationError), TestClient(create_app(disabled)):
        pass


@pytest.mark.parametrize("kind", ["ingestion", "semantic", "execution", "outbox"])
def test_real_service_worker_startup_rejects_owner_without_opt_in(owner_environment, kind):
    shared, settings, _ = owner_environment
    w, _, _, _, _, _, actor, _ = shared
    ontology = "projects" if kind == "execution" else w.definition.id
    with pytest.raises(ApplicationError):
        worker_context(
            settings.model_copy(update={"allow_owner_runtime_role": False}),
            w.sessions,
            kind,
            ontology,
        )
    actual, _ = worker_context(settings, w.sessions, kind, ontology)
    assert actual.principal_id == actor.principal_id and actual.principal_type == "service"


def test_ingestion_cli_processes_job_as_owner_without_weakening_grants(
    owner_environment, monkeypatch
):
    from ontology_platform.ingestion import __main__ as entry

    shared, settings, _ = owner_environment
    w, _, _, _, alice, _, _, svc = shared
    job = submit(w, svc, alice)
    monkeypatch.setattr(entry, "get_settings", lambda: settings)
    monkeypatch.setattr(sys, "argv", ["ingestion", "--ontology", w.definition.id])
    entry.main()
    assert svc.get(alice, w.definition.id, job.id).status == "COMPLETED"
    with w.sessions() as s:
        grant = s.scalar(select(JobExecutionGrant).where(JobExecutionGrant.ingestion_id == job.id))
        grant_id = grant.id
    with pytest.raises(DBAPIError), w.sessions.begin() as s:
        s.execute(
            update(JobExecutionGrant).where(JobExecutionGrant.id == grant_id).values(operations=[])
        )
    with pytest.raises(DBAPIError), w.sessions.begin() as s:
        s.execute(text("DELETE FROM authorization_audit"))


def test_semantic_cli_processes_job_as_owner(owner_environment, monkeypatch):
    from ontology_platform.semantic import __main__ as entry

    shared, settings, _ = owner_environment
    w, auth, _, _, alice, _, _, _ = shared
    svc = SemanticService(w.sessions, auth)
    compiled = svc.compile(
        alice, w.definition.id, CompileInput(schema_version=w.definition.version)
    )
    asserted = svc.export(
        alice,
        w.definition.id,
        ExportInput(
            schema_version=w.definition.version, selections=(QueryRequest(object_type="Factory"),)
        ),
    )
    job = svc.submit(
        alice,
        w.definition.id,
        JobInput(operation="validation", primary_artifact=asserted, secondary_artifact=compiled[1]),
    )
    monkeypatch.setattr(entry, "get_settings", lambda: settings)
    monkeypatch.setattr(sys, "argv", ["semantic", "--ontology", w.definition.id])
    entry.main()
    assert svc.job(alice, w.definition.id, job.id).status == "COMPLETED"


def test_execution_controller_main_uses_owner_mode_for_startup_and_refresh(
    owner_environment, monkeypatch
):
    from ontology_platform.execution.worker import ExecutionWorker

    shared, settings, _ = owner_environment
    _, _, _, _, alice, _, _, _ = shared
    svc, resource, definition, _ = function_world(shared)
    job = svc.invoke(
        alice,
        resource.id,
        Invoke(
            definition_id=definition.id,
            inputs={"text": "owner-runtime"},
            idempotency_key="owner-runtime",
        ),
    )
    script = runpy.run_path(str(ROOT / "scripts/run_execution_worker.py"))
    script["main"].__globals__["get_settings"] = lambda: settings
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    original = ExecutionWorker.run_one

    def run_one(worker):
        key = original(worker)
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        return key

    monkeypatch.setattr(ExecutionWorker, "run_one", run_one)
    try:
        script["main"]()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    assert svc.status(alice, job.id).state == "SUCCEEDED"


def test_migration_utility_checks_current_schema_as_same_owner(owner_environment):
    shared, settings, _ = owner_environment
    script = runpy.run_path(str(ROOT / "scripts/migrate_kubernetes.py"))
    script["main"].__globals__["get_settings"] = lambda: settings
    script["main"]()
    require_runtime_role(shared[0].sessions, allow_owner_runtime_role=True)


def test_owner_mode_keeps_external_connector_credentials_readonly(owner_environment, monkeypatch):
    from ontology_platform.ingestion.catalog import Binding, InputColumn
    from ontology_platform.ingestion.connectors import postgres

    shared, settings, _ = owner_environment
    monkeypatch.setenv("FOUNDRY_ALLOW_OWNER_RUNTIME_ROLE", "true")
    binding = Binding(
        tenant_id=shared[4].tenant_id,
        key="owner-source",
        kind="postgres",
        columns=[InputColumn(name="object_id")],
        source_key_column="object_id",
        url=settings.database_url,
        table_schema=settings.database_schema,
        table="objects",
    )
    with pytest.raises(ApplicationError) as error:
        postgres(binding, 0, 10)
    assert error.value.code == "source_credentials_not_readonly"


def test_owner_provisioning_validates_existing_account_without_admin_secret(
    owner_environment, monkeypatch
):
    _, settings, _ = owner_environment
    monkeypatch.setenv("FOUNDRY_ALLOW_OWNER_RUNTIME_ROLE", "true")
    monkeypatch.delenv("FOUNDRY_ADMIN_DATABASE_URL", raising=False)
    monkeypatch.setattr("ontology_platform.config.get_settings", lambda: settings)
    monkeypatch.setattr(sys, "argv", ["provision", "--apply", "--grant-runtime"])
    script = runpy.run_path(str(ROOT / "scripts/provision_production_database.py"))
    script["main"]()
