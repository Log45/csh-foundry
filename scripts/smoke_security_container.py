"""Read-only Phase 7 image probe; no identity bootstrap or operational writes."""

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from ontology_platform.config import get_settings
from sqlalchemy.engine import make_url

url = make_url(get_settings().database_url.get_secret_value()).set(host="host.docker.internal")
environment = dict(os.environ, FOUNDRY_DATABASE_URL=url.render_as_string(hide_password=False))
container = subprocess.check_output(
    [
        "docker",
        "run",
        "--rm",
        "-d",
        "-p",
        "127.0.0.1::8000",
        "-e",
        "FOUNDRY_DATABASE_URL",
        "-e",
        "FOUNDRY_AUTH_MODE=disabled",
        "-e",
        "FOUNDRY_TRUSTED_LOCAL_IDENTITY=false",
        os.environ.get("FOUNDRY_SMOKE_IMAGE", "csh-foundry-phase7"),
    ],
    env=environment,
    text=True,
).strip()
checks = []
try:
    port = (
        subprocess.check_output(["docker", "port", container, "8000"], text=True)
        .strip()
        .rsplit(":", 1)[1]
    )
    base = f"http://127.0.0.1:{port}"

    def call(path, headers=None):
        with urllib.request.urlopen(
            urllib.request.Request(base + path, headers=headers or {}), timeout=5
        ) as response:
            return json.load(response)

    for _ in range(80):
        try:
            assert call("/health/live")["status"] == "ok"
            break
        except OSError:
            time.sleep(0.25)
    else:
        raise RuntimeError("Image did not start")
    checks.append("PASS final image liveness")
    assert call("/health/ready")["status"] == "ready"
    checks.append("PASS final image PostgreSQL readiness at 0013_security")
    spec = call("/api/v1/openapi.json")
    assert "HTTPBearer" in spec["components"]["securitySchemes"]
    assert "/api/v1/security/policies" in spec["paths"]
    checks.append("PASS final image security OpenAPI and Bearer scheme")
    for path in ("/api/v1/security/me", "/api/v1/ontologies", "/api/v1/tenant"):
        try:
            call(
                path,
                {
                    "X-Principal-ID": "administrator",
                    "X-Tenant-ID": "00000000-0000-0000-0000-000000000001",
                    "Authorization": "Bearer forged",
                },
            )
        except urllib.error.HTTPError as error:
            assert error.code == 401
        else:
            raise AssertionError("Spoofed identity accepted")
    checks.append("PASS disabled mode denies forged identity/tenant/token headers")
finally:
    logs = subprocess.check_output(
        ["docker", "logs", container], stderr=subprocess.STDOUT, text=True
    )
    subprocess.run(["docker", "stop", container], check=True, capture_output=True)
    Path(
        os.environ.get(
            "FOUNDRY_SMOKE_EVIDENCE", "docs/architecture/evidence/phase-7/docker-smoke.txt"
        )
    ).write_text("\n".join(checks) + "\n" + logs)
invalid = subprocess.run(
    [
        "docker",
        "run",
        "--rm",
        "-e",
        "FOUNDRY_DATABASE_URL=postgresql+psycopg://localhost/unused",
        "-e",
        "FOUNDRY_AUTH_MODE=oidc",
        os.environ.get("FOUNDRY_SMOKE_IMAGE", "csh-foundry-phase7"),
    ],
    capture_output=True,
    text=True,
)
assert invalid.returncode != 0
assert "OIDC mode requires trusted providers" in invalid.stderr
checks.append(
    "PASS OIDC image startup fails closed without required trusted provider configuration"
)
Path(
    os.environ.get("FOUNDRY_SMOKE_EVIDENCE", "docs/architecture/evidence/phase-7/docker-smoke.txt")
).write_text("\n".join(checks) + "\n" + logs)
print("\n".join(checks))
