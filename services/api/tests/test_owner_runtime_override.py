"""The API runtime-role override is explicit and leaves OIDC startup enabled."""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from ontology_platform.config import Settings
from ontology_platform.errors import ApplicationError
from ontology_platform.main import create_app


def test_owner_runtime_override_defaults_to_false(monkeypatch):
    monkeypatch.delenv("FOUNDRY_ALLOW_OWNER_RUNTIME_ROLE", raising=False)
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://unused/unused")
    assert settings.allow_owner_runtime_role is False


@pytest.mark.parametrize("enabled", [False, True])
def test_production_api_role_override(monkeypatch, enabled):
    monkeypatch.setenv("FOUNDRY_ALLOW_OWNER_RUNTIME_ROLE", str(enabled).lower())
    monkeypatch.setenv("FOUNDRY_ARTIFACT_BACKEND", "disabled")
    check = Mock(side_effect=ApplicationError("runtime_role_unsafe", "Unsafe role", 503))
    monkeypatch.setattr("ontology_platform.main.require_runtime_role", check)
    settings = Settings(
        _env_file=None,
        environment="production",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        auth_mode="oidc",
        public_origin="https://studio.example.test",
        allowed_hosts=("api",),
        oidc_providers=(
            {
                "id": "keycloak",
                "issuer": "https://identity.example.test/realms/foundry",
                "audience": "foundry-api",
                "clients": ["studio", "worker"],
                "algorithms": ["RS256"],
            },
        ),
        browser_state_secret="x" * 43,
        browser_state_keys="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        query_cursor_secret="x" * 32,
    )
    assert settings.allow_owner_runtime_role is enabled
    app = create_app(settings)
    warm = Mock()
    monkeypatch.setattr(app.state.oidc, "warm", warm)
    if enabled:
        with TestClient(app):
            warm.assert_called_once_with()
        check.assert_not_called()
    else:
        with pytest.raises(ApplicationError, match="Unsafe role"), TestClient(app):
            pass
        check.assert_called_once_with(app.state.sessions)
        warm.assert_not_called()
