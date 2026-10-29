"""Local-only signed OIDC provider and isolated PostgreSQL E2E fixture.

Invoked by scripts/test_studio.py. Never expose this deterministic test provider externally.
"""

import csv
import ipaddress
import json
import os
import ssl
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import jwt
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from ontology_platform.config import Settings, get_settings
from ontology_platform.ingestion.catalog import Binding, InputColumn, SourceCatalog
from ontology_platform.ingestion.worker import IngestionWorker
from ontology_platform.main import create_app
from ontology_platform.metadata.service import RegistryService
from ontology_platform.security.admin import SecurityAdministration
from ontology_platform.security.bootstrap import bootstrap
from ontology_platform.security.contracts import AssignmentInput, DelegationInput, IdentityInput
from ontology_platform.security.identity import resolve
from ontology_platform.security.oidc import OIDCVerifier, Provider
from ontology_platform.security.service import PlatformAuthorizer
from ontology_platform.semantic.engine import OpenOntologiesAdapter
from ontology_platform.semantic.worker import SemanticWorker
from ontology_schema.models import OntologyDefinition

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services/api/tests"))
from test_phase1 import database, make_world  # noqa: E402

ISSUER = "https://127.0.0.1/oidc"
CERTS = ROOT / "artifacts/studio-e2e"


def main():
    CERTS.mkdir(parents=True, exist_ok=True)
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Foundry E2E local CA")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(private.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(private, hashes.SHA256())
    )
    cert_path, key_path = CERTS / "cert.pem", CERTS / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    public.update(kid="e2e", alg="RS256", use="sig")
    provider = FastAPI()
    codes = {}

    @provider.get("/oidc/.well-known/openid-configuration")
    def metadata():
        return {
            "issuer": ISSUER,
            "authorization_endpoint": ISSUER + "/authorize",
            "token_endpoint": ISSUER + "/token",
            "jwks_uri": ISSUER + "/keys",
            "code_challenge_methods_supported": ["S256"],
        }

    @provider.get("/oidc/keys")
    def keys():
        return {"keys": [public]}

    @provider.get("/oidc/authorize")
    def authorize(request: Request):
        from secrets import token_urlsafe
        from urllib.parse import urlencode

        params = dict(request.query_params)
        if (
            params.get("redirect_uri") != "http://127.0.0.1:3000/auth/callback"
            or params.get("client_id") != "studio"
            or params.get("code_challenge_method") != "S256"
        ):
            return {"error": "invalid_client"}
        code = token_urlsafe(32)
        codes[code] = params
        return RedirectResponse(
            params["redirect_uri"] + "?" + urlencode({"state": params["state"], "code": code})
        )

    @provider.post("/oidc/token")
    async def token(request: Request):
        import base64
        import hashlib
        from urllib.parse import parse_qs

        params = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
        login = codes.pop(params.get("code"), None)
        challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(params.get("code_verifier", "").encode()).digest()
            )
            .decode()
            .rstrip("=")
        )
        if (
            not login
            or challenge != login["code_challenge"]
            or params.get("redirect_uri") != login["redirect_uri"]
            or params.get("client_id") != "studio"
        ):
            from fastapi.responses import JSONResponse

            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        now = int(time.time())
        common = {"iss": ISSUER, "sub": "operator", "iat": now, "exp": now + 1800}
        return {
            "token_type": "Bearer",
            "id_token": jwt.encode(
                common | {"aud": "studio", "nonce": login["nonce"]},
                private,
                algorithm="RS256",
                headers={"kid": "e2e"},
            ),
            "access_token": jwt.encode(
                common | {"aud": "foundry", "jti": params["code"], "client_id": "studio"},
                private,
                algorithm="RS256",
                headers={"kid": "e2e", "typ": "at+jwt"},
            ),
        }

    server = uvicorn.Server(
        uvicorn.Config(
            provider,
            host="127.0.0.1",
            port=8443,
            ssl_certfile=str(cert_path),
            ssl_keyfile=str(key_path),
            log_level="warning",
            access_log=False,
        )
    )
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("Local TLS provider could not bind 127.0.0.1:8443")
    os.environ.setdefault("TEST_DATABASE_URL", get_settings().database_url.get_secret_value())
    fixture = database.__wrapped__()
    db = next(fixture)
    try:
        w = make_world(db)
        with w.sessions.begin() as sql:
            bootstrap(sql, w.actor.tenant_id, ISSUER, "operator", "Manufacturing E2E")
            from uuid import uuid4

            bootstrap(sql, uuid4(), ISSUER, "operator", "Other E2E")
        auth = PlatformAuthorizer(w.sessions)
        p = resolve(
            w.sessions,
            ISSUER,
            "operator",
            w.actor.tenant_id,
            method="oidc",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        data = w.definition.model_dump(mode="json")
        data["action_types"] = json.loads(
            (ROOT / "ontologies/examples/manufacturing-actions.json").read_text()
        )
        definition = OntologyDefinition.model_validate(data)
        RegistryService(w.sessions, auth).create(p, definition)
        bindings = []
        for kind, file, key in [
            ("Factory", "factories.csv", "factoryId"),
            ("Machine", "machines.csv", "machineId"),
            ("Employee", "employees.csv", "employeeId"),
            ("MaintenanceTask", "maintenance_tasks.csv", "taskId"),
        ]:
            headers = next(csv.reader((ROOT / "fixtures" / file).read_text().splitlines()))
            bindings.append(
                Binding(
                    tenant_id=p.tenant_id,
                    key=kind,
                    kind="csv",
                    root=str(ROOT / "fixtures"),
                    file_name=file,
                    source_key_column=key,
                    columns=[InputColumn(name=h) for h in headers],
                )
            )
        catalog = SourceCatalog(bindings)
        admin = SecurityAdministration(auth)
        workers = {}
        for kind in ["ingestion", "semantic"]:
            wid = admin.identity(
                p, IdentityInput(issuer=ISSUER, subject="worker-" + kind, principal_type="service")
            )
            admin.assign(p, AssignmentInput(principal_id=wid, role_id="tenant-administrator"))
            admin.delegate(
                p,
                DelegationInput(
                    worker_id=wid,
                    principal_id=p.principal_id,
                    ontology_id=definition.id,
                    kind=kind,
                    expires_at=p.expires_at,
                ),
            )
            workers[kind] = p.model_copy(
                update={
                    "authentication_method": "delegated",
                    "actor_id": wid,
                    "delegation_kind": kind,
                    "delegation_ontology": definition.id,
                }
            )
        stop = threading.Event()

        def work():
            ingestion = IngestionWorker(w.sessions, auth, catalog)
            semantic = SemanticWorker(
                w.sessions, auth, engine=OpenOntologiesAdapter(ROOT / ".external/open-ontologies")
            )
            while not stop.wait(0.3):
                ingestion.run_one(workers["ingestion"], definition.id)
                semantic.run_one(workers["semantic"], definition.id)

        settings = Settings(
            database_url=w.settings.database_url,
            auth_mode="oidc",
            trusted_local_identity=False,
            local_tenant_id=None,
            local_principal_id=None,
            oidc_providers=(
                Provider(id="e2e", issuer=ISSUER, audience="foundry", clients=("studio",)),
            ),
            _env_file=None,
        )
        app = create_app(settings)
        app.state.sessions = w.sessions
        app.state.authorizer = auth
        app.state.ingestion_catalog = catalog
        app.state.oidc.client.close()

        def provider_transport(request):
            if request.url.host != "127.0.0.1" or not request.url.path.startswith("/oidc/"):
                raise RuntimeError("Unexpected test provider request")
            request.url = request.url.copy_with(port=8443)

        app.state.oidc = OIDCVerifier(
            settings.oidc_providers,
            client=httpx.Client(
                verify=ssl.create_default_context(cafile=str(cert_path)),
                trust_env=False,
                timeout=3,
                event_hooks={"request": [provider_transport]},
            ),
        )
        worker_thread = threading.Thread(target=work, daemon=True)
        worker_thread.start()
        uvicorn.run(app, host="127.0.0.1", port=8001, log_level="warning", access_log=False)
    finally:
        stop.set()
        if "worker_thread" in locals():
            worker_thread.join(timeout=45)
        server.should_exit = True
        fixture.close()
        key_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
