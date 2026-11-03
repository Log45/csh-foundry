"""Explicit approved-target maintenance rollout; migration failure leaves workloads stopped.

Only --apply mutates a cluster. Supply reviewed rendered YAML, never a live overlay directory.
"""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

import yaml
from validate_kubernetes import validate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--migration", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    # YAML is parsed by the standard CLI, with no cluster access during preflight.
    base = ["kubectl", "--context", args.context, "--namespace", args.namespace]
    for path in (args.configuration, args.migration):
        raw = path.read_text()
        if "example.test" in raw or "example.invalid" in raw or "0" * 64 in raw:
            parser.error("Replace all example deployment configuration before rollout")
    validate(list(yaml.safe_load_all(args.configuration.read_text())), production=True)
    validate(list(yaml.safe_load_all(args.migration.read_text())), production=True)
    if not args.apply:
        print(
            "Validated placeholder preflight only; no cluster changes. Review release gates first."
        )
        return

    # Operator must have approved this target and candidate before invoking --apply.
    def run(*command: str) -> None:
        subprocess.run([*base, *command], check=True)

    # Deliberately no automatic restart after migration failure; forward repair/restore is reviewed.
    resources = list(yaml.safe_load_all(args.configuration.read_text()))
    prerequisites = [r for r in resources if r["kind"] not in {"Deployment", "Route", "Service"}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as file:
        json.dump({"apiVersion": "v1", "kind": "List", "items": prerequisites}, file)
        file.flush()
        run("apply", "-f", file.name)
    previous = subprocess.check_output(
        [*base, "get", "job", "foundry-migrate", "--ignore-not-found", "-o", "json"], text=True
    ).strip()
    if previous and json.loads(previous).get("status", {}).get("active", 0):
        raise RuntimeError("Migration Job is still active; refusing to replace it")
    run("delete", "job", "foundry-migrate", "--ignore-not-found", "--wait=true")
    existing = json.loads(
        subprocess.check_output(
            [*base, "get", "deployment", "-l", "app.kubernetes.io/part-of=foundry", "-o", "json"]
        )
    )["items"]
    if existing:
        run("scale", "deployment", "-l", "app.kubernetes.io/part-of=foundry", "--replicas=0")
        run(
            "wait",
            "--for=delete",
            "pod",
            "-l",
            "app.kubernetes.io/part-of=foundry",
            "--timeout=180s",
        )
    run("apply", "-f", str(args.migration))
    run("wait", "--for=condition=complete", "job/foundry-migrate", "--timeout=600s")
    # Reviewed grants must already cover new tables through DBA-managed default privileges.
    run("apply", "-f", str(args.configuration))
    for name in ("api", "studio", "ingestion-worker", "semantic-worker"):
        run("rollout", "status", "deployment/" + name, "--timeout=300s")


if __name__ == "__main__":
    main()
