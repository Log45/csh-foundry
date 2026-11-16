"""Owner runtime is a narrow catalog-policy exception, shared by API and all workers."""

import runpy
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from fastapi.testclient import TestClient
from ontology_platform.config import Settings
from ontology_platform.db.session import require_runtime_role
from ontology_platform.errors import ApplicationError
from ontology_platform.main import create_app
from ontology_platform.security.workers import WorkerPool

ROOT = Path(__file__).resolve().parents[3]
ISSUER = "https://identity.example.test/realms/foundry"


def production(enabled):
    return Settings(
        _env_file=None,
        environment="production",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        allow_owner_runtime_role=enabled,
        auth_mode="oidc",
        public_origin="https://studio.example.test",
        allowed_hosts=("api",),
        oidc_providers=(
            {
                "id": "keycloak",
                "issuer": ISSUER,
                "audience": "foundry-api",
                "clients": ["studio", "worker"],
                "algorithms": ["RS256"],
            },
        ),
        browser_state_secret="x" * 43,
        browser_state_keys="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        query_cursor_secret="x" * 32,
        worker_access_token="verified-by-test-verifier",
    )


def catalog(*, owner, privileged=False):
    sessions = MagicMock()
    sessions.return_value.__enter__.return_value.scalar.side_effect = [privileged, owner]
    return sessions


def test_owner_runtime_override_defaults_to_false(monkeypatch):
    monkeypatch.delenv("FOUNDRY_ALLOW_OWNER_RUNTIME_ROLE", raising=False)
    assert (
        Settings(
            _env_file=None, database_url="postgresql+psycopg://unused/unused"
        ).allow_owner_runtime_role
        is False
    )


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("owner", [False, True])
@pytest.mark.parametrize("privileged", [False, True])
def test_catalog_exception_is_limited_to_ownership(enabled, owner, privileged):
    sessions = catalog(owner=owner, privileged=privileged)
    if privileged or (owner and not enabled):
        with pytest.raises(ApplicationError) as error:
            require_runtime_role(sessions, allow_owner_runtime_role=enabled)
        assert error.value.code == "runtime_role_unsafe"
    else:
        require_runtime_role(sessions, allow_owner_runtime_role=enabled)


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("privileged", [False, True])
def test_production_api_role_override_keeps_oidc_and_authentication(
    monkeypatch, enabled, privileged
):
    monkeypatch.setenv("FOUNDRY_ARTIFACT_BACKEND", "disabled")
    app = create_app(production(enabled))
    app.state.sessions = catalog(owner=True, privileged=privileged)
    warm = Mock()
    monkeypatch.setattr(app.state.oidc, "warm", warm)
    if enabled and not privileged:
        with TestClient(app) as client:
            warm.assert_called_once_with()
            assert client.get("/api/v1/security/me", headers={"host": "api"}).status_code == 401
    else:
        with pytest.raises(ApplicationError), TestClient(app):
            pass
        warm.assert_not_called()


@pytest.mark.parametrize("enabled", [False, True])
def test_worker_startup_verifies_credentials_without_tenant(monkeypatch, enabled):
    settings = production(enabled)
    verifier = Mock()
    verifier.verify.return_value = (
        SimpleNamespace(issuer=ISSUER),
        {
            "sub": "service-subject",
            "client_id": "worker",
            "exp": (datetime.now(UTC) + timedelta(hours=1)).timestamp(),
        },
    )
    monkeypatch.setattr(
        "ontology_platform.security.workers.OIDCVerifier", Mock(return_value=verifier)
    )
    service = Mock(return_value=None)
    monkeypatch.setattr(WorkerPool, "service_id", service)
    if not enabled:
        with pytest.raises(ApplicationError):
            WorkerPool(settings, catalog(owner=True))
        verifier.verify.assert_not_called()
        service.assert_not_called()
        return
    pool = WorkerPool(settings, catalog(owner=True))
    assert pool.scopes("execution") == []
    verifier.verify.assert_called_once_with("verified-by-test-verifier")
    verifier.client.close.assert_called_once_with()


@pytest.mark.parametrize("failure", ["credentials", "token", "client", "human"])
def test_owner_mode_does_not_bypass_worker_security(monkeypatch, failure):
    settings = production(True)
    if failure == "credentials":
        settings.worker_access_token = None
    verifier = Mock()
    verifier.verify.return_value = (
        SimpleNamespace(issuer=ISSUER),
        {
            "sub": "worker",
            "client_id": "studio" if failure == "client" else "worker",
            "exp": (datetime.now(UTC) + timedelta(hours=1)).timestamp(),
        },
    )
    if failure == "token":
        verifier.verify.side_effect = ApplicationError("invalid_token", "Invalid token", 401)
    monkeypatch.setattr(
        "ontology_platform.security.workers.OIDCVerifier", Mock(return_value=verifier)
    )
    sessions = catalog(owner=True)
    connection = sessions.return_value.__enter__.return_value
    connection.get.side_effect = [
        SimpleNamespace(principal_id="worker"),
        SimpleNamespace(principal_type="user", enabled=True),
    ]
    with pytest.raises(ApplicationError) as error:
        WorkerPool(settings, sessions)
    assert error.value.code == (
        "invalid_token" if failure == "token" else "worker_identity_required"
    )


def test_owner_provisioning_never_connects_as_admin_or_changes_grants(monkeypatch, capsys):
    script = runpy.run_path(str(ROOT / "scripts/provision_production_database.py"))
    monkeypatch.setenv("FOUNDRY_ALLOW_OWNER_RUNTIME_ROLE", "true")
    monkeypatch.delenv("FOUNDRY_ADMIN_DATABASE_URL", raising=False)
    monkeypatch.setattr(sys, "argv", ["provision", "--apply", "--grant-runtime"])
    monkeypatch.setattr("psycopg.connect", Mock(side_effect=AssertionError("No admin connection")))
    engine = Mock()
    monkeypatch.setattr(
        "ontology_platform.config.get_settings", Mock(return_value=production(True))
    )
    monkeypatch.setattr("ontology_platform.db.session.make_engine", Mock(return_value=engine))
    check = Mock()
    monkeypatch.setattr("ontology_platform.db.session.require_runtime_role", check)
    script["main"]()
    assert check.call_args.kwargs == {"allow_owner_runtime_role": True}
    engine.dispose.assert_called_once_with()
    assert "no roles, databases or grants changed" in capsys.readouterr().out


@pytest.mark.parametrize("enabled", [False, True])
def test_owner_runtime_flag_loads_from_environment(monkeypatch, enabled):
    monkeypatch.setenv("FOUNDRY_ALLOW_OWNER_RUNTIME_ROLE", str(enabled).lower())
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://unused/unused")
    assert settings.allow_owner_runtime_role is enabled
