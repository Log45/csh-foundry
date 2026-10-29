"""Read-only smoke of the Phase 5 API image, with local identity disabled."""

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
        "FOUNDRY_TRUSTED_LOCAL_IDENTITY=false",
        "csh-foundry-phase5",
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

    def call(path, data=None):
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}" + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.load(response)

    for _ in range(80):
        try:
            assert call("/health/live")["status"] == "ok"
            break
        except (OSError, urllib.error.HTTPError):
            time.sleep(0.25)
    else:
        raise RuntimeError("Container failed to become live")
    checks.append("PASS container liveness")
    assert call("/health/ready")["status"] == "ready"
    checks.append("PASS container readiness with PostgreSQL at current Alembic head")
    assert "/api/v1/ontologies/{ontology_id}/semantic/jobs" in call("/api/v1/openapi.json")["paths"]
    checks.append("PASS container OpenAPI exposes typed semantic endpoints")
    try:
        call(
            "/api/v1/ontologies/manufacturing/semantic/jobs",
            {
                "operation": "validation",
                "primary_artifact": "00000000-0000-0000-0000-000000000001",
                "secondary_artifact": "00000000-0000-0000-0000-000000000002",
            },
        )
    except urllib.error.HTTPError as error:
        assert error.code == 401
    else:
        raise AssertionError("Missing identity was not rejected")
    checks.append("PASS container semantic endpoint denies absent identity with 401")
finally:
    logs = subprocess.check_output(
        ["docker", "logs", container], stderr=subprocess.STDOUT, text=True
    )
    subprocess.run(["docker", "stop", container], check=True, capture_output=True)
    path = (
        Path(__file__).resolve().parents[1] / "docs/architecture/evidence/phase-5/docker-smoke.txt"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(checks) + "\n" + logs)
print("\n".join(checks))
