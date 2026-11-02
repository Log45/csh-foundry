"""Keycloak administrative realm configuration; runtime application auth stays standard OIDC."""

from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from ontology_platform.security.oidc import https_url

KEYCLOAK_VERSION = "26.8.1"


def realm_configuration(
    issuer: str,
    studio_origin: str,
    *,
    entra_tenant: UUID | None = None,
    entra_client: str | None = None,
    google_client: str | None = None,
    workspace_client: str | None = None,
    workspace_domain: str | None = None,
) -> dict[str, Any]:
    """No credentials, users, identity bindings or platform roles are generated."""
    https_url(issuer)
    https_url(studio_origin)
    origin = urlsplit(studio_origin)
    realm = urlsplit(issuer).path.split("/")
    if len(realm) != 3 or realm[1] != "realms" or not realm[2].replace("-", "").isalnum():
        raise ValueError("Issuer must use /realms/REALM")
    if origin.path not in ("", "/"):
        raise ValueError("Studio origin must not include a path")
    studio_origin = studio_origin.rstrip("/")
    if bool(entra_tenant) != bool(entra_client):
        raise ValueError("Entra requires an explicit organization tenant UUID and client")
    if bool(workspace_client) != bool(workspace_domain):
        raise ValueError("Workspace requires a client and exact managed domain")
    if workspace_domain:
        import re

        if not re.fullmatch(
            r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+",
            workspace_domain,
        ):
            raise ValueError("Workspace requires one exact lowercase DNS domain")
    providers: list[dict[str, Any]] = []

    def provider(alias: str, type_id: str, config: dict[str, str]) -> None:
        providers.append(
            {
                "alias": alias,
                "providerId": type_id,
                "enabled": True,
                "trustEmail": False,
                "storeToken": False,
                "addReadTokenRoleOnCreate": False,
                "linkOnly": False,
                "firstBrokerLoginFlowAlias": "foundry-deny-unlinked",
                "config": config | {"syncMode": "IMPORT"},
            }
        )

    if entra_tenant:
        base = f"https://login.microsoftonline.com/{entra_tenant}"
        provider(
            "entra",
            "oidc",
            {
                "clientId": str(entra_client),
                "clientSecret": "${ENTRA_CLIENT_SECRET}",
                "authorizationUrl": base + "/oauth2/v2.0/authorize",
                "tokenUrl": base + "/oauth2/v2.0/token",
                "issuer": base + "/v2.0",
                "jwksUrl": base + "/discovery/v2.0/keys",
                "useJwksUrl": "true",
                "validateSignature": "true",
                "pkceEnabled": "true",
                "pkceMethod": "S256",
                "defaultScope": "openid profile email",
                "clientAuthMethod": "client_secret_post",
            },
        )
    for alias, client in (("google", google_client), ("workspace", workspace_client)):
        if client:
            provider(
                alias,
                "google",
                {
                    "clientId": client,
                    "clientSecret": "${GOOGLE_CLIENT_SECRET}"
                    if alias == "google"
                    else "${WORKSPACE_CLIENT_SECRET}",
                    "defaultScope": "openid profile email",
                    "offlineAccess": "false",
                    **({"hostedDomain": workspace_domain or ""} if alias == "workspace" else {}),
                },
            )
    result: dict[str, Any] = {
        "realm": realm[2],
        "enabled": True,
        "sslRequired": "all",
        "registrationAllowed": False,
        "resetPasswordAllowed": False,
        "loginWithEmailAllowed": False,
        "duplicateEmailsAllowed": False,
        "editUsernameAllowed": False,
        "rememberMe": False,
        "bruteForceProtected": True,
        "failureFactor": 5,
        "maxFailureWaitSeconds": 900,
        "accessTokenLifespan": 300,
        "ssoSessionIdleTimeout": 1800,
        "ssoSessionMaxLifespan": 3600,
        "defaultSignatureAlgorithm": "RS256",
        "eventsEnabled": True,
        "eventsExpiration": 604800,
        "adminEventsEnabled": True,
        "adminEventsDetailsEnabled": False,
        "authenticationFlows": [
            {
                "alias": "foundry-deny-unlinked",
                "description": "Operator-verified external links only",
                "providerId": "basic-flow",
                "topLevel": True,
                "builtIn": False,
                "authenticationExecutions": [
                    {
                        "authenticator": "deny-access-authenticator",
                        "requirement": "REQUIRED",
                        "priority": 10,
                        "authenticatorFlow": False,
                    }
                ],
            }
        ],
        "identityProviders": providers,
        "clients": [
            {
                "clientId": "studio",
                "protocol": "openid-connect",
                "enabled": True,
                "publicClient": True,
                "standardFlowEnabled": True,
                "implicitFlowEnabled": False,
                "directAccessGrantsEnabled": False,
                "serviceAccountsEnabled": False,
                "fullScopeAllowed": False,
                "redirectUris": [studio_origin + "/auth/callback"],
                "webOrigins": [studio_origin],
                "defaultClientScopes": ["basic"],
                "optionalClientScopes": [],
                "attributes": {
                    "pkce.code.challenge.method": "S256",
                    "access.token.header.type.rfc9068": "true",
                    "access.token.signed.response.alg": "RS256",
                    "id.token.signed.response.alg": "RS256",
                    "use.refresh.tokens": "false",
                    "client.use.lightweight.access.token.enabled": "false",
                    "post.logout.redirect.uris": studio_origin,
                    "standard.token.exchange.enabled": "false",
                },
                "protocolMappers": [
                    {
                        "name": "platform-api-audience",
                        "protocol": "openid-connect",
                        "protocolMapper": "oidc-audience-mapper",
                        "config": {
                            "included.custom.audience": "foundry-api",
                            "access.token.claim": "true",
                            "id.token.claim": "false",
                            "introspection.token.claim": "true",
                        },
                    },
                    {
                        "name": "platform-client-id",
                        "protocol": "openid-connect",
                        "protocolMapper": "oidc-hardcoded-claim-mapper",
                        "config": {
                            "claim.name": "client_id",
                            "claim.value": "studio",
                            "jsonType.label": "String",
                            "access.token.claim": "true",
                            "id.token.claim": "false",
                            "userinfo.token.claim": "false",
                            "introspection.token.claim": "true",
                        },
                    },
                ],
            }
        ],
    }

    import copy

    worker = copy.deepcopy(result["clients"][0])
    worker.update(
        {
            "clientId": "worker",
            "publicClient": False,
            "standardFlowEnabled": False,
            "serviceAccountsEnabled": True,
            "secret": "${WORKER_CLIENT_SECRET}",
            "redirectUris": [],
            "webOrigins": [],
        }
    )
    worker["protocolMappers"][1]["config"]["claim.value"] = "worker"
    result["clients"].append(worker)
    return result
