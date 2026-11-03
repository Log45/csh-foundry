"""Run Studio E2E with a local TLS IdP, actual FastAPI and disposable PostgreSQL schema."""

import os
import secrets
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path

import httpx
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
studio_port = int(os.environ.get("STUDIO_E2E_PORT", "3000"))
api_port = int(os.environ.get("STUDIO_E2E_API_PORT", "8001"))
replica_port = int(os.environ.get("STUDIO_E2E_REPLICA_PORT", "3001"))
origin = f"http://127.0.0.1:{studio_port}"
api_origin = f"http://127.0.0.1:{api_port}"
log = Path(os.environ.get("STUDIO_E2E_DIRECTORY", str(ROOT / "artifacts/studio-e2e")))
cert = log / "cert.pem"
# Refuse occupied listeners before starting anything; readiness must be our process.
for port in (studio_port, api_port, 8443) + (
    (replica_port,) if os.environ.get("STUDIO_E2E_DURABLE") == "true" else ()
):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))
log.mkdir(parents=True, exist_ok=True)
env = os.environ | {
    "STUDIO_ORIGIN": origin,
    "STUDIO_OIDC_ISSUER": "https://127.0.0.1/oidc",
    "STUDIO_OIDC_CLIENT_ID": "studio",
    "STUDIO_API_AUDIENCE": "foundry",
    "STUDIO_API_ORIGIN": api_origin,
    "NODE_EXTRA_CA_CERTS": str(cert),
    "NODE_OPTIONS": "--import=" + str(ROOT / "apps/studio/tests/oidc_transport.mjs"),
}
processes = []
durable = os.environ.get("STUDIO_E2E_DURABLE") == "true"
if durable:
    shutil.copytree(
        ROOT / "apps/studio/.next/static",
        ROOT / "apps/studio/.next/standalone/.next/static",
        dirs_exist_ok=True,
    )
    credential = secrets.token_urlsafe(32)
    env.update(
        {
            "STUDIO_STATE_SECRET": credential,
            "FOUNDRY_BROWSER_STATE_SECRET": credential,
            "FOUNDRY_BROWSER_STATE_KEYS": Fernet.generate_key().decode(),
            "STUDIO_E2E_REPLICA_PORT": str(replica_port),
        }
    )
try:
    with (log / "backend.log").open("w") as backend, (log / "next.log").open("w") as frontend:
        processes.append(
            subprocess.Popen(
                ["uv", "run", "python", "apps/studio/tests/e2e_backend.py"],
                cwd=ROOT,
                stdout=backend,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
            )
        )
        for _ in range(120):
            if processes[0].poll() is not None:
                raise RuntimeError("E2E backend failed; see artifacts/studio-e2e/backend.log")
            try:
                if httpx.get(api_origin + "/health/ready").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError("Backend readiness timed out")
        processes.append(
            subprocess.Popen(
                ["node", ".next/standalone/server.js"] if durable else ["npm", "run", "dev"],
                cwd=ROOT / "apps/studio",
                stdout=frontend,
                stderr=subprocess.STDOUT,
                env=env | {"HOSTNAME": "127.0.0.1", "PORT": str(studio_port)},
                start_new_session=True,
            )
        )
        for _ in range(120):
            try:
                if httpx.get(origin, timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError("Frontend readiness timed out")
        if durable:
            replica = subprocess.Popen(
                ["node", ".next/standalone/server.js"],
                cwd=ROOT / "apps/studio",
                stdout=frontend,
                stderr=subprocess.STDOUT,
                env=env | {"HOSTNAME": "127.0.0.1", "PORT": str(replica_port)},
                start_new_session=True,
            )
            processes.append(replica)
            for _ in range(120):
                try:
                    if httpx.get(f"http://127.0.0.1:{replica_port}", timeout=2).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
            else:
                raise RuntimeError("Second replica readiness timed out")
            env["STUDIO_E2E_REPLICA_PID"] = str(replica.pid)
        raise SystemExit(
            subprocess.call(["npm", "run", "test:e2e"], cwd=ROOT / "apps/studio", env=env)
        )
finally:
    for process in reversed(processes):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
    for process in reversed(processes):
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
