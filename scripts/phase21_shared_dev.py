"""Targeted authorized development rollout. Never invokes Keycloak or PostgreSQL lifecycle commands.

Private connection configuration is captured into artifacts/phase21/rollout-config.json (0600).
Use prepare once, then build, storage, deploy, verify. Migrate separately with an explicit revision
only after backup/restore and disposable migration checks. No destructive recovery is automated.
"""

import argparse
import json
import os
import secrets
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "artifacts/phase21/rollout-config.json"
parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=["prepare", "build", "storage", "deploy", "verify"])
args = parser.parse_args()


def inspect(*names: str) -> list[dict]:
    return json.loads(subprocess.check_output(["docker", "inspect", *names]))


def protected() -> list[dict]:
    return [
        {
            "Id": c["Id"],
            "Name": c["Name"],
            "Mounts": sorted(c["Mounts"], key=lambda m: m["Destination"]),
            "StartedAt": c["State"]["StartedAt"],
            "Networks": sorted(c["NetworkSettings"]["Networks"]),
        }
        for c in inspect("foundry-keycloak", "foundry-keycloak-tls")
    ]


baseline = json.loads((ROOT / "artifacts/phase21/keycloak-before.json").read_text())
for item in baseline:
    item["Mounts"] = sorted(item["Mounts"], key=lambda m: m["Destination"])
    item["Networks"] = sorted(item["Networks"])
assert protected() == baseline, "Protected container state changed; stop rollout"
if args.mode == "prepare":
    if PRIVATE.exists():
        raise SystemExit("Private rollout configuration already exists; reuse it")
    containers = inspect("csh-foundry-api-1", "csh-foundry-postgres-1", "csh-foundry-studio-1")
    values = {}
    for c in containers:
        values.update(
            dict(
                v.split("=", 1)
                for v in c["Config"]["Env"]
                if "=" in v
                and v.startswith(("FOUNDRY_", "POSTGRES_", "STUDIO_", "NODE_EXTRA_CA_CERTS="))
            )
        )
    api = containers[0]
    values["FOUNDRY_OIDC_CA_DIRECTORY"] = next(
        m["Source"] for m in api["Mounts"] if m["Destination"] == "/etc/foundry/certs"
    )
    values["FOUNDRY_DOCKER_OIDC_CA_BUNDLE"] = values.get("FOUNDRY_OIDC_CA_BUNDLE", "")
    values["STUDIO_NODE_EXTRA_CA_CERTS"] = values.get("NODE_EXTRA_CA_CERTS", "")
    values.update(
        {
            "FOUNDRY_ARTIFACT_BACKEND": "s3",
            "FOUNDRY_ARTIFACT_ENDPOINT": "http://minio:9000",
            "FOUNDRY_ARTIFACT_DEVELOPMENT_HTTP": "true",
            "MINIO_ROOT_USER": "bootstrap-" + secrets.token_hex(8),
            "MINIO_ROOT_PASSWORD": secrets.token_urlsafe(40),
            "MINIO_APP_USER": "foundry-" + secrets.token_hex(8),
            "MINIO_APP_PASSWORD": secrets.token_urlsafe(40),
        }
    )
    values["FOUNDRY_ARTIFACT_ACCESS_KEY"] = values["MINIO_APP_USER"]
    values["FOUNDRY_ARTIFACT_SECRET_KEY"] = values["MINIO_APP_PASSWORD"]
    fd = os.open(PRIVATE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as file:
        json.dump(values, file)
    print("PASS private rollout configuration captured; protected containers unchanged")
else:
    env = os.environ | json.loads(PRIVATE.read_text())
    compose = [
        "docker",
        "compose",
        "--env-file",
        "/dev/null",
        "-p",
        "csh-foundry",
        "-f",
        str(ROOT / "infrastructure/compose.yaml"),
        "--profile",
        "studio",
        "--profile",
        "worker",
        "--profile",
        "minio",
    ]

    def run(*cmd: str) -> None:
        subprocess.run([*compose, *cmd], cwd=ROOT, env=env, check=True)

    if args.mode == "build":
        run("build", "api", "studio")
    elif args.mode == "storage":
        run("up", "-d", "--no-deps", "--pull", "never", "--wait", "minio")
        run("run", "--rm", "--no-deps", "minio-init")
        run("run", "--rm", "--no-deps", "minio-init")
    elif args.mode == "deploy":
        revision = subprocess.check_output(
            [
                "docker",
                "exec",
                "csh-foundry-postgres-1",
                "psql",
                "-U",
                env["POSTGRES_USER"],
                "-d",
                env["POSTGRES_DB"],
                "-Atc",
                "select version_num from public.alembic_version",
            ],
            text=True,
        ).strip()
        if revision != "0027_lineage_observability":
            raise SystemExit("Refusing Phase 21 runtime against incompatible shared schema")
        run("up", "-d", "--no-deps", "--no-build", "api", "worker", "studio")
    else:
        print(
            subprocess.check_output(
                ["docker", "ps", "--format", "{{.Names}} {{.Status}}"], text=True
            )
        )
    after = protected()
    assert after == baseline, "Protected containers changed"
    (ROOT / "artifacts/phase21/keycloak-after.json").write_text(json.dumps(after, indent=2))
    print("PASS protected container IDs, start times, mounts and networks unchanged")
