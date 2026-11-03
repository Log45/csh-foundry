"""Targeted Closure 4: final broker cap, correlated load and bounded governed writes."""

import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from accept_phase10 import ROOT, Acceptance
from accept_phase10_closure3 import ClosureAcceptance
from phase10_diagnostics import Sampler, correlate
from sqlalchemy import text


class Closure4Acceptance(ClosureAcceptance):
    def prepare(self):
        super().prepare()
        self.request_local = threading.local()
        self.diagnostic_requests = True
        self.values["API_IMAGE"] = "csh-foundry-api:phase10-closure4"
        self.values["STUDIO_IMAGE"] = "csh-foundry-studio:phase10-closure4"
        self.env.update(self.values)
        diagnostic = self.root / "diagnostic.yaml"
        template = (ROOT / "infrastructure/production/nginx.conf.template").read_text()
        template = template.replace(
            '"duration":$request_time}',
            '"duration":$request_time,"trace_id":"$http_traceparent",'
            '"epoch":$msec,"upstream_connect":"$upstream_connect_time",'
            '"upstream_header":"$upstream_header_time","upstream_response":"$upstream_response_time"}',
        )
        # The harness sends a full traceparent. Normalize only during the redacted join.
        ingress = self.root / "diagnostic-nginx.template"
        ingress.write_text(template)
        diagnostic.write_text(
            'services:\n  api:\n    environment:\n      FOUNDRY_DIAGNOSTIC_TIMING: "true"\n'
            '  studio:\n    environment:\n      STUDIO_DIAGNOSTIC_TIMING: "true"\n'
            "  ingress:\n    volumes:\n      - "
            + str(ingress)
            + ":/etc/nginx/templates/default.conf.template:ro\n"
        )
        self.compose += ["-f", str(diagnostic)]
        self.dc("config", "--quiet")

    def workflow(self):
        """Prepare comparable 63-object dataset without replaying accepted crash/recovery drills."""
        prefix = "/ontologies/manufacturing"
        started = time.monotonic()
        job = self.api(
            "POST",
            prefix + "/ingestion/runs",
            {
                "idempotency_key": "closure4-seed",
                "batch_size": 25,
                "mappings": [
                    {"id": kind, "version": 2}
                    for kind in ("Factory", "Machine", "Employee", "MaintenanceTask")
                ],
            },
        )
        admission = time.monotonic() - started
        self.dc("--profile", "workers", "up", "-d", "ingestion-worker", "semantic-worker")
        for _ in range(180):
            job = self.api("GET", prefix + "/ingestion/runs/" + job["id"])
            if job["status"] in ("COMPLETED", "FAILED"):
                break
            time.sleep(1)
        assert job["status"] == "COMPLETED" and job["created"] == 63 and job["links_created"] == 70
        self.api(
            "POST",
            prefix + "/actions/UpdateMachineStatus/execute",
            {
                "parameters": {
                    "machineId": "MCH-005",
                    "newStatus": "STOPPED",
                    "expectedRevision": 1,
                },
                "idempotency_key": "closure4-baseline-action",
            },
        )
        self.record(
            "comparable-manufacturing-fixture-through-governed-ingestion",
            objects=63,
            links=70,
            admission_seconds=admission,
            completion_seconds=time.monotonic() - started,
        )

    def runtime_configuration(self):
        containers = self.dc("ps", "-q").split()
        raw = json.loads(self.run(["docker", "inspect", *containers]))
        records = []
        for item in raw:
            env = dict(e.split("=", 1) for e in item["Config"]["Env"] if "=" in e)
            records.append(
                {
                    "name": item["Name"],
                    "image": item["Image"],
                    "command": item["Config"]["Cmd"],
                    "settings": {
                        k: v
                        for k, v in env.items()
                        if k
                        in {
                            "KC_DB_POOL_INITIAL_SIZE",
                            "KC_DB_POOL_MIN_SIZE",
                            "KC_DB_POOL_MAX_SIZE",
                            "FOUNDRY_DIAGNOSTIC_TIMING",
                            "STUDIO_DIAGNOSTIC_TIMING",
                        }
                    },
                    "memory": item["HostConfig"]["Memory"],
                    "nano_cpus": item["HostConfig"]["NanoCpus"],
                    "networks": sorted(item["NetworkSettings"]["Networks"]),
                }
            )
        (self.output / "final-runtime.json").write_text(json.dumps(records, indent=2) + "\n")
        with self.engine.connect() as sql:
            assert sql.scalar(text("SHOW max_connections")) == "100"
        broker = next(r for r in records if "keycloak" in r["name"])
        assert broker["settings"]["KC_DB_POOL_MAX_SIZE"] == "10"
        self.record("final-runtime-broker-pool-cap-and-postgres-budget")

    def writes(self):
        prefix = "/ontologies/manufacturing"
        samples = []

        journal = []

        def timed(operation, method, path, body, expected=200):
            stamp = time.monotonic()
            status = "FAIL"
            try:
                response = self.api(method, prefix + path, body, expected=expected)
                status = "PASS"
                return response
            finally:
                sample = {
                    "operation": operation,
                    "seconds": time.monotonic() - stamp,
                    "result": status,
                    "concurrency": concurrency,
                    **getattr(self.request_local, "timing", {}),
                }
                samples.append(sample)
                journal.append(sample)
                (self.output / "write-request-journal.json").write_text(
                    json.dumps(journal, indent=2) + "\n"
                )

        for concurrency in (1, 4, 8):
            self.login()
            samples.clear()
            started = time.monotonic()

            def write(index, concurrency=concurrency):
                key = f"C4-{concurrency}-{index}"
                timed(
                    "object_create",
                    "POST",
                    "/objects/Factory",
                    {
                        "object_id": key,
                        "properties": {
                            "factoryId": key,
                            "factoryName": key,
                            "location": "Acceptance",
                        },
                    },
                )
                time.sleep(0.25)
                obj = self.api("GET", "/ontologies/manufacturing/objects/Factory/" + key)
                timed(
                    "object_update",
                    "PATCH",
                    "/objects/Factory/" + key,
                    {"expected_version": obj["version"], "properties": {"location": "Updated"}},
                )

            with ThreadPoolExecutor(concurrency) as pool:
                list(pool.map(write, range(8)))
            # No race in the setup reads; actual action contention is a distinct retained drill.
            for _index in range(4):
                obj = self.api("GET", prefix + "/objects/Machine/MCH-005")
                body = {
                    "parameters": {
                        "machineId": "MCH-005",
                        "newStatus": "STOPPED",
                        "expectedRevision": obj["version"],
                    },
                    "idempotency_key": str(uuid4()),
                }
                timed(
                    "action_preview",
                    "POST",
                    "/actions/UpdateMachineStatus/preview",
                    {"parameters": body["parameters"]},
                )
                first = timed(
                    "action_execute", "POST", "/actions/UpdateMachineStatus/execute", body
                )
                assert (
                    timed("action_replay", "POST", "/actions/UpdateMachineStatus/execute", body)
                    == first
                )
                time.sleep(0.3)
            for _index in range(4):
                timed(
                    "artifact_sdk",
                    "POST",
                    "/sdk/generate",
                    {"version": "1.0.0", "language": "python"},
                )
                time.sleep(0.15)
            source = timed(
                "branch_create", "POST", "/branches", {"name": f"c4-source-{concurrency}"}
            )
            target = timed(
                "branch_create", "POST", "/branches", {"name": f"c4-target-{concurrency}"}
            )
            head = self.api("GET", prefix + "/branches/" + source["id"] + "/head")
            head["definition"]["name"] = f"Closure 4 revision {concurrency}"
            timed(
                "branch_revision",
                "POST",
                "/branches/" + source["id"] + "/edit",
                {
                    "expected_revision": 1,
                    "definition": head["definition"],
                    "summary": "Closure 4",
                },
            )
            merge = {"source_branch": source["id"], "source_revision": 2, "target_revision": 1}
            preview = timed(
                "merge_preview", "POST", "/branches/" + target["id"] + "/merge-preview", merge
            )
            assert not preview["conflicts"]
            timed(
                "merge_execute",
                "POST",
                "/branches/" + target["id"] + "/merge",
                {
                    **merge,
                    "preview_hash": preview["preview_hash"],
                },
            )
            self.login()
            shapes = timed(
                "semantic_artifact", "POST", "/semantic/compile", {"schema_version": "1.0.0"}
            )[1]
            export = timed(
                "semantic_export",
                "POST",
                "/semantic/exports",
                {
                    "schema_version": "1.0.0",
                    "selections": [{"object_type": "Factory", "limit": concurrency}],
                },
            )
            pending = []
            for kind, route, body in (
                (
                    "ingestion",
                    "/ingestion/runs",
                    {
                        "idempotency_key": str(uuid4()),
                        "mappings": [{"id": "Factory", "version": 2}],
                    },
                ),
                (
                    "semantic",
                    "/semantic/jobs",
                    {
                        "operation": "validation",
                        "primary_artifact": export,
                        "secondary_artifact": shapes,
                    },
                ),
            ):
                submitted = time.monotonic()
                job = timed(kind + "_admission", "POST", route, body)
                pending.append((kind, route, job["id"], submitted))
            for kind, route, key, submitted in pending:
                for _ in range(90):
                    job = self.api("GET", prefix + route + "/" + key)
                    if job["status"] in ("COMPLETED", "FAILED"):
                        break
                    time.sleep(0.5)
                assert job["status"] == "COMPLETED"
                with self.engine.connect() as sql:
                    if kind == "ingestion":
                        created, claimed, completed = sql.execute(
                            text(
                                "SELECT created_at,started_at,completed_at "
                                "FROM ingestion_runs WHERE id=:id"
                            ),
                            {"id": key},
                        ).one()
                    else:
                        created, completed, history = sql.execute(
                            text(
                                "SELECT created_at,completed_at,history "
                                "FROM semantic_jobs WHERE id=:id"
                            ),
                            {"id": key},
                        ).one()
                        claimed = datetime.fromisoformat(
                            next(event["at"] for event in history if event["event"] == "CLAIMED")
                        )
                    assert claimed is not None and completed is not None
                self.record(
                    kind + "-asynchronous-completion",
                    concurrency=concurrency,
                    completion_seconds=time.monotonic() - submitted,
                    job_status=job["status"],
                    server_queue_seconds=(claimed - created).total_seconds(),
                    server_worker_seconds=(completed - claimed).total_seconds(),
                    server_total_seconds=(completed - created).total_seconds(),
                )
            elapsed = time.monotonic() - started
            (self.output / f"writes-{concurrency}.json").write_text(
                json.dumps(
                    {
                        "measurements": [
                            {
                                "concurrency": concurrency,
                                "seconds": elapsed,
                                "requests": len(samples),
                                "errors": 0,
                                "samples": samples.copy(),
                            }
                        ],
                        "scope": "Bounded TLS/BFF writes; async completion measured separately",
                    },
                    indent=2,
                )
                + "\n"
            )
        self.record("bounded-governed-object-action-artifact-write-load")
        # Reuse the existing exact two-replica concurrency/assertion protocol, no full fault rerun.
        self.dc("--profile", "workers", "stop", "ingestion-worker", "semantic-worker")
        self.api_replicas()

    def execute(self):
        try:
            self.prepare()
            self.provision()
            self.dc("up", "-d", "--wait", "api", "studio")
            self.seed()
            self.dc("restart", "api")
            self.wait("api.accept.test", "/health/ready")
            self.login()
            self.workflow()
            self.runtime_configuration()
            if getattr(self, "scope", "all") == "all":
                # Paired observation of optional timing overhead, on the same images and fixture.
                original = self.compose.copy()
                disabled = self.root / "disabled-diagnostic.yaml"
                disabled.write_text(
                    "services:\n  api:\n    environment:\n"
                    '      FOUNDRY_DIAGNOSTIC_TIMING: "false"\n'
                    "  studio:\n    environment:\n"
                    '      STUDIO_DIAGNOSTIC_TIMING: "false"\n'
                )
                self.compose += ["-f", str(disabled)]
                self.dc("up", "-d", "--no-deps", "--force-recreate", "--wait", "api", "studio")
                self.login()
                Acceptance.load(
                    self,
                    concurrencies=(8,),
                    iterations=10,
                    filename="overhead-diagnostics-disabled.json",
                )
                self.compose = original
                self.dc("up", "-d", "--no-deps", "--force-recreate", "--wait", "api", "studio")
                self.login()
                # Paired sampler-only overhead probe; same instrumentation and request mix.
                Acceptance.load(
                    self,
                    concurrencies=(8,),
                    iterations=10,
                    filename="overhead-without-sampler.json",
                )
            with Sampler(self):
                if getattr(self, "scope", "all") == "all":
                    self.login()
                    Acceptance.load(
                        self,
                        concurrencies=(8,),
                        iterations=10,
                        filename="overhead-with-sampler.json",
                    )
                if getattr(self, "scope", "all") in ("all", "reads"):
                    self.load()
                if getattr(self, "scope", "all") in ("all", "writes"):
                    self.login()
                    self.writes()
            from phase10_outbox_probe import exercise

            if getattr(self, "scope", "all") == "all":
                exercise(self)
        except Exception as error:
            (self.root / "failure.txt").write_text(
                str(error) + "\n" + str(getattr(error, "output", ""))
            )
            self.record("closure4-execution", "FAIL", error_type=type(error).__name__)
            raise
        finally:
            if self.compose:
                correlate(self)
                (self.root / "compose.log").write_text(self.dc("logs", "--no-color"))
                self.dc("--profile", "workers", "down", "--volumes", "--remove-orphans")
            if hasattr(self, "engine"):
                self.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scope", choices=("all", "reads", "writes"), default="all")
    args = parser.parse_args()
    acceptance = Closure4Acceptance(args.output)
    acceptance.scope = args.scope
    try:
        acceptance.execute()
    except Exception:
        raise SystemExit("FAIL: see deployment.json and its private diagnostics") from None


if __name__ == "__main__":
    main()
