"""Phase 8 membership discovery and concurrent editor safety on real PostgreSQL."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from ontology_platform.config import Settings
from ontology_platform.db.models import Membership, PlatformPrincipal
from ontology_platform.errors import ApplicationError
from ontology_platform.main import create_app
from ontology_platform.security.contracts import MembershipInput
from test_phase1 import database, world  # noqa: F401
from test_security_platform import ISSUER, security  # noqa: F401


def app_for(w, subject="alice"):
    app = create_app(
        Settings(
            database_url=w.settings.database_url,
            auth_mode="test",
            test_issuer=ISSUER,
            test_subject=subject,
            trusted_local_identity=False,
            local_tenant_id=None,
            local_principal_id=None,
        )
    )

    from ontology_platform.security.service import PlatformAuthorizer

    app.state.sessions = w.sessions
    app.state.authorizer = PlatformAuthorizer(w.sessions, test_mode=True)
    return app


def test_membership_discovery_requires_verified_identity(security):  # noqa: F811
    w, _, service, admin, reader, _ = security
    with TestClient(app_for(w)) as client:
        response = client.get("/api/v1/security/tenants", headers={"X-Tenant-ID": str(uuid4())})
        assert response.status_code == 200
        assert response.json() == [
            {"id": str(w.actor.tenant_id), "name": "Manufacturing test tenant"}
        ]
        service.member(admin, reader.principal_id, MembershipInput(enabled=False))
        assert client.get("/api/v1/security/tenants").json() == []
    with TestClient(app_for(w, "unknown")) as client:
        assert client.get("/api/v1/security/tenants").status_code == 403
    with w.sessions.begin() as session:
        session.get(PlatformPrincipal, reader.principal_id).enabled = False
    with TestClient(app_for(w)) as client:
        assert client.get("/api/v1/security/tenants").status_code == 403


def test_discovery_without_selected_tenant_and_disabled_auth(security):  # noqa: F811
    w, _, _, _, reader, _ = security
    from ontology_platform.db.models import SecurityState, Tenant

    tenant = uuid4()
    with w.sessions.begin() as session:
        session.add(Tenant(id=tenant, name="Second"))
        session.flush()
        session.add(SecurityState(tenant_id=tenant))
        session.flush()
        session.add(
            Membership(
                tenant_id=tenant, principal_id=reader.principal_id, enabled=True, attributes={}
            )
        )
    with TestClient(app_for(w)) as client:
        assert len(client.get("/api/v1/security/tenants").json()) == 2
        assert client.get("/api/v1/security/me").status_code == 403
        selected = client.get(
            "/api/v1/security/me", headers={"X-Tenant-ID": str(w.actor.tenant_id)}
        )
        assert selected.status_code == 200
    app = create_app(
        Settings(
            database_url=w.settings.database_url,
            auth_mode="disabled",
            trusted_local_identity=False,
            local_tenant_id=None,
            local_principal_id=None,
        )
    )
    with TestClient(app) as client:
        assert client.get("/api/v1/security/tenants").status_code == 401


def test_draft_hash_compare_and_set_is_atomic(world):  # noqa: F811
    w = world
    first = w.registry.create(w.actor, w.definition)
    edited = w.definition.model_copy(update={"name": "Edited"})
    saved = w.registry.draft(
        w.actor, edited.id, edited, replace=True, expected_hash=first.content_hash
    )
    assert saved.definition.name == "Edited"
    with pytest.raises(ApplicationError) as error:
        w.registry.draft(
            w.actor, edited.id, w.definition, replace=True, expected_hash=first.content_hash
        )
    assert error.value.status_code == 412
    assert w.registry.version(w.actor, edited.id, edited.version).content_hash == saved.content_hash
