"""Cryptographic access-token threats against the real verifier, with bounded test IdP I/O."""

import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from ontology_platform.config import Settings
from ontology_platform.errors import ApplicationError
from ontology_platform.security.oidc import OIDCVerifier, Provider
from pydantic import SecretStr, ValidationError

ISSUER = "https://identity.example/realm"


@pytest.fixture
def idp():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    public.update(kid="first", alg="RS256", use="sig")
    state = {
        "keys": [public],
        "requests": [],
        "metadata": {"issuer": ISSUER, "jwks_uri": "https://identity.example/keys"},
    }

    def transport(request):
        state["requests"].append(str(request.url))
        body = (
            state["metadata"]
            if request.url.path.endswith("openid-configuration")
            else {"keys": state["keys"]}
        )
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps(body).encode()))

    provider = Provider(id="example", issuer=ISSUER, audience="foundry", clients=("studio",))
    verifier = OIDCVerifier(
        (provider,), client=httpx.Client(transport=httpx.MockTransport(transport))
    )
    yield private, state, verifier
    verifier.client.close()


def token(private, *, claims=None, headers=None):
    now = int(time.time())
    body = {
        "iss": ISSUER,
        "sub": "alice",
        "aud": "foundry",
        "exp": now + 300,
        "iat": now,
        "jti": "token-1",
        "client_id": "studio",
    }
    body.update(claims or {})
    for key in [key for key, value in body.items() if value is None]:
        del body[key]
    return jwt.encode(
        body,
        private,
        algorithm="RS256",
        headers={"kid": "first", "typ": "at+jwt"} | (headers or {}),
    )


def test_signed_access_token_cache_and_untrusted_claims(idp):
    private, state, verifier = idp
    signed = token(private, claims={"tenant_id": "attacker", "roles": ["admin"]})
    assert verifier.verify(signed)[1]["sub"] == "alice"
    assert verifier.verify(signed)[1]["sub"] == "alice"
    assert len(state["requests"]) == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"exp": 1},
        {"nbf": int(time.time()) + 600},
        {"iat": int(time.time()) + 600},
        {"iss": "https://evil.example"},
        {"aud": "other"},
        {"sub": ""},
        {"sub": None},
        {"exp": None},
        {"iat": None},
        {"jti": None},
        {"client_id": None},
        {"client_id": "untrusted"},
        {"azp": "untrusted"},
        {"token_use": "id"},
        {"exp": "9999999999"},
        {"iat": True},
    ],
)
def test_invalid_claims_reject(idp, changes):
    private, _, verifier = idp
    with pytest.raises(ApplicationError) as error:
        verifier.verify(token(private, claims=changes))
    assert error.value.status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {"typ": "JWT"},
        {"typ": "id+jwt"},
        {"kid": "unknown"},
        {"jku": "https://evil.example/key"},
        {"x5u": "https://evil.example/key"},
        {"jwk": {}},
        {"crit": ["untrusted"]},
    ],
)
def test_header_confusion_reject(idp, headers):
    private, state, verifier = idp
    with pytest.raises(ApplicationError):
        verifier.verify(token(private, headers=headers))
    assert all("evil" not in url for url in state["requests"])


@pytest.mark.parametrize("bad", ["garbage", "a.b.c", "x" * 17000])
def test_malformed_token(idp, bad):
    with pytest.raises(ApplicationError):
        idp[2].verify(bad)


def test_signature_none_and_hmac_confusion(idp):
    private, _, verifier = idp
    foreign = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    signed = token(private)
    body = jwt.decode(signed, options={"verify_signature": False})
    for bad in (
        token(foreign),
        jwt.encode(body, "", algorithm="none", headers={"typ": "at+jwt", "kid": "first"}),
        jwt.encode(
            body,
            "fake-secret-at-least-thirty-two-bytes",
            algorithm="HS256",
            headers={"typ": "at+jwt", "kid": "first"},
        ),
    ):
        with pytest.raises(ApplicationError):
            verifier.verify(bad)


def test_rotation_unknown_key_refresh_and_outage(idp):
    private, state, verifier = idp
    verifier.verify(token(private))
    rotated = dict(state["keys"][0], kid="rotated")
    state["keys"] = [rotated]
    verifier.attempts["example"] -= 31
    assert verifier.verify(token(private, headers={"kid": "rotated"}))[1]["sub"] == "alice"
    before = len(state["requests"])
    for _ in range(5):
        with pytest.raises(ApplicationError):
            verifier.verify(token(private, headers={"kid": "missing"}))
    assert len(state["requests"]) == before
    verifier.cache["example"] = (0, {})
    verifier.attempts["example"] -= 31
    state["metadata"] = {"issuer": ISSUER, "jwks_uri": "https://evil.example/keys"}
    with pytest.raises(ApplicationError):
        verifier.verify(token(private))
    assert all("evil" not in url for url in state["requests"])


@pytest.mark.parametrize(
    "body,status", [(b"{}", 302), (b"x" * 262145, 200), (b"[]", 200), (b"invalid", 200)]
)
def test_bounded_metadata_and_redirects(body, status):
    provider = Provider(id="example", issuer=ISSUER, audience="foundry", clients=("studio",))
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(status, stream=httpx.ByteStream(body))
        )
    )
    verifier = OIDCVerifier((provider,), client=client)
    with pytest.raises((ValueError, httpx.HTTPError)):
        verifier.warm()
    client.close()


@pytest.mark.parametrize(
    "values",
    [
        {"auth_mode": "oidc"},
        {"auth_mode": "local"},
        {"auth_mode": "test"},
        {"auth_mode": "oidc", "trusted_local_identity": True},
    ],
)
def test_configuration_fail_closed(values):
    with pytest.raises(ValidationError):
        Settings(
            database_url=SecretStr("postgresql+psycopg://localhost/unused"),
            _env_file=None,
            **values,
        )


def test_es256_access_token_uses_curve_and_algorithm_constraints():
    from cryptography.hazmat.primitives.asymmetric import ec

    private = ec.generate_private_key(ec.SECP256R1())
    public = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(private.public_key()))
    public.update(kid="ec", alg="ES256")

    def transport(request):
        body = (
            {"issuer": ISSUER, "jwks_uri": "https://identity.example/keys"}
            if request.url.path.endswith("openid-configuration")
            else {"keys": [public]}
        )
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps(body).encode()))

    provider = Provider(
        id="ec", issuer=ISSUER, audience="foundry", clients=("studio",), algorithms=("ES256",)
    )
    client = httpx.Client(transport=httpx.MockTransport(transport))
    verifier = OIDCVerifier((provider,), client=client)
    now = int(time.time())
    encoded = jwt.encode(
        {
            "iss": ISSUER,
            "sub": "alice",
            "aud": "foundry",
            "exp": now + 300,
            "iat": now,
            "jti": "ec",
            "client_id": "studio",
        },
        private,
        algorithm="ES256",
        headers={"typ": "at+jwt", "kid": "ec"},
    )
    assert verifier.verify(encoded)[1]["sub"] == "alice"
    client.close()


def test_operator_ca_bundle_keeps_tls_verification(tmp_path):
    """A local CA is additive; missing trust and hostname mismatches still reject."""
    import ipaddress
    import ssl
    import threading
    from datetime import UTC, datetime, timedelta
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "isolated-test-ca")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    ca = tmp_path / "ca.pem"
    ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    secret = tmp_path / "key.pem"
    secret.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"verified":true}')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(ca, secret)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    trusted = OIDCVerifier((), ca_bundle=ca)
    default = OIDCVerifier(())
    try:
        url = f"https://127.0.0.1:{server.server_port}"
        assert trusted.document(url) == {"verified": True}
        with pytest.raises(httpx.ConnectError, match="[Cc]ertificate verify failed"):
            default.document(url)
        with pytest.raises(httpx.ConnectError, match="[Cc]ertificate verify failed"):
            trusted.document(f"https://localhost:{server.server_port}")
    finally:
        trusted.client.close()
        default.client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_invalid_operator_ca_bundle_fails_closed(tmp_path):
    import ssl

    with pytest.raises(FileNotFoundError):
        OIDCVerifier((), ca_bundle=tmp_path / "missing.pem")
    bad = tmp_path / "invalid.pem"
    bad.write_text("not a certificate")
    with pytest.raises(ssl.SSLError):
        OIDCVerifier((), ca_bundle=bad)
