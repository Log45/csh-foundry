"""Disposable Compose surrogate for OKD image/UID compatibility; never deploys Kubernetes.

Uses the existing full acceptance harness with explicit immutable image identities. The output
must be a new directory; all test databases, realms, volumes and cleanup belong to its unique
Compose project. Actual SCC admission, routing and cross-node storage remain separate checks.
"""

import argparse
import json
import subprocess
import time
from pathlib import Path

import yaml
from accept_phase10 import Acceptance


class NonrootAcceptance(Acceptance):
    def prepare(self) -> None:
        super().prepare()
        override = self.root / "arbitrary-uid.yaml"
        override.write_text(
            yaml.safe_dump(
                {
                    "services": {
                        name: {"user": "1001230001:1001230002"}
                        for name in (
                            "api",
                            "studio",
                            "ingestion-worker",
                            "semantic-worker",
                            "outbox-worker",
                            "ingress",
                        )
                    }
                }
            )
        )
        self.compose += ["-f", str(override)]

    def worker_token(self) -> str:
        from accept_phase10_operations import OperationsAcceptance

        return OperationsAcceptance.worker_token(self)

    def execute_replicas(self) -> None:
        from accept_phase10_closure3 import ClosureAcceptance

        try:
            self.prepare()
            self.provision()
            self.dc("up", "-d", "--wait", "api", "studio")
            self.wait("identity.accept.test", "/realms/foundry/.well-known/openid-configuration")
            self.seed()
            self.dc("restart", "api")
            self.wait("api.accept.test", "/health/ready")
            self.login()
            run = self.api(
                "POST",
                "/ontologies/manufacturing/ingestion/runs",
                {
                    "idempotency_key": "two-worker-seed",
                    "batch_size": 10,
                    "mappings": [
                        {"id": kind, "version": 2}
                        for kind in ("Factory", "Machine", "Employee", "MaintenanceTask")
                    ],
                },
            )
            self.dc(
                "--profile",
                "workers",
                "up",
                "-d",
                "--scale",
                "ingestion-worker=2",
                "ingestion-worker",
            )
            workers = self.dc("ps", "-q", "ingestion-worker").split()
            assert len(workers) == 2
            for _ in range(120):
                view = self.api("GET", "/ontologies/manufacturing/ingestion/runs/" + run["id"])
                if view["status"] in ("COMPLETED", "FAILED"):
                    break
                time.sleep(1)
            assert view["status"] == "COMPLETED"
            self.dc("stop", "ingestion-worker")
            self.record(
                "two-arbitrary-uid-ingestion-workers-shared-db-no-duplicate-claim",
                workers=2,
                job_status=view["status"],
            )
            ClosureAcceptance.api_replicas(self)
        except Exception as error:
            (self.root / "failure.txt").write_text(
                str(error) + "\n" + str(getattr(error, "output", ""))
            )
            self.record("replica-validation", "FAIL", error_type=type(error).__name__)
            raise
        finally:
            if self.compose:
                (self.root / "compose.log").write_text(self.dc("logs", "--no-color"))
                self.dc("--profile", "workers", "down", "--volumes", "--remove-orphans")
            if hasattr(self, "engine"):
                self.engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-images", type=Path, required=True)
    parser.add_argument("--scope", choices=("all", "replicas"), default="all")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new output directory; previous evidence must be preserved")
    version = subprocess.check_output(["node", "--version"], text=True).strip()
    if int(version.lstrip("v").split(".")[0]) < 22:
        parser.error("Use Node >=22 on PATH before starting disposable infrastructure")
    images = json.loads(args.candidate_images.read_text())
    runner = NonrootAcceptance(args.output, images)
    if args.scope == "replicas":
        runner.execute_replicas()
    else:
        runner.execute()


if __name__ == "__main__":
    main()
