"""Additional isolated API scrape/alert and real broker outage acceptance."""

import argparse
import json
import time
from pathlib import Path

import jwt
from accept_phase10 import ROOT, Acceptance
from cryptography.hazmat.primitives.asymmetric import rsa
from test_alert_delivery import main as alerts


class OperationsAcceptance(Acceptance):
    def worker_token(self) -> str:
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
        assert response.status_code == 200
        return response.json()["access_token"]

    def validate_fresh(self, token: str, expected: bool) -> None:
        code = """import os
from ontology_platform.config import get_settings
from ontology_platform.security.oidc import OIDCVerifier
from ontology_platform.errors import ApplicationError
s=get_settings()
v=OIDCVerifier(s.oidc_providers,ca_bundle=s.oidc_ca_bundle)
try:
 try:
  v.verify(os.environ['ACCEPT_TOKEN'])
  actual=True
 except ApplicationError:
  actual=False
 assert actual == (os.environ['ACCEPT_EXPECTED']=='true')
finally:
 v.client.close()
"""
        self.dc(
            "exec",
            "-T",
            "-e",
            "ACCEPT_TOKEN=" + token,
            "-e",
            "ACCEPT_EXPECTED=" + str(expected).lower(),
            "api",
            "python",
            "-c",
            code,
        )

    def authentication_faults(self) -> None:
        token = self.worker_token()
        self.validate_fresh(token, True)
        headers = {"Authorization": "Bearer " + token, "X-Tenant-ID": str(self.tenant)}
        assert (
            self.request("api.accept.test", "/api/v1/security/me", headers=headers).status_code
            == 200
        )
        config_path = "/etc/nginx/conf.d/default.conf"
        original = self.dc("exec", "-T", "ingress", "cat", config_path)

        def configure(config):
            self.dc(
                "exec",
                "-T",
                "ingress",
                "sh",
                "-ec",
                "cat > /etc/nginx/conf.d/default.conf; nginx -t; nginx -s reload",
                input=config,
            )
            time.sleep(1)

        try:
            configure(
                original.replace(
                    "server_name identity.accept.test;",
                    "server_name identity.accept.test;\n"
                    "location = /realms/foundry/protocol/openid-connect/certs { return 503; }",
                )
            )
            assert (
                self.request(
                    "identity.accept.test", "/realms/foundry/.well-known/openid-configuration"
                ).status_code
                == 200
            )
            assert (
                self.request(
                    "identity.accept.test", "/realms/foundry/protocol/openid-connect/certs"
                ).status_code
                == 503
            )
            self.validate_fresh(token, False)
        finally:
            configure(original)
        self.validate_fresh(token, True)
        self.record("real-jwks-only-outage-new-verifier-denial-and-recovery")
        self.dc("stop", "keycloak")
        try:
            assert (
                self.request(
                    "identity.accept.test", "/realms/foundry/.well-known/openid-configuration"
                ).status_code
                >= 500
            )
            self.validate_fresh(token, False)
            # A known, valid cached signing key remains acceptable until its bounded TTL.
            assert (
                self.request("api.accept.test", "/api/v1/security/me", headers=headers).status_code
                == 200
            )
            login = self.request(
                "studio.accept.test", "/auth/login", "POST", headers={"Origin": self.origin}
            )
            if login.status_code == 200:
                from urllib.parse import urlsplit

                target = urlsplit(login.json()["authorization"])
                assert (
                    self.request(
                        "identity.accept.test", target.path + "?" + target.query
                    ).status_code
                    >= 500
                )
            else:
                assert login.status_code >= 400
        finally:
            self.dc("start", "keycloak")
            self.wait("identity.accept.test", "/realms/foundry/.well-known/openid-configuration")
        self.record(
            "broker-outage-login-unavailable-cached-token-bounded-and-fresh-verifier-denied"
        )
        forged = jwt.encode(
            jwt.decode(token, options={"verify_signature": False}),
            rsa.generate_private_key(public_exponent=65537, key_size=2048),
            algorithm="RS256",
            headers=jwt.get_unverified_header(token),
        )
        assert (
            self.request(
                "api.accept.test",
                "/api/v1/security/me",
                headers=headers | {"Authorization": "Bearer " + forged},
            ).status_code
            == 401
        )
        self.record("real-api-invalid-signing-key-denied")
        # Change only this disposable realm, then obtain a genuinely issuer-signed short token.
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
        command = [
            "exec",
            "-T",
            "keycloak",
            "/opt/keycloak/bin/kcadm.sh",
            "update",
            "realms/foundry",
            "--config",
            "/tmp/accept-kcadm.config",
            "-s",
        ]
        self.dc(*command, "accessTokenLifespan=1")
        try:
            expired = self.worker_token()
            time.sleep(2)
            assert (
                self.request(
                    "api.accept.test",
                    "/api/v1/security/me",
                    headers=headers | {"Authorization": "Bearer " + expired},
                ).status_code
                == 401
            )
        finally:
            self.dc(*command, "accessTokenLifespan=300")
        self.record("real-issuer-signed-expired-access-token-denied")
        self.login()
        OperationsAcceptance.deployed_capacity(self)
        OperationsAcceptance.sdk_faults(self)
        OperationsAcceptance.signing_rotation(self)

    def deployed_capacity(self) -> None:
        import base64
        import hashlib
        from concurrent.futures import ThreadPoolExecutor

        from ontology_platform.config import Settings
        from ontology_platform.db.models import TenantResourceUsage
        from ontology_platform.security.bootstrap import bootstrap
        from ontology_platform.security.browser import BrowserStore
        from pydantic import SecretStr
        from test_ingestion import setup

        folder = self.root / "ingestion" / "second-tenant"
        folder.mkdir()
        world, ingestion, _ = setup((self.engine, self.sessions, self.url), folder)
        other = world.actor.tenant_id
        self.secondary_tenant = other
        with self.sessions.begin() as sql:
            bootstrap(sql, other, self.issuer, self.subject, "Second disposable tenant")
        catalog = self.root / "catalog.json"
        original_catalog = catalog.read_text()
        additions = [
            b.model_dump(mode="json") | {"root": "/data/ingestion/second-tenant"}
            for b in ingestion.catalog.bindings.values()
        ]
        catalog.write_text(json.dumps(json.loads(original_catalog) + additions))
        # Publish the changed server-side root as a new governed registration version.
        # Reusing the host-path fingerprint would correctly fail registration_changed.
        from ontology_platform.db.models import IngestionMapping
        from ontology_platform.ingestion.catalog import Binding, SourceCatalog
        from ontology_platform.ingestion.contracts import MappingInput, SourceInput

        ingestion.catalog = SourceCatalog([Binding.model_validate(b) for b in additions])
        for kind in ("Factory", "Machine", "Employee", "MaintenanceTask"):
            ingestion.create_source(
                world.actor,
                "manufacturing",
                SourceInput(id=kind, name=kind, binding=kind, identity_namespace=kind, version=2),
            )
            with self.sessions() as sql:
                row = sql.get(IngestionMapping, (other, "manufacturing", kind, 1))
                mapping = MappingInput.model_validate_json(row.definition_json)
            ingestion.create_mapping(
                world.actor,
                "manufacturing",
                mapping.model_copy(update={"version": 2, "source_version": 2}),
            )
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
        token = BrowserStore(self.sessions, settings).operate("session", key, "GET").data["token"]
        self.user_token_for_faults = token

        def call(tenant, path, body, credential=token):
            return self.request(
                "api.accept.test",
                "/api/v1/ontologies/manufacturing/" + path,
                "POST",
                headers={"Authorization": "Bearer " + credential, "X-Tenant-ID": str(tenant)},
                json=body,
            )

        def usage(tenant):
            with self.sessions() as sql:
                row = sql.get(TenantResourceUsage, tenant)
                return row.bytes_used if row else 0

        self.dc("restart", "api")
        self.wait("api.accept.test", "/health/ready")
        shapes = {}
        exports = {}
        tenants = (self.tenant, other)
        for tenant in tenants:
            r = call(tenant, "semantic/compile", {"schema_version": "1.0.0"})
            assert r.status_code == 200
            shapes[tenant] = r.json()[1]
            exports[tenant] = []
            for limit in (45, 46, 47):
                r = call(
                    tenant,
                    "semantic/exports",
                    {
                        "schema_version": "1.0.0",
                        "selections": [{"object_type": "Factory", "limit": limit}],
                    },
                )
                assert r.status_code == 200
                exports[tenant].append(r.json())
        before = {tenant: usage(tenant) for tenant in tenants}
        # Exercise a valid production setting: the application requires at least one MiB.
        for index in range(32):
            if before[self.tenant] >= 1048576:
                break
            padding = f'<urn:quota:padding:{index}> <urn:p> "' + "p" * 60000 + '" .'
            response = call(
                self.tenant,
                "semantic/native-artifacts",
                {"schema_version": "1.0.0", "kind": "ontology", "content": padding},
            )
            assert response.status_code == 200, response.status_code
            before[self.tenant] = usage(self.tenant)
            time.sleep(0.15)
        assert before[self.tenant] >= 1048576
        capacity = before[self.tenant] + 18000
        assert before[other] + 120000 < capacity
        override = self.root / "deployed-quotas.yaml"
        override.write_text(
            "services:\n  api:\n    environment:\n"
            '      FOUNDRY_TENANT_PENDING_JOB_LIMIT: "4"\n'
            f'      FOUNDRY_TENANT_STORAGE_LIMIT_BYTES: "{capacity}"\n'
        )
        original = self.compose.copy()
        self.compose = original + ["-f", str(override)]
        try:
            self.dc("up", "-d", "--no-deps", "--force-recreate", "--wait", "api")

            def upload(pair):
                tenant, index = pair
                body = {
                    "schema_version": "1.0.0",
                    "kind": "ontology",
                    "content": f'<urn:quota:{index}> <urn:p> "' + "x" * 12000 + '" .',
                }
                r = call(tenant, "semantic/native-artifacts", body)
                assert r.status_code in (200, 409), r.status_code
                if r.status_code == 409:
                    assert r.json()["error"]["code"] == "constraint_conflict"
                return tenant, body, r.status_code, r.json()

            with ThreadPoolExecutor(8) as pool:
                uploads = list(pool.map(upload, [(t, i) for i in range(8) for t in tenants]))
            accepted = [(b, r) for t, b, status, r in uploads if t == self.tenant and status == 200]
            assert len(accepted) == 1
            assert sum(status == 409 for t, _, status, _ in uploads if t == self.tenant) == 7
            assert all(status == 200 for t, _, status, _ in uploads if t == other)
            used = {t: usage(t) for t in tenants}
            assert before[self.tenant] < used[self.tenant] <= capacity
            assert before[other] < used[other] <= capacity
            body, key = accepted[0]
            assert call(self.tenant, "semantic/native-artifacts", body).json() == key
            assert usage(self.tenant) == used[self.tenant]
            assert (
                call(
                    self.tenant, "semantic/native-artifacts", body | {"content": "invalid ttl"}
                ).status_code
                == 422
            )
            assert usage(self.tenant) == used[self.tenant]
            self.record(
                "deployed-logical-byte-saturation-concurrent-rollback-retry-independent-tenant",
                quota_bytes=capacity,
                primary_admitted=1,
                primary_rejected_409=7,
                secondary_admitted=8,
                primary_bytes_used=used[self.tenant],
                secondary_bytes_used=used[other],
                invalid_upload_rollback="PASS",
            )
            time.sleep(4)  # Separate tenant-capacity batches from the unchanged edge budget.

            def submit(pair):
                tenant, index = pair
                path = "semantic/jobs" if index < 3 else "ingestion/runs"
                body = (
                    {
                        "operation": "validation",
                        "primary_artifact": exports[tenant][index],
                        "secondary_artifact": shapes[tenant],
                    }
                    if index < 3
                    else {
                        "idempotency_key": "two-tenants-" + str(index),
                        "mappings": [{"id": "Factory", "version": 2}],
                    }
                )
                response = call(tenant, path, body)
                assert response.status_code in (200, 409), response.status_code
                return tenant, path, body, response.status_code, response.json()

            with ThreadPoolExecutor(8) as pool:
                attempts = list(pool.map(submit, [(t, i) for i in range(8) for t in tenants]))
            time.sleep(4)  # Allow quota replay/cancellation checks their own edge burst.
            for tenant in tenants:
                admitted = [
                    (path, body, r["id"])
                    for t, path, body, status, r in attempts
                    if t == tenant and status == 200
                ]
                from sqlalchemy import text

                runtime_limits = self.dc(
                    "exec",
                    "-T",
                    "api",
                    "python",
                    "-c",
                    "from ontology_platform.config import get_settings; "
                    "from ontology_platform.db.session import make_engine; "
                    "from sqlalchemy import text; s=get_settings(); e=make_engine(s); "
                    "c=e.connect(); print(s.tenant_pending_job_limit, "
                    "c.scalar(text('SHOW foundry.job_limit'))); c.close(); e.dispose()",
                )
                with self.sessions() as sql:
                    active = sql.scalar(
                        text(
                            "SELECT (SELECT count(*) FROM ingestion_runs "
                            "WHERE tenant_id=:tenant AND status IN ('PENDING','RUNNING')) + "
                            "(SELECT count(*) FROM semantic_jobs WHERE tenant_id=:tenant "
                            "AND status IN ('PENDING','RUNNING'))"
                        ),
                        {"tenant": tenant},
                    )
                observation = {
                    "tenant_index": tenants.index(tenant),
                    "accepted": len(admitted),
                    "active": active,
                    "runtime_limits": runtime_limits.strip(),
                    "attempts": [
                        {
                            "kind": path,
                            "status": status,
                            "id": r.get("id"),
                            "error_code": r.get("error", {}).get("code"),
                        }
                        for t, path, _, status, r in attempts
                        if t == tenant
                    ],
                }
                (
                    self.output / ("two-tenant-observation-" + str(tenants.index(tenant)) + ".json")
                ).write_text(json.dumps(observation, indent=2) + "\n")
                assert len(admitted) == 4, observation
                assert sum(status == 409 for t, _, _, status, _ in attempts if t == tenant) == 4
                for path, body, key in admitted:
                    assert call(tenant, path, body).json()["id"] == key
                    assert (
                        call(tenant, path + "/" + key + "/cancel", {}).json()["status"]
                        == "CANCELLED"
                    )
            worker = self.worker_token()
            for path, body in [
                ("semantic/native-artifacts", accepted[0][0]),
                (
                    "ingestion/runs",
                    {"idempotency_key": "denied", "mappings": [{"id": "Factory", "version": 1}]},
                ),
                (
                    "semantic/jobs",
                    {
                        "operation": "validation",
                        "primary_artifact": exports[other][0],
                        "secondary_artifact": shapes[other],
                    },
                ),
            ]:
                assert call(other, path, body, worker).status_code == 403
            assert {t: usage(t) for t in tenants} == used
            self.record(
                "two-deployed-tenants-shared-mixed-job-and-logical-byte-quota-isolation",
                job_limit_per_tenant=4,
                admitted_per_tenant=4,
                rejected_per_tenant=4,
                primary_uploads_admitted=1,
                primary_uploads_rejected=7,
                independent_secondary_uploads_admitted=8,
                quota_bytes=capacity,
                invalid_upload_rollback="PASS",
                artifact_retry_no_charge="PASS",
                unauthorized_ingestion_semantic_artifact_no_charge="PASS",
            )
        finally:
            catalog.write_text(original_catalog)
            self.compose = original
            self.dc("up", "-d", "--no-deps", "--force-recreate", "--wait", "api")

    def sdk_faults(self) -> None:
        import base64
        from concurrent.futures import ThreadPoolExecutor

        import psycopg
        from ontology_platform.sdk.integrity import verify_archive
        from sqlalchemy import text

        token = self.user_token_for_faults
        prefix = "/api/v1/ontologies/manufacturing/sdk"
        headers = {"Authorization": "Bearer " + token, "X-Tenant-ID": str(self.tenant)}
        with self.engine.connect() as sql:
            version = (
                "1.1.0"
                if sql.scalar(
                    text(
                        "SELECT count(*) FROM ontology_versions "
                        "WHERE tenant_id=:tenant AND version='1.1.0' AND status='PUBLISHED'"
                    ),
                    {"tenant": self.tenant},
                )
                else "1.0.0"
            )
        body = {"version": version, "language": "typescript"}
        with self.engine.connect() as sql:
            assert (
                sql.scalar(
                    text(
                        "SELECT count(*) FROM sdk_artifacts WHERE "
                        "tenant_id=:tenant AND schema_version=:version AND language='typescript'"
                    ),
                    {"tenant": self.tenant, "version": version},
                )
                == 0
            )

        def generate():
            return self.request(
                "api.accept.test", prefix + "/generate", "POST", headers=headers, json=body
            )

        with self.engine.connect() as blocker, ThreadPoolExecutor(1) as pool:
            blocker.execute(text("LOCK TABLE sdk_artifacts IN SHARE MODE"))
            pending = pool.submit(generate)
            observed = False
            try:
                for _ in range(50):
                    # Runtime/migrator roles cannot see another role's SQL/wait details.
                    # Observe with this disposable cluster's existing admin connection;
                    # do not broaden runtime privileges merely to implement a fault probe.
                    with psycopg.connect(
                        self.env["FOUNDRY_ADMIN_DATABASE_URL"], dbname="foundry", autocommit=True
                    ) as observer:
                        observed = (
                            observer.execute(
                                "SELECT count(*) FROM pg_stat_activity WHERE datname='foundry' "
                                "AND usename='foundry_runtime' AND wait_event_type='Lock' "
                                "AND query ILIKE '%sdk_artifacts%'"
                            ).fetchone()[0]
                            > 0
                        )
                    if observed:
                        break
                    time.sleep(0.02)
                assert observed, "Generation did not enter the intended SQL fault window"
                self.dc("kill", "-s", "SIGKILL", "api")
            finally:
                blocker.rollback()
            interrupted = pending.result()
            assert interrupted.status_code >= 400
        self.dc("start", "api")
        self.wait("api.accept.test", "/health/ready")
        with self.engine.connect() as sql:
            assert (
                sql.scalar(
                    text(
                        "SELECT count(*) FROM sdk_artifacts WHERE "
                        "tenant_id=:tenant AND schema_version=:version AND language='typescript'"
                    ),
                    {"tenant": self.tenant, "version": version},
                )
                == 0
            )
        result = generate()
        assert result.status_code == 200
        artifact = result.json()
        with ThreadPoolExecutor(4) as pool:
            responses = list(pool.map(lambda _: generate(), range(8)))
        assert all(r.status_code == 200 and r.json()["id"] == artifact["id"] for r in responses)
        download = self.request(
            "api.accept.test",
            prefix + "/artifacts/" + artifact["id"] + "/download",
            headers=headers,
        )
        assert download.status_code == 200
        archive = base64.b64decode(download.json()["archive_base64"])
        verify_archive(archive, artifact["content_hash"])
        try:
            verify_archive(archive + b"tampered", artifact["content_hash"])
        except ValueError:
            pass
        else:
            raise AssertionError("Corrupt archive accepted")
        assert (
            self.request(
                "api.accept.test",
                prefix + "/artifacts/" + artifact["id"] + "/download",
                headers=headers | {"X-Tenant-ID": str(self.secondary_tenant)},
            ).status_code
            == 404
        )
        assert (
            self.request(
                "api.accept.test",
                prefix + "/artifacts/00000000-0000-0000-0000-000000000099/download",
                headers=headers,
            ).status_code
            == 404
        )
        self.record(
            "sdk-interrupted-transaction-no-partial-artifact-retry-concurrent-integrity-isolation",
            interrupted_status=interrupted.status_code,
            concurrent_retries=8,
            unique_artifact_ids=1,
            corrupt_archive_rejected=True,
        )

    def signing_rotation(self) -> None:
        # Supplier-documented kcadm generated-RSA provider procedure; only this test realm.
        old = self.worker_token()
        command = ["exec", "-T", "keycloak", "/opt/keycloak/bin/kcadm.sh"]
        realm = json.loads(
            self.dc(
                *command,
                "get",
                "realms/foundry",
                "--config",
                "/tmp/accept-kcadm.config",
                "--fields",
                "id",
            )
        )
        self.dc(
            *command,
            "create",
            "components",
            "-r",
            "foundry",
            "--config",
            "/tmp/accept-kcadm.config",
            "-s",
            "name=acceptance-rotated-rsa",
            "-s",
            "providerId=rsa-generated",
            "-s",
            "providerType=org.keycloak.keys.KeyProvider",
            "-s",
            "parentId=" + realm["id"],
            "-s",
            'config.priority=["200"]',
            "-s",
            'config.enabled=["true"]',
            "-s",
            'config.active=["true"]',
            "-s",
            'config.keySize=["2048"]',
        )
        new = self.worker_token()
        assert jwt.get_unverified_header(old)["kid"] != jwt.get_unverified_header(new)["kid"]
        self.validate_fresh(old, True)
        self.validate_fresh(new, True)
        statuses = []
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            response = self.request(
                "api.accept.test",
                "/api/v1/security/me",
                headers={"Authorization": "Bearer " + new, "X-Tenant-ID": str(self.tenant)},
            )
            statuses.append(response.status_code)
            if response.status_code == 200:
                break
            assert response.status_code == 401
            time.sleep(2)
        assert statuses[-1] == 200
        assert (
            self.request(
                "api.accept.test",
                "/api/v1/security/me",
                headers={"Authorization": "Bearer " + old, "X-Tenant-ID": str(self.tenant)},
            ).status_code
            == 200
        )
        self.record(
            "real-broker-signing-key-rotation-new-kid-overlap-bounded-refresh",
            new_key_statuses=statuses,
            old_key_overlap="PASS",
        )

    def execute(self) -> None:
        try:
            self.prepare()
            self.provision()
            self.dc("up", "-d", "--wait", "api", "studio")
            self.seed()
            self.dc("restart", "api")
            self.wait("api.accept.test", "/health/ready")
            self.login()
            self.record("operations-scope", scope=getattr(self, "scope", "all"))
            if getattr(self, "scope", "all") != "replicas":
                self.authentication_faults()
            run = self.api(
                "POST",
                "/ontologies/manufacturing/ingestion/runs",
                {
                    "idempotency_key": "diagnostic-seed",
                    "batch_size": 100,
                    "mappings": [
                        {"id": kind, "version": 2}
                        for kind in ("Factory", "Machine", "Employee", "MaintenanceTask")
                    ],
                },
            )
            self.dc("--profile", "workers", "up", "-d", "ingestion-worker")
            for _ in range(90):
                view = self.api("GET", "/ontologies/manufacturing/ingestion/runs/" + run["id"])
                if view["status"] in ("COMPLETED", "FAILED"):
                    break
                time.sleep(1)
            assert view["status"] == "COMPLETED"
            self.dc("stop", "ingestion-worker")
            if getattr(self, "scope", "all") != "replicas":
                self.run(
                    [
                        "uv",
                        "run",
                        "python",
                        "scripts/profile_phase10_queries.py",
                        "--project",
                        self.project,
                        "--output",
                        str(self.output / "query-profile.json"),
                    ]
                )
                self.record("governed-query-sql-pool-diagnostic-and-redacted-explain-analyze")
                alerts(
                    target="api:8000",
                    credential=self.passwords["FOUNDRY_BROWSER_STATE_SECRET"],
                    network=self.project + "_front",
                    output=self.output / "real-api-alerts.json",
                )
                self.record(
                    "actual-authenticated-api-scrape-real-alert-firing-local-delivery-resolution"
                )
            from accept_phase10_closure3 import ClosureAcceptance

            ClosureAcceptance.api_replicas(self)
            self.login()
            Acceptance.faults(self)

        except Exception as error:
            (self.root / "failure.txt").write_text(
                str(error) + "\n" + str(getattr(error, "output", ""))
            )
            self.record("additional-operations", "FAIL", error_type=type(error).__name__)
            raise
        finally:
            if self.compose:
                (self.root / "compose.log").write_text(self.dc("logs", "--no-color"))
                self.dc("--profile", "workers", "down", "--volumes", "--remove-orphans")
            if hasattr(self, "engine"):
                self.engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs/architecture/evidence/phase-10-closure-3/operations",
    )
    parser.add_argument("--scope", choices=("all", "replicas"), default="all")
    args = parser.parse_args()
    runner = OperationsAcceptance(args.output)
    runner.scope = args.scope
    runner.execute()


if __name__ == "__main__":
    main()
