"""Phase 10 controls on real PostgreSQL, cryptography, processes and HTTP boundaries."""

import json
import secrets
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from ontology_platform.config import Settings
from ontology_platform.db.models import BrowserState, TenantResourceUsage
from ontology_platform.errors import ApplicationError
from ontology_platform.jobs.supervisor import run_child
from ontology_platform.main import create_app
from ontology_platform.operations import rate_limit
from ontology_platform.security.broker import realm_configuration
from ontology_platform.security.browser import BrowserStore, StateInput
from pydantic import SecretStr, ValidationError
from sqlalchemy import text
from test_phase1 import database, world  # noqa: F401


@pytest.fixture
def stores(world):  # noqa: F811
    key = Fernet.generate_key().decode()
    settings = world.settings.model_copy(
        update={
            "browser_state_secret": SecretStr(secrets.token_urlsafe(32)),
            "browser_state_keys": SecretStr(key),
            "browser_state_capacity": 3,
        }
    )
    return (
        world,
        settings,
        BrowserStore(world.sessions, settings),
        BrowserStore(world.sessions, settings),
    )


def state(ttl=200000, **data):
    return StateInput(
        expires=int(time.time() * 1000) + ttl,
        data={"token": "sensitive-api-token", "csrf": "secret-csrf"} | data,
    )


def test_session_replica_restart_logout_encryption_and_capacity(stores):
    world, settings, a, b = stores  # noqa: F811
    key = secrets.token_urlsafe(32)
    created = a.operate("session", key, "PUT", state())
    assert b.operate("session", key, "GET").data == created.data
    with world.sessions() as session:
        row = session.get(BrowserState, ("session", key))
        assert b"sensitive-api-token" not in row.ciphertext
        assert b"secret-csrf" not in row.ciphertext
    restarted = BrowserStore(world.sessions, settings)
    assert restarted.operate("session", key, "GET") == created
    b.operate("session", key, "DELETE")
    with pytest.raises(ApplicationError, match="Session expired"):
        a.operate("session", key, "GET")
    for _ in range(3):
        a.operate("session", secrets.token_urlsafe(32), "PUT", state())
    with pytest.raises(ApplicationError) as error:
        b.operate("session", secrets.token_urlsafe(32), "PUT", state())
    assert error.value.code == "session_capacity"


def test_login_consume_and_session_compare_swap_race(stores):
    _, _, a, b = stores
    login = secrets.token_urlsafe(32)
    a.operate("login", login, "PUT", state())

    def consume(store):
        try:
            return store.operate("login", login, "DELETE").revision
        except ApplicationError:
            return 0

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(consume, (a, b))) == [0, 1]
    key = secrets.token_urlsafe(32)
    old = a.operate("session", key, "PUT", state())

    def update(store):
        try:
            return store.operate("session", key, "PATCH", old).revision
        except ApplicationError:
            return 0

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(update, (a, b))) == [0, 2]
    a.operate("session", key, "DELETE")
    with pytest.raises(ApplicationError):
        b.operate("session", key, "PATCH", old)


def test_expiration_tampering_and_key_rotation(stores):
    world, settings, a, _ = stores  # noqa: F811
    key = secrets.token_urlsafe(32)
    a.operate("session", key, "PUT", state())
    rotated = settings.model_copy(
        update={
            "browser_state_keys": SecretStr(
                Fernet.generate_key().decode()
                + ","
                + settings.browser_state_keys.get_secret_value()
            )
        }
    )
    b = BrowserStore(world.sessions, rotated)
    old = b.operate("session", key, "GET")
    b.operate("session", key, "PATCH", old)
    with pytest.raises(ApplicationError) as error:
        a.operate("session", key, "GET")
    assert error.value.status_code == 503
    with world.sessions.begin() as session:
        row = session.get(BrowserState, ("session", key))
        row.expires_at = session.scalar(text("SELECT now() - interval '1 second'"))
    with pytest.raises(ApplicationError) as error:
        b.operate("session", key, "GET")
    assert error.value.status_code == 401


def test_internal_state_service_and_metrics_are_not_public(stores):
    _, settings, _, _ = stores
    app = create_app(settings)
    # Use the test's isolated schema, never the development application's state.
    app.state.browser_store = stores[2]
    with TestClient(app) as client:
        key = secrets.token_urlsafe(32)
        path = "/internal/browser-state/session/" + key
        assert client.get(path).status_code == 403
        assert client.get("/internal/metrics").status_code == 403
        headers = {"Authorization": "Bearer " + settings.browser_state_secret.get_secret_value()}
        assert client.put(path, headers=headers, json=state().model_dump()).status_code == 200
        assert client.get(path, headers=headers).status_code == 200
        assert (
            client.get("/internal/metrics", headers=headers).text.find("foundry_requests_total")
            >= 0
        )
        assert "/internal/" not in json.dumps(client.get("/api/v1/openapi.json").json())
        response = client.get("/health/live?secret=never-log", headers={"traceparent": "bad"})
        assert len(response.headers["traceparent"]) == 55
        assert response.headers["cache-control"] == "no-store"


def test_rate_budget_is_shared_and_atomic(world):  # noqa: F811
    def attempt(_):
        try:
            rate_limit(world.sessions, "same-verified-subject", 5)
            return True
        except ApplicationError as error:
            assert error.status_code == 429
            return False

    with ThreadPoolExecutor(8) as pool:
        assert sum(pool.map(attempt, range(12))) == 5


def test_artifact_quota_rolls_back_and_accounts_existing_content(world):  # noqa: F811
    from ontology_platform.sdk.service import GenerateInput, SDKService
    from test_phase1 import active

    active(world)
    with pytest.raises(ApplicationError), world.sessions.begin() as session:
        session.execute(text("SET LOCAL foundry.storage_limit = '1'"))
        scoped = SDKService(world.sessions, world.registry.authorizer, session=session)
        scoped.generate(
            world.actor,
            "manufacturing",
            GenerateInput(version=world.definition.version, language="python"),
            create_app(world.settings).openapi(),
        )
    with world.sessions() as session:
        assert session.get(TenantResourceUsage, world.actor.tenant_id) is None


def test_supervisor_kills_timed_out_process_and_stops():
    stop = threading.Event()
    started = time.monotonic()
    assert run_child([sys.executable, "-c", "import time; time.sleep(60)"], stop, 0.3) == 124
    assert time.monotonic() - started < 7
    stop.set()
    assert run_child([sys.executable, "-c", "import time; time.sleep(60)"], stop, 60) == 124


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"auth_mode": "local"},
        {"auth_mode": "test"},
        {"public_origin": "http://localhost"},
        {"allowed_hosts": ("*",)},
    ],
)
def test_production_configuration_fails_closed(value):
    with pytest.raises(ValidationError):
        Settings(
            database_url=SecretStr("postgresql+psycopg://localhost/test"),
            environment="production",
            _env_file=None,
            **value,
        )


def test_keycloak_profile_and_provider_configuration():
    from uuid import UUID

    config = realm_configuration(
        "https://identity.example/realms/foundry",
        "https://studio.example",
        entra_tenant=UUID(int=1),
        entra_client="entra-client",
        google_client="google-client",
        workspace_client="workspace-client",
        workspace_domain="example.org",
    )
    client = config["clients"][0]
    assert client["attributes"]["access.token.header.type.rfc9068"] == "true"
    assert client["attributes"]["pkce.code.challenge.method"] == "S256"
    assert client["directAccessGrantsEnabled"] is False
    assert not config.get("users")
    assert not client["fullScopeAllowed"]
    providers = {p["alias"]: p for p in config["identityProviders"]}
    assert providers["entra"]["config"]["issuer"].endswith(
        "00000000-0000-0000-0000-000000000001/v2.0"
    )
    assert providers["workspace"]["config"]["hostedDomain"] == "example.org"
    assert all(not p["trustEmail"] and not p["storeToken"] for p in providers.values())
    assert all(
        p["firstBrokerLoginFlowAlias"] == "foundry-deny-unlinked" for p in providers.values()
    )
    assert (
        config["authenticationFlows"][0]["authenticationExecutions"][0]["authenticator"]
        == "deny-access-authenticator"
    )


@pytest.mark.parametrize(
    "arguments",
    [
        {"issuer": "http://identity.example/realms/foundry"},
        {"issuer": "https://identity.example/not-a-realm"},
        {"workspace_client": "client"},
        {"workspace_client": "client", "workspace_domain": "*"},
        {"workspace_client": "client", "workspace_domain": "evil.example,example.org"},
        {"entra_client": "client"},
    ],
)
def test_broker_rejects_ambiguous_configuration(arguments):
    with pytest.raises(ValueError):
        realm_configuration(
            **(
                {
                    "issuer": "https://identity.example/realms/foundry",
                    "studio_origin": "https://studio.example",
                }
                | arguments
            )
        )


def test_sdk_independent_verifier_rejects_tampering(world):  # noqa: F811
    import hashlib

    from ontology_platform.sdk.generator import GENERATOR_VERSION, generate
    from ontology_platform.sdk.integrity import verify_archive

    generated = generate(world.definition, "python", create_app(world.settings).openapi())
    archive = generated.archive()
    digest = hashlib.sha256(archive).hexdigest()
    assert (
        verify_archive(archive, digest, generator_version=GENERATOR_VERSION)["ontology_id"]
        == "manufacturing"
    )
    with pytest.raises(ValueError):
        verify_archive(archive + b"tampered", digest)
    generated.files["README.md"] += "tampered"
    corrupted = generated.archive()
    with pytest.raises(ValueError, match="Manifest file hash"):
        verify_archive(corrupted, hashlib.sha256(corrupted).hexdigest())
    with pytest.raises(ValueError):
        verify_archive(archive, digest, schema_hash="wrong-schema")


def test_pending_job_admission_rolls_back(database, tmp_path):  # noqa: F811
    from ontology_platform.ingestion.contracts import MappingRef, RunInput
    from ontology_platform.ingestion.service import IngestionService
    from test_ingestion import setup

    fixture, service, _ = setup(database, tmp_path)
    with pytest.raises(ApplicationError), fixture.sessions.begin() as session:
        session.execute(text("SET LOCAL foundry.job_limit = '1'"))
        scoped = IngestionService(
            fixture.sessions, service.authorizer, service.catalog, session=session
        )
        for key in ("one", "two"):
            scoped.submit(
                fixture.actor,
                "manufacturing",
                RunInput(idempotency_key=key, mappings=[MappingRef(id="Factory", version=1)]),
            )
    from ontology_platform.db.models import IngestionRun
    from sqlalchemy import func, select

    with fixture.sessions() as session:
        assert session.scalar(select(func.count()).select_from(IngestionRun)) == 0


def test_transport_size_and_time_bounds():
    import asyncio

    from fastapi import FastAPI
    from ontology_platform.operations import TransportBounds

    inner = FastAPI()

    @inner.get("/large")
    def large():
        return "x" * 200

    @inner.get("/slow")
    async def slow():
        await asyncio.sleep(1)

    with TestClient(
        TransportBounds(inner, request_bytes=10, response_bytes=100, deadline=0.05)
    ) as client:
        assert client.post("/large", content="x" * 11).status_code == 413
        assert client.get("/large").status_code == 503
        assert client.get("/slow").status_code == 504


def test_worker_client_credentials_preserve_authority(world, monkeypatch):  # noqa: F811
    from datetime import UTC, datetime, timedelta

    import httpx
    from ontology_platform.security import workers
    from ontology_platform.security.admin import SecurityAdministration
    from ontology_platform.security.bootstrap import bootstrap
    from ontology_platform.security.contracts import AssignmentInput, IdentityInput
    from ontology_platform.security.identity import resolve
    from ontology_platform.security.service import PlatformAuthorizer
    from test_security_oidc import ISSUER, token
    from test_security_oidc import idp as fixture

    original = fixture.__wrapped__()
    private, state, verifier = next(original)
    state["metadata"]["token_endpoint"] = ISSUER + "/token"
    seen = []

    def transport(request):
        if request.method == "POST":
            seen.append(request.content.decode())
            body = {"token_type": "Bearer", "access_token": token(private)}
        else:
            body = (
                state["metadata"]
                if request.url.path.endswith("openid-configuration")
                else {"keys": state["keys"]}
            )
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps(body).encode()))

    verifier.client.close()
    verifier.client = httpx.Client(transport=httpx.MockTransport(transport))
    monkeypatch.setattr(workers, "OIDCVerifier", lambda *a, **k: verifier)
    with world.sessions.begin() as session:
        bootstrap(session, world.actor.tenant_id, ISSUER, "admin", "Worker test")
    admin = resolve(
        world.sessions,
        ISSUER,
        "admin",
        world.actor.tenant_id,
        method="oidc",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    administration = SecurityAdministration(PlatformAuthorizer(world.sessions))
    worker = administration.identity(
        admin, IdentityInput(issuer=ISSUER, subject="alice", principal_type="service")
    )
    administration.assign(
        admin, AssignmentInput(principal_id=worker, role_id="tenant-administrator")
    )
    settings = world.settings.model_copy(
        update={
            "auth_mode": "oidc",
            "trusted_local_identity": False,
            "oidc_providers": verifier.providers,
            "worker_tenant_id": world.actor.tenant_id,
            "worker_client_id": "studio",
            "worker_provider_id": "example",
            "worker_access_token": None,
            "worker_client_secret": SecretStr("service-secret"),
        }
    )
    try:
        actor, _ = workers.worker_context(settings, world.sessions, "outbox", "manufacturing")
        assert actor.principal_type == "service"
        assert actor.principal_id == worker
        assert len(seen) == 1 and "grant_type=client_credentials" in seen[0]
    finally:
        original.close()
