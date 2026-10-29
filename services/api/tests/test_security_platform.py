"""Production policy integration on real PostgreSQL; no local-authorizer bypass."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from ontology_platform.config import Settings
from ontology_platform.contracts import ObjectPatch
from ontology_platform.db.models import (
    AuthorizationAudit,
    Object,
    PlatformPrincipal,
)
from ontology_platform.errors import ApplicationError
from ontology_platform.main import create_app
from ontology_platform.objects.service import ObjectService
from ontology_platform.queries.ast import AggregateRequest, QueryRequest
from ontology_platform.queries.service import QueryService
from ontology_platform.security.admin import SecurityAdministration
from ontology_platform.security.bootstrap import bootstrap
from ontology_platform.security.contracts import (
    AssignmentInput,
    IdentityInput,
    MembershipInput,
    PolicyInput,
    RoleInput,
)
from ontology_platform.security.identity import resolve
from ontology_platform.security.service import PlatformAuthorizer
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_phase1 import active, database, factory, world  # noqa: F401
from test_security_oidc import idp as idp_fixture

ISSUER = "https://identity.example/realm"


@pytest.fixture
def idp():
    yield from idp_fixture.__wrapped__()


@pytest.fixture
def security(world):  # noqa: F811
    active(world)
    with world.sessions.begin() as session:
        bootstrap(session, world.actor.tenant_id, ISSUER, "admin", "Existing tenant")
    auth = PlatformAuthorizer(world.sessions)
    admin = resolve(
        world.sessions,
        ISSUER,
        "admin",
        world.actor.tenant_id,
        method="oidc",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    service = SecurityAdministration(auth)
    reader_id = service.identity(
        admin, IdentityInput(issuer=ISSUER, subject="alice", attributes={"location": "North"})
    )
    service.role(
        admin,
        RoleInput(
            id="reader",
            permissions=(
                "tenant:read",
                "schema:read",
                "object:read",
                "object:query",
                "object:aggregate",
                "object:count",
                "property:read",
                "link:read",
            ),
        ),
    )
    service.assign(admin, AssignmentInput(principal_id=reader_id, role_id="reader"))
    reader = resolve(
        world.sessions,
        ISSUER,
        "alice",
        world.actor.tenant_id,
        method="oidc",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    objects = ObjectService(world.sessions, auth)
    objects.create(admin, "manufacturing", factory("F1", location="North"))
    objects.create(admin, "manufacturing", factory("F2", location="South"))
    return world, auth, service, admin, reader, objects


def restrict(service, admin, **overrides):
    body = {
        "id": "department",
        "expected_version": 0,
        "ontology_id": "manufacturing",
        "object_type": "Factory",
        "visible_properties": ["factoryId", "factoryName"],
        "rules": [
            {
                "effect": "allow",
                "conditions": [{"property": "location", "principal_attribute": "location"}],
            }
        ],
    }
    body.update(overrides)
    return service.policy(admin, PolicyInput.model_validate(body))


def test_identity_unknown_membership_selection_and_issuer_collision(security):
    w, auth, service, admin, reader, _ = security
    with pytest.raises(ApplicationError):
        resolve(w.sessions, ISSUER, "unknown", None, method="oidc", expires_at=admin.expires_at)
    with pytest.raises(ApplicationError):
        resolve(w.sessions, ISSUER, "alice", uuid4(), method="oidc", expires_at=admin.expires_at)
    other = service.identity(admin, IdentityInput(issuer="https://other.example", subject="alice"))
    assert other != reader.principal_id
    service.member(admin, reader.principal_id, MembershipInput(enabled=False))
    with pytest.raises(ApplicationError):
        auth.require(reader, "tenant:read", f"{reader.tenant_id}/tenant")


def test_query_crud_counts_and_hidden_property_side_channels(security):
    w, auth, service, admin, reader, objects = security
    restrict(service, admin, principal_id=reader.principal_id)
    query = QueryService(w.sessions, auth)
    page = query.query(reader, "manufacturing", QueryRequest(object_type="Factory"))
    assert [item.object_id for item in page.items] == ["F1"]
    assert "location" not in page.items[0].properties
    assert "location" not in objects.get(reader, "manufacturing", "Factory", "F1").properties
    assert objects.count(reader, "manufacturing", "Factory") == 1
    with pytest.raises(ApplicationError):
        objects.get(reader, "manufacturing", "Factory", "F2")
    for request in [
        QueryRequest(
            object_type="Factory",
            filter={"property": "location", "operator": "eq", "value": "North"},
        ),
        QueryRequest(object_type="Factory", order_by=[{"property": "location"}]),
        QueryRequest(object_type="Factory", select=["location"]),
    ]:
        with pytest.raises(ApplicationError):
            query.query(reader, "manufacturing", request)
    with pytest.raises(ApplicationError):
        query.aggregate(
            reader,
            "manufacturing",
            AggregateRequest(
                object_type="Factory",
                group_by="location",
                metrics=[{"name": "count", "operator": "count"}],
            ),
        )


def test_policy_proposed_write_missing_attributes_deny_precedence(security):
    w, auth, service, admin, reader, objects = security
    restrict(
        service,
        admin,
        principal_id=admin.principal_id,
        visible_properties=None,
        rules=[{"effect": "deny", "conditions": [{"property": "location", "value": "South"}]}],
    )
    with pytest.raises(ApplicationError):
        objects.create(admin, "manufacturing", factory("F3", location="South"))
    with pytest.raises(ApplicationError):
        objects.patch(
            admin,
            "manufacturing",
            "Factory",
            "F1",
            ObjectPatch(expected_version=1, properties={"location": "South"}),
        )
    assert objects.get(admin, "manufacturing", "Factory", "F1").properties["location"] == "North"
    restrict(
        service,
        admin,
        id="missing",
        principal_id=reader.principal_id,
        rules=[
            {
                "effect": "allow",
                "conditions": [{"property": "location", "principal_attribute": "missing"}],
            }
        ],
    )
    assert (
        QueryService(w.sessions, auth)
        .query(reader, "manufacturing", QueryRequest(object_type="Factory"))
        .items
        == []
    )


def test_policy_revision_invalidates_cursor_and_revocations(security):
    w, auth, service, admin, reader, _ = security
    query = QueryService(w.sessions, auth)
    request = QueryRequest(object_type="Factory", limit=1)
    cursor = query.query(reader, "manufacturing", request).next_cursor
    assert cursor
    restrict(service, admin, principal_id=reader.principal_id, rules=[], visible_properties=None)
    with pytest.raises(ApplicationError) as error:
        query.query(reader, "manufacturing", request.model_copy(update={"cursor": cursor}))
    assert error.value.code == "invalid_cursor"
    service.assign(
        admin, AssignmentInput(principal_id=reader.principal_id, role_id="reader"), revoke=True
    )
    with pytest.raises(ApplicationError):
        query.query(reader, "manufacturing", request)


def test_no_escalation_and_durable_denial_audit(security):
    w, auth, service, admin, reader, _ = security
    with pytest.raises(ApplicationError):
        service.role(reader, RoleInput(id="escalate", permissions=("security:role:manage",)))
    with w.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuthorizationAudit)
                .where(AuthorizationAudit.allowed.is_(False))
            )
            >= 1
        )
    with pytest.raises(DBAPIError), w.sessions.begin() as session:
        session.execute(text("DELETE FROM authorization_audit"))
    with pytest.raises(DBAPIError), w.sessions.begin() as session:
        session.execute(text("UPDATE security_roles SET permissions = '[]'"))


def test_transaction_revocation_serialization(security):
    w, auth, service, admin, reader, _ = security
    started, release = Event(), Event()

    def in_flight():
        with w.sessions.begin() as session, auth.security_context(session, reader):
            auth.require(reader, "object:read", f"{reader.tenant_id}/manufacturing")
            started.set()
            assert release.wait(4)

    def revoke():
        service.assign(
            admin, AssignmentInput(principal_id=reader.principal_id, role_id="reader"), revoke=True
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(in_flight)
        assert started.wait(2)
        revocation = pool.submit(revoke)
        assert not revocation.done()
        release.set()
        running.result()
        revocation.result()
    with pytest.raises(ApplicationError):
        auth.require(reader, "object:read", f"{reader.tenant_id}/manufacturing")


def test_test_mode_uses_real_authorization_services(security):
    w, _, _, _, _, _ = security
    settings = Settings(
        database_url=SecretStr(w.settings.database_url.get_secret_value()),
        auth_mode="test",
        test_issuer=ISSUER,
        test_subject="alice",
        _env_file=None,
    )
    app = create_app(settings)
    app.state.sessions = w.sessions
    app.state.authorizer = PlatformAuthorizer(w.sessions, test_mode=True)
    with TestClient(app) as client:
        assert client.get("/api/v1/security/me").status_code == 200
        assert (
            client.post(
                "/api/v1/security/roles",
                json={"id": "escalate", "permissions": ["security:role:manage"]},
            ).status_code
            == 403
        )
        assert (
            client.get("/api/v1/security/me", headers={"X-Tenant-ID": str(uuid4())}).status_code
            == 403
        )


def test_oidc_http_real_signature_membership_and_impersonation(security, idp):
    from test_security_oidc import token

    w, auth, _, admin, reader, _ = security
    private, _, verifier = idp
    settings = Settings(
        database_url=w.settings.database_url,
        auth_mode="oidc",
        oidc_providers=verifier.providers,
        _env_file=None,
    )
    app = create_app(settings)
    app.state.sessions, app.state.authorizer, app.state.oidc = w.sessions, auth, verifier
    with TestClient(app) as client:
        assert (
            client.get(
                "/api/v1/security/me", headers={"X-Principal-ID": admin.principal_id}
            ).status_code
            == 401
        )
        headers = {
            "Authorization": "Bearer "
            + token(private, claims={"roles": ["tenant-administrator"], "tenant_id": str(uuid4())})
        }
        assert (
            client.get("/api/v1/security/me", headers=headers).json()["principal"]["principal_id"]
            == reader.principal_id
        )
        assert (
            client.post(
                "/api/v1/security/roles",
                headers=headers,
                json={"id": "admin", "permissions": ["security:role:manage"]},
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/api/v1/security/me", headers=headers | {"X-Tenant-ID": str(uuid4())}
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/api/v1/security/me", headers={"Authorization": "Bearer invalid"}
            ).status_code
            == 401
        )
        with w.sessions.begin() as session:
            session.get(PlatformPrincipal, reader.principal_id).enabled = False
        assert client.get("/api/v1/security/me", headers=headers).status_code == 403
    app.state.engine.dispose()


def test_oidc_startup_does_not_fallback(security, idp):
    w, _, _, _, _, _ = security
    _, state, verifier = idp
    state["metadata"] = {
        "issuer": "https://evil.example",
        "jwks_uri": "https://identity.example/keys",
    }
    settings = Settings(
        database_url=w.settings.database_url,
        auth_mode="oidc",
        oidc_providers=verifier.providers,
        _env_file=None,
    )
    app = create_app(settings)
    app.state.oidc = verifier
    with pytest.raises(ValueError), TestClient(app):
        pass


def test_multitenant_membership_and_role_isolation(security):
    from ontology_platform.db.models import RoleAssignment

    w, auth, _, admin, reader, objects = security
    other_tenant = uuid4()
    with w.sessions.begin() as session:
        same_principal = bootstrap(session, other_tenant, ISSUER, "alice", "Other")
    assert same_principal == reader.principal_id
    with pytest.raises(ApplicationError) as error:
        resolve(w.sessions, ISSUER, "alice", None, method="oidc", expires_at=admin.expires_at)
    assert error.value.code == "tenant_selection_required"
    # Administrator in the other tenant remains a reader in this tenant.
    with pytest.raises(ApplicationError):
        auth.require(reader, "security:role:manage", f"{reader.tenant_id}/security")
    foreign = resolve(
        w.sessions, ISSUER, "alice", other_tenant, method="oidc", expires_at=admin.expires_at
    )
    assert auth.authorize(foreign, "security:role:manage", f"{other_tenant}/security").allowed
    with pytest.raises(ApplicationError):
        objects.get(foreign, "manufacturing", "Factory", "F1")
    with w.sessions() as session:
        assert (
            session.scalar(
                select(RoleAssignment.role_id).where(
                    RoleAssignment.tenant_id == reader.tenant_id,
                    RoleAssignment.principal_id == reader.principal_id,
                )
            )
            == "reader"
        )


def test_links_apply_sql_target_policy_before_pagination(security):
    from ontology_platform.contracts import LinkInput
    from test_phase1 import machine

    w, auth, service, admin, reader, objects = security
    objects.create(admin, "manufacturing", machine("M1"))
    objects.create_link(
        admin,
        "manufacturing",
        LinkInput(
            link_type_id="locatedInFactory",
            source_object_type_id="Machine",
            source_object_id="M1",
            target_object_type_id="Factory",
            target_object_id="F2",
        ),
    )
    restrict(service, admin, principal_id=reader.principal_id)
    assert objects.neighbors(reader, "manufacturing", "Machine", "M1", "locatedInFactory") == []
    assert (
        QueryService(w.sessions, auth)
        .query(
            reader,
            "manufacturing",
            QueryRequest(object_type="Machine", traverse=[{"link": "locatedInFactory"}]),
        )
        .items
        == []
    )
    # Write permission never substitutes for visibility of both endpoints.
    with pytest.raises(ApplicationError):
        objects.create_link(
            reader,
            "manufacturing",
            LinkInput(
                link_type_id="locatedInFactory",
                source_object_type_id="Machine",
                source_object_id="M1",
                target_object_type_id="Factory",
                target_object_id="F2",
            ),
        )


def test_phase7_upgrade_downgrade_preserves_operational_rows(security):
    from ontology_platform.db.models import SecurityState
    from test_phase1 import migrate

    w, _, _, _, _, _ = security
    migrate(w.engine, "0012_ontology_imports", downgrade=True)
    with w.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Object)) == 2
    migrate(w.engine)
    with w.sessions() as session:
        assert session.get(SecurityState, w.actor.tenant_id) is not None
        assert session.scalar(select(func.count()).select_from(Object)) == 2


def test_policy_versions_in_predicate_and_missing_deny_fail_closed(security):
    w, auth, service, admin, reader, _ = security
    restrict(
        service,
        admin,
        principal_id=reader.principal_id,
        visible_properties=None,
        rules=[
            {
                "effect": "allow",
                "conditions": [
                    {"property": "location", "operator": "in", "value": ["North", "South"]}
                ],
            },
            {"effect": "deny", "conditions": [{"property": "location", "value": "South"}]},
        ],
    )
    query = QueryService(w.sessions, auth)
    request = QueryRequest(object_type="Factory")
    assert [row.object_id for row in query.query(reader, "manufacturing", request).items] == ["F1"]
    with pytest.raises(ApplicationError):
        restrict(service, admin, principal_id=reader.principal_id)
    restrict(
        service,
        admin,
        expected_version=1,
        principal_id=reader.principal_id,
        visible_properties=None,
        rules=[
            {
                "effect": "deny",
                "conditions": [{"property": "location", "principal_attribute": "missing"}],
            }
        ],
    )
    assert query.query(reader, "manufacturing", request).items == []
    restrict(service, admin, expected_version=2, enabled=False, principal_id=reader.principal_id)
    assert len(query.query(reader, "manufacturing", request).items) == 2
    with pytest.raises(DBAPIError), w.sessions.begin() as session:
        session.execute(text("DELETE FROM security_policy_versions"))


def test_transaction_snapshot_cannot_switch_tenants(security):
    w, auth, _, admin, _, _ = security
    with w.sessions.begin() as session, auth.security_context(session, admin):
        foreign = admin.model_copy(update={"tenant_id": uuid4()})
        assert not auth.authorize(foreign, "tenant:read", f"{foreign.tenant_id}/tenant").allowed
        with pytest.raises(ApplicationError), auth.security_context(session, foreign):
            pass


def test_audit_batches_survive_business_rollback_and_have_bounded_flush(security):
    w, auth, _, admin, _, objects = security
    with w.sessions() as session:
        before = session.scalar(select(func.count()).select_from(AuthorizationAudit))
    with w.sessions.begin() as session, auth.security_context(session, admin):
        for _ in range(260):
            auth.require(admin, "tenant:read", f"{admin.tenant_id}/tenant")
        assert len(auth.snapshot.get().pending_audit) == 4
    with w.sessions() as session:
        assert session.scalar(select(func.count()).select_from(AuthorizationAudit)) == before + 260
    with (
        pytest.raises(RuntimeError),
        objects.operation(admin, "object:create", "manufacturing") as session,
    ):
        ObjectService(w.sessions, auth, session=session).create(
            admin, "manufacturing", factory("ROLLBACK")
        )
        raise RuntimeError("business failure after authorization")
    with w.sessions() as session:
        assert (
            session.get(Object, (admin.tenant_id, "manufacturing", "Factory", "ROLLBACK")) is None
        )
        assert session.scalar(select(func.count()).select_from(AuthorizationAudit)) > before + 260


def test_audit_failure_rolls_back_authorized_mutations(security, monkeypatch):
    w, auth, _, admin, _, objects = security

    def unavailable(snapshot):
        raise ApplicationError("audit_unavailable", "Audit unavailable", 503)

    monkeypatch.setattr(auth, "flush_audit", unavailable)
    with pytest.raises(ApplicationError):
        objects.create(admin, "manufacturing", factory("NO-AUDIT"))
    with w.sessions() as session:
        assert (
            session.get(Object, (admin.tenant_id, "manufacturing", "Factory", "NO-AUDIT")) is None
        )
