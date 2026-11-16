import json
from urllib.parse import parse_qs

import httpx
import pytest
from ontology_platform.config import Settings
from ontology_platform.errors import ApplicationError
from ontology_platform.security.directory import search_users
from ontology_platform.security.oidc import OIDCVerifier, Provider
from pydantic import SecretStr

ISSUER = "https://identity.example/auth/realms/foundry"
TOKEN_PATH = "/auth/realms/foundry/protocol/openid-connect/token"


def settings():
    return Settings(
        _env_file=None,
        database_url=SecretStr("postgresql+psycopg://unused/unused"),
        auth_mode="oidc",
        directory_provider_id="keycloak",
        directory_client_id="directory",
        directory_client_secret=SecretStr("test-only"),
        oidc_providers=(
            Provider(
                id="keycloak",
                issuer=ISSUER,
                audience="foundry",
                clients=("studio", "worker"),
                access_token_profile="keycloak",
            ),
        ),
    )


def test_directory_queries_only_configured_realm_and_returns_enabled_users():
    config = settings()
    paths = []

    def response(payload):
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps(payload).encode()))

    def transport(request):
        paths.append(request.url.path)
        if request.url.path.endswith("openid-configuration"):
            return response(
                {
                    "issuer": ISSUER,
                    "token_endpoint": "https://identity.example" + TOKEN_PATH,
                },
            )
        if request.url.path == TOKEN_PATH:
            assert parse_qs(request.content.decode()) == {
                "grant_type": ["client_credentials"],
                "client_id": ["directory"],
                "client_secret": ["test-only"],
            }
            return response({"access_token": "directory-token"})
        assert request.url.path == "/auth/admin/realms/foundry/users"
        assert request.headers["authorization"] == "Bearer directory-token"
        assert dict(request.url.params) == {
            "search": "Ali",
            "enabled": "true",
            "briefRepresentation": "true",
            "max": "50",
        }
        return response(
            [
                {
                    "id": "first",
                    "username": "alice",
                    "enabled": True,
                    "email": "alice@example.test",
                },
                {"id": "second", "username": "alicia", "enabled": False},
            ],
        )

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        verifier = OIDCVerifier(config.oidc_providers, client=client)
        assert search_users(config, verifier, ISSUER, "*") == []
        with pytest.raises(ApplicationError) as error:
            search_users(config, verifier, "https://other.example", "Ali")
        assert error.value.code == "directory_unconfigured"
        assert not paths
        assert [user.model_dump() for user in search_users(config, verifier, ISSUER, "Ali")] == [
            {"subject": "first", "label": "alice"},
        ]
