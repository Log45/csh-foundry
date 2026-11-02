"""Actual pinned broker Code/PKCE contract, in a disposable loopback-only container."""

import base64
import hashlib
import html
import json
import re
import secrets
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt
from ontology_platform.errors import ApplicationError
from ontology_platform.security.broker import KEYCLOAK_VERSION, realm_configuration
from ontology_platform.security.oidc import OIDCVerifier, Provider

ISSUER = "https://identity.phase10.test/realms/phase10"
ORIGIN = "https://studio.phase10.test"


def main() -> None:
    container = None
    with tempfile.TemporaryDirectory(prefix="foundry-keycloak-test-") as directory:
        configuration = realm_configuration(ISSUER, ORIGIN)
        # Test transport only: no HTTP exception is added to the platform verifier.
        configuration["sslRequired"] = "none"
        password = secrets.token_urlsafe(32)
        worker_secret = secrets.token_urlsafe(32)
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
                    "-p",
                    "127.0.0.1::8080",
                    "-v",
                    f"{path}:/opt/keycloak/data/import/phase10-realm.json:ro",
                    f"quay.io/keycloak/keycloak:{KEYCLOAK_VERSION}",
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
                "scope": "openid",
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
                # Only trusted discovery/JWKS calls are mapped to this local test container.
                actual = client.get(local(request.url))
                return httpx.Response(actual.status_code, stream=httpx.ByteStream(actual.content))

            provider = Provider(
                id="keycloak", issuer=ISSUER, audience="foundry-api", clients=("studio", "worker")
            )
            with httpx.Client(transport=httpx.MockTransport(transport)) as proxy:
                oidc = OIDCVerifier((provider,), client=proxy)
                _, claims = oidc.verify(tokens["access_token"])
                assert claims["client_id"] == "studio"
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
