"""Verified platform identities across existing action, import, ingestion and semantic services."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from ontology_platform.actions.contracts import ActionRequest, ExecuteRequest
from ontology_platform.actions.service import ActionExecutionService
from ontology_platform.db.models import AuthorizationAudit, Link, Object, SemanticArtifact
from ontology_platform.errors import ApplicationError
from ontology_platform.ingestion.service import IngestionService
from ontology_platform.ingestion.worker import IngestionWorker
from ontology_platform.interoperability.service import InteroperabilityService
from ontology_platform.objects.service import ObjectService
from ontology_platform.security.admin import SecurityAdministration
from ontology_platform.security.bootstrap import bootstrap
from ontology_platform.security.contracts import (
    AssignmentInput,
    DelegationInput,
    IdentityInput,
    MembershipInput,
    PolicyInput,
    RoleInput,
)
from ontology_platform.security.identity import resolve
from ontology_platform.security.service import PlatformAuthorizer
from ontology_platform.semantic.contracts import CompileInput, ExportInput, JobInput
from ontology_platform.semantic.engine import OpenOntologiesAdapter
from ontology_platform.semantic.service import SemanticService
from ontology_platform.semantic.worker import SemanticWorker
from sqlalchemy import func, select
from test_actions import world as action_world
from test_ingestion import setup, submit
from test_ontology_import import request as import_request
from test_phase1 import database as database_fixture

ISSUER = "https://identity.example/realm"


@pytest.fixture
def database():
    yield from database_fixture.__wrapped__()


def secure(w):
    with w.sessions.begin() as session:
        bootstrap(session, w.actor.tenant_id, ISSUER, "operator", "Existing")
    auth = PlatformAuthorizer(w.sessions)
    principal = resolve(
        w.sessions,
        ISSUER,
        "operator",
        w.actor.tenant_id,
        method="oidc",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    w.actor = principal
    w.objects = ObjectService(w.sessions, auth)
    return auth, SecurityAdministration(auth), principal


def delegation(w, auth, service, p, kind):
    worker_id = service.identity(
        p, IdentityInput(issuer=ISSUER, subject="worker-" + kind, principal_type="service")
    )
    # A worker can hold broad tenant permissions, but delegation further limits operations/data.
    service.assign(p, AssignmentInput(principal_id=worker_id, role_id="tenant-administrator"))
    service.delegate(
        p,
        DelegationInput(
            worker_id=worker_id,
            principal_id=p.principal_id,
            ontology_id=w.definition.id,
            kind=kind,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
    )
    worker = resolve(
        w.sessions, ISSUER, "worker-" + kind, p.tenant_id, method="oidc", expires_at=p.expires_at
    )
    return worker.model_copy(
        update={
            "principal_id": p.principal_id,
            "principal_type": "user",
            "authentication_method": "delegated",
            "actor_id": worker_id,
            "delegation_kind": kind,
            "delegation_ontology": w.definition.id,
        }
    )


def test_actions_preview_revocation_replay_and_private_import(database):
    w = action_world.__wrapped__(database)
    auth, admin, p = secure(w)
    actions = ActionExecutionService(w.sessions, auth)
    params = {"machineId": "MCH-001", "newStatus": "STOPPED", "expectedRevision": 1}
    actions.preview(p, w.definition.id, "UpdateMachineStatus", ActionRequest(parameters=params))
    result = actions.execute(
        p,
        w.definition.id,
        "UpdateMachineStatus",
        ExecuteRequest(idempotency_key="same", parameters=params),
    )
    replay = actions.execute(
        p,
        w.definition.id,
        "UpdateMachineStatus",
        ExecuteRequest(idempotency_key="same", parameters=params),
    )
    assert result.execution_id == replay.execution_id
    # Revoke after successful preview/execution. Neither a replay nor the preview carries authority.
    admin.role(
        p,
        RoleInput(
            id="limited", permissions=("tenant:read", "object:read", "property:read", "schema:read")
        ),
    )
    admin.assign(p, AssignmentInput(principal_id=p.principal_id, role_id="limited"))
    imports = InteroperabilityService(w.sessions, auth)
    original = imports.import_ontology(p, w.definition.id, import_request(w))
    other_id = admin.identity(p, IdentityInput(issuer=ISSUER, subject="other"))
    admin.assign(p, AssignmentInput(principal_id=other_id, role_id="tenant-administrator"))
    other = resolve(
        w.sessions, ISSUER, "other", p.tenant_id, method="oidc", expires_at=p.expires_at
    )
    with pytest.raises(ApplicationError):
        imports.original(other, w.definition.id, original.id)
    admin.assign(
        p, AssignmentInput(principal_id=p.principal_id, role_id="tenant-administrator"), revoke=True
    )
    for key in ("same", "new"):
        with pytest.raises(ApplicationError):
            actions.execute(
                p,
                w.definition.id,
                "UpdateMachineStatus",
                ExecuteRequest(idempotency_key=key, parameters=params),
            )
    assert w.objects.get(p, w.definition.id, "Machine", "MCH-001").version == 2


def test_delegated_manufacturing_ingestion_and_worker_intersection(database, tmp_path):
    w, old_service, _ = setup(database, tmp_path)
    auth, admin, p = secure(w)
    service = IngestionService(w.sessions, auth, old_service.catalog)
    worker = IngestionWorker(w.sessions, auth, old_service.catalog)
    delegated = delegation(w, auth, admin, p, "ingestion")
    run = submit((w, service, worker))
    assert worker.run_one(delegated, w.definition.id) == run.id
    assert service.get(p, w.definition.id, run.id).status == "COMPLETED", service.get(
        p, w.definition.id, run.id
    ).last_error
    with w.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Object)) == 63
        assert session.scalar(select(func.count()).select_from(Link)) == 70
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuthorizationAudit)
                .where(AuthorizationAudit.actor_id == delegated.actor_id)
            )
            > 0
        )
    # A semantic delegation cannot execute ingestion, even with both principals holding all roles.
    semantic = delegation(w, auth, admin, p, "semantic")
    with pytest.raises(ApplicationError):
        worker.claim(semantic, w.definition.id)
    # Current service permissions and membership remain required between batches.
    admin.member(p, delegated.actor_id, MembershipInput(enabled=False))
    with pytest.raises(ApplicationError):
        worker.claim(delegated, w.definition.id)


def test_semantic_worker_rechecks_revoked_delegation_before_output_commit(database, tmp_path):
    from ontology_platform.queries.ast import QueryRequest
    from ontology_platform.security.contracts import DelegationInput

    w, _, _ = setup(database, tmp_path)
    auth, admin, p = secure(w)
    delegated = delegation(w, auth, admin, p, "semantic")
    service = SemanticService(w.sessions, auth)
    compiled = service.compile(
        p, w.definition.id, CompileInput(schema_version=w.definition.version)
    )
    asserted = service.export(
        p,
        w.definition.id,
        ExportInput(
            schema_version=w.definition.version, selections=(QueryRequest(object_type="Factory"),)
        ),
    )
    job = service.submit(
        p,
        w.definition.id,
        JobInput(operation="validation", primary_artifact=asserted, secondary_artifact=compiled[1]),
    )
    binary = Path(os.environ.get("OPEN_ONTOLOGIES_BIN", ".external/open-ontologies"))
    engine = OpenOntologiesAdapter(binary)

    completed_external_work = []

    class RevokeAfterWork:
        def validate_shapes(self, shapes, data):
            result = engine.validate_shapes(shapes, data)
            completed_external_work.append(True)
            admin.delegate(
                p,
                DelegationInput(
                    worker_id=delegated.actor_id,
                    principal_id=p.principal_id,
                    ontology_id=w.definition.id,
                    kind="semantic",
                    enabled=False,
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                ),
            )
            return result

    worker = SemanticWorker(w.sessions, auth, engine=RevokeAfterWork())
    claim = worker.claim(delegated, w.definition.id)
    assert claim[0] == job.id
    with w.sessions() as session:
        before = session.scalar(select(func.count()).select_from(SemanticArtifact))
    with pytest.raises(ApplicationError):
        worker.execute(delegated, w.definition.id, *claim)
    assert completed_external_work == [True]
    with w.sessions() as session:
        assert session.scalar(select(func.count()).select_from(SemanticArtifact)) == before
    assert service.job(p, w.definition.id, job.id).status == "RUNNING"


def test_verified_worker_factory_and_revoked_delegation(database, monkeypatch):
    from ontology_platform.config import Settings
    from ontology_platform.security.workers import worker_context
    from test_security_oidc import idp as idp_fixture
    from test_security_oidc import token

    w = action_world.__wrapped__(database)
    auth, admin, p = secure(w)
    delegated = delegation(w, auth, admin, p, "ingestion")
    fixture = idp_fixture.__wrapped__()
    private, _, verifier = next(fixture)
    settings = Settings(
        database_url=w.settings.database_url,
        auth_mode="oidc",
        oidc_providers=verifier.providers,
        worker_tenant_id=p.tenant_id,
        worker_subject_id=p.principal_id,
        worker_access_token=token(private, claims={"sub": "worker-ingestion"}),
        _env_file=None,
    )

    def verifier_factory(providers, *, ca_bundle=None):
        assert providers == verifier.providers
        assert ca_bundle is None
        return verifier

    monkeypatch.setattr("ontology_platform.security.workers.OIDCVerifier", verifier_factory)
    try:
        actor, actual = worker_context(settings, w.sessions, "ingestion", w.definition.id)
        assert actor.actor_id == delegated.actor_id
        assert actor.principal_id == p.principal_id
        assert isinstance(actual, PlatformAuthorizer)
    finally:
        fixture.close()
    admin.delegate(
        p,
        DelegationInput(
            worker_id=delegated.actor_id,
            principal_id=p.principal_id,
            ontology_id=w.definition.id,
            kind="ingestion",
            enabled=False,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
    )
    with pytest.raises(ApplicationError):
        auth.require(delegated, "ingestion:claim", f"{p.tenant_id}/{w.definition.id}")


def test_delegated_row_grants_intersect_worker_and_initiator(database):
    from ontology_platform.queries.ast import QueryRequest
    from ontology_platform.queries.service import QueryService

    w = action_world.__wrapped__(database)
    auth, admin, p = secure(w)
    delegated = delegation(w, auth, admin, p, "semantic")
    admin.policy(
        p,
        PolicyInput.model_validate(
            {
                "id": "service-boundary",
                "expected_version": 0,
                "ontology_id": w.definition.id,
                "object_type": "Machine",
                "principal_id": delegated.actor_id,
                "visible_properties": ["machineId"],
                "rules": [
                    {
                        "effect": "allow",
                        "conditions": [{"property": "operationalStatus", "value": "CRITICAL"}],
                    }
                ],
            }
        ),
    )
    query = QueryService(w.sessions, auth)
    assert len(query.query(p, w.definition.id, QueryRequest(object_type="Machine")).items) == 1
    assert query.query(delegated, w.definition.id, QueryRequest(object_type="Machine")).items == []


def test_current_delegated_semantic_job_completes_and_owner_reads_result(database, tmp_path):
    from ontology_platform.queries.ast import QueryRequest

    w, _, _ = setup(database, tmp_path)
    auth, admin, p = secure(w)
    delegated = delegation(w, auth, admin, p, "semantic")
    service = SemanticService(w.sessions, auth)
    compiled = service.compile(
        p, w.definition.id, CompileInput(schema_version=w.definition.version)
    )
    asserted = service.export(
        p,
        w.definition.id,
        ExportInput(
            schema_version=w.definition.version, selections=(QueryRequest(object_type="Factory"),)
        ),
    )
    job = service.submit(
        p,
        w.definition.id,
        JobInput(operation="validation", primary_artifact=asserted, secondary_artifact=compiled[1]),
    )
    worker = SemanticWorker(
        w.sessions,
        auth,
        engine=OpenOntologiesAdapter(
            Path(os.environ.get("OPEN_ONTOLOGIES_BIN", ".external/open-ontologies"))
        ),
    )
    assert worker.run_one(delegated, w.definition.id) == job.id
    completed = service.job(p, w.definition.id, job.id)
    assert completed.status == "COMPLETED", completed.last_error
    assert completed.outputs
    for key in completed.outputs:
        artifact = service.get(p, w.definition.id, key)
        assert artifact
