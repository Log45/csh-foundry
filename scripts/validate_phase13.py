"""Disposable PostgreSQL schemas and real MinIO; never migrate shared developer data.

Only the generated Compose project and its private volume are removed. Reuse cached digest
images when upstream registries are unavailable. --browser also runs Studio browser workflows.
"""

import argparse
import json
import os
import secrets
import signal
import socket
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from ontology_platform.config import get_settings

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--browser", action="store_true")
parser.add_argument("--full", action="store_true")
args = parser.parse_args()
project = "phase13-" + uuid4().hex[:12]
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
env = os.environ | {
    "POSTGRES_PASSWORD": secrets.token_urlsafe(
        24
    ),  # Compose interpolation only; no postgres service.
    "MINIO_ROOT_USER": "bootstrap-" + secrets.token_hex(8),
    "MINIO_ROOT_PASSWORD": "-" + secrets.token_urlsafe(32),
    "MINIO_APP_USER": "artifact-" + secrets.token_hex(8),
    "MINIO_APP_PASSWORD": "-" + secrets.token_urlsafe(32),
    "FOUNDRY_ARTIFACT_BACKEND": "s3",
    "FOUNDRY_ARTIFACT_ENDPOINT": f"http://127.0.0.1:{port}",
    "FOUNDRY_ARTIFACT_DEVELOPMENT_HTTP": "true",
}
env["FOUNDRY_ARTIFACT_ACCESS_KEY"] = env["MINIO_APP_USER"]
env["FOUNDRY_ARTIFACT_SECRET_KEY"] = env["MINIO_APP_PASSWORD"]
env["TEST_DATABASE_URL"] = (
    os.environ.get("TEST_DATABASE_URL") or get_settings().database_url.get_secret_value()
)
env["OPEN_ONTOLOGIES_BIN"] = str(root / ".external/open-ontologies")
if args.browser:
    for name, value in {
        "STUDIO_E2E_PORT": "3100",
        "STUDIO_E2E_API_PORT": "8101",
        "STUDIO_E2E_REPLICA_PORT": "3101",
        "STUDIO_E2E_DURABLE": "true",
        "STUDIO_E2E_DIRECTORY": str(root / "artifacts/phase13-browser"),
    }.items():
        env.setdefault(name, value)
with tempfile.TemporaryDirectory(prefix="foundry-phase13-") as directory:
    override = Path(directory) / "compose.json"
    override.write_text(json.dumps({"services": {"minio": {"ports": [f"127.0.0.1:{port}:9000"]}}}))
    compose = [
        "docker",
        "compose",
        "--env-file",
        "/dev/null",
        "-p",
        project,
        "-f",
        str(root / "infrastructure/compose.yaml"),
        "-f",
        str(override),
        "--profile",
        "minio",
    ]

    def run(*cmd: str) -> None:
        process = subprocess.Popen(list(cmd), cwd=root, env=env)
        try:
            code = process.wait()
        except BaseException:
            # Let pytest/service runners clean their own schemas/processes before MinIO teardown.
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
        if code:
            raise subprocess.CalledProcessError(code, cmd)

    try:
        disabled = subprocess.run(
            compose[:-2] + ["config", "--services"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        assert disabled.stdout.splitlines() == ["postgres"]
        print("PASS disabled Compose profile requires no MinIO services", flush=True)
        run(*compose, "up", "-d", "--pull", "never", "--wait", "minio")
        run(*compose, "run", "--rm", "--no-deps", "minio-init")
        run(*compose, "run", "--rm", "--no-deps", "minio-init")
        # Sentinel verifies persistence and repeatable initialization, without shared buckets.
        import hashlib
        import io

        from ontology_platform.artifacts.config import StorageSettings
        from ontology_platform.artifacts.s3 import S3ArtifactStore
        from ontology_platform.artifacts.storage import ObjectKey

        settings = StorageSettings(
            _env_file=None,
            backend="s3",
            endpoint=env["FOUNDRY_ARTIFACT_ENDPOINT"],
            development_http=True,
            access_key=env["MINIO_APP_USER"],
            secret_key=env["MINIO_APP_PASSWORD"],
        )
        store = S3ArtifactStore(settings)
        key = ObjectKey(uuid4(), uuid4(), uuid4())
        checksum = hashlib.sha256(b"persistent").hexdigest()
        store.put(key, io.BytesIO(b"persistent"), 10, checksum)
        run(*compose, "restart", "minio")
        run(*compose, "up", "-d", "--pull", "never", "--wait", "minio")
        run(*compose, "run", "--rm", "--no-deps", "minio-init")
        store.verify(key, 10, checksum)
        print("PASS MinIO initialization repeated and bytes retained after restart", flush=True)
        if args.full:
            run("uv", "run", "python", "scripts/validate_phase11.py")
        else:
            run(
                "uv",
                "run",
                "pytest",
                "services/api/tests/test_artifacts.py",
                "services/api/tests/test_datasets.py",
                "-ra",
                "--tb=short",
            )
        if args.browser:
            run("uv", "run", "python", "scripts/test_studio.py")
    finally:
        subprocess.run(
            compose + ["down", "--volumes", "--remove-orphans"], cwd=root, env=env, check=True
        )
