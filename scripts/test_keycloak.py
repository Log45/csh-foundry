"""Actual pinned broker Code/PKCE contract, in a disposable loopback-only container."""

import argparse
import base64
import hashlib
import html
import json
import os
import re
import secrets
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID, uuid4

import httpx
import jwt
from ontology_platform.errors import ApplicationError
from ontology_platform.security.broker import KEYCLOAK_VERSION, realm_configuration
from ontology_platform.security.oidc import OIDCVerifier, Provider

ISSUER = "https://identity.phase10.test/realms/phase10"
ORIGIN = "https://studio.phase10.test"
ONBOARDING_ROLE = "foundry-personal-workspace"
DIRECTORY_ID = "foundry-directory-test"
DIRECTORY_SUBJECT = "1512cd7d-fd13-4d2e-8c2f-ea0520a20156"


def test_onboarding(
    url: str,
    proxy: httpx.Client,
    token: str,
    worker_token: str,
    worker_subject: str,
    directory_secret: str,
) -> None:
    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient
    from ontology_platform.config import Settings
    from ontology_platform.db.models import ExternalIdentity, Membership, PersonalTenant
    from ontology_platform.main import create_app
    from pydantic import SecretStr
    from sqlalchemy import create_engine, select, text

    schema = "test_keycloak_phase22_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema}"})
    try:
        configuration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        with engine.begin() as connection:
            configuration.attributes["connection"] = connection
            command.upgrade(configuration, "head")
        provider = Provider(
            id="keycloak",
            issuer=ISSUER,
            audience="foundry-api",
            clients=("studio", "worker"),
            access_token_profile="keycloak",
            personal_tenant_client="studio",
            personal_tenant_role=ONBOARDING_ROLE,
        )
        app = create_app(
            Settings(
                _env_file=None,
                database_url=url,
                database_schema=schema,
                auth_mode="oidc",
                oidc_providers=(provider,),
                worker_provider_id="keycloak",
                worker_subject=worker_subject,
                directory_provider_id="keycloak",
                directory_client_id=DIRECTORY_ID,
                directory_client_secret=SecretStr(directory_secret),
            )
        )
        app.state.oidc.client.close()
        app.state.oidc = OIDCVerifier((provider,), client=proxy)
        with TestClient(app) as api:
            path = "/api/v1/security/personal-tenant"
            human = {"Authorization": "Bearer " + token}
            worker = {"Authorization": "Bearer " + worker_token}
            assert api.get("/api/v1/security/tenants", headers=human).status_code == 403
            assert api.post(path, headers=worker).status_code == 403
            first = api.post(path, headers=human)
            assert first.status_code == 200, first.json()
            tenant = UUID(first.json()["personal_tenant_id"])
            assert api.post(path, headers=human).json() == first.json()
            assert api.post(path, headers=worker).status_code == 403
            with app.state.sessions() as session:
                assert session.scalars(select(PersonalTenant.tenant_id)).all() == [tenant]
                identity = session.get(ExternalIdentity, (ISSUER, worker_subject))
                assert session.get(Membership, (tenant, identity.principal_id)).enabled
            human["X-Tenant-ID"] = str(tenant)
            registered = api.post(
                "/api/v1/security/identities",
                headers=human,
                json={
                    "issuer": ISSUER,
                    "subject": DIRECTORY_SUBJECT,
                    "principal_type": "user",
                },
            )
            assert registered.status_code == 201, registered.json()
            directory = api.get("/api/v1/shares/recipients?search=Directory", headers=human)
            assert directory.status_code == 200, directory.json()
            assert directory.json() == [
                {
                    "id": registered.json()["principal_id"],
                    "label": "directory-person",
                }
            ]
        print("PASS Keycloak realm role onboards one personal tenant and denies service onboarding")
        print("PASS Keycloak directory search resolves username to a Foundry principal ID")
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase22", action="store_true", help="Also verify personal onboarding")
    parser.add_argument(
        "--directory-profile",
        action="store_true",
        help="Verify preferred_username with a disposable Studio client that permits profile",
    )
    args = parser.parse_args()
    phase22 = args.phase22
    database_url = os.environ.get("TEST_DATABASE_URL", "")
    if phase22 and not database_url:
        parser.error("--phase22 needs TEST_DATABASE_URL pointing to a disposable database")
    container = None
    with tempfile.TemporaryDirectory(prefix="foundry-keycloak-test-") as directory:
        configuration = realm_configuration(
            ISSUER,
            ORIGIN,
            entra_tenant=UUID("00000000-0000-0000-0000-000000000001"),
            entra_client="disposable-entra-client",
            google_client="disposable-google-client",
            workspace_client="disposable-workspace-client",
            workspace_domain="example.test",
        )
        # Import compatibility only. Never invoke these external providers or use real credentials.
        for upstream in configuration["identityProviders"]:
            upstream["config"]["clientSecret"] = secrets.token_urlsafe(32)
        # Test transport only: no HTTP exception is added to the platform verifier.
        configuration["sslRequired"] = "none"
        password = secrets.token_urlsafe(32)
        worker_secret = secrets.token_urlsafe(32)
        directory_secret = secrets.token_urlsafe(32)
        configuration["clients"][1]["secret"] = worker_secret
        configuration["users"] = [
            {
                "username": "operator",
                "firstName": "Test",
                "lastName": "Operator",
                "email": "operator@example.test",
                "emailVerified": True,
                "enabled": True,
                "credentials": [{"type": "password", "value": password, "temporary": False}],
            }
        ]
        if args.directory_profile:
            configuration["clients"][0]["optionalClientScopes"].append("profile")
        if phase22:
            configuration["roles"] = {"realm": [{"name": ONBOARDING_ROLE}]}
            configuration["scopeMappings"] = [{"client": "studio", "roles": [ONBOARDING_ROLE]}]
            configuration["clients"][0]["defaultClientScopes"].append("roles")
            configuration["users"][0]["realmRoles"] = [ONBOARDING_ROLE]
            configuration["clients"].append(
                {
                    "clientId": DIRECTORY_ID,
                    "protocol": "openid-connect",
                    "enabled": True,
                    "publicClient": False,
                    "secret": directory_secret,
                    "serviceAccountsEnabled": True,
                    "standardFlowEnabled": False,
                    "directAccessGrantsEnabled": False,
                    "fullScopeAllowed": False,
                    "defaultClientScopes": ["basic", "roles"],
                }
            )
            configuration["clientScopeMappings"] = {
                "realm-management": [{"client": DIRECTORY_ID, "roles": ["view-users"]}],
            }
            configuration["users"].extend(
                [
                    {
                        "username": "service-account-" + DIRECTORY_ID,
                        "enabled": True,
                        "serviceAccountClientId": DIRECTORY_ID,
                        "clientRoles": {"realm-management": ["view-users"]},
                    },
                    {"id": DIRECTORY_SUBJECT, "username": "directory-person", "enabled": True},
                    {"username": "directory-unprovisioned", "enabled": True},
                ]
            )
        path = Path(directory) / "phase10-realm.json"
        path.write_text(json.dumps(configuration))
        path.chmod(0o644)  # Disposable generated test credentials, removed in finally.
        try:
            container = subprocess.check_output(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-d",
                    *(["--pull", "never"] if phase22 else []),
                    "-p",
                    "127.0.0.1::8080",
                    "-v",
                    f"{path}:/opt/keycloak/data/import/phase10-realm.json:ro",
                    f"quay.io/keycloak/keycloak:{KEYCLOAK_VERSION}"
                    "@sha256:3f3c5f8e03c614774b4bd9173b88391fefa4153bfc010d8012d59ad825377332",
                    "start-dev",
                    "--hostname",
                    "https://identity.phase10.test",
                    "--import-realm",
                ],
                text=True,
            ).strip()
            binding = subprocess.check_output(["docker", "port", container, "8080"], text=True)
            base = "http://127.0.0.1:" + binding.strip().rsplit(":", 1)[1]
            client = httpx.Client(timeout=5, follow_redirects=False, trust_env=False)
            for _ in range(180):
                try:
                    if (
                        client.get(
                            base + "/realms/phase10/.well-known/openid-configuration"
                        ).status_code
                        == 200
                    ):
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
            else:
                raise RuntimeError("Pinned Keycloak did not become ready")
            print("PASS pinned Keycloak imports Entra/Google/Workspace provider configurations")

            def local(url):
                parsed = urlsplit(str(url))
                return base + parsed.path + ("?" + parsed.query if parsed.query else "")

            verifier = secrets.token_urlsafe(32)
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .decode()
                .rstrip("=")
            )
            parameters = {
                "client_id": "studio",
                "redirect_uri": ORIGIN + "/auth/callback",
                "response_type": "code",
                "scope": "openid profile" if args.directory_profile else "openid",
                "state": secrets.token_urlsafe(32),
                "nonce": secrets.token_urlsafe(32),
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
            authorize = ISSUER + "/protocol/openid-connect/auth?"
            missing = {k: v for k, v in parameters.items() if not k.startswith("code_challenge")}
            rejected = client.get(local(authorize + urlencode(missing)))
            assert rejected.status_code == 302
            assert "error=" in rejected.headers["location"]
            print("PASS pinned Keycloak rejects missing PKCE")

            page = client.get(local(authorize + urlencode(parameters)))
            action = re.search(r'<form[^>]*action="([^"]+)"', page.text)
            if not action:
                raise RuntimeError("Expected Keycloak login form")
            login = client.post(
                local(html.unescape(action[1])),
                data={"username": "operator", "password": password},
                headers={"Cookie": "; ".join(f"{k}={v}" for k, v in client.cookies.items())},
            )
            location = login.headers.get("location", "")
            if not location.startswith(ORIGIN + "/auth/callback?"):
                title = re.search(r"<title>(.*?)</title>", login.text, re.S)
                raise RuntimeError(
                    f"Login returned {login.status_code}, path {urlsplit(location).path}, "
                    f"title {title[1].strip() if title else None}"
                )
            callback = parse_qs(urlsplit(location).query)
            assert callback["state"] == [parameters["state"]]
            payload = {
                "grant_type": "authorization_code",
                "client_id": "studio",
                "code": callback["code"][0],
                "redirect_uri": ORIGIN + "/auth/callback",
                "code_verifier": verifier,
            }
            token_url = local(ISSUER + "/protocol/openid-connect/token")
            response = client.post(token_url, data=payload)
            response.raise_for_status()
            tokens = response.json()
            assert "refresh_token" not in tokens

            def transport(request):
                # Map trusted IdP calls to this disposable local container.
                actual = client.request(
                    request.method,
                    local(request.url),
                    content=request.content,
                    headers={
                        k: request.headers[k]
                        for k in ("content-type", "authorization")
                        if k in request.headers
                    },
                )
                return httpx.Response(actual.status_code, stream=httpx.ByteStream(actual.content))

            provider = Provider(
                id="keycloak", issuer=ISSUER, audience="foundry-api", clients=("studio", "worker")
            )
            with httpx.Client(transport=httpx.MockTransport(transport)) as proxy:
                oidc = OIDCVerifier((provider,), client=proxy)
                _, claims = oidc.verify(tokens["access_token"])
                assert claims["client_id"] == "studio"
                if args.directory_profile:
                    assert claims["preferred_username"] == "operator"
                    assert claims["sub"]
                    print("PASS verified Studio access token carries the invited username")
                assert jwt.get_unverified_header(tokens["access_token"])["typ"] == "at+jwt"
                keys = oidc.cache["keycloak"][1]
                kid = jwt.get_unverified_header(tokens["id_token"])["kid"]
                identity = jwt.decode(
                    tokens["id_token"],
                    jwt.PyJWK(keys[kid]).key,
                    algorithms=["RS256"],
                    issuer=ISSUER,
                    audience="studio",
                )
                assert identity["nonce"] == parameters["nonce"]
                assert identity["sub"] == claims["sub"]
                worker_response = client.post(
                    token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": "worker",
                        "client_secret": worker_secret,
                    },
                )
                worker_response.raise_for_status()
                service = oidc.verify(worker_response.json()["access_token"])[1]
                assert service["client_id"] == "worker" and service["sub"] != claims["sub"]
                try:
                    oidc.verify(tokens["id_token"])
                except ApplicationError as error:
                    assert error.status_code == 401
                else:
                    raise AssertionError("ID token accepted as API bearer")
                if phase22:
                    assert ONBOARDING_ROLE in claims["realm_access"]["roles"]
                    test_onboarding(
                        database_url,
                        proxy,
                        tokens["access_token"],
                        worker_response.json()["access_token"],
                        service["sub"],
                        directory_secret,
                    )
            assert client.post(token_url, data=payload).status_code == 400
            client.close()
            print(
                "PASS Code/PKCE exchange, nonce, RFC 9068, API audience, client_id, "
                "issuer, signature"
            )
            print(
                "PASS ID-token rejection, single-use authorization code, no refresh-token issuance"
            )
            print(
                "NOT RUN live Microsoft/Google/Workspace: provider credentials and "
                "organizations unavailable"
            )
        finally:
            if container:
                subprocess.run(["docker", "stop", container], check=True, capture_output=True)


if __name__ == "__main__":
    main()
