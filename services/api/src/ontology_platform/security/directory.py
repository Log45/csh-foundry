"""Bounded search of the operator-configured Keycloak realm."""

from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel

from ontology_platform.config import Settings
from ontology_platform.errors import ApplicationError
from ontology_platform.security.oidc import OIDCVerifier, https_url


class DirectoryUser(BaseModel):
    subject: str
    label: str


def search_users(
    settings: Settings, verifier: OIDCVerifier, issuer: str | None, search: str
) -> list[DirectoryUser]:
    provider = next(
        (
            p
            for p in settings.oidc_providers
            if p.id == settings.directory_provider_id and p.issuer == issuer
        ),
        None,
    )
    secret = settings.directory_client_secret
    client_id = settings.directory_client_id
    if provider is None or not client_id or secret is None:
        raise ApplicationError("directory_unconfigured", "Recipient directory is unavailable", 503)
    search = search.strip()
    if sum(char.isalnum() for char in search) < 2 or any(char in search for char in '*:"'):
        return []
    base, separator, realm = provider.issuer.rstrip("/").rpartition("/realms/")
    if not separator or not realm or "/" in realm:
        raise ApplicationError("directory_unconfigured", "Recipient directory is unavailable", 503)
    try:
        metadata = verifier.document(
            provider.issuer.rstrip("/") + "/.well-known/openid-configuration"
        )
        endpoint = metadata.get("token_endpoint")
        if (
            metadata.get("issuer") != provider.issuer
            or not isinstance(endpoint, str)
            or urlsplit(https_url(endpoint)).netloc != urlsplit(provider.issuer).netloc
        ):
            raise ValueError("Invalid directory discovery")
        token = verifier.document(
            endpoint,
            form={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": secret.get_secret_value(),
            },
        )
        bearer = token.get("access_token")
        if not isinstance(bearer, str) or not bearer or len(bearer) > 16384:
            raise ValueError("Invalid directory token")
        users = verifier.response_json(
            f"{base}/admin/realms/{realm}/users",
            headers={"Authorization": f"Bearer {bearer}"},
            params={
                "search": search,
                "enabled": "true",
                "briefRepresentation": "true",
                "max": "50",
            },
        )
        if not isinstance(users, list) or len(users) > 50:
            raise ValueError("Invalid directory response")
        return [
            DirectoryUser(subject=user["id"], label=user["username"][:200])
            for user in users
            if isinstance(user, dict)
            and user.get("enabled") is True
            and isinstance(user.get("id"), str)
            and 0 < len(user["id"]) <= 512
            and isinstance(user.get("username"), str)
            and user["username"].strip()
        ]
    except (ValueError, httpx.HTTPError):
        raise ApplicationError(
            "directory_unavailable", "Recipient directory is unavailable", 503
        ) from None
