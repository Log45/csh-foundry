"""Run Studio E2E with a local TLS IdP, actual FastAPI and disposable PostgreSQL schema."""

import os
import signal
import subprocess
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
cert = ROOT / "artifacts/studio-e2e/cert.pem"
log = ROOT / "artifacts/studio-e2e"
log.mkdir(parents=True, exist_ok=True)
env = os.environ | {
    "STUDIO_ORIGIN": "http://127.0.0.1:3000",
    "STUDIO_OIDC_ISSUER": "https://127.0.0.1/oidc",
    "STUDIO_OIDC_CLIENT_ID": "studio",
    "STUDIO_API_AUDIENCE": "foundry",
    "STUDIO_API_ORIGIN": "http://127.0.0.1:8001",
    "NODE_EXTRA_CA_CERTS": str(cert),
    "NODE_OPTIONS": "--import=" + str(ROOT / "apps/studio/tests/oidc_transport.mjs"),
}
processes = []
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
                if httpx.get("http://127.0.0.1:8001/health/ready").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError("Backend readiness timed out")
        processes.append(
            subprocess.Popen(
                ["npm", "run", "dev"],
                cwd=ROOT / "apps/studio",
                stdout=frontend,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
            )
        )
        for _ in range(120):
            try:
                if httpx.get("http://127.0.0.1:3000", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError("Frontend readiness timed out")
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
