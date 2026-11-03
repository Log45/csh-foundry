"""Extend the existing disposable profile with controlled load and mixed admission.

No developer service, volume or credential is used. Raw runtime material stays private.
Run scans/builds/regression separately before or after this command.
"""

import argparse
import hashlib
import json
import math
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from accept_phase10 import ROOT, Acceptance
from sqlalchemy import text


class ClosureAcceptance(Acceptance):
    def snapshot_resources(self, name: str) -> None:
        containers = self.dc("--profile", "workers", "ps", "-q").split()
        stats = self.run(["docker", "stats", "--no-stream", "--format", "{{json .}}", *containers])
        with self.engine.connect() as sql:
            settings = dict(
                sql.execute(
                    text(
                        "SELECT name,setting FROM pg_settings WHERE name IN "
                        "('max_connections','superuser_reserved_connections','reserved_connections',"
                        "'shared_buffers','work_mem','max_worker_processes')"
                    )
                ).all()
            )
            db = dict(
                sql.execute(
                    text(
                        "SELECT numbackends,xact_commit,xact_rollback,"
                        "temp_bytes,deadlocks FROM pg_stat_database "
                        "WHERE datname=current_database()"
                    )
                )
                .mappings()
                .one()
            )
            usage = dict(
                sql.execute(
                    text(
                        "SELECT pg_database_size(current_database()) AS db_bytes,"
                        "(SELECT wal_bytes FROM pg_stat_wal) AS wal_bytes,"
                        "(SELECT count(*) FROM pg_stat_activity "
                        "WHERE wait_event_type='Lock') AS lock_waiters"
                    )
                )
                .mappings()
                .one()
            )
        (self.output / (name + ".json")).write_text(
            json.dumps(
                {
                    "containers": [json.loads(line) for line in stats.splitlines()],
                    "postgres_settings": settings,
                    "database": db,
                    "usage": usage,
                },
                indent=2,
                default=str,
            )
            + "\n"
        )

    def load(self, **kwargs):
        if self.candidate_images is not None:
            return super().load(**kwargs)  # Bounded security regression, no latency investigation.
        if getattr(self, "retained_load", None):
            prior = self.retained_load
            fields = ("image", "memory", "nano_cpus", "pids", "read_only")

            def identities(path):
                return sorted(tuple(row[k] for k in fields) for row in json.loads(path.read_text()))

            assert identities(prior / "runtime.json") == identities(self.output / "runtime.json")
            summary = prior / "load-summary.json"
            self.record(
                "retained-controlled-load-runtime-identities-match",
                evidence=str(summary.relative_to(ROOT)),
                sha256=hashlib.sha256(summary.read_bytes()).hexdigest(),
                new_measurement="NOT RUN",
                read_target="FAIL; see retained repeated samples",
            )
            return []
        if kwargs:
            return super().load(**kwargs)
        self.snapshot_resources("resources-before")
        # One complete original workload cycle at every concurrency warms each path.
        super().load(iterations=5, filename="warmup.json")
        runs = []
        for repeat in range(3):
            self.login()  # Fresh broker token; each measured run has the same request mix.
            runs.extend(
                (f"repeat-{repeat + 1}", m)
                for m in super().load(filename=f"isolated-{repeat + 1}.json")
            )
        self.login()
        runs.extend(
            ("sustained", m)
            for m in super().load(concurrencies=(8,), iterations=90, filename="sustained.json")
        )
        self.snapshot_resources("resources-after-isolated")
        self.login()
        # Bounded, explicitly labelled one-CPU competitor, never a development container.
        image = self.values["API_IMAGE"]
        competitor = self.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--network",
                "none",
                "--name",
                self.project + "-contention",
                "--cpus",
                "1",
                "--memory",
                "128m",
                "--pids-limit",
                "16",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                image,
                "python",
                "-c",
                "import time; end=time.monotonic()+90\nwhile time.monotonic()<end: pass",
            ]
        ).strip()
        try:
            runs.extend(
                ("contention-one-cpu", m)
                for m in super().load(concurrencies=(8,), iterations=20, filename="contention.json")
            )
        finally:
            subprocess.run(["docker", "stop", competitor], capture_output=True, check=False)
        summary = []
        for label, measurement in runs:
            operations = {}
            for operation in ("query", "object_set", "traversal", "preview", "sdk"):
                samples = sorted(
                    s["seconds"] * 1000
                    for s in measurement["samples"]
                    if s["operation"] == operation
                )
                operations[operation] = round(samples[math.ceil(0.95 * len(samples)) - 1], 3)
            summary.append(
                {
                    "run": label,
                    "concurrency": measurement["concurrency"],
                    "requests": measurement["requests"],
                    "errors": measurement["errors"],
                    "p95_by_operation_ms": operations,
                    "read_target": "PASS"
                    if max(v for k, v in operations.items() if k != "sdk") < 500
                    else "FAIL",
                    "sdk_write_target": "PASS" if operations["sdk"] < 2000 else "FAIL",
                }
            )
        (self.output / "load-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        self.record(
            "controlled-repeated-sustained-and-contention-load",
            isolated_read_target="PASS"
            if all(r["read_target"] == "PASS" for r in summary if r["run"] != "contention-one-cpu")
            else "FAIL",
            sdk_write_target="PASS"
            if all(r["sdk_write_target"] == "PASS" for r in summary)
            else "FAIL",
            requests=sum(r["requests"] for r in summary),
        )
        return []

    def verify_recovered_application(self, restored: str) -> None:
        """Reconnect only this disposable project's apps to its restored cluster."""
        secret = self.root / "secrets/FOUNDRY_DATABASE_URL"
        original = secret.read_text()
        override = self.root / "recovered-app.yaml"
        override.write_text(
            "services:\n  keycloak:\n    environment:\n"
            "      KC_DB_URL: jdbc:postgresql://recovered-postgres:5432/keycloak\n"
        )
        source_compose = self.compose.copy()
        self.dc(
            "--profile",
            "workers",
            "stop",
            "ingestion-worker",
            "semantic-worker",
            "studio",
            "api",
            "keycloak",
        )
        network = self.project + "_data"
        try:
            secret.chmod(0o600)
            secret.write_text(original.replace("@postgres:", "@recovered-postgres:"))
            secret.chmod(0o440)
            self.compose = source_compose + ["-f", str(override)]
            self.dc("up", "-d", "--no-deps", "--force-recreate", "--wait", "keycloak")
            self.dc("up", "-d", "--no-deps", "--force-recreate", "--wait", "api", "studio")
            self.wait("api.accept.test", "/health/ready")
            self.wait("identity.accept.test", "/realms/foundry/.well-known/openid-configuration")
            self.login()
            prefix = "/ontologies/manufacturing"
            assert self.api("GET", prefix)["active_version"] == "1.0.0"
            assert (
                self.api("GET", prefix + "/objects/Factory/PITR-target")["object_id"]
                == "PITR-target"
            )
            self.api("GET", prefix + "/objects/Factory/PITR-after", expected=404)
            assert self.api("GET", prefix + "/merges")
            artifacts = self.api("GET", prefix + "/sdk/artifacts")
            assert artifacts
            self.api("GET", prefix + "/sdk/artifacts/" + artifacts[0]["id"] + "/download")
            denied = self.request("api.accept.test", "/api/v1" + prefix)
            assert denied.status_code == 401
            self.record(
                "recovered-keycloak-api-studio-startup-login-metadata-objects-history-sdk-auth"
            )
        finally:
            self.dc("stop", "studio", "api", "keycloak")
            secret.chmod(0o600)
            secret.write_text(original)
            secret.chmod(0o440)
            self.compose = source_compose
            self.dc("up", "-d", "--no-deps", "--force-recreate", "--wait", "keycloak")
            self.dc("up", "-d", "--no-deps", "--force-recreate", "--wait", "api", "studio")
            self.run(["docker", "network", "disconnect", network, restored])
            self.login()

    def faults(self) -> None:
        from accept_phase10_operations import OperationsAcceptance
        from test_alert_delivery import main as alerts

        OperationsAcceptance.authentication_faults(self)
        if self.candidate_images is None:
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
        self.record("actual-authenticated-api-scrape-real-alert-firing-local-delivery-resolution")
        self.api_replicas()
        self.login()
        super().faults()

    def api_replicas(self) -> None:
        from ontology_platform.db.models import AuthorizationAudit, IngestionRun, SemanticJob
        from sqlalchemy import func, select

        override = self.root / "api-capacity.yaml"
        override.write_text(
            'services:\n  api:\n    environment:\n      FOUNDRY_TENANT_PENDING_JOB_LIMIT: "4"\n'
        )
        original = self.compose.copy()
        self.compose += ["-f", str(override)]
        try:
            self.dc(
                "up", "-d", "--no-deps", "--force-recreate", "--scale", "api=2", "--wait", "api"
            )
            replicas = self.dc("ps", "-q", "api").split()
            assert len(replicas) == 2
            token = self.worker_token()

            def call(index, method, path, body=None):
                code = """import os,json,httpx
r=httpx.request(os.environ['METHOD'],'http://127.0.0.1:8000'+os.environ['ROUTE'],
 headers={'host':'api','authorization':'Bearer '+os.environ['TOKEN'],
 'x-tenant-id':os.environ['TENANT']},json=json.loads(os.environ['BODY']),timeout=20)
print(json.dumps({'status':r.status_code,'body':r.json()}))
"""
                return json.loads(
                    self.run(
                        [
                            "docker",
                            "exec",
                            "-e",
                            "TOKEN=" + token,
                            "-e",
                            "TENANT=" + str(self.tenant),
                            "-e",
                            "METHOD=" + method,
                            "-e",
                            "ROUTE=" + path,
                            "-e",
                            "BODY=" + json.dumps(body),
                            replicas[index % 2],
                            "python",
                            "-c",
                            code,
                        ]
                    )
                )

            prefix = "/api/v1/ontologies/manufacturing"

            def create(index):
                key = "REPLICA-" + str(index)
                return call(
                    index,
                    "POST",
                    prefix + "/objects/Factory",
                    {
                        "object_id": key,
                        "properties": {
                            "factoryId": key,
                            "factoryName": key,
                            "location": "Acceptance",
                        },
                    },
                )["status"]

            with ThreadPoolExecutor(8) as pool:
                assert list(pool.map(create, range(8))) == [201] * 8

            machine = call(0, "GET", prefix + "/objects/Machine/MCH-005")["body"]

            def action(index):
                body = {
                    "parameters": {
                        "machineId": "MCH-005",
                        "newStatus": "STOPPED",
                        "expectedRevision": machine["version"],
                    },
                    "idempotency_key": "replica-action-" + str(index),
                }
                return (
                    index,
                    body,
                    call(index, "POST", prefix + "/actions/UpdateMachineStatus/execute", body),
                )

            with ThreadPoolExecutor(8) as pool:
                actions = list(pool.map(action, range(8)))
            committed = [(i, b, r) for i, b, r in actions if r["status"] == 200]
            assert len(committed) == 1 and sum(r["status"] == 409 for _, _, r in actions) == 7
            i, b, r = committed[0]
            assert (
                call(i, "POST", prefix + "/actions/UpdateMachineStatus/execute", b)["body"]
                == r["body"]
            )
            assert (
                call(0, "GET", prefix + "/objects/Machine/MCH-005")["body"]["version"]
                == machine["version"] + 1
            )
            self.record(
                "two-api-concurrent-governed-actions-revision-conflicts-idempotent-replay",
                committed=1,
                conflicts_409=7,
                final_revision=machine["version"] + 1,
            )
            source = call(0, "POST", prefix + "/branches", {"name": "replica-merge-source"})["body"]
            target = call(1, "POST", prefix + "/branches", {"name": "replica-merge-target"})["body"]
            head = call(0, "GET", prefix + "/branches/" + source["id"] + "/head")["body"]
            head["definition"]["name"] = "Replica governed merge"
            assert (
                call(
                    0,
                    "POST",
                    prefix + "/branches/" + source["id"] + "/edit",
                    {
                        "expected_revision": 1,
                        "definition": head["definition"],
                        "summary": "Concurrent merge fixture",
                    },
                )["status"]
                == 200
            )
            merge = {"source_branch": source["id"], "source_revision": 2, "target_revision": 1}
            preview = call(
                0, "POST", prefix + "/branches/" + target["id"] + "/merge-preview", merge
            )["body"]
            assert not preview["conflicts"]
            merge["preview_hash"] = preview["preview_hash"]
            with ThreadPoolExecutor(4) as pool:
                merges = list(
                    pool.map(
                        lambda i: call(
                            i, "POST", prefix + "/branches/" + target["id"] + "/merge", merge
                        ),
                        range(4),
                    )
                )
            assert sum(r["status"] == 200 for r in merges) == 1
            assert sum(r["status"] == 412 for r in merges) == 3
            final_head = call(0, "GET", prefix + "/branches/" + target["id"] + "/head")["body"]
            assert (
                final_head["revision"] == 2
                and final_head["definition"]["name"] == "Replica governed merge"
            )
            self.record(
                "two-api-concurrent-branch-merges-stale-preview-and-provenance",
                committed=1,
                stale_preconditions_412=3,
                final_revision=2,
            )

            def submit(index):
                body = {
                    "idempotency_key": "replica-" + str(index),
                    "mappings": [{"id": "Factory", "version": 2}],
                }
                return index, body, call(index, "POST", prefix + "/ingestion/runs", body)

            with ThreadPoolExecutor(8) as pool:
                attempts = list(pool.map(submit, range(8)))
            accepted = [(i, b, r["body"]["id"]) for i, b, r in attempts if r["status"] == 200]
            assert len(accepted) == 4
            assert sum(r["status"] == 409 for _, _, r in attempts) == 4
            with self.sessions() as sql:
                before = sql.scalar(select(func.count()).select_from(AuthorizationAudit))
            failed = call(
                1,
                "POST",
                prefix + "/actions/UpdateMachineStatus/execute",
                {
                    "parameters": {
                        "machineId": "MCH-005",
                        "newStatus": "RUNNING",
                        "expectedRevision": 999999,
                    },
                    "idempotency_key": "replica-stale",
                },
            )
            assert failed["status"] == 409
            with self.sessions() as sql:
                assert sql.scalar(select(func.count()).select_from(AuthorizationAudit)) > before
            for i, body, key in accepted:
                assert call(i, "POST", prefix + "/ingestion/runs", body)["body"]["id"] == key
                assert (
                    call(i, "POST", prefix + "/ingestion/runs/" + key + "/cancel", {})["status"]
                    == 200
                )
            with self.sessions() as sql:
                active = sum(
                    sql.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(model.status.in_(("PENDING", "RUNNING")))
                    )
                    for model in (IngestionRun, SemanticJob)
                )
            assert active == 0
            assert all(call(i, "GET", "/health/ready")["status"] == 200 for i in (0, 1))
            self.record(
                "two-real-api-replicas-concurrent-writes-audit-rollback-shared-admission-recovery",
                writes=8,
                submitted=8,
                admitted=4,
                rejected_409=4,
                final_active=0,
                maximum_api_connections=24,
                broker_pool_max=10,
            )
        finally:
            self.compose = original
            self.dc(
                "up", "-d", "--no-deps", "--force-recreate", "--scale", "api=1", "--wait", "api"
            )

    def worker_token(self) -> str:
        from accept_phase10_operations import OperationsAcceptance

        return OperationsAcceptance.worker_token(self)

    def validate_fresh(self, token: str, expected: bool) -> None:
        from accept_phase10_operations import OperationsAcceptance

        OperationsAcceptance.validate_fresh(self, token, expected)

    def admission(self) -> None:
        super().admission()
        self.login()
        self.dc("--profile", "workers", "stop", "ingestion-worker", "semantic-worker")
        prefix = "/ontologies/manufacturing"
        # Distinct governed exports produce distinct semantic fingerprints.
        shapes = self.api("POST", prefix + "/semantic/compile", {"schema_version": "1.0.0"})[1]
        reports = []
        for concurrency in (2, 8, 12):
            exports = [
                self.api(
                    "POST",
                    prefix + "/semantic/exports",
                    {
                        "schema_version": "1.0.0",
                        "selections": [{"object_type": kind, "limit": concurrency}],
                    },
                )
                for kind in ("Factory", "Machine", "Employee", "MaintenanceTask")
            ]

            time.sleep(4)  # Refill the unchanged 10r/s ingress budget between batches.

            def submit(index, exports=exports):
                semantic = index < 4
                path = prefix + ("/semantic/jobs" if semantic else "/ingestion/runs")
                body = (
                    {
                        "operation": "validation",
                        "primary_artifact": exports[index],
                        "secondary_artifact": shapes,
                    }
                    if semantic
                    else {
                        "idempotency_key": str(uuid4()),
                        "mappings": [{"id": "Factory", "version": 2}],
                    }
                )
                response = self.request(
                    "studio.accept.test",
                    "/bff",
                    "POST",
                    cookies=self.cookie,
                    headers={"Origin": self.origin, "x-csrf-token": self.csrf},
                    json={
                        "method": "POST",
                        "path": "/api/v1" + path,
                        "expected_tenant": str(self.tenant),
                        "body": body,
                    },
                )
                assert response.status_code in (200, 409), response.status_code
                payload = response.json()
                if response.status_code == 409:
                    assert payload["error"]["code"] == "constraint_conflict"
                return response.status_code, payload.get("id"), semantic

            with ThreadPoolExecutor(concurrency) as pool:
                attempts = list(pool.map(submit, range(28)))
            accepted = [(key, semantic) for status, key, semantic in attempts if status == 200]
            assert len(accepted) == 20, attempts
            assert any(s for _, s in accepted) and any(not s for _, s in accepted)
            with self.engine.connect() as sql:
                active = sql.scalar(
                    text(
                        "SELECT (SELECT count(*) FROM ingestion_runs WHERE "
                        "status IN ('PENDING','RUNNING')) + (SELECT count(*) FROM semantic_jobs "
                        "WHERE status IN ('PENDING','RUNNING'))"
                    )
                )
            assert active == 20
            for key, semantic in accepted:
                path = prefix + ("/semantic/jobs/" if semantic else "/ingestion/runs/") + key
                assert self.api("POST", path + "/cancel", {})["status"] == "CANCELLED"
                time.sleep(0.11)
                assert self.api("POST", path + "/cancel", {})["status"] == "CANCELLED"
                time.sleep(0.11)
            with self.engine.connect() as sql:
                final = sql.scalar(
                    text(
                        "SELECT (SELECT count(*) FROM ingestion_runs WHERE "
                        "status IN ('PENDING','RUNNING')) + (SELECT count(*) FROM semantic_jobs "
                        "WHERE status IN ('PENDING','RUNNING'))"
                    )
                )
            assert final == 0
            reports.append(
                {
                    "concurrency": concurrency,
                    "accepted": 20,
                    "rejected_409": 8,
                    "semantic_accepted": sum(s for _, s in accepted),
                    "final_active": final,
                    "repeated_cancel": "PASS",
                }
            )
        (self.output / "mixed-admission.json").write_text(json.dumps(reports, indent=2) + "\n")
        self.record("mixed-ingestion-semantic-deployed-shared-quota", samples=reports)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs/architecture/evidence/phase-10-closure-3"
    )
    parser.add_argument("--retained-load", type=Path)
    parser.add_argument("--candidate-images", type=Path)
    args = parser.parse_args()
    images = json.loads(args.candidate_images.read_text()) if args.candidate_images else None
    acceptance = ClosureAcceptance(args.output, images)
    acceptance.retained_load = args.retained_load.resolve() if args.retained_load else None
    acceptance.execute()


if __name__ == "__main__":
    main()
