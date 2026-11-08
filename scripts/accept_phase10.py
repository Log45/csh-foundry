"""Exercise the production Compose template in a new, disposable local project.

Never reads .env, never attaches existing volumes, and never contacts external IdPs.
Private generated credentials/logs stay beneath artifacts; only redacted results are exported.
Requires built phase10-closure API/Studio and amd64 semantic images.
"""

import argparse
import html
import json
import os
import re
import secrets
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[1]


class Acceptance:
    def __init__(self, output: Path, candidate_images: dict[str, str] | None = None) -> None:
        self.candidate_images = candidate_images
        self.output = output.resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.project = "foundry-accept-" + secrets.token_hex(4)
        self.root = ROOT / "artifacts" / self.project
        self.root.mkdir(mode=0o700, parents=True)
        self.results = []
        self.env = {
            k: v for k, v in os.environ.items() if not k.startswith(("FOUNDRY_", "STUDIO_"))
        }
        self.env["COMPOSE_PROJECT_NAME"] = self.project
        self.passwords = {}
        self.tenant = uuid4()
        self.subject = str(uuid4())
        self.issuer = "https://identity.accept.test/realms/foundry"
        self.origin = "https://studio.accept.test"
        self.compose = []

    def run(self, args: list[str], **kwargs: Any) -> str:
        return subprocess.check_output(
            args, cwd=ROOT, env=self.env, text=True, stderr=subprocess.STDOUT, **kwargs
        )

    def dc(self, *args: str, **kwargs: Any) -> str:
        return self.run(self.compose + list(args), **kwargs)

    def record(self, name: str, status: str = "PASS", **details: Any) -> None:
        self.results.append({"check": name, "result": status, **details})
        (self.output / "deployment.json").write_text(
            json.dumps(
                {
                    "project": self.project,
                    "environment": "Disposable local Compose; test CA; loopback ports",
                    "private_evidence": str(self.root.relative_to(ROOT)),
                    "checks": self.results,
                },
                indent=2,
            )
            + "\n"
        )
        print(status, name, flush=True)

    def prepare(self) -> None:
        from ontology_platform.security.broker import realm_configuration

        for name in ("secrets", "tls", "wal", "realm", "ingestion"):
            (self.root / name).mkdir()
        for name in (
            "postgres_password",
            "migrator_password",
            "runtime_password",
            "keycloak_password",
            "keycloak_admin_password",
            "FOUNDRY_BROWSER_STATE_SECRET",
            "FOUNDRY_QUERY_CURSOR_SECRET",
            "FOUNDRY_WORKER_CLIENT_SECRET",
        ):
            self.passwords[name] = secrets.token_urlsafe(36)
        self.passwords["FOUNDRY_BROWSER_STATE_KEYS"] = Fernet.generate_key().decode()
        self.passwords["FOUNDRY_DATABASE_URL"] = (
            f"postgresql+psycopg://foundry_runtime:{self.passwords['runtime_password']}@postgres:5432/foundry"
        )
        for name, value in self.passwords.items():
            path = self.root / "secrets" / name
            path.write_text(value)
            path.chmod(0o440)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(UTC)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, self.project)])
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
            .add_extension(
                x509.SubjectAlternativeName(
                    [
                        x509.DNSName(h)
                        for h in ("studio.accept.test", "api.accept.test", "identity.accept.test")
                    ]
                ),
                False,
            )
            .sign(key, hashes.SHA256())
        )
        (self.root / "tls/fullchain.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        (self.root / "tls/key.pem").write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        (self.root / "tls/key.pem").chmod(0o644)  # Disposable test key only.
        realm = realm_configuration(self.issuer, self.origin)
        self.login_password = secrets.token_urlsafe(32)
        realm["users"] = [
            {
                "id": self.subject,
                "username": "operator",
                "firstName": "Acceptance",
                "lastName": "Operator",
                "enabled": True,
                "emailVerified": True,
                "email": "operator@example.test",
                "credentials": [
                    {"type": "password", "value": self.login_password, "temporary": False}
                ],
            }
        ]
        (self.root / "realm/foundry-realm.json").write_text(json.dumps(realm))
        (self.root / "catalog.json").write_text("[]")
        values = {
            "STUDIO_HOST": "studio.accept.test",
            "API_HOST": "api.accept.test",
            "IDENTITY_HOST": "identity.accept.test",
            "API_IMAGE": "csh-foundry-api:phase10-closure",
            "INGRESS_IMAGE": "csh-foundry-ingress:phase10-closure",
            "STUDIO_IMAGE": "csh-foundry-studio:phase10-closure",
            "SEMANTIC_IMAGE": "csh-foundry-semantic:phase10-closure",
            "POSTGRES_IMAGE": "csh-foundry-postgres:phase10-security",
            "SECRETS_DIRECTORY": str(self.root / "secrets"),
            "TLS_DIRECTORY": str(self.root / "tls"),
            "WAL_ARCHIVE_DIRECTORY": str(self.root / "wal"),
            "KEYCLOAK_IMPORT_DIRECTORY": str(self.root / "realm"),
            "WORKER_CATALOG_FILE": str(self.root / "catalog.json"),
            "INGESTION_DIRECTORY": str(self.root / "ingestion"),
            "WORKER_TENANT_ID": str(self.tenant),
        }
        self.values = values
        self.env.update(values)
        envfile = self.root / "compose.env"
        envfile.write_text("\n".join(k + "=" + v for k, v in values.items()) + "\n")
        override = self.root / "override.yaml"
        text = """services:
  postgres:
    networks: !override [data, acceptance]
    ports: ["127.0.0.1::5432"]
  ingress:
    ports: !override ["127.0.0.1::8443", "127.0.0.1::8080"]
    networks:
      front:
        ipv4_address: 172.29.100.2
      identity:
        ipv4_address: 172.29.101.2
  keycloak:
    environment:
      KC_PROXY_TRUSTED_ADDRESSES: 172.29.101.2/32
  api: &ca
    environment:
      FOUNDRY_OIDC_CA_BUNDLE: /test-ca/fullchain.pem
      FOUNDRY_REQUEST_LIMIT_PER_MINUTE: "10000"
    volumes:
      - CA_PATH:/test-ca:ro
  ingestion-worker:
    <<: *ca
  semantic-worker:
    <<: *ca
    platform: linux/amd64
  studio:
    environment:
      NODE_EXTRA_CA_CERTS: /test-ca/fullchain.pem
    volumes:
      - CA_PATH:/test-ca:ro
networks:
  acceptance: {}
  front:
    ipam:
      config: !override [{subnet: 172.29.100.0/24}]
  identity:
    ipam:
      config: !override [{subnet: 172.29.101.0/24}]
"""
        override.write_text(text.replace("CA_PATH", str(self.root / "tls")))
        self.compose = [
            "docker",
            "compose",
            "--env-file",
            str(envfile),
            "-p",
            self.project,
            "-f",
            str(ROOT / "infrastructure/production/compose.yaml"),
            "-f",
            str(override),
        ]
        if self.candidate_images is not None:
            from verify_release_evidence import IMAGE_ROLES

            if set(self.candidate_images) != IMAGE_ROLES or any(
                not re.fullmatch(r"sha256:[0-9a-f]{64}", value)
                for value in self.candidate_images.values()
            ):
                raise ValueError("Exactly six immutable candidate image identities required")
            for role, variable in {
                "api": "API_IMAGE",
                "studio": "STUDIO_IMAGE",
                "semantic": "SEMANTIC_IMAGE",
                "ingress": "INGRESS_IMAGE",
            }.items():
                self.values[variable] = self.candidate_images[role]
            self.env.update(self.values)
            services = {
                service: {"image": self.candidate_images[role], "pull_policy": "never"}
                for service, role in {
                    "api": "api",
                    "studio": "studio",
                    "semantic-worker": "semantic",
                    "ingestion-worker": "api",
                    "outbox-worker": "api",
                    "ingress": "ingress",
                    "postgres": "postgres",
                    "keycloak": "keycloak",
                }.items()
            }
            candidate = self.root / "candidate.json"
            candidate.write_text(json.dumps({"services": services}))
            self.compose += ["-f", str(candidate)]
            (self.output / "candidate-images.json").write_text(
                json.dumps(self.candidate_images, indent=2) + "\n"
            )
        self.dc("--profile", "workers", "config", "--quiet")
        self.record("production-template-configuration")

    def provision(self) -> None:
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import create_engine

        self.dc("up", "-d", "--wait", "postgres")
        from phase10_pitr import prepare_archive

        prepare_archive(self.dc("ps", "-q", "postgres").strip(), self.project, self.root / "wal")
        self.record("disposable-production-wal-directory-owner-and-write-permission")
        port = self.dc("port", "postgres", "5432").strip().rsplit(":", 1)[1]
        self.env["FOUNDRY_ADMIN_DATABASE_URL"] = (
            f"postgresql://postgres:{self.passwords['postgres_password']}@127.0.0.1:{port}/postgres"
        )
        self.run(
            [
                "uv",
                "run",
                "python",
                "scripts/provision_production_database.py",
                "--apply",
                "--secrets",
                str(self.root / "secrets"),
            ]
        )
        url = f"postgresql+psycopg://foundry_migrator:{self.passwords['migrator_password']}@127.0.0.1:{port}/foundry"
        self.engine = create_engine(url)
        with self.engine.begin() as connection:
            cfg = Config(str(ROOT / "alembic.ini"))
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "head")
            command.check(cfg)
        self.run(
            [
                "uv",
                "run",
                "python",
                "scripts/provision_production_database.py",
                "--apply",
                "--grant-runtime",
                "--secrets",
                str(self.root / "secrets"),
            ]
        )
        self.url = url
        self.record("new-cluster-owner-migration-and-runtime-grants", head="0017_capacity")

    def seed(self) -> None:
        import jwt
        from ontology_platform.security.admin import SecurityAdministration
        from ontology_platform.security.bootstrap import bootstrap
        from ontology_platform.security.contracts import (
            AssignmentInput,
            IdentityInput,
        )
        from ontology_platform.security.identity import resolve
        from ontology_platform.security.service import PlatformAuthorizer
        from sqlalchemy.orm import sessionmaker

        sys.path.insert(0, str(ROOT / "services/api/tests"))
        from test_ingestion import setup

        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        world, service, _ = setup((self.engine, self.sessions, self.url), self.root / "ingestion")
        self.tenant = world.actor.tenant_id
        self.env["WORKER_TENANT_ID"] = str(self.tenant)
        catalog = [
            b.model_dump(mode="json") | {"root": "/data/ingestion"}
            for b in service.catalog.bindings.values()
        ]
        (self.root / "catalog.json").write_text(json.dumps(catalog))
        # Publish a new governed registration version for the container-side path.
        from ontology_platform.db.models import IngestionMapping
        from ontology_platform.ingestion.catalog import Binding, SourceCatalog
        from ontology_platform.ingestion.contracts import MappingInput, SourceInput

        service.catalog = SourceCatalog([Binding.model_validate(b) for b in catalog])
        for kind in ("Factory", "Machine", "Employee", "MaintenanceTask"):
            service.create_source(
                world.actor,
                "manufacturing",
                SourceInput(id=kind, name=kind, binding=kind, identity_namespace=kind, version=2),
            )
            with self.sessions() as sql:
                row = sql.get(IngestionMapping, (self.tenant, "manufacturing", kind, 1))
                mapping = MappingInput.model_validate_json(row.definition_json)
            service.create_mapping(
                world.actor,
                "manufacturing",
                mapping.model_copy(update={"version": 2, "source_version": 2}),
            )

        with self.sessions.begin() as sql:
            bootstrap(sql, self.tenant, self.issuer, self.subject, "Disposable acceptance")
        self.actor = resolve(
            self.sessions,
            self.issuer,
            self.subject,
            self.tenant,
            method="oidc",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        self.auth = PlatformAuthorizer(self.sessions)
        self.admin = SecurityAdministration(self.auth)
        # Worker subject comes from a broker token; workers verify its signature.
        response = self.request(
            "identity.accept.test",
            "/realms/foundry/protocol/openid-connect/token",
            "POST",
            data={
                "grant_type": "client_credentials",
                "client_id": "worker",
                "client_secret": self.passwords["FOUNDRY_WORKER_CLIENT_SECRET"],
            },
        )
        assert response.status_code == 200, response.status_code
        worker_subject = jwt.decode(
            response.json()["access_token"], options={"verify_signature": False}
        )["sub"]
        worker_id = self.admin.identity(
            self.actor,
            IdentityInput(issuer=self.issuer, subject=worker_subject, principal_type="service"),
        )
        self.worker_id = worker_id
        self.admin.assign(
            self.actor, AssignmentInput(principal_id=worker_id, role_id="tenant-administrator")
        )
        self.record("governed-manufacturing-schema-and-service-worker-identity")

    def request(self, host: str, path: str, method: str = "GET", **kwargs: Any) -> httpx.Response:
        # Explicit DNS mapping keeps all traffic on the disposable loopback listener.
        from urllib.parse import urlencode

        if not hasattr(self, "ingress_port"):
            self.ingress_port = self.dc("port", "ingress", "8443").strip().rsplit(":", 1)[1]
        port = self.ingress_port
        headers = kwargs.pop("headers", {})
        diagnostic = getattr(self, "diagnostic_requests", False)
        if diagnostic:
            headers["traceparent"] = (
                "00-" + secrets.token_hex(16) + "-" + secrets.token_hex(8) + "-01"
            )
        if cookies := kwargs.pop("cookies", None):
            headers["Cookie"] = cookies
        body = None
        if "json" in kwargs:
            body = json.dumps(kwargs["json"]).encode()
            headers["Content-Type"] = "application/json"
        if "data" in kwargs:
            body = urlencode(kwargs["data"]).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        unique = secrets.token_hex(8)
        response_file = self.root / (unique + ".body")
        header_file = self.root / (unique + ".headers")
        args = [
            "curl",
            "--silent",
            "--show-error",
            "--max-time",
            "20",
            "--noproxy",
            "*",
            "--cacert",
            str(self.root / "tls/fullchain.pem"),
            "--resolve",
            f"{host}:{port}:127.0.0.1",
            "-H",
            "Host: " + host,
            "-X",
            method,
            "-D",
            str(header_file),
            "-o",
            str(response_file),
            "-w",
            "%{json}" if diagnostic else "%{http_code}",
            f"https://{host}:{port}{path}",
        ]
        for name, value in headers.items():
            args += ["-H", name + ": " + value]
        if body is not None:
            args += ["--data-binary", "@-"]
        try:
            transport_started = time.monotonic()
            epoch_started = time.time()
            raw = self.run(args, input=body.decode() if body else None)
            if diagnostic:
                transport = json.loads(raw)
                # Explicit allowlist: curl JSON also contains headers/URLs, which stay private.
                self.request_local.timing = {
                    "trace_id": headers["traceparent"].split("-")[1],
                    "start_epoch": epoch_started,
                    "end_epoch": time.time(),
                    "transport_wall_seconds": time.monotonic() - transport_started,
                    **{
                        key: transport[key]
                        for key in (
                            "time_namelookup",
                            "time_connect",
                            "time_appconnect",
                            "time_pretransfer",
                            "time_starttransfer",
                            "time_total",
                            "http_code",
                        )
                    },
                }
                status = int(transport["http_code"])
            else:
                status = int(raw)
            pairs = [
                line.split(": ", 1) for line in header_file.read_text().splitlines() if ": " in line
            ]
            return httpx.Response(
                status,
                headers=pairs,
                content=response_file.read_bytes(),
                request=httpx.Request(method, f"https://{host}{path}"),
            )
        finally:
            response_file.unlink(missing_ok=True)
            header_file.unlink(missing_ok=True)

    def wait(self, host: str, path: str, expected: int = 200) -> None:
        for _ in range(100):
            try:
                if self.request(host, path).status_code == expected:
                    return
            except (subprocess.CalledProcessError, ValueError):
                pass
            time.sleep(1)
        raise RuntimeError("readiness timeout: " + host + path)

    def login(self) -> None:
        start = self.request(
            "studio.accept.test", "/auth/login", "POST", headers={"Origin": self.origin}
        )
        assert start.status_code == 200, (start.status_code, start.text)
        self.login_cookie = start.headers["set-cookie"].split(";", 1)[0]
        auth_url = urlsplit(start.json()["authorization"])
        page = self.request("identity.accept.test", auth_url.path + "?" + auth_url.query)
        action = re.search(r'<form[^>]*action="([^"]+)"', page.text)
        assert action, page.status_code
        kc_cookies = "; ".join(k + "=" + v for k, v in page.cookies.items())
        target = urlsplit(html.unescape(action[1]))
        response = self.request(
            "identity.accept.test",
            target.path + "?" + target.query,
            "POST",
            cookies=kc_cookies,
            data={"username": "operator", "password": self.login_password},
        )
        callback = urlsplit(response.headers["location"])
        done = self.request(
            "studio.accept.test", callback.path + "?" + callback.query, cookies=self.login_cookie
        )
        assert done.status_code == 303, (done.status_code, done.text)
        # Cookie header can contain multiple values; extract the opaque session only.
        match = re.search(r"foundry-session=([^;, ]+)", done.headers["set-cookie"])
        assert match
        self.cookie = "foundry-session=" + match[1]
        for attr in ("HttpOnly", "Secure", "SameSite=lax"):
            assert attr.lower() in done.headers["set-cookie"].lower()
        session = self.request("studio.accept.test", "/auth/session", cookies=self.cookie)
        assert session.status_code == 200, session.text
        self.csrf = session.json()["csrf"]
        selected = self.request(
            "studio.accept.test",
            "/auth/tenant",
            "POST",
            cookies=self.cookie,
            headers={"Origin": self.origin, "x-csrf-token": self.csrf},
            json={"tenant": str(self.tenant)},
        )
        assert selected.status_code == 200, selected.text
        assert (
            self.request(
                "studio.accept.test",
                callback.path + "?" + callback.query,
                cookies=self.login_cookie,
            ).status_code
            == 401
        )
        self.record("https-keycloak-code-pkce-studio-session-callback-replay-and-secure-cookie")

    def api(self, method: str, path: str, body: Any = None, expected: int = 200) -> Any:
        result = self.request(
            "studio.accept.test",
            "/bff",
            "POST",
            cookies=self.cookie,
            headers={"Origin": self.origin, "x-csrf-token": self.csrf},
            json={
                "method": method,
                "path": "/api/v1" + path,
                "expected_tenant": str(self.tenant),
                **({"body": body} if body is not None else {}),
            },
        )
        assert result.status_code == (200 if expected < 300 else expected), (
            method,
            path,
            result.status_code,
            result.text[:500],
        )
        return result.json()

    def workflow(self) -> None:
        prefix = "/ontologies/manufacturing"
        mappings = [
            {"id": x, "version": 2} for x in ("Factory", "Machine", "Employee", "MaintenanceTask")
        ]
        run = self.api(
            "POST",
            prefix + "/ingestion/runs",
            {"idempotency_key": "accept-seed", "mappings": mappings, "batch_size": 1},
            202,
        )
        self.dc("--profile", "workers", "up", "-d", "ingestion-worker", "semantic-worker")
        killed = False
        for _ in range(180):
            job = self.api("GET", prefix + "/ingestion/runs/" + run["id"])
            if job["status"] == "RUNNING" and job["checkpoint"] > 0 and not killed:
                self.dc("kill", "-s", "SIGKILL", "ingestion-worker")
                stopped = self.api("GET", prefix + "/ingestion/runs/" + run["id"])
                assert stopped["status"] == "RUNNING"
                self.dc("start", "ingestion-worker")
                killed = True
            if job["status"] in ("COMPLETED", "FAILED"):
                break
            time.sleep(1)
        if killed:
            assert job["attempts"] >= 2 and job["checkpoint"] > stopped["checkpoint"]
            self.record(
                "deployed-ingestion-sigkill-durable-checkpoint-lease-reclaim-idempotent-final-state",
                attempts=job["attempts"],
                checkpoint_at_kill=stopped["checkpoint"],
                final_checkpoint=job["checkpoint"],
            )
        else:
            self.record(
                "deployed-ingestion-crash-recovery",
                "NOT RUN",
                reason="Job completed before checkpoint kill window",
            )
        assert job["status"] == "COMPLETED", job
        assert job["created"] == 63 and job["links_created"] == 70, job
        obj = self.api("GET", prefix + "/objects/Machine/MCH-005")
        assert obj["object_id"] == "MCH-005", obj
        self.api("POST", prefix + "/objects/Machine/query", {"object_type": "Machine"})
        self.api("POST", prefix + "/object-sets/query", {"object_type": "Machine"})
        self.api(
            "POST",
            prefix + "/traverse",
            {"object_type": "Machine", "traverse": [{"link": "locatedInFactory"}]},
        )
        params = {
            "machineId": "MCH-005",
            "newStatus": "STOPPED",
            "expectedRevision": obj["version"],
        }
        self.api("POST", prefix + "/actions/UpdateMachineStatus/preview", {"parameters": params})
        result = self.api(
            "POST",
            prefix + "/actions/UpdateMachineStatus/execute",
            {"parameters": params, "idempotency_key": "accept-action"},
        )
        assert (
            self.api(
                "POST",
                prefix + "/actions/UpdateMachineStatus/execute",
                {"parameters": params, "idempotency_key": "accept-action"},
            )
            == result
        )
        self.api(
            "POST",
            prefix + "/actions/UpdateMachineStatus/execute",
            {"parameters": params, "idempotency_key": "accept-stale"},
            409,
        )
        self.record(
            "production-ingestion-worker-63-objects-70-links-query-traversal-action-idempotency-concurrency"
        )
        import base64

        from ontology_platform.sdk.integrity import verify_archive

        for language in ("python", "typescript"):
            sdk = self.api(
                "POST", prefix + "/sdk/generate", {"version": "1.0.0", "language": language}
            )
            download = self.api("GET", prefix + f"/sdk/artifacts/{sdk['id']}/download")
            archive = base64.b64decode(download["archive_base64"])
            verify_archive(archive, sdk["content_hash"], schema_hash=sdk["manifest"]["schema_hash"])
            try:
                verify_archive(archive + b"tampered", sdk["content_hash"])
            except ValueError:
                pass
            else:
                raise AssertionError("tampered deployed SDK accepted")
            (self.root / (language + ".zip")).write_bytes(archive)
            self.record(
                "production-sdk-generation-download-integrity-" + language, artifact=sdk["id"]
            )
        branches = []
        for name in ("accept-source", "accept-target"):
            branch = self.api("POST", prefix + "/branches", {"name": name})
            head = self.api("GET", prefix + f"/branches/{branch['id']}/head")
            head["definition"]["name"] = name
            self.api(
                "POST",
                prefix + f"/branches/{branch['id']}/edit",
                {"expected_revision": 1, "definition": head["definition"], "summary": name},
            )
            branches.append(branch)
        a, b = branches
        self.api("POST", prefix + f"/branches/{a['id']}/compare", {})
        merge = {"source_branch": a["id"], "source_revision": 2, "target_revision": 2}
        preview = self.api("POST", prefix + f"/branches/{b['id']}/merge-preview", merge)
        assert preview["conflicts"]
        merge["resolutions"] = [
            {"conflict": c["id"], "strategy": "source"} for c in preview["conflicts"]
        ]
        resolved = self.api("POST", prefix + f"/branches/{b['id']}/merge-preview", merge)
        assert resolved["definition"] and all(c["resolved"] for c in resolved["conflicts"])
        merge["preview_hash"] = resolved["preview_hash"]
        self.api("POST", prefix + f"/branches/{b['id']}/merge", merge)
        assert self.api("GET", prefix + "/merges")
        self.api(
            "POST",
            prefix + f"/branches/{b['id']}/draft",
            {"expected_revision": 3, "version": "1.1.0"},
        )
        self.api("POST", prefix + "/versions/1.1.0/validate", {})
        self.api("POST", prefix + "/versions/1.1.0/publish", {})
        assert self.api("GET", prefix)["active_version"] == "1.0.0"
        self.record(
            "production-branch-conflict-resolved-merge-provenance-draft-publication-separate-activation"
        )
        artifacts = self.api("POST", prefix + "/semantic/compile", {"schema_version": "1.0.0"})
        asserted = self.api(
            "POST",
            prefix + "/semantic/exports",
            {"schema_version": "1.0.0", "selections": [{"object_type": "Machine"}]},
        )
        for operation, secondary in (("validation", artifacts[1]), ("reasoning", artifacts[0])):
            job = self.api(
                "POST",
                prefix + "/semantic/jobs",
                {
                    "operation": operation,
                    "primary_artifact": asserted,
                    "secondary_artifact": secondary,
                    "profile": "owl-rl-ext",
                },
            )
            for _ in range(90):
                job = self.api("GET", prefix + "/semantic/jobs/" + job["id"])
                if job["status"] in ("COMPLETED", "FAILED"):
                    break
                time.sleep(1)
            assert job["status"] == "COMPLETED", job
            for artifact in job["outputs"]:
                view = self.api("GET", prefix + "/semantic/artifacts/" + artifact)
                assert view["manifest"]["engine_version"]
            self.record("production-semantic-supervised-" + operation, outputs=len(job["outputs"]))
        assert self.api("GET", prefix + "/objects/Machine/MCH-005")["version"] == obj["version"] + 1
        self.record("semantic-and-schema-development-did-not-mutate-operational-objects")

    def runtime_controls(self) -> None:
        containers = self.dc("--profile", "workers", "ps", "-q").split()
        inventory = []
        for container in containers:
            state = json.loads(self.run(["docker", "inspect", container]))[0]
            host = state["HostConfig"]
            inventory.append(
                {
                    "name": state["Name"],
                    "image": state["Image"],
                    "user": state["Config"]["User"],
                    "read_only": host["ReadonlyRootfs"],
                    "memory": host["Memory"],
                    "nano_cpus": host["NanoCpus"],
                    "pids": host["PidsLimit"],
                    "tmpfs": host.get("Tmpfs", {}),
                    "cap_drop": host["CapDrop"],
                    "security_opt": host["SecurityOpt"],
                    "networks": list(state["NetworkSettings"]["Networks"]),
                }
            )
        (self.output / "runtime.json").write_text(json.dumps(inventory, indent=2) + "\n")
        if self.candidate_images is not None:
            expected = {
                "api": "api",
                "studio": "studio",
                "semantic-worker": "semantic",
                "ingestion-worker": "api",
                "postgres": "postgres",
                "keycloak": "keycloak",
                "ingress": "ingress",
            }
            for service, role in expected.items():
                actual = next(c for c in inventory if c["name"].endswith("-" + service + "-1"))
                assert actual["image"] == self.candidate_images[role]
            for service in ("api", "semantic-worker"):
                self.dc(
                    "exec",
                    "-T",
                    service,
                    "python",
                    "-c",
                    "import os,shutil; assert os.getuid()!=0; "
                    "assert shutil.which('uv') is None; assert shutil.which('mount') is None",
                )
            self.dc(
                "exec",
                "-T",
                "studio",
                "node",
                "-e",
                "if(process.getuid()===0 || require('fs').existsSync('/usr/bin/mount')) "
                "process.exit(1)",
            )
            pid = self.dc(
                "exec", "-T", "postgres", "sh", "-ec", 'head -1 "$PGDATA/postmaster.pid"'
            ).strip()
            assert pid.isdigit()
            status = self.dc("exec", "-T", "postgres", "cat", "/proc/" + pid + "/status")
            uid = next(line.split()[1:] for line in status.splitlines() if line.startswith("Uid:"))
            assert all(value != "0" for value in uid)
            self.dc(
                "exec",
                "-T",
                "postgres",
                "sh",
                "-ec",
                "! command -v gpg; ! command -v mount; command -v pg_basebackup; "
                "command -v pg_restore; command -v sqv",
            )
            self.record(
                "exact-six-candidate-identities-nonroot-runtime-tool-removal-and-recovery-tools"
            )

        semantic = next(c for c in inventory if "semantic-worker" in c["name"])
        assert semantic["read_only"] and semantic["memory"] == 768 * 1024 * 1024
        assert semantic["nano_cpus"] == 1000000000 and semantic["pids"] == 128
        assert "ALL" in semantic["cap_drop"]
        assert "egress" not in " ".join(semantic["networks"])
        self.record("actual-runtime-semantic-container-limits-and-network-configuration")
        self.dc(
            "exec",
            "-T",
            "api",
            "python",
            "-c",
            "from ontology_platform.config import get_settings; "
            "from ontology_platform.db.session import make_engine,require_runtime_role; "
            "from sqlalchemy.orm import sessionmaker; "
            "settings=get_settings(); "
            "require_runtime_role(sessionmaker(make_engine(settings)), "
            "allow_owner_runtime_role=settings.allow_owner_runtime_role)",
        )
        self.record("actual-runtime-database-privilege-check")
        code = """import errno,os,pathlib,socket,json
assert os.getuid()!=0
try: pathlib.Path('/app/not-writable').write_text('x')
except OSError as error: assert error.errno in (errno.EROFS,errno.EACCES)
else: raise AssertionError('writable application filesystem')
assert os.statvfs('/tmp').f_blocks * os.statvfs('/tmp').f_frsize <= 128*1024*1024
values={name:pathlib.Path('/sys/fs/cgroup/'+name).read_text().strip()
        for name in ('memory.max','cpu.max','pids.max')}
assert values['memory.max']=='805306368' and values['pids.max']=='128'
assert values['cpu.max'].split()[0]==values['cpu.max'].split()[1]
try: socket.create_connection(('1.1.1.1',443),timeout=2)
except OSError: pass
else: raise AssertionError('direct Internet egress allowed')
print(json.dumps(values))
"""
        limits = json.loads(self.dc("exec", "-T", "semantic-worker", "python", "-c", code))
        self.record(
            "semantic-nonroot-readonly-tmpfs-cgroup-enforcement-no-direct-egress", cgroups=limits
        )

    def independent_sdks(self) -> None:
        import base64
        import hashlib
        import io
        import zipfile

        from ontology_platform.config import Settings
        from ontology_platform.db.models import BrowserState
        from ontology_platform.security.browser import BrowserStore
        from pydantic import SecretStr

        handle = self.cookie.split("=", 1)[1]
        key = (
            base64.urlsafe_b64encode(hashlib.sha256(handle.encode()).digest()).decode().rstrip("=")
        )
        settings = Settings(
            database_url=SecretStr(self.url),
            browser_state_secret=SecretStr(self.passwords["FOUNDRY_BROWSER_STATE_SECRET"]),
            browser_state_keys=SecretStr(self.passwords["FOUNDRY_BROWSER_STATE_KEYS"]),
            _env_file=None,
        )
        state = BrowserStore(self.sessions, settings).operate("session", key, "GET")
        token = state.data["token"]
        with self.sessions() as sql:
            assert token.encode() not in sql.get(BrowserState, ("session", key)).ciphertext
        for language in ("python", "typescript"):
            directory = self.root / (language + "-sdk")
            with zipfile.ZipFile(
                io.BytesIO((self.root / (language + ".zip")).read_bytes())
            ) as archive:
                archive.extractall(directory)
        venv = self.root / "sdk-venv"
        self.run(["uv", "venv", str(venv), "--python", "3.12"])
        self.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(venv / "bin/python"),
                str(self.root / "python-sdk"),
            ]
        )
        self.run(
            [
                "node",
                str(ROOT / "apps/studio/node_modules/typescript/bin/tsc"),
                "-p",
                str(self.root / "typescript-sdk/tsconfig.json"),
            ]
        )
        port = self.dc("port", "ingress", "8443").strip().rsplit(":", 1)[1]
        sdk_env = self.env | {
            "SDK_URL": f"https://api.accept.test:{port}",
            "SDK_TOKEN": token,
            "SDK_TENANT": str(self.tenant),
            "SSL_CERT_FILE": str(self.root / "tls/fullchain.pem"),
            "NODE_EXTRA_CA_CERTS": str(self.root / "tls/fullchain.pem"),
            "NO_PROXY": "*",
        }
        py = self.root / "python-sdk-check.py"
        py.write_text("""import os,socket,asyncio,ssl,httpx
from ontology_sdk import OntologyClient,SDKError
from ontology_sdk.models import UpdateMachineStatusParameters
original=socket.getaddrinfo
def resolve(host,*args,**kwargs):
 target='127.0.0.1' if host in ('api.accept.test',b'api.accept.test') else host
 return original(target,*args,**kwargs)
socket.getaddrinfo=resolve
async def token(): return os.environ['SDK_TOKEN']
async def main():
 http=httpx.AsyncClient(verify=ssl.create_default_context(cafile=os.environ['SSL_CERT_FILE']),
                        trust_env=False,follow_redirects=False,timeout=30)
 client=OntologyClient(os.environ['SDK_URL'],token,os.environ['SDK_TENANT'],http=http)
 assert (await client.Machine.get('MCH-005')).object_id=='MCH-005'
 critical=client.Machine.query().where(client.Machine.fields.operationalStatus.eq('CRITICAL'))
 assert len((await critical.execute()).items)==2
 machine=await client.Machine.get('MCH-006')
 params=UpdateMachineStatusParameters(machineId='MCH-006',newStatus='STOPPED',expectedRevision=machine.version)
 action=client.actions.UpdateMachineStatus
 result=await action.execute(params,idempotency_key='deployed-python-sdk')
 replay=await action.execute(params,idempotency_key='deployed-python-sdk')
 assert result.execution_id==replay.execution_id
 async def invalid(): return 'invalid'
 cases=((invalid,os.environ['SDK_TENANT'],401),
        (token,'00000000-0000-0000-0000-000000000099',403))
 for provider,tenant,status in cases:
  denied=OntologyClient(os.environ['SDK_URL'],provider,tenant,http=http)
  try: await denied.Machine.get('MCH-005')
  except SDKError as error: assert error.status==status
  else: raise AssertionError('unauthorized SDK access')
  await denied.close()
 await client.close()
 await http.aclose()
asyncio.run(main())
""")
        ts = self.root / "typescript-sdk/check.mjs"
        ts.write_text("""import dns from 'node:dns';
import assert from 'node:assert/strict';
import {OntologyClient,SDKError} from './dist/index.js';
const original=dns.lookup;
dns.lookup=function(host,options,callback){
 if(host!=='api.accept.test')return original.apply(this,arguments);
 if(typeof options==='function'){callback=options;options={};}
 queueMicrotask(()=>options?.all?callback(null,[{address:'127.0.0.1',family:4}]):callback(null,'127.0.0.1',4));
};
const options={baseUrl:process.env.SDK_URL,tenantId:process.env.SDK_TENANT,
 tokenProvider:async()=>process.env.SDK_TOKEN};
const client=new OntologyClient(options);
assert.equal((await client.Machine.get('MCH-005')).object_id,'MCH-005');
const machine=await client.Machine.get('MCH-006');
const params={machineId:'MCH-006',newStatus:'RUNNING',expectedRevision:machine.version};
const result=await client.actions.UpdateMachineStatus.execute(params,'deployed-ts-sdk');
const replay=await client.actions.UpdateMachineStatus.execute(params,'deployed-ts-sdk');
assert.equal(result.execution_id,replay.execution_id);
const cases=[[{...options,tokenProvider:async()=>'invalid'},401],
 [{...options,tenantId:'00000000-0000-0000-0000-000000000099'},403]];
for(const [settings,status] of cases){
 const denied=new OntologyClient(settings);
 await assert.rejects(denied.Machine.get('MCH-005'),e=>e instanceof SDKError&&e.status===status);
}
""")
        for args in ([str(venv / "bin/python"), str(py)], ["node", str(ts)]):
            result = subprocess.run(
                args, cwd=self.root, env=sdk_env, capture_output=True, text=True
            )
            (
                self.root
                / ("sdk-check-" + ("python" if args[0] != "node" else "typescript") + ".log")
            ).write_text(result.stdout + result.stderr)
            assert result.returncode == 0, "Independent SDK execution failed; private sdk-check log"
        self.record(
            "independently-installed-python-built-typescript-sdks-real-https-queries-actions-replay-unauthorized-cross-tenant-denials"
        )

    def load(
        self,
        *,
        concurrencies: tuple[int, ...] = (1, 4, 8),
        iterations: int = 20,
        filename: str = "deployed-load.json",
    ) -> list[dict[str, Any]]:
        import math
        import statistics
        from concurrent.futures import ThreadPoolExecutor

        prefix = "/ontologies/manufacturing"
        cases = [
            ("query", "POST", prefix + "/objects/Machine/query", {"object_type": "Machine"}),
            ("object_set", "POST", prefix + "/object-sets/query", {"object_type": "Machine"}),
            (
                "traversal",
                "POST",
                prefix + "/traverse",
                {"object_type": "Machine", "traverse": [{"link": "locatedInFactory"}]},
            ),
            (
                "preview",
                "POST",
                prefix + "/actions/UpdateMachineStatus/preview",
                {
                    "parameters": {
                        "machineId": "MCH-005",
                        "newStatus": "RUNNING",
                        "expectedRevision": 2,
                    }
                },
            ),
            ("sdk", "POST", prefix + "/sdk/generate", {"version": "1.0.0", "language": "python"}),
        ]
        measurements = []
        for concurrency in concurrencies:
            started = time.monotonic()

            def client(index: int) -> list[dict]:
                samples = []
                for iteration in range(iterations):
                    name, method, path, body = cases[(iteration + index) % len(cases)]
                    stamp = time.monotonic()
                    try:
                        self.api(method, path, body)
                        status = "PASS"
                    except Exception:
                        status = "FAIL"
                    samples.append(
                        {
                            "operation": name,
                            "seconds": time.monotonic() - stamp,
                            "result": status,
                            "client": index,
                            "iteration": iteration,
                            **(
                                getattr(self.request_local, "timing", {})
                                if getattr(self, "diagnostic_requests", False)
                                else {}
                            ),
                        }
                    )
                    time.sleep(max(0, 1 - (time.monotonic() - stamp)))
                return samples

            with ThreadPoolExecutor(concurrency) as pool:
                samples = [s for group in pool.map(client, range(concurrency)) for s in group]
            elapsed = time.monotonic() - started
            latency = sorted(s["seconds"] * 1000 for s in samples)
            measurements.append(
                {
                    "concurrency": concurrency,
                    "seconds": elapsed,
                    "requests": len(samples),
                    "requests_per_second": len(samples) / elapsed,
                    "errors": sum(s["result"] != "PASS" for s in samples),
                    "p50_ms": statistics.median(latency),
                    "p95_ms": latency[math.ceil(0.95 * len(latency)) - 1],
                    "p99_ms": latency[math.ceil(0.99 * len(latency)) - 1],
                    "samples": samples,
                }
            )
        self.dc("--profile", "workers", "ps", "--format", "json")
        (self.output / filename).write_text(
            json.dumps(
                {
                    "measurements": measurements,
                    "scope": (
                        f"{iterations} iterations/client at {concurrencies} clients; "
                        "paced <=1 request/s/client "
                        "through HTTPS Studio BFF; fixture scale; curl/client overhead included; "
                        "not saturation or approved capacity certification"
                    ),
                    "metrics_not_measured": [
                        "continuous database pool usage",
                        "lock-wait distribution",
                        "worker throughput",
                        "queue age",
                        "storage growth under sustained ingestion",
                    ],
                    "provisional_targets": (
                        "read p95 <500ms; writes <2000ms; zero errors; not business SLOs"
                    ),
                },
                indent=2,
            )
            + "\n"
        )
        assert all(m["errors"] == 0 for m in measurements), measurements
        self.record(
            "paced-deployed-https-load",
            evidence=filename,
            requests=sum(m["requests"] for m in measurements),
        )

        return measurements

    def rotate_credentials(self) -> None:
        import psycopg
        from psycopg import sql

        def write_secret(name: str, value: str) -> None:
            path = self.root / "secrets" / name
            path.chmod(0o600)
            path.write_text(value)
            path.chmod(0o440)
            self.passwords[name] = value

        # Public Studio clients have no client secret. Rotate the confidential worker client.
        self.dc(
            "exec",
            "-T",
            "keycloak",
            "/bin/bash",
            "-ec",
            "/opt/keycloak/bin/kcadm.sh config credentials --config /tmp/accept-kcadm.config "
            "--server http://127.0.0.1:8080 --realm master --user operator "
            '--password "$(cat /run/secrets/keycloak_admin_password)"',
        )
        command = self.compose + ["exec", "-T", "keycloak", "/opt/keycloak/bin/kcadm.sh"]
        clients = json.loads(
            self.run(
                command
                + [
                    "get",
                    "clients",
                    "--config",
                    "/tmp/accept-kcadm.config",
                    "-r",
                    "foundry",
                    "-q",
                    "clientId=worker",
                    "--fields",
                    "id,clientId",
                ]
            )
        )
        new = secrets.token_urlsafe(36)
        self.run(
            command
            + [
                "update",
                "clients/" + clients[0]["id"],
                "--config",
                "/tmp/accept-kcadm.config",
                "-r",
                "foundry",
                "--merge",
                "-f",
                "-",
            ],
            input=json.dumps({"secret": new}),
        )
        endpoint = "/realms/foundry/protocol/openid-connect/token"
        form = {
            "grant_type": "client_credentials",
            "client_id": "worker",
            "client_secret": self.passwords["FOUNDRY_WORKER_CLIENT_SECRET"],
        }
        assert self.request("identity.accept.test", endpoint, "POST", data=form).status_code == 401
        assert (
            self.request(
                "identity.accept.test", endpoint, "POST", data=form | {"client_secret": new}
            ).status_code
            == 200
        )
        write_secret("FOUNDRY_WORKER_CLIENT_SECRET", new)
        self.dc("restart", "ingestion-worker", "semantic-worker")
        self.record("deployed-worker-oidc-client-secret-rotation-old-secret-rejected")
        # Exercise revocation before a queued job is claimed, independently of JWT expiry.
        from ontology_platform.security.contracts import MembershipInput

        self.admin.member(self.actor, self.worker_id, MembershipInput(enabled=False))
        run = self.api(
            "POST",
            "/ontologies/manufacturing/ingestion/runs",
            {
                "idempotency_key": "rotation-revocation-repeat",
                "mappings": [
                    {"id": k, "version": 2}
                    for k in ("Factory", "Machine", "Employee", "MaintenanceTask")
                ],
            },
        )
        time.sleep(5)
        job = self.api("GET", "/ontologies/manufacturing/ingestion/runs/" + run["id"])
        assert job["status"] == "PENDING" and job["attempts"] == 0
        self.admin.member(self.actor, self.worker_id, MembershipInput(enabled=True))
        for _ in range(90):
            job = self.api("GET", "/ontologies/manufacturing/ingestion/runs/" + run["id"])
            if job["status"] in ("COMPLETED", "FAILED"):
                break
            time.sleep(1)
        assert job["status"] == "COMPLETED" and job["created"] == 0, job
        self.record(
            "deployed-worker-reacquires-rotated-credential-queued-service-revocation-idempotent-continuation"
        )
        # Rotate API/Studio internal transport credential together in a maintenance window.
        write_secret("FOUNDRY_BROWSER_STATE_SECRET", secrets.token_urlsafe(36))
        self.dc("restart", "api", "studio")
        self.wait("api.accept.test", "/health/ready")
        for _ in range(60):
            if (
                self.request("studio.accept.test", "/auth/session", cookies=self.cookie).status_code
                == 200
            ):
                break
            time.sleep(1)
        else:
            raise RuntimeError("Internal credential rotation lost a valid session")
        self.record(
            "deployed-api-studio-internal-credential-maintenance-rotation-session-continuity"
        )
        self.dc("stop", "api", "ingestion-worker", "semantic-worker")
        new_password = secrets.token_urlsafe(36)
        old_password = self.passwords["runtime_password"]
        with psycopg.connect(self.env["FOUNDRY_ADMIN_DATABASE_URL"], autocommit=True) as connection:
            connection.execute(
                sql.SQL("ALTER ROLE foundry_runtime PASSWORD {}").format(sql.Literal(new_password))
            )
        write_secret("runtime_password", new_password)
        write_secret(
            "FOUNDRY_DATABASE_URL",
            f"postgresql+psycopg://foundry_runtime:{new_password}@postgres:5432/foundry",
        )
        from psycopg.conninfo import make_conninfo

        info = make_conninfo(
            self.env["FOUNDRY_ADMIN_DATABASE_URL"],
            user="foundry_runtime",
            dbname="foundry",
            password=old_password,
        )
        try:
            psycopg.connect(info).close()
        except psycopg.OperationalError:
            pass
        else:
            raise AssertionError("Revoked database password accepted on new connection")
        with psycopg.connect(make_conninfo(info, password=new_password)) as connection:
            assert connection.execute("SELECT current_user").fetchone()[0] == "foundry_runtime"
        self.dc("start", "api", "ingestion-worker", "semantic-worker")
        self.wait("api.accept.test", "/health/ready")
        assert (
            self.request("studio.accept.test", "/auth/session", cookies=self.cookie).status_code
            == 200
        )
        self.record(
            "deployed-database-credential-maintenance-rotation-old-login-rejected-session-continuity"
        )

    def ingress_negatives(self) -> None:
        from urllib.parse import parse_qs

        port = self.dc("port", "ingress", "8443").strip().rsplit(":", 1)[1]
        plain = self.dc("port", "ingress", "8080").strip().rsplit(":", 1)[1]
        value = self.run(
            [
                "curl",
                "-sS",
                "--noproxy",
                "*",
                "--resolve",
                f"studio.accept.test:{plain}:127.0.0.1",
                "-H",
                "Host: studio.accept.test",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code} %{redirect_url}",
                f"http://studio.accept.test:{plain}/safe?code=disposable-redirect-log-sentinel",
            ]
        )
        assert (
            value == "308 https://studio.accept.test/safe?code=disposable-redirect-log-sentinel"
        ), value
        unknown = subprocess.run(
            [
                "curl",
                "-sS",
                "--noproxy",
                "*",
                "--cacert",
                str(self.root / "tls/fullchain.pem"),
                "--resolve",
                f"studio.accept.test:{port}:127.0.0.1",
                "-H",
                "Host: attacker.example",
                f"https://studio.accept.test:{port}/?code=disposable-default-log-sentinel",
            ],
            capture_output=True,
        )
        assert unknown.returncode != 0
        untrusted = subprocess.run(
            [
                "curl",
                "-sS",
                "--noproxy",
                "*",
                "--resolve",
                f"studio.accept.test:{port}:127.0.0.1",
                f"https://studio.accept.test:{port}/",
            ],
            capture_output=True,
        )
        assert untrusted.returncode == 60
        assert (
            self.request(
                "studio.accept.test",
                "/auth/login",
                "POST",
                headers={
                    "Origin": "https://attacker.example",
                    "X-Forwarded-Host": "studio.accept.test",
                    "X-Forwarded-Proto": "https",
                },
            ).status_code
            == 403
        )
        auth = self.request(
            "studio.accept.test",
            "/auth/login",
            "POST",
            headers={"Origin": self.origin, "X-Forwarded-Host": "attacker.example"},
            json={"returnTo": "https://attacker.example"},
        )
        assert parse_qs(urlsplit(auth.json()["authorization"]).query)["redirect_uri"] == [
            self.origin + "/auth/callback"
        ]
        assert auth.headers.get("strict-transport-security") == "max-age=31536000"
        assert (
            self.request(
                "studio.accept.test",
                "/bff",
                "POST",
                cookies=self.cookie,
                headers={"Origin": self.origin},
                json={},
            ).status_code
            == 403
        )
        assert (
            self.request(
                "studio.accept.test", "/bff", "POST", json={"oversized": "x" * 70000}
            ).status_code
            == 413
        )
        logs = self.dc("logs", "--no-color", "ingress")
        assert "disposable-redirect-log-sentinel" not in logs
        assert "disposable-default-log-sentinel" not in logs
        self.record(
            "deployed-http-redirect-unknown-host-untrusted-cert-forged-origin-fixed-callback-hsts-csrf-body-limit-redacted-logs"
        )

    def recovery(self) -> None:
        import hashlib

        from sqlalchemy import text

        self.dc("--profile", "workers", "stop", "ingestion-worker", "semantic-worker")
        container = self.dc("ps", "-q", "postgres").strip()
        tables = [
            "alembic_version",
            "ontologies",
            "ontology_versions",
            "schema_activations",
            "objects",
            "object_links",
            "ontology_branches",
            "ontology_branch_revisions",
            "ontology_branch_merges",
            "sdk_artifacts",
            "principals",
            "external_identities",
            "tenant_memberships",
            "role_assignments",
            "authorization_audit",
            "action_executions",
            "action_audit_events",
            "ingestion_runs",
            "semantic_jobs",
            "semantic_artifacts",
            "browser_state",
        ]

        def snapshot(database: str) -> dict[str, str]:
            return {
                table: self.run(
                    [
                        "docker",
                        "exec",
                        container,
                        "psql",
                        "-U",
                        "postgres",
                        "-d",
                        database,
                        "-Atc",
                        "SELECT count(*)||':'||md5(coalesce(string_agg(md5(to_jsonb(t)::text),"
                        f"'' ORDER BY md5(to_jsonb(t)::text)),'')) FROM {table} t",
                    ]
                ).strip()
                for table in tables
            }

        before = snapshot("foundry")
        age = ROOT / "artifacts/age-tool/age"
        if not (age / "age-keygen").is_file():
            self.record(
                "deployed-encrypted-logical-recovery",
                "NOT RUN",
                reason="Install age and age-keygen; no plaintext backup substituted",
            )
            return
        self.env["PATH"] = str(age) + os.pathsep + self.env["PATH"]
        key = self.root / "backup.key"
        self.run(["age-keygen", "-o", str(key)])
        recipient = self.run(["age-keygen", "-y", str(key)]).strip()
        backup = self.root / "foundry.dump.age"
        self.run(
            [
                "uv",
                "run",
                "python",
                "scripts/backup_database.py",
                "--container",
                container,
                "--database",
                "foundry",
                "--user",
                "foundry_migrator",
                "--recipient",
                recipient,
                "--output",
                str(backup),
            ]
        )
        self.run(["docker", "exec", container, "createdb", "-U", "postgres", "acceptance_restore"])
        decrypted = subprocess.run(
            ["age", "-d", "-i", str(key), str(backup)],
            env=self.env,
            capture_output=True,
            check=True,
        )
        restored = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                container,
                "pg_restore",
                "-U",
                "postgres",
                "--no-owner",
                "--exit-on-error",
                "-d",
                "acceptance_restore",
            ],
            input=decrypted.stdout,
            capture_output=True,
        )
        assert restored.returncode == 0, restored.stderr.decode()
        after = snapshot("acceptance_restore")
        assert before == after, {k: (v, after[k]) for k, v in before.items() if v != after[k]}
        self.record(
            "deployed-encrypted-logical-restore-all-domain-identity-history-session-checksums",
            tables=before,
            ciphertext_sha256=hashlib.sha256(backup.read_bytes()).hexdigest(),
        )
        with self.engine.connect() as sql:
            assert sql.scalar(text("SELECT version_num FROM alembic_version")) == "0017_capacity"

    def admission(self) -> None:
        import statistics
        import threading
        from concurrent.futures import ThreadPoolExecutor

        from ontology_platform.db.models import IngestionRun, SemanticJob
        from sqlalchemy import func, select, text

        self.dc("--profile", "workers", "stop", "ingestion-worker", "semantic-worker")
        prefix = "/ontologies/manufacturing/ingestion/runs"
        stop = threading.Event()
        waiters: list[int] = []

        def observe() -> None:
            while not stop.is_set():
                with self.engine.connect() as sql:
                    waiters.append(
                        sql.scalar(
                            text(
                                "SELECT count(*) FROM pg_stat_activity "
                                "WHERE datname='foundry' AND wait_event_type='Lock'"
                            )
                        )
                    )
                stop.wait(0.02)

        def submit(index: int) -> tuple[int, str | None, float]:
            stamp = time.monotonic()
            response = self.request(
                "studio.accept.test",
                "/bff",
                "POST",
                cookies=self.cookie,
                headers={"Origin": self.origin, "x-csrf-token": self.csrf},
                json={
                    "method": "POST",
                    "path": "/api/v1" + prefix,
                    "expected_tenant": str(self.tenant),
                    "body": {
                        "idempotency_key": "admission-" + str(index),
                        "mappings": [{"id": "Factory", "version": 2}],
                    },
                },
            )
            result = response.json()
            if response.status_code == 409:
                assert result["error"]["code"] == "constraint_conflict", result
            return response.status_code, result.get("id"), time.monotonic() - stamp

        thread = threading.Thread(target=observe, daemon=True)
        thread.start()
        try:
            with ThreadPoolExecutor(12) as pool:
                attempts = list(pool.map(submit, range(24)))
        finally:
            stop.set()
            thread.join(timeout=5)
        accepted = [key for status, key, _ in attempts if status == 200]
        time.sleep(1)  # Refill the separate ingress burst budget before cancellation checks.
        assert len(accepted) == 20 and sum(status == 409 for status, _, _ in attempts) == 4, (
            attempts
        )

        def active() -> int:
            with self.sessions() as sql:
                return sum(
                    sql.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(
                            model.tenant_id == self.tenant, model.status.in_(("PENDING", "RUNNING"))
                        )
                    )
                    for model in (IngestionRun, SemanticJob)
                )

        assert active() == 20
        assert submit(100)[0] == 409 and active() == 20
        self.api("POST", prefix + "/" + accepted[0] + "/cancel", {})
        assert active() == 19
        status, key, _ = submit(101)
        assert status == 200 and key and active() == 20
        for run in accepted[1:] + [key]:
            assert self.api("POST", prefix + "/" + run + "/cancel", {})["status"] == "CANCELLED"
        assert active() == 0
        report = {
            "requests": 24,
            "concurrent_clients": 12,
            "accepted": 20,
            "quota_rejected": 4,
            "active_limit": 20,
            "after_cancellation": 0,
            "failed_admission_consumed_slot": False,
            "cancelled_slot_reused": True,
            "lock_waiter_samples": waiters,
            "peak_observed_lock_waiters": max(waiters, default=0),
            "median_http_ms": round(statistics.median(a[2] for a in attempts) * 1000, 3),
            "max_http_ms": round(max(a[2] for a in attempts) * 1000, 3),
            "scope": "One disposable tenant's shared ingestion/semantic admission; "
            "not physical storage or cross-tenant quota saturation certification",
        }
        (self.output / "admission.json").write_text(json.dumps(report, indent=2) + "\n")
        self.record("deployed-concurrent-job-admission-limit-rollback-and-cancel-release", **report)

    def physical_recovery(self) -> None:
        from phase10_pitr import physical_recovery

        # Freeze broker writes so both databases can be compared at one recovery point.
        # Existing valid cached JWTs remain usable; no new sign-in is attempted during outage.
        self.login()
        self.dc("stop", "keycloak")
        try:

            def commit_record(stage: str) -> None:
                key = "PITR-" + stage
                self.api(
                    "POST",
                    "/ontologies/manufacturing/objects/Factory",
                    {
                        "object_id": key,
                        "properties": {
                            "factoryId": key,
                            "factoryName": "Disposable recovery " + stage,
                            "location": "Acceptance",
                        },
                    },
                )

            result = physical_recovery(
                source=self.dc("ps", "-q", "postgres").strip(),
                project=self.project,
                archive=self.root / "wal",
                private=self.root,
                commit_record=commit_record,
                verify_application=getattr(self, "verify_recovered_application", None),
                recovery_network=self.project + "_data"
                if hasattr(self, "verify_recovered_application")
                else None,
            )
            (self.output / "physical-recovery.json").write_text(json.dumps(result, indent=2) + "\n")
            self.record(
                "complete-profile-postgresql-17-physical-wal-pitr-foundry-and-keycloak",
                tables={db: len(tables) for db, tables in result["databases"].items()},
                records=result["restored_records"],
                target_lsn=result["target_lsn"],
            )
        finally:
            self.dc("start", "keycloak")
            self.wait("identity.accept.test", "/realms/foundry/.well-known/openid-configuration")

    def revocation(self) -> None:
        from ontology_platform.security.contracts import (
            AssignmentInput,
            IdentityInput,
            MembershipInput,
        )
        from ontology_platform.security.identity import resolve

        maintenance = self.admin.identity(
            self.actor, IdentityInput(issuer=self.issuer, subject="disposable-maintenance")
        )
        self.admin.assign(
            self.actor, AssignmentInput(principal_id=maintenance, role_id="tenant-administrator")
        )
        operator = resolve(
            self.sessions,
            self.issuer,
            "disposable-maintenance",
            self.tenant,
            method="oidc",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        self.admin.assign(
            operator,
            AssignmentInput(principal_id=self.actor.principal_id, role_id="tenant-administrator"),
            revoke=True,
        )
        self.api("GET", "/ontologies/manufacturing/objects/Machine/MCH-005", expected=403)
        self.admin.assign(
            operator,
            AssignmentInput(principal_id=self.actor.principal_id, role_id="tenant-administrator"),
        )
        self.admin.member(operator, self.actor.principal_id, MembershipInput(enabled=False))
        self.api("GET", "/ontologies/manufacturing/objects/Machine/MCH-005", expected=403)
        self.admin.member(operator, self.actor.principal_id, MembershipInput(enabled=True))
        assert (
            self.api("GET", "/ontologies/manufacturing/objects/Machine/MCH-005")["object_id"]
            == "MCH-005"
        )
        self.record("deployed-active-session-role-and-membership-revocation-before-jwt-expiry")

    def rollback(self) -> None:
        before = self.api("GET", "/ontologies/manufacturing/objects/Machine/MCH-005")
        artifacts = self.api("GET", "/ontologies/manufacturing/sdk/artifacts")
        self.dc("stop", "api")
        assert (
            self.request("studio.accept.test", "/auth/session", cookies=self.cookie).status_code
            >= 400
        )
        previous = self.env["API_IMAGE"]
        self.env["API_IMAGE"] = "csh-foundry-api:phase10"
        try:
            self.dc("up", "-d", "--no-deps", "--force-recreate", "api")
            self.wait("api.accept.test", "/health/ready")
            assert self.api("GET", "/ontologies/manufacturing/objects/Machine/MCH-005") == before
            assert self.api("GET", "/ontologies/manufacturing/sdk/artifacts") == artifacts
            assert self.api("GET", "/ontologies/manufacturing")["active_version"] == "1.0.0"
            self.record(
                "same-schema-api-outage-rollback-to-previous-image-session-data-sdk-history"
            )
        finally:
            self.env["API_IMAGE"] = previous
            self.dc("up", "-d", "--no-deps", "--force-recreate", "api")
            self.wait("api.accept.test", "/health/ready")

    def replica_session(self, container: str) -> int:
        name = (
            self.run(["docker", "inspect", container, "--format", "{{.Name}}"]).strip().lstrip("/")
        )
        code = """import sys,json,urllib.request,urllib.error
request=urllib.request.Request('http://'+sys.argv[1]+':3000/auth/session',
 headers={'Cookie':sys.stdin.read(),'Host':'studio.accept.test'})
try: response=urllib.request.urlopen(request,timeout=3)
except urllib.error.HTTPError as error: response=error
print(response.status)
"""
        return int(
            self.run(
                self.compose + ["exec", "-T", "api", "python", "-c", code, name], input=self.cookie
            )
        )

    def rotate_session_keys(self) -> None:
        path = self.root / "secrets/FOUNDRY_BROWSER_STATE_KEYS"
        path.chmod(0o600)
        new = Fernet.generate_key().decode()
        path.write_text(new + "," + self.passwords["FOUNDRY_BROWSER_STATE_KEYS"])
        path.chmod(0o440)
        self.dc("restart", "api")
        self.wait("api.accept.test", "/health/ready")
        assert (
            self.request("studio.accept.test", "/auth/session", cookies=self.cookie).status_code
            == 200
        )
        path.chmod(0o600)
        path.write_text(new)
        path.chmod(0o440)
        self.dc("restart", "api")
        self.wait("api.accept.test", "/health/ready")
        assert (
            self.request("studio.accept.test", "/auth/session", cookies=self.cookie).status_code
            >= 400
        )
        self.record("deployed-session-key-overlap-and-unsupported-ciphertext-rejection")
        self.passwords["FOUNDRY_BROWSER_STATE_KEYS"] = new
        self.login()

    def faults(self) -> None:
        assert self.request("api.accept.test", "/api/v1/ontologies").status_code == 401
        for host, path in (
            ("api.accept.test", "/internal/metrics"),
            ("studio.accept.test", "/internal/browser-state/session/x"),
            ("identity.accept.test", "/admin/"),
        ):
            assert self.request(host, path).status_code == 404
        self.record("public-private-route-and-unauthenticated-denial")
        self.dc("up", "-d", "--scale", "studio=2", "studio")
        replicas = self.dc("ps", "-q", "studio").split()
        assert len(replicas) == 2

        def ready(container: str) -> None:
            for _ in range(60):
                try:
                    if self.replica_session(container) == 200:
                        return
                except subprocess.CalledProcessError:
                    pass
                time.sleep(1)
            raise RuntimeError("replica did not accept durable session")

        for replica in replicas:
            ready(replica)
        self.run(["docker", "restart", replicas[0]])
        assert self.replica_session(replicas[1]) == 200
        ready(replicas[0])
        self.run(["docker", "restart", replicas[1]])
        assert self.replica_session(replicas[0]) == 200
        ready(replicas[1])
        self.record("deployed-two-studio-replicas-both-restarts-durable-session-continuity")
        self.dc("restart", "studio")
        for _ in range(60):
            try:
                if (
                    self.request(
                        "studio.accept.test", "/auth/session", cookies=self.cookie
                    ).status_code
                    == 200
                ):
                    break
            except subprocess.CalledProcessError:
                pass
            time.sleep(1)
        else:
            raise RuntimeError("session did not survive Studio restart")
        self.record("production-studio-restart-session-continuity")
        self.dc("stop", "postgres")
        assert (
            self.request("studio.accept.test", "/auth/session", cookies=self.cookie).status_code
            >= 400
        )
        assert self.request("api.accept.test", "/api/v1/ontologies").status_code >= 400
        self.record("production-session-store-outage-fails-closed")
        self.dc("start", "postgres")
        self.wait("api.accept.test", "/health/ready")
        logout = self.request(
            "studio.accept.test",
            "/auth/logout",
            "POST",
            cookies=self.cookie,
            headers={"Origin": self.origin, "x-csrf-token": self.csrf},
        )
        assert logout.status_code == 200
        assert (
            self.request("studio.accept.test", "/auth/session", cookies=self.cookie).status_code
            == 401
        )
        assert all(self.replica_session(replica) == 401 for replica in replicas)
        self.record("production-shared-logout-rejection-both-deployed-replicas")

    def execute(self) -> None:
        try:
            self.prepare()
            self.provision()
            self.dc("up", "-d", "--wait", "api", "studio")
            self.wait("identity.accept.test", "/realms/foundry/.well-known/openid-configuration")
            self.record("complete-production-profile-core-startup")
            self.seed()
            self.dc("restart", "api")
            self.wait("api.accept.test", "/health/ready")
            self.login()
            self.workflow()
            self.runtime_controls()
            self.independent_sdks()
            self.load()
            self.revocation()
            self.login()
            self.rotate_credentials()
            self.recovery()
            self.admission()
            self.physical_recovery()
            self.rollback()
            self.rotate_session_keys()
            self.ingress_negatives()
            self.faults()
        except Exception as error:
            # Never export HTTP callback/token bodies or command environment in public evidence.
            (self.root / "failure.txt").write_text(
                str(error) + "\n" + str(getattr(error, "output", ""))
            )
            self.record(
                "acceptance-execution",
                "FAIL",
                error_type=type(error).__name__,
                detail="See private failure.txt; downstream checks NOT RUN",
            )
            raise
        finally:
            if self.compose:
                (self.root / "compose.log").write_text(self.dc("logs", "--no-color"))
                (self.root / "containers.json").write_text(
                    self.dc("ps", "--all", "--format", "json")
                )
                self.dc("--profile", "workers", "down", "--volumes", "--remove-orphans")
            if hasattr(self, "engine"):
                self.engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs/architecture/evidence/phase-10-closure"
    )
    parser.add_argument("--candidate-images", type=Path)
    args = parser.parse_args()
    try:
        images = json.loads(args.candidate_images.read_text()) if args.candidate_images else None
        Acceptance(args.output, images).execute()
    except Exception:
        raise SystemExit("FAIL: see deployment.json and its private evidence directory") from None


if __name__ == "__main__":
    main()
