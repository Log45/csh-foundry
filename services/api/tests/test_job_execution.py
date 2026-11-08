# ruff: noqa: F811
"""Shared service workers: live authority, durable grants, fencing, and isolated identities."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from ontology_platform.artifacts.config import StorageSettings
from ontology_platform.artifacts.contracts import CreateArtifact
from ontology_platform.automations.contracts import AutomationDefinition, Enable, Trigger
from ontology_platform.automations.service import AutomationService
from ontology_platform.db.models import (
    AuthorizationAudit,
    ExecutionJob,
    IngestionRun,
    JobExecutionGrant,
    Object,
)
from ontology_platform.db.session import clock
from ontology_platform.errors import ApplicationError
from ontology_platform.execution.worker import ExecutionWorker
from ontology_platform.functions.contracts import Invoke
from ontology_platform.functions.service import FunctionService
from ontology_platform.ingestion.contracts import MappingRef, RunInput
from ontology_platform.ingestion.service import IngestionService
from ontology_platform.ingestion.worker import IngestionWorker
from ontology_platform.pipelines.service import PipelineService
from ontology_platform.projects.contracts import CreateProject, MemberChange
from ontology_platform.security import job_grants
from ontology_platform.security.contracts import (
    AssignmentInput,
    IdentityInput,
    MembershipInput,
    RoleInput,
)
from ontology_platform.security.identity import resolve
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from test_artifacts import store  # noqa: F401
from test_ingestion import setup
from test_media_functions_automations import definition
from test_phase1 import database, historical_database  # noqa: F401
from test_security_workflows import ISSUER, secure

pytestmark = pytest.mark.integration


def identity(w, admin, owner, subject, *, service=False):
    key = admin.identity(
        owner,
        IdentityInput(
            issuer=ISSUER, subject=subject, principal_type="service" if service else "user"
        ),
    )
    admin.assign(owner, AssignmentInput(principal_id=key, role_id="tenant-administrator"))
    return resolve(
        w.sessions, ISSUER, subject, owner.tenant_id, method="oidc", expires_at=owner.expires_at
    )


@pytest.fixture
def shared(database, tmp_path):  # noqa: F811
    w, old, _ = setup(database, tmp_path)
    auth, admin, owner = secure(w)
    alice = identity(w, admin, owner, "alice")
    bob = identity(w, admin, owner, "bob")
    actor = identity(w, admin, owner, "pool", service=True)
    return w, auth, admin, owner, alice, bob, actor, IngestionService(w.sessions, auth, old.catalog)


def submit(w, svc, p):
    return svc.submit(
        p,
        w.definition.id,
        RunInput(
            idempotency_key=uuid4().hex,
            validation_policy="reject_run",
            batch_size=25,
            mappings=[MappingRef(id="Factory", version=1)],
        ),
    )


def test_shared_pool_executes_alice_and_bob_and_preserves_audit(shared):
    w, auth, _, _, alice, bob, actor, svc = shared
    jobs = [submit(w, svc, p) for p in (alice, bob)]
    worker = IngestionWorker(w.sessions, auth, svc.catalog)
    assert {worker.run_one(actor, w.definition.id) for _ in jobs} == {j.id for j in jobs}
    for p, job in zip((alice, bob), jobs, strict=True):
        assert svc.get(p, w.definition.id, job.id).status == "COMPLETED"
        with w.sessions() as s:
            events = list(
                s.scalars(
                    select(AuthorizationAudit).where(
                        AuthorizationAudit.job_id == job.id,
                        AuthorizationAudit.operation == "job:completed",
                    )
                )
            )
            assert events and all(e.principal_id == p.principal_id for e in events)
            assert all(e.actor_id == actor.principal_id and e.execution_grant_id for e in events)
    with w.sessions() as s:
        assert s.scalar(select(func.count()).select_from(Object)) == 6


@pytest.mark.parametrize("revocation", ["disabled", "membership", "permissions", "grant"])
def test_revocation_between_batches_prevents_output_and_retires_attempt(shared, revocation):
    w, auth, admin, owner, alice, _, actor, svc = shared
    job = submit(w, svc, alice)
    worker = IngestionWorker(w.sessions, auth, svc.catalog)
    key, token = worker.claim(actor, w.definition.id)
    p = job_grants.resolve_attempt(worker, actor, "ingestion", w.definition.id, key, token)
    assert worker.step(p, w.definition.id, key, token)
    if revocation == "disabled":
        from ontology_platform.db.models import PlatformPrincipal

        with admin.operation(owner, "security:membership:manage", write=True) as s:
            s.get(PlatformPrincipal, alice.principal_id).enabled = False
    elif revocation == "membership":
        admin.member(owner, alice.principal_id, MembershipInput(enabled=False))
    elif revocation == "permissions":
        admin.assign(
            owner,
            AssignmentInput(principal_id=alice.principal_id, role_id="tenant-administrator"),
            revoke=True,
        )
    else:
        admin.revoke_job_grant(owner, str(p.execution_grant_id))
    with pytest.raises(ApplicationError):
        worker.step(p, w.definition.id, key, token)
    worker.fail(p, w.definition.id, key, token, "job_authorization_denied")
    with w.sessions() as s:
        assert s.get(IngestionRun, (alice.tenant_id, w.definition.id, job.id)).status == "FAILED"
        assert s.scalar(select(func.count()).select_from(Object)) == 0


def test_denied_and_legacy_jobs_do_not_starve_eligible_jobs(shared):
    w, auth, admin, owner, alice, bob, actor, svc = shared
    denied = submit(w, svc, alice)
    legacy = submit(w, svc, alice)
    good = submit(w, svc, bob)
    with w.sessions.begin() as s:
        s.query(JobExecutionGrant).filter(JobExecutionGrant.ingestion_id == legacy.id).delete()
    admin.member(owner, alice.principal_id, MembershipInput(enabled=False))
    worker = IngestionWorker(w.sessions, auth, svc.catalog)
    assert worker.run_one(actor, w.definition.id) == good.id
    with w.sessions() as s:
        for job in (denied, legacy):
            row = s.get(IngestionRun, (alice.tenant_id, w.definition.id, job.id))
            assert row.status == "FAILED" and row.last_error == "job_authorization_denied"


def test_worker_permissions_tenant_and_job_binding(shared):
    w, auth, admin, owner, alice, bob, actor, svc = shared
    first, second = submit(w, svc, alice), submit(w, svc, bob)
    worker = IngestionWorker(w.sessions, auth, svc.catalog)
    key, token = worker.claim(actor, w.definition.id)
    p = job_grants.resolve_attempt(worker, actor, "ingestion", w.definition.id, key, token)
    with w.sessions() as s:
        other_grant = job_grants.find(s, bob.tenant_id, "ingestion", second.id)
    for forged in (
        p.model_copy(update={"principal_id": bob.principal_id}),
        p.model_copy(update={"tenant_id": uuid4()}),
        p.model_copy(update={"execution_grant_id": other_grant.id}),
        p.model_copy(update={"job_id": second.id}),
    ):
        with pytest.raises(ApplicationError):
            auth.require(forged, "ingestion:execute", f"{alice.tenant_id}/{w.definition.id}")
    with pytest.raises(ApplicationError):
        auth.require(p, "object:read", f"{alice.tenant_id}/unrelated/objects/Factory")
    # A service role alone never replaces the submitting user's permissions.
    admin.assign(
        owner,
        AssignmentInput(principal_id=actor.principal_id, role_id="tenant-administrator"),
        revoke=True,
    )
    with pytest.raises(ApplicationError):
        worker.claim(actor, w.definition.id)
    assert first.id == key


def test_parallel_claims_recovery_fences_old_context(shared):
    w, auth, _, _, alice, bob, actor, svc = shared
    jobs = [submit(w, svc, p) for p in (alice, bob)]
    worker = IngestionWorker(w.sessions, auth, svc.catalog)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: worker.claim(actor, w.definition.id), range(2)))
    assert {c[0] for c in claims} == {j.id for j in jobs}
    key, token = claims[0]
    old = job_grants.resolve_attempt(worker, actor, "ingestion", w.definition.id, key, token)
    with w.sessions.begin() as s:
        s.execute(
            update(IngestionRun)
            .where(IngestionRun.id == key)
            .values(lease_until=clock(s) - timedelta(seconds=1))
        )
    recovered, new_token = worker.claim(actor, w.definition.id)
    assert recovered == key and new_token != token
    with pytest.raises(ApplicationError):
        worker.step(old, w.definition.id, key, token)
    worker.renew(actor, w.definition.id, key, new_token)


def test_grant_creation_rollback_expiry_and_cancellation(shared):
    w, auth, _, _, alice, _, actor, svc = shared
    with pytest.raises(RuntimeError), w.sessions.begin() as s:
        transactional = IngestionService(w.sessions, auth, svc.catalog)
        transactional.transaction_session = s
        submit(w, transactional, alice)
        raise RuntimeError("abort admission")
    with w.sessions() as s:
        assert s.scalar(select(func.count()).select_from(JobExecutionGrant)) == 0
    job = submit(w, svc, alice)
    worker = IngestionWorker(w.sessions, auth, svc.catalog)
    key, token = worker.claim(actor, w.definition.id)
    p = job_grants.resolve_attempt(worker, actor, "ingestion", w.definition.id, key, token)
    svc.cancel(alice, w.definition.id, job.id)
    with pytest.raises(ApplicationError):
        worker.step(p, w.definition.id, key, token)
    with w.sessions.begin() as s, pytest.raises(DBAPIError):
        grant = s.get(JobExecutionGrant, p.execution_grant_id)
        grant.principal_id = "forged"
        s.flush()


def function_world(shared):
    w, auth, admin, owner, alice, bob, actor, _ = shared
    svc = FunctionService(w.sessions, auth, StorageSettings(), None)
    project = svc.create_project(owner, CreateProject(name="Jobs"))
    for member in (alice, bob, actor):
        project = svc.member(
            owner,
            project.id,
            MemberChange(
                principal_id=member.principal_id, role="editor", expected_revision=project.revision
            ),
        )
    resource = svc.create(owner, project.id, CreateArtifact(name="Function"))
    published = svc.publish_function(owner, resource.id, definition())
    worker = ExecutionWorker(PipelineService(w.sessions, auth, svc.settings, None), actor)
    return svc, resource, published, worker


def test_function_shared_execution_and_resource_revocation(shared):
    w, auth, _, owner, alice, bob, actor, _ = shared
    svc, resource, published, worker = function_world(shared)
    jobs = [
        svc.invoke(
            p,
            resource.id,
            Invoke(
                definition_id=published.id,
                inputs={"text": p.principal_id},
                idempotency_key=uuid4().hex,
            ),
        )
        for p in (alice, bob)
    ]
    assert {worker.run_one() for _ in jobs} == {j.id for j in jobs}
    for p, job in zip((alice, bob), jobs, strict=True):
        assert svc.result(p, job.id).values == {"text": p.principal_id}
    job = svc.invoke(
        alice,
        resource.id,
        Invoke(
            definition_id=published.id, inputs={"text": "no output"}, idempotency_key=uuid4().hex
        ),
    )
    tenant, key, token = worker.claim()
    # Project revocation interrupts heartbeat/isolated child, before any output is published.
    svc.member(
        owner,
        resource.project_id,
        MemberChange(
            principal_id=alice.principal_id,
            role=None,
            expected_revision=svc.get_project(owner, resource.project_id).revision,
        ),
    )
    assert worker.heartbeat(tenant, key, token) is False
    with w.sessions() as s:
        assert s.get(ExecutionJob, (tenant, job.id)).state == "FAILED"


def test_scheduler_uses_bound_owner_and_service_identity(shared):
    w, auth, _, owner, alice, _, actor, _ = shared
    functions, function, published, worker = function_world(shared)
    svc = AutomationService(w.sessions, auth, functions.settings, None)
    automation = svc.create(alice, function.project_id, CreateArtifact(name="Schedule"))
    spec = AutomationDefinition(
        function_id=function.id,
        function_definition_id=published.id,
        inputs={"text": "scheduled"},
        trigger=Trigger(kind="interval", interval_seconds=60),
    )
    definition_row = svc.publish_automation(alice, automation.id, spec)
    svc.enable(alice, automation.id, Enable(definition_id=definition_row.id, enabled=True))
    from ontology_platform.db.models import AutomationState

    with w.sessions.begin() as s:
        state = s.get(AutomationState, (alice.tenant_id, automation.id))
        state.next_run_at = clock(s) - timedelta(seconds=1)
    with pytest.raises(ApplicationError):
        svc.tick()
    assert svc.tick(actor) == 1
    job = worker.run_one()
    with w.sessions() as s:
        grant = job_grants.find(s, alice.tenant_id, "execution", job)
        assert grant.principal_id == alice.principal_id
        assert s.get(ExecutionJob, (alice.tenant_id, job)).state == "SUCCEEDED"


def test_unauthorized_submission_creates_no_grant_and_expired_grants_fail_closed(
    shared, monkeypatch
):
    w, auth, admin, owner, alice, _, actor, svc = shared
    admin.assign(
        owner,
        AssignmentInput(principal_id=alice.principal_id, role_id="tenant-administrator"),
        revoke=True,
    )
    with pytest.raises(ApplicationError):
        submit(w, svc, alice)
    with w.sessions() as s:
        assert s.scalar(select(func.count()).select_from(JobExecutionGrant)) == 0
    real_clock = job_grants.clock
    with monkeypatch.context() as patch:
        patch.setattr(job_grants, "clock", lambda s: real_clock(s) - timedelta(days=8))
        job = submit(w, svc, owner)
    worker = IngestionWorker(w.sessions, auth, svc.catalog)
    assert worker.run_one(actor, w.definition.id) is None
    assert svc.get(owner, w.definition.id, job.id).status == "FAILED"


def test_completed_context_is_consumed_and_cannot_touch_unrelated_source(shared):
    w, auth, _, _, alice, _, actor, svc = shared
    job = submit(w, svc, alice)
    worker = IngestionWorker(w.sessions, auth, svc.catalog)
    key, token = worker.claim(actor, w.definition.id)
    p = job_grants.resolve_attempt(worker, actor, "ingestion", w.definition.id, key, token)
    for operation, suffix in (
        ("source:read", "sources/Machine"),
        ("object:read", "objects/Machine/M1"),
        ("ingestion:execute", "ingestion/runs/" + str(uuid4())),
    ):
        with pytest.raises(ApplicationError):
            auth.require(p, operation, f"{alice.tenant_id}/{w.definition.id}/{suffix}")
    for _ in range(20):
        if not worker.step(p, w.definition.id, key, token):
            break
    assert svc.get(alice, w.definition.id, job.id).status == "COMPLETED"
    with pytest.raises(ApplicationError):
        worker.step(p, w.definition.id, key, token)


def test_worker_and_initiator_property_policies_intersect(shared):
    from ontology_platform.security.contracts import PolicyInput

    w, auth, admin, owner, alice, _, actor, svc = shared
    job = submit(w, svc, alice)
    admin.policy(
        owner,
        PolicyInput(
            id="worker-properties",
            expected_version=0,
            ontology_id=w.definition.id,
            object_type="Factory",
            principal_id=actor.principal_id,
            visible_properties=["factoryId"],
            rules=[],
        ),
    )
    worker = IngestionWorker(w.sessions, auth, svc.catalog)
    assert worker.run_one(actor, w.definition.id) == job.id
    assert svc.get(alice, w.definition.id, job.id).status == "FAILED"
    with w.sessions() as s:
        assert s.scalar(select(func.count()).select_from(Object)) == 0


def test_execution_service_cannot_use_another_tenant_token(shared):
    _, _, _, _, alice, _, _, _ = shared
    svc, resource, published, worker = function_world(shared)
    job = svc.invoke(
        alice,
        resource.id,
        Invoke(definition_id=published.id, inputs={"text": "bounded"}, idempotency_key=uuid4().hex),
    )
    _, key, token = worker.claim()
    with pytest.raises(ApplicationError):
        worker.heartbeat(uuid4(), key, token)
    with pytest.raises(ApplicationError):
        worker.fail(uuid4(), key, token, "forged", False)
    assert svc.status(alice, job.id).state == "ADMITTED"


def test_worker_skips_projects_it_cannot_serve_without_failing_their_jobs(shared):
    _, _, _, owner, alice, _, _, _ = shared
    svc, shared_function, published, worker = function_world(shared)
    private_project = svc.create_project(owner, CreateProject(name="Different worker scope"))
    private_function = svc.create(
        owner, private_project.id, CreateArtifact(name="Private function")
    )
    private_definition = svc.publish_function(owner, private_function.id, definition())
    private_job = svc.invoke(
        owner,
        private_function.id,
        Invoke(
            definition_id=private_definition.id,
            inputs={"text": "other pool"},
            idempotency_key=uuid4().hex,
        ),
    )
    eligible = svc.invoke(
        alice,
        shared_function.id,
        Invoke(
            definition_id=published.id, inputs={"text": "this pool"}, idempotency_key=uuid4().hex
        ),
    )
    assert worker.run_one() == eligible.id
    assert svc.status(owner, private_job.id).state == "QUEUED"


def test_upgrade_quarantines_real_legacy_job_without_backfilling_authority(
    historical_database, tmp_path
):
    from test_phase1 import migrate

    migrate(historical_database[0], "0027_lineage_observability")
    w, legacy_svc, _ = setup(historical_database, tmp_path)
    job = submit(w, legacy_svc, w.actor)
    migrate(historical_database[0])
    auth, admin, owner = secure(w)
    actor = identity(w, admin, owner, "migrated-worker", service=True)
    worker = IngestionWorker(w.sessions, auth, legacy_svc.catalog)
    assert worker.run_one(actor, w.definition.id) is None
    with w.sessions() as s:
        assert job_grants.find(s, owner.tenant_id, "ingestion", job.id) is None
        assert s.get(IngestionRun, (owner.tenant_id, w.definition.id, job.id)).status == "FAILED"
        assert s.scalar(select(func.count()).select_from(Object)) == 0


def test_pipeline_pool_resolves_each_initiator_for_publication(shared, store):
    from types import SimpleNamespace

    from test_execution import pipeline

    w, auth, _, owner, alice, bob, actor, _ = shared
    secured = SimpleNamespace(
        sessions=w.sessions, registry=SimpleNamespace(authorizer=auth), actor=owner
    )
    svc, _, resource, _, body = pipeline(secured, store)
    for p in (alice, bob, actor):
        svc.member(
            owner,
            resource.project_id,
            MemberChange(
                principal_id=p.principal_id,
                role="editor",
                expected_revision=svc.get_project(owner, resource.project_id).revision,
            ),
        )
    jobs = [svc.start(p, resource.id, body) for p in (alice, bob)]
    worker = ExecutionWorker(svc, actor)
    assert {worker.run_one() for _ in jobs} == {j.id for j in jobs}
    for p, job in zip((alice, bob), jobs, strict=True):
        assert svc.status(p, job.id).state == "SUCCEEDED"
        with w.sessions() as s:
            assert s.scalar(
                select(AuthorizationAudit.id).where(
                    AuthorizationAudit.job_id == job.id,
                    AuthorizationAudit.principal_id == p.principal_id,
                    AuthorizationAudit.actor_id == actor.principal_id,
                    AuthorizationAudit.operation == "project:pipeline_run_succeeded:committed",
                )
            )


def test_submitter_needs_no_worker_claim_or_delegation_permissions(shared):
    w, auth, admin, owner, alice, _, actor, svc = shared
    admin.role(
        owner,
        RoleInput(
            id="submitter", permissions=tuple(sorted(job_grants.INGESTION - {"ingestion:claim"}))
        ),
    )
    admin.assign(owner, AssignmentInput(principal_id=alice.principal_id, role_id="submitter"))
    admin.assign(
        owner,
        AssignmentInput(principal_id=alice.principal_id, role_id="tenant-administrator"),
        revoke=True,
    )
    job = submit(w, svc, alice)
    worker = IngestionWorker(w.sessions, auth, svc.catalog)
    key, token = worker.claim(actor, w.definition.id)
    worker.renew(actor, w.definition.id, key, token)
    for _ in range(20):
        if not worker.step(actor, w.definition.id, key, token):
            break
    assert svc.get(alice, w.definition.id, job.id).status == "COMPLETED"


def test_grant_expiring_during_a_batch_prevents_commit(shared, monkeypatch):
    w, auth, _, _, alice, _, actor, svc = shared
    job = submit(w, svc, alice)
    worker = IngestionWorker(w.sessions, auth, svc.catalog)
    key, token = worker.claim(actor, w.definition.id)
    assert worker.step(actor, w.definition.id, key, token)  # Stage inputs.
    assert worker.step(actor, w.definition.id, key, token)  # Validate the bounded run.
    clock_elapsed = False
    real_clock = job_grants.clock

    def grant_clock(s):
        return real_clock(s) + (timedelta(days=8) if clock_elapsed else timedelta())

    def expire_before_commit():
        nonlocal clock_elapsed
        clock_elapsed = True

    with monkeypatch.context() as patch:
        patch.setattr(job_grants, "clock", grant_clock)
        with pytest.raises(ApplicationError):
            worker.step(actor, w.definition.id, key, token, before_commit=expire_before_commit)
    with w.sessions() as s:
        assert s.scalar(select(func.count()).select_from(Object)) == 0
        assert s.get(IngestionRun, (alice.tenant_id, w.definition.id, job.id)).status == "RUNNING"


@pytest.mark.parametrize("historical_refs", [0, 100])
def test_semantic_execution_revalidates_ingestion_backed_input_provenance(shared, historical_refs):
    from pathlib import Path

    from ontology_platform.queries.ast import QueryRequest
    from ontology_platform.semantic.contracts import CompileInput, ExportInput, JobInput
    from ontology_platform.semantic.engine import OpenOntologiesAdapter
    from ontology_platform.semantic.service import SemanticService
    from ontology_platform.semantic.worker import SemanticWorker

    w, auth, _, _, alice, _, actor, ingestion = shared
    run = submit(w, ingestion, alice)
    assert (
        IngestionWorker(w.sessions, auth, ingestion.catalog).run_one(actor, w.definition.id)
        == run.id
    )
    if historical_refs:
        from ontology_platform.db.models import IngestionStage
        from sqlalchemy import insert, literal

        with w.sessions.begin() as s:
            for _ in range(historical_refs):
                historical_id = uuid4()
                for model, key_name in ((IngestionRun, "id"), (IngestionStage, "run_id")):
                    table = model.__table__
                    values = [
                        literal(historical_id)
                        if c.name == key_name
                        else literal(uuid4().hex * 2)
                        if c.name == "key_hash"
                        else c
                        for c in table.columns
                    ]
                    s.execute(
                        insert(table).from_select(
                            list(table.columns.keys()),
                            select(*values).where(table.c[key_name] == run.id),
                        )
                    )
    semantic = SemanticService(w.sessions, auth)
    compiled = semantic.compile(
        alice, w.definition.id, CompileInput(schema_version=w.definition.version)
    )
    asserted = semantic.export(
        alice,
        w.definition.id,
        ExportInput(
            schema_version=w.definition.version, selections=(QueryRequest(object_type="Factory"),)
        ),
    )
    job = semantic.submit(
        alice,
        w.definition.id,
        JobInput(operation="validation", primary_artifact=asserted, secondary_artifact=compiled[1]),
    )
    worker = SemanticWorker(
        w.sessions,
        auth,
        engine=OpenOntologiesAdapter(
            Path(__file__).resolve().parents[3] / ".external/open-ontologies"
        ),
    )
    assert worker.run_one(actor, w.definition.id) == job.id
    result = semantic.job(alice, w.definition.id, job.id)
    assert result.status == "COMPLETED", result.last_error


def test_semantic_resubmission_uses_fresh_key_after_revocation(shared):
    from pathlib import Path

    from ontology_platform.queries.ast import QueryRequest
    from ontology_platform.semantic.contracts import CompileInput, ExportInput, JobInput
    from ontology_platform.semantic.engine import OpenOntologiesAdapter
    from ontology_platform.semantic.service import SemanticService
    from ontology_platform.semantic.worker import SemanticWorker

    w, auth, admin, owner, alice, _, actor, _ = shared
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
    body = JobInput(
        operation="validation", primary_artifact=asserted, secondary_artifact=compiled[1]
    )
    first = svc.submit(alice, w.definition.id, body)
    with w.sessions() as s:
        first_grant = job_grants.find(s, alice.tenant_id, "semantic", first.id)
    admin.revoke_job_grant(owner, str(first_grant.id))
    # Reusing a key preserves deduplication; a fresh key is a new authorized admission.
    assert svc.submit(alice, w.definition.id, body).id == first.id
    fresh = svc.submit(
        alice, w.definition.id, body.model_copy(update={"idempotency_key": "new-admission"})
    )
    assert fresh.id != first.id
    worker = SemanticWorker(
        w.sessions,
        auth,
        engine=OpenOntologiesAdapter(
            Path(__file__).resolve().parents[3] / ".external/open-ontologies"
        ),
    )
    assert worker.run_one(actor, w.definition.id) == fresh.id
    assert svc.job(alice, w.definition.id, first.id).status == "FAILED"
    assert svc.job(alice, w.definition.id, fresh.id).status == "COMPLETED"
