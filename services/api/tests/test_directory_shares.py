# ruff: noqa: F811
"""Directory picker and invitation lifecycle against migrated PostgreSQL."""

import hashlib
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from ontology_platform.db.models import AuthorizationAudit, ExternalIdentity, TenantShare
from ontology_platform.errors import ApplicationError
from ontology_platform.security.admin import SecurityAdministration
from ontology_platform.security.contracts import AssignmentInput, IdentityInput
from ontology_platform.security.directory import DirectoryUser
from ontology_platform.security.ldap_directory import Person
from ontology_platform.security.oidc import Provider
from sqlalchemy import func, select, text
from test_phase1 import database, migrate  # noqa: F401
from test_phase22 import ONBOARD, actor, onboard, phase22, profile
from test_security_oidc import ISSUER, idp  # noqa: F401

pytestmark = pytest.mark.integration
SHARES = "/api/v1/shares"
DIRECTORY = SHARES + "/recipient-directory"
LDAP = {
    "directory_sources": ("ldap",),
    "directory_ldap_url": "ldap://directory.example.test",
    "directory_ldap_base_dn": "ou=people,dc=example,dc=test",
}


def create_project(client, headers, name):
    result = client.post("/api/v1/projects", headers=headers, json={"name": name})
    assert result.status_code == 201, result.text
    return result.json()["id"]


@pytest.fixture
def ldap_site(database, idp, monkeypatch):
    provider = Provider.model_validate(
        profile().model_dump() | {"personal_tenant_all_users": True, "personal_tenant_role": None}
    )
    client, sessions, _, headers = phase22(database, idp, monkeypatch, provider, **LDAP)
    monkeypatch.setattr(
        client.app.state.ldap_directory, "page", lambda *_: ([Person("newuser", "New User")], None)
    )

    def name_workspace(subject):
        request_headers = headers(subject, preferred_username=subject)
        first = client.post(ONBOARD, headers=request_headers)
        assert first.json() == {"personal_tenant_id": None, "name_required": True}
        result = client.post(
            ONBOARD, headers=request_headers, json={"name": subject + " workspace"}
        )
        assert result.status_code == 200, result.text
        return UUID(result.json()["personal_tenant_id"])

    owner = name_workspace("sender")
    owner_h = headers("sender", owner, preferred_username="sender")
    project = create_project(client, owner_h, "Owner project")
    selection = client.get(DIRECTORY, headers=owner_h).json()["results"][0]["id"]
    return client, sessions, headers, name_workspace, owner, owner_h, project, selection


def send(client, headers, project, selection):
    return client.post(
        SHARES + "/directory-invitations",
        headers=headers,
        json={"project_id": project, "selection": selection, "access": "viewer"},
    )


def test_named_onboarding_claim_binds_only_exact_principal_and_is_single_use(ldap_site):
    client, sessions, headers, name, owner, owner_h, project, selection = ldap_site
    response = send(client, owner_h, project, selection)
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    invitation = response.json()
    secret = invitation["claim_secret"]
    key = UUID(invitation["share"]["id"])
    claim_url = f"{SHARES}/{key}/claim"
    assert invitation["share"]["owner_tenant_id"] == str(owner)
    assert invitation["share"]["directory_username"] == "newuser"
    assert invitation["share"]["recipient_principal_id"] is None
    with sessions() as s:
        assert s.get(ExternalIdentity, (ISSUER, "immutable-new-subject")) is None
        assert (
            s.get(TenantShare, key).directory_digest == hashlib.sha256(secret.encode()).hexdigest()
        )
    outgoing = client.get(SHARES + "?direction=outgoing", headers=owner_h)
    assert outgoing.json()[0]["id"] == str(key)
    assert secret not in outgoing.text

    # No principal before signing in and completing the naming form.
    newcomer = headers("immutable-new-subject", preferred_username="newuser")
    assert client.post(claim_url, headers=newcomer, json={"secret": secret}).status_code == 403
    recipient_tenant = name("immutable-new-subject")
    recipient_h = headers("immutable-new-subject", recipient_tenant, preferred_username="newuser")
    recipient = actor(sessions, "immutable-new-subject", recipient_tenant).principal_id
    other_tenant = name("outsider")
    other_h = headers("outsider", other_tenant, preferred_username="outsider")
    assert client.get(SHARES + "?direction=incoming", headers=recipient_h).json() == []
    assert client.post(f"{SHARES}/{key}/accept", headers=recipient_h).status_code == 403
    assert client.post(claim_url, headers=other_h, json={"secret": secret}).status_code == 403
    for lacking_username in (
        headers("immutable-new-subject", recipient_tenant),
        headers(
            "immutable-new-subject",
            recipient_tenant,
            preferred_username="newuser",
            client_id="other",
        ),
    ):
        error = client.post(claim_url, headers=lacking_username, json={"secret": secret})
        assert error.json()["error"]["code"] == "invitation_username_unavailable"
    assert (
        client.post(
            claim_url,
            headers=recipient_h,
            json={
                "secret": secrets.token_urlsafe(32),
            },
        ).status_code
        == 403
    )
    assert send(client, other_h, project, selection).status_code == 409
    own_selection = client.get(DIRECTORY, headers=other_h).json()["results"][0]["id"]
    assert send(client, other_h, project, own_selection).status_code in (403, 404)

    def claim():
        return client.post(claim_url, headers=recipient_h, json={"secret": secret})

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: claim(), range(4)))
    assert sorted(result.status_code for result in responses) == [200, 403, 403, 403]
    assert claim().status_code == 403
    with sessions() as s:
        row = s.get(TenantShare, key)
        assert row.recipient_principal_id == recipient and row.directory_digest is None
        assert (
            s.scalar(
                select(func.count())
                .select_from(AuthorizationAudit)
                .where(
                    AuthorizationAudit.share_id == key,
                    AuthorizationAudit.operation == "share:accept:committed",
                )
            )
            == 1
        )

    path = f"/api/v1/projects/{project}"
    assert client.get(path, headers=recipient_h).status_code == 404
    assert client.get(path, headers=recipient_h | {"X-Resource-Share": str(key)}).status_code == 200
    assert client.get(path, headers=other_h | {"X-Resource-Share": str(key)}).status_code == 403
    assert (
        client.patch(
            path,
            headers=recipient_h | {"X-Resource-Share": str(key)},
            json={"expected_revision": 1, "name": "Forbidden"},
        ).status_code
        == 403
    )


def test_expired_revoked_and_sender_authority_are_checked_at_claim(ldap_site):
    client, sessions, headers, name, owner, owner_h, project, selection = ldap_site
    recipient_h = headers("newuser", name("newuser"), preferred_username="newuser")

    def invite():
        response = send(client, owner_h, project, selection)
        assert response.status_code == 201, response.text
        data = response.json()
        return UUID(data["share"]["id"]), {"secret": data["claim_secret"]}

    pending, secret = invite()
    with sessions.begin() as s:
        s.get(TenantShare, pending).directory_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert (
        client.post(f"{SHARES}/{pending}/claim", headers=recipient_h, json=secret).status_code
        == 403
    )

    revoked, secret = invite()
    assert client.delete(f"{SHARES}/{revoked}", headers=owner_h).status_code == 200
    assert (
        client.post(f"{SHARES}/{revoked}/claim", headers=recipient_h, json=secret).status_code
        == 403
    )

    racing, secret = invite()
    with ThreadPoolExecutor(max_workers=2) as pool:
        claim = pool.submit(
            client.post, f"{SHARES}/{racing}/claim", headers=recipient_h, json=secret
        )
        revoke = pool.submit(client.delete, f"{SHARES}/{racing}", headers=owner_h)
        assert revoke.result().status_code == 200
        assert claim.result().status_code in (200, 403)
    assert (
        client.post(f"{SHARES}/{racing}/claim", headers=recipient_h, json=secret).status_code == 403
    )
    with sessions() as s:
        assert s.get(TenantShare, racing).state == "revoked"

    unauthorized, secret = invite()
    sender = actor(sessions, "sender", owner)
    admin = SecurityAdministration(client.app.state.authorizer)
    admin.assign(
        sender,
        AssignmentInput(principal_id=sender.principal_id, role_id="tenant-owner"),
        revoke=True,
    )
    assert (
        client.post(
            f"{SHARES}/{unauthorized}/claim",
            headers=recipient_h,
            json=secret,
        ).status_code
        == 403
    )
    with sessions() as s:
        assert s.get(TenantShare, unauthorized).state == "pending"


def test_disabled_and_mixed_sources_preserve_source_identity(database, idp, monkeypatch):
    client, sessions, settings, headers = phase22(
        database,
        idp,
        monkeypatch,
        **(
            LDAP
            | {
                "directory_sources": ("keycloak", "ldap"),
                "directory_provider_id": "example",
                "directory_client_id": "directory",
                "directory_client_secret": "test-only",
            }
        ),
    )
    owner, recipient = (onboard(client, headers, who) for who in ("sender", "id-alice"))
    owner_h = headers("sender", owner)
    admin = SecurityAdministration(client.app.state.authorizer)
    sender = actor(sessions, "sender", owner)
    alice = actor(sessions, "id-alice", recipient).principal_id
    admin.identity(sender, IdentityInput(issuer=ISSUER, subject="id-alice"))
    admin.assign(sender, AssignmentInput(principal_id=alice, role_id="tenant-viewer"))
    assert client.get(DIRECTORY, headers=headers("id-alice", owner)).status_code == 403
    assert client.get(DIRECTORY).status_code == 401

    def unavailable(*_):
        raise ApplicationError("directory_unavailable", "Unavailable", 503)

    monkeypatch.setattr(
        "ontology_platform.security.routes.search_users",
        lambda *_: [DirectoryUser(subject="id-alice", label="alice", display_name="Alice Example")],
    )
    monkeypatch.setattr(client.app.state.ldap_directory, "page", unavailable)
    data = client.get(DIRECTORY + "?search=al", headers=owner_h).json()
    assert data["unavailable_sources"] == ["ldap"]
    assert data["results"] == [
        {"source": "keycloak", "id": alice, "username": "alice", "display_name": "Alice Example"}
    ]
    assert client.get(SHARES + "/recipients?search=al", headers=owner_h).json() == [
        {"id": alice, "label": "alice"}
    ]
    monkeypatch.setattr(
        client.app.state.ldap_directory,
        "page",
        lambda *_: ([Person("alice", "Alice LDAP")], uuid4()),
    )
    data = client.get(DIRECTORY + "?search=al", headers=owner_h).json()
    assert [(row["source"], row["username"]) for row in data["results"]] == [
        ("keycloak", "alice"),
        ("ldap", "alice"),
    ]
    monkeypatch.setattr("ontology_platform.security.routes.search_users", unavailable)
    data = client.get(DIRECTORY + "?search=al", headers=owner_h).json()
    assert data["unavailable_sources"] == ["keycloak"]
    assert [row["source"] for row in data["results"]] == ["ldap"]
    settings.directory_sources = ("ldap",)
    assert client.get(DIRECTORY, headers=owner_h).json()["unavailable_sources"] == []
    settings.directory_sources = ()
    assert (
        client.get(DIRECTORY, headers=owner_h).json()["error"]["code"] == "directory_unconfigured"
    )


@pytest.fixture
def old_shares_database():
    yield from database.__wrapped__(None, "0029_personal_tenants")


def test_upgrade_with_existing_pending_and_accepted_shares(old_shares_database, idp, monkeypatch):
    engine, _, _ = old_shares_database
    client, sessions, _, headers = phase22(old_shares_database, idp, monkeypatch)
    owner, recipient = (onboard(client, headers, who) for who in ("sender", "recipient"))
    sender = actor(sessions, "sender", owner).principal_id
    user = actor(sessions, "recipient", recipient).principal_id
    project = create_project(client, headers("sender", owner), "Existing project")
    pending, accepted = uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(
            text("""
            INSERT INTO tenant_shares (id, owner_tenant_id, project_id, recipient_principal_id,
                recipient_tenant_id, created_by, access, state)
            VALUES (:pending, :owner, :project, :user, NULL, :sender, 'viewer', 'pending'),
                   (:accepted, :owner, :project, NULL, :tenant, :sender, 'viewer', 'accepted')
            """),
            {
                "pending": pending,
                "accepted": accepted,
                "owner": owner,
                "project": project,
                "user": user,
                "sender": sender,
                "tenant": recipient,
            },
        )
    migrate(engine)
    recipient_h = headers("recipient", recipient)
    result = client.get(SHARES + "?direction=incoming", headers=recipient_h)
    assert {row["id"]: row["state"] for row in result.json()} == {
        str(pending): "pending",
        str(accepted): "accepted",
    }
    assert client.post(f"{SHARES}/{pending}/accept", headers=recipient_h).status_code == 200
    assert (
        client.get(
            f"/api/v1/projects/{project}", headers=recipient_h | {"X-Resource-Share": str(accepted)}
        ).status_code
        == 200
    )
