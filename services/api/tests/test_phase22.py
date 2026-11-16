# ruff: noqa: F811
"""Phase 22 public contracts and claims against a disposable PostgreSQL schema."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from ontology_platform.config import Settings
from ontology_platform.db.models import (
    AuthorizationAudit,
    ExternalIdentity,
    IngestionMapping,
    IngestionRun,
    IngestionSource,
    JobExecutionGrant,
    Membership,
    PersonalTenant,
    PlatformPrincipal,
    Tenant,
)
from ontology_platform.ingestion.catalog import SourceCatalog
from ontology_platform.ingestion.contracts import MappingInput, SourceInput
from ontology_platform.ingestion.service import IngestionService
from ontology_platform.ingestion.worker import IngestionWorker
from ontology_platform.main import create_app
from ontology_platform.metadata.service import RegistryService
from ontology_platform.security.bootstrap import bootstrap
from ontology_platform.security.contracts import (
    AssignmentInput,
    IdentityInput,
    MembershipInput,
    RoleInput,
)
from ontology_platform.security.directory import DirectoryUser
from ontology_platform.security.identity import resolve
from ontology_platform.security.oidc import OIDCVerifier, Provider
from ontology_platform.security.workers import WorkerPool
from ontology_schema.models import OntologyDefinition
from sqlalchemy import func, select, text
from test_ingestion import setup
from test_job_execution import submit
from test_phase1 import database, migrate  # noqa: F401
from test_security_oidc import ISSUER, idp, token  # noqa: F401
from test_security_workflows import secure

pytestmark = pytest.mark.integration
ONBOARD = "/api/v1/security/personal-tenant"


def profile():
    return Provider(
        id="example",
        issuer=ISSUER,
        audience="foundry",
        clients=("studio", "worker", "other"),
        access_token_profile="keycloak",
        personal_tenant_client="studio",
        personal_tenant_role="human",
    )


def phase22(database, idp, monkeypatch, provider=None):
    engine, sessions, url = database
    private, identity_state, verifier = idp
    provider = provider or profile()
    verifier.providers = (provider,)
    monkeypatch.setattr("ontology_platform.main.OIDCVerifier", lambda *a, **kw: verifier)

    def document(request):
        body = (
            identity_state["metadata"]
            if request.url.path.endswith("openid-configuration")
            else {"keys": identity_state["keys"]}
        )
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps(body).encode()))

    monkeypatch.setattr(
        "ontology_platform.security.workers.OIDCVerifier",
        lambda *a, **kw: OIDCVerifier(
            (provider,), client=httpx.Client(transport=httpx.MockTransport(document))
        ),
    )
    with engine.connect() as conn:
        schema = conn.scalar(text("SELECT current_schema()"))
    settings = Settings(
        _env_file=None,
        database_url=url,
        database_schema=schema,
        auth_mode="oidc",
        oidc_providers=(provider,),
        worker_client_id="worker",
        worker_subject="pool",
        worker_provider_id=provider.id,
        worker_access_token=token(private, claims={"client_id": "worker", "sub": "pool"}),
    )

    def headers(subject, tenant=None, share=None, **claims):
        signed = token(
            private, claims={"sub": subject, "realm_access": {"roles": ["human"]}} | claims
        )
        return (
            {"Authorization": f"Bearer {signed}"}
            | ({"X-Tenant-ID": str(tenant)} if tenant else {})
            | ({"X-Resource-Share": str(share)} if share else {})
        )

    return TestClient(create_app(settings)), sessions, settings, headers


def onboard(client, headers, subject):
    response = client.post(ONBOARD, headers=headers(subject))
    assert response.status_code == 200, response.text
    return UUID(response.json()["personal_tenant_id"])


def actor(sessions, subject, tenant):
    return resolve(
        sessions,
        ISSUER,
        subject,
        tenant,
        method="oidc",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def test_concurrent_and_repeat_onboarding_keeps_existing_authority(database, idp, monkeypatch):
    client, sessions, _, headers = phase22(database, idp, monkeypatch)
    shared = uuid4()
    with sessions.begin() as s:
        existing = bootstrap(s, shared, ISSUER, "alice", "Shared workspace")
        s.add(PlatformPrincipal(id="disabled", principal_type="user", enabled=False))
        s.flush()
        s.add(ExternalIdentity(issuer=ISSUER, subject="disabled", principal_id="disabled"))
        s.add(PlatformPrincipal(id="service", principal_type="service", enabled=True))
        s.flush()
        s.add(ExternalIdentity(issuer=ISSUER, subject="service", principal_id="service"))

    assert client.get("/api/v1/security/tenants", headers=headers("alice")).json() == [
        {"id": str(shared), "name": "Shared workspace"}
    ]
    assert client.get("/api/v1/security/tenants", headers=headers("unknown")).status_code == 403
    with ThreadPoolExecutor(max_workers=6) as replicas:
        personal = set(replicas.map(lambda _: onboard(client, headers, "alice"), range(6)))
    assert len(personal) == 1
    tenant = personal.pop()
    assert onboard(client, headers, "alice") == tenant != shared
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(Tenant)) == 2
        assert s.get(PersonalTenant, existing).tenant_id == tenant
        assert s.get(Membership, (shared, existing)).enabled
        assert (
            s.scalar(
                select(func.count())
                .select_from(AuthorizationAudit)
                .where(AuthorizationAudit.operation == "tenant:onboard:committed")
            )
            == 1
        )
    assert client.get("/api/v1/security/me", headers=headers("alice")).status_code == 403
    assert client.get("/api/v1/security/me", headers=headers("alice", shared)).status_code == 200
    assert client.get("/api/v1/security/me", headers=headers("alice", tenant)).status_code == 200
    tenants = client.get("/api/v1/security/tenants", headers=headers("alice")).json()
    assert [row["id"] for row in tenants] == [str(tenant), str(shared)]
    for subject, claims in (("disabled", {}), ("service", {}), ("pool", {"client_id": "worker"})):
        assert client.post(ONBOARD, headers=headers(subject, **claims)).status_code == 403
    for claims in ({"realm_access": {"roles": []}}, {"client_id": "other"}):
        assert client.post(ONBOARD, headers=headers("ineligible", **claims)).status_code == 403
        known = client.post(ONBOARD, headers=headers("alice", **claims))
        assert known.status_code == 200 and known.json() == {"personal_tenant_id": None}
    with sessions() as s:
        assert s.get(ExternalIdentity, (ISSUER, "ineligible")) is None
        assert s.get(ExternalIdentity, (ISSUER, "unknown")) is None


def test_all_studio_users_can_name_one_personal_workspace(database, idp, monkeypatch):
    provider = Provider.model_validate(
        profile().model_dump() | {"personal_tenant_all_users": True, "personal_tenant_role": None}
    )
    client, sessions, _, headers = phase22(database, idp, monkeypatch, provider)
    signed_in = headers("newcomer", realm_access=None)
    assert client.post(ONBOARD, headers=signed_in).json() == {
        "personal_tenant_id": None,
        "name_required": True,
    }
    with sessions() as s:
        assert s.get(ExternalIdentity, (ISSUER, "newcomer")) is None
        assert s.scalar(select(func.count()).select_from(Tenant)) == 0
    for name in ("   ", "x" * 201, "a\x00b"):
        assert client.post(ONBOARD, headers=signed_in, json={"name": name}).status_code == 422
    for subject, client_id in (("other", "other"), ("pool", "studio"), ("pool", "worker")):
        assert (
            client.post(
                ONBOARD,
                headers=headers(subject, client_id=client_id, realm_access=None),
                json={"name": "Forbidden"},
            ).status_code
            == 403
        )

    def submit_name():
        response = client.post(ONBOARD, headers=signed_in, json={"name": " My Workspace "})
        assert response.status_code == 200, response.text
        return response.json()

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: submit_name(), range(3)))
    assert results[0] == results[1] == results[2]
    tenant = results[0]["personal_tenant_id"]
    assert client.post(ONBOARD, headers=signed_in).json() == {"personal_tenant_id": tenant}
    assert client.post(ONBOARD, headers=signed_in, json={"name": "Overwrite"}).json() == {
        "personal_tenant_id": tenant
    }
    assert client.get("/api/v1/security/tenants", headers=signed_in).json() == [
        {"id": tenant, "name": "My Workspace"}
    ]
    other = client.post(
        ONBOARD, headers=headers("second-user", realm_access=None), json={"name": "Second"}
    )
    assert other.status_code == 200
    assert other.json()["personal_tenant_id"] != tenant
    assert (
        client.get(
            "/api/v1/security/me", headers=headers("second-user", tenant, realm_access=None)
        ).status_code
        == 403
    )


def test_sharing_lifecycle_and_abac(database, idp, monkeypatch, tmp_path):
    client, sessions, _, headers = phase22(database, idp, monkeypatch)
    w, old, _ = setup(database, tmp_path)
    auth, admin, owner = secure(w)
    alice = owner.tenant_id
    bob, outsider = (onboard(client, headers, name) for name in ("bob", "outsider"))
    bob_id = actor(sessions, "bob", bob).principal_id
    outsider_id = actor(sessions, "outsider", outsider).principal_id
    owner_h = headers("operator", alice)
    bob_h = headers("bob", bob)
    admin.identity(actor(sessions, "bob", bob), IdentityInput(issuer=ISSUER, subject="outsider"))
    admin.assign(
        actor(sessions, "bob", bob),
        AssignmentInput(
            principal_id=outsider_id,
            role_id="tenant-viewer",
        ),
    )
    assert client.get("/api/v1/ontologies", headers=bob_h).json() == []
    assert client.get("/api/v1/ontologies", headers=owner_h).json()
    project = client.post("/api/v1/projects", headers=owner_h, json={"name": "Private project"})
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    targets = "/api/v1/shares/targets"
    assert client.get(targets + "/project?search=PRIVATE", headers=owner_h).json() == [
        {"id": project_id, "label": "Private project"}
    ]
    assert client.get(targets + "/project?search=PRIVATE", headers=bob_h).json() == []
    assert client.get(targets + "/ontology?search=manufact", headers=owner_h).json() == [
        {"id": w.definition.id, "label": w.definition.id}
    ]
    assert client.get(targets + "/ontology", headers=headers("outsider", bob)).status_code == 403

    def directory_search(settings, verifier, issuer, search):
        assert issuer == ISSUER and search == "bo"
        return [
            DirectoryUser(subject="bob", label="bobby"),
            DirectoryUser(subject="pool", label="service-account-worker"),
            DirectoryUser(subject="unprovisioned", label="unknown"),
            DirectoryUser(subject="operator", label="self"),
        ]

    recipients = "/api/v1/shares/recipients?search=bo"
    assert client.get(recipients, headers=owner_h).status_code == 503
    monkeypatch.setattr("ontology_platform.security.routes.search_users", directory_search)
    assert client.get(recipients, headers=owner_h).json() == [{"id": bob_id, "label": "bobby"}]
    assert client.get(recipients, headers=headers("outsider", bob)).status_code == 403
    project_path = f"/api/v1/projects/{project_id}"
    ontology = f"/api/v1/ontologies/{w.definition.id}"
    for h in (bob_h, headers("outsider", outsider)):
        assert client.get(project_path, headers=h).status_code == 404
        assert client.get(ontology, headers=h).status_code == 404
    assert client.get("/api/v1/security/me", headers=headers("operator", bob)).status_code == 403

    def invite(**body):
        result = client.post("/api/v1/shares", headers=owner_h, json=body)
        assert result.status_code == 201, result.text
        assert result.json()["owner_tenant_id"] == str(alice)
        return result.json()["id"]

    viewer = invite(ontology_id=w.definition.id, recipient_principal_id=bob_id, access="viewer")
    collaborator = invite(
        project_id=project_id, recipient_tenant_id=str(bob), access="collaborator"
    )
    acceptance = f"/api/v1/shares/{collaborator}/accept"
    assert client.post(acceptance, headers=headers("outsider", bob)).status_code == 403
    assert client.post(acceptance, headers=bob_h).json()["state"] == "accepted"
    assert client.get(ontology, headers=headers("bob", bob, viewer)).status_code == 403
    assert client.post(f"/api/v1/shares/{viewer}/accept", headers=bob_h).status_code == 200

    share_h = headers("bob", bob, viewer)
    assert client.get(ontology, headers=share_h).status_code == 200
    assert client.get("/api/v1/ontologies/elsewhere", headers=share_h).status_code == 403
    assert client.get("/api/v1/ontologies", headers=share_h).status_code == 403
    assert client.get(ontology, headers=headers("outsider", bob, viewer)).status_code == 403
    assert (
        client.post(
            ontology + "/objects/Factory",
            headers=share_h,
            json={
                "object_id": "X",
                "properties": {"factoryId": "X", "factoryName": "X", "location": "X"},
            },
        ).status_code
        == 403
    )

    edit_id = invite(
        ontology_id=w.definition.id, recipient_principal_id=bob_id, access="collaborator"
    )
    assert client.post(f"/api/v1/shares/{edit_id}/accept", headers=bob_h).status_code == 200
    ontology_editor = headers("bob", bob, edit_id)
    draft = w.definition.model_dump(mode="json") | {"version": "1.1.0"}
    assert (
        client.post(ontology + "/versions", headers=ontology_editor, json=draft).status_code == 201
    )
    assert (
        client.post(ontology + "/versions/1.1.0/publish", headers=ontology_editor).status_code
        == 403
    )
    assert (
        client.post(
            ontology + "/objects/Factory",
            headers=ontology_editor,
            json={
                "object_id": "FAC-002",
                "properties": {
                    "factoryId": "FAC-002",
                    "factoryName": "Shared factory",
                    "location": "X",
                },
            },
        ).status_code
        == 201
    )

    run = submit(w, IngestionService(sessions, auth, old.catalog), owner)
    worker = IngestionWorker(sessions, auth, old.catalog)
    worker_actor = actor(sessions, "pool", bob)
    assert worker.claim(worker_actor, w.definition.id) is None
    # Owner data is present; restrictive owner policies apply to direct sharing.
    from ontology_platform.security.contracts import PolicyInput
    from test_phase1 import factory

    w.objects.create(owner, w.definition.id, factory())
    admin.policy(
        owner,
        PolicyInput(
            id="share-projection",
            expected_version=0,
            ontology_id=w.definition.id,
            object_type="Factory",
            principal_id=bob_id,
            visible_properties=("factoryId",),
        ),
    )
    query = client.post(
        ontology + "/objects/Factory/query", headers=share_h, json={"object_type": "Factory"}
    )
    assert query.status_code == 200, query.text
    assert query.json()["items"][0]["properties"] == {"factoryId": "FAC-001"}
    aggregate = {"object_type": "Factory", "metrics": [{"name": "count", "operator": "count"}]}
    assert client.post(ontology + "/aggregate", headers=share_h, json=aggregate).status_code == 200
    assert (
        client.post(
            ontology + "/aggregate",
            headers=share_h,
            json={
                **aggregate,
                "group_by": "location",
            },
        ).status_code
        == 403
    )
    from ontology_platform.contracts import LinkInput
    from test_phase1 import machine

    w.objects.create(owner, w.definition.id, machine())
    w.objects.create_link(
        owner,
        w.definition.id,
        LinkInput(
            link_type_id="locatedInFactory",
            source_object_type_id="Machine",
            source_object_id="MCH-001",
            target_object_type_id="Factory",
            target_object_id="FAC-001",
        ),
    )
    traversed = client.post(
        ontology + "/traverse",
        headers=share_h,
        json={
            "object_type": "Machine",
            "traverse": [{"link": "locatedInFactory"}],
        },
    )
    assert traversed.status_code == 200, traversed.text
    assert traversed.json()["items"][0]["properties"] == {"factoryId": "FAC-001"}
    assert client.post(ontology + "/ingestion/runs", headers=share_h, json={}).status_code == 403
    assert client.post(ontology + "/semantic/exports", headers=share_h, json={}).status_code == 403
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(JobExecutionGrant)) == 1
        assert s.get(IngestionRun, (alice, w.definition.id, run.id)).status == "PENDING"

    collab_h = headers("outsider", bob, collaborator)
    assert client.get(project_path, headers=collab_h).json()["role"] == "editor"
    assert (
        client.get(project_path, headers=headers("outsider", outsider, collaborator)).status_code
        == 403
    )
    assert (
        client.patch(
            project_path, headers=collab_h, json={"name": "Shared project", "expected_revision": 1}
        ).status_code
        == 200
    )
    assert (
        client.post(
            project_path + "/folders", headers=collab_h, json={"name": "Shared folder"}
        ).status_code
        == 201
    )
    assert (
        client.get(project_path + "/resources?search=private", headers=collab_h).status_code == 403
    )
    assert client.get(project_path + "/members", headers=collab_h).status_code == 403
    assert client.get("/api/v1/security/me", headers=collab_h).status_code == 403
    admin.member(actor(sessions, "bob", bob), outsider_id, MembershipInput(enabled=False))
    assert client.get(project_path, headers=collab_h).status_code == 403

    incoming = client.get("/api/v1/shares?direction=incoming", headers=bob_h)
    outgoing = client.get("/api/v1/shares?direction=outgoing", headers=owner_h)
    assert {s["id"] for s in incoming.json()} == {viewer, collaborator, edit_id}
    assert {s["id"] for s in outgoing.json()} == {viewer, collaborator, edit_id}
    assert client.delete(f"/api/v1/shares/{viewer}", headers=owner_h).json()["state"] == "revoked"
    assert client.get(ontology, headers=share_h).status_code == 403
    assert client.post(f"/api/v1/shares/{viewer}/accept", headers=bob_h).status_code == 403
    with sessions() as s:
        operations = set(
            s.scalars(
                select(AuthorizationAudit.operation).where(
                    AuthorizationAudit.share_id == UUID(viewer),
                    AuthorizationAudit.acting_tenant_id == bob,
                )
            )
        )
        assert "share:accept:committed" in operations and "object:query" in operations


def test_worker_idle_then_claims_in_two_tenants_with_concurrent_replicas(
    database, idp, monkeypatch, tmp_path
):
    client, sessions, settings, headers = phase22(database, idp, monkeypatch)
    pool = WorkerPool(settings, sessions)
    for kind in ("ingestion", "semantic", "execution", "automation", "outbox"):
        assert pool.scopes(kind) == []
    w, old, _ = setup(database, tmp_path)
    auth, admin, owner = secure(w)
    service_id = admin.identity(
        owner, IdentityInput(issuer=ISSUER, subject="pool", principal_type="service")
    )
    admin.assign(owner, AssignmentInput(principal_id=service_id, role_id="tenant-administrator"))
    personal = onboard(client, headers, "new-user")
    p = actor(sessions, "new-user", personal)
    registry = RegistryService(sessions, auth)
    definition = OntologyDefinition.model_validate(
        w.definition.model_dump() | {"tenant_id": personal, "id": "new-ontology"}
    )
    registry.create(p, definition)
    registry.publish(p, definition.id, definition.version)
    registry.activate(p, definition.id, definition.version)
    original = old.catalog.get(owner.tenant_id, "Factory")
    catalog = SourceCatalog([original, original.model_copy(update={"tenant_id": personal})])
    svc = IngestionService(sessions, auth, catalog)
    with sessions() as s:
        source = s.get(IngestionSource, (owner.tenant_id, w.definition.id, "Factory", 1))
        mapping = s.get(IngestionMapping, (owner.tenant_id, w.definition.id, "Factory", 1))
        svc.create_source(p, definition.id, SourceInput.model_validate_json(source.definition_json))
        svc.create_mapping(
            p, definition.id, MappingInput.model_validate_json(mapping.definition_json)
        )
    first = submit(w, svc, owner)
    second = submit(replace(w, definition=definition), svc, p)
    assert {actor.tenant_id for actor, _ in pool.scopes("ingestion")} == {personal, owner.tenant_id}
    assert actor(sessions, "pool", personal).principal_id == service_id
    worker = IngestionWorker(sessions, pool.authorizer, catalog)

    def claim(p, scope):
        lease = worker.claim(p, scope)
        return (p, scope, *lease) if lease else None

    with ThreadPoolExecutor(max_workers=3) as replicas:
        claimed = list(replicas.map(lambda _: next(pool.run("ingestion", claim), None), range(3)))
    attempts = [lease for lease in claimed if lease is not None]
    assert sorted(str(lease[2]) for lease in attempts) == sorted([str(first.id), str(second.id)])
    from ontology_platform.security.job_grants import resolve_attempt

    for service_actor, scope, run_id, fencing_token in attempts:
        context = resolve_attempt(worker, service_actor, "ingestion", scope, run_id, fencing_token)
        for _ in range(25):
            if not worker.step(context, scope, run_id, fencing_token):
                break
        else:
            pytest.fail("Fixture ingestion exceeded its expected number of steps")
    assert svc.get(owner, w.definition.id, first.id).status == "COMPLETED"
    assert svc.get(p, definition.id, second.id).status == "COMPLETED"

    denied = submit(w, svc, owner)
    good = submit(replace(w, definition=definition), svc, p)
    admin.member(owner, service_id, MembershipInput(enabled=False))
    assert next(pool.run("ingestion", worker.run_one), None) == good.id
    assert svc.get(owner, w.definition.id, denied.id).status == "PENDING"


@pytest.fixture
def upgrade_database():
    yield from database.__wrapped__(None, "0028_job_execution_grants")


def test_upgrade_preserves_existing_ids_memberships_and_queued_grants(upgrade_database, tmp_path):
    engine, sessions, _ = upgrade_database
    w, old, _ = setup(upgrade_database, tmp_path)
    auth, admin, p = secure(w)
    legacy = admin.identity(
        p, IdentityInput(issuer=ISSUER, subject="legacy", principal_type="service")
    )
    admin.role(p, RoleInput(id="old-worker", permissions=("ingestion:claim",)))
    admin.assign(p, AssignmentInput(principal_id=legacy, role_id="old-worker"))
    from ontology_platform.projects.contracts import ShareChange
    from test_projects import project, resource, svc

    projects = svc(w, auth)
    source, recipient = project(projects, p), project(projects, p, "Legacy recipient")
    registered = resource(projects, p, source.id)
    projects.share(
        p,
        registered.id,
        ShareChange(
            project_id=recipient.id,
            enabled=True,
            expected_revision=registered.revision,
        ),
    )
    job = submit(w, IngestionService(sessions, auth, old.catalog), p)
    with sessions() as s:
        grant = s.scalar(select(JobExecutionGrant).where(JobExecutionGrant.ingestion_id == job.id))
        grant_id = grant.id
    migrate(engine)
    assert [row.id for row in projects.resources(p, recipient.id, shared=True)] == [registered.id]
    with sessions() as s:
        assert s.get(Tenant, p.tenant_id) is not None
        assert s.get(ExternalIdentity, (ISSUER, "operator")).principal_id == p.principal_id
        assert s.get(Membership, (p.tenant_id, legacy)).enabled
        assert s.get(IngestionRun, (p.tenant_id, w.definition.id, job.id)).status == "PENDING"
        assert s.get(JobExecutionGrant, grant_id).principal_id == p.principal_id
        assert s.get(PersonalTenant, p.principal_id) is None


def test_live_pool_processes_semantic_and_tenant_scoped_delivery(
    database, idp, monkeypatch, tmp_path
):
    from pathlib import Path

    from ontology_platform.db.models import ActionExecution, OutboxEvent
    from ontology_platform.jobs.webhooks import WebhookRunner
    from ontology_platform.queries.ast import QueryRequest
    from ontology_platform.semantic.contracts import CompileInput, ExportInput, JobInput
    from ontology_platform.semantic.engine import OpenOntologiesAdapter
    from ontology_platform.semantic.service import SemanticService
    from ontology_platform.semantic.worker import SemanticWorker

    client, sessions, settings, headers = phase22(database, idp, monkeypatch)
    pool = WorkerPool(settings, sessions)
    assert pool.scopes("semantic") == []
    w, _, _ = setup(database, tmp_path)
    auth, admin, first = secure(w)
    service = admin.identity(
        first,
        IdentityInput(
            issuer=ISSUER,
            subject="pool",
            principal_type="service",
        ),
    )
    admin.assign(first, AssignmentInput(principal_id=service, role_id="tenant-administrator"))
    new_tenant = onboard(client, headers, "personal")
    second = actor(sessions, "personal", new_tenant)
    registry = RegistryService(sessions, auth)
    definition = OntologyDefinition.model_validate(
        w.definition.model_dump() | {"tenant_id": new_tenant}
    )
    registry.create(second, definition)
    registry.publish(second, definition.id, definition.version)
    registry.activate(second, definition.id, definition.version)
    semantic = SemanticService(sessions, auth)
    jobs = {}
    for user in (first, second):
        compiled = semantic.compile(
            user, definition.id, CompileInput(schema_version=definition.version)
        )
        exported = semantic.export(
            user,
            definition.id,
            ExportInput(
                schema_version=definition.version,
                selections=(QueryRequest(object_type="Factory"),),
            ),
        )
        jobs[user.tenant_id] = semantic.submit(
            user,
            definition.id,
            JobInput(
                operation="validation",
                primary_artifact=exported,
                secondary_artifact=compiled[1],
            ),
        )
    worker = SemanticWorker(
        sessions, pool.authorizer, engine=OpenOntologiesAdapter(Path(".external/open-ontologies"))
    )
    assert set(pool.run("semantic", worker.run_one)) == {job.id for job in jobs.values()}
    for user in (first, second):
        assert semantic.job(user, definition.id, jobs[user.tenant_id].id).status == "COMPLETED"
        # Existing action regressions cover the producer. Seed two committed delivery rows
        # to exercise worker authorization independently of the action timing budget.
        execution_id = uuid4()
        with sessions.begin() as s:
            s.add(
                ActionExecution(
                    tenant_id=user.tenant_id,
                    ontology_id=definition.id,
                    id=execution_id,
                    action_id="UpdateMachineStatus",
                    action_version="0" * 64,
                    schema_version=definition.version,
                    principal_id=user.principal_id,
                    key_hash="0" * 64,
                    request_hash="0" * 64,
                    fingerprint="0" * 64,
                    result={},
                )
            )
            s.flush()
            s.add(
                OutboxEvent(
                    tenant_id=user.tenant_id,
                    ontology_id=definition.id,
                    id=uuid4(),
                    execution_id=execution_id,
                    payload={},
                )
            )
    assert {candidate.tenant_id for candidate, _ in pool.scopes("outbox")} == {first.tenant_id}
    destination = "https://example.org/events"
    runner = WebhookRunner(sessions, pool.authorizer)
    received = []

    def delivery(url, event_id, _payload):
        assert url == destination
        received.append(event_id)
        return 204

    events = list(
        pool.run(
            "outbox",
            lambda p, scope: runner.run_one(
                p,
                scope,
                destination,
                transport=delivery,
            ),
        )
    )
    assert received == [str(item) for item in events]
    with sessions() as s:
        assert dict(s.execute(select(OutboxEvent.tenant_id, OutboxEvent.status)).all()) == {
            first.tenant_id: "DELIVERED",
            second.tenant_id: "PENDING",
        }
