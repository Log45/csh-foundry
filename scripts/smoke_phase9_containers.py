"""Read-only API/Studio image checks for SDK packaging and private routes."""

import os
import subprocess
import time
from contextlib import contextmanager

import httpx
from ontology_platform.config import get_settings
from sqlalchemy.engine import make_url


@contextmanager
def running(image, port, environment=None):
    command = ["docker", "run", "--rm", "-d", "-p", f"127.0.0.1::{port}"]
    for name in environment or {}:
        command += ["-e", name]
    command.append(image)
    container = subprocess.check_output(
        command, env=os.environ | (environment or {}), text=True
    ).strip()
    try:
        binding = subprocess.check_output(
            ["docker", "port", container, str(port)], text=True
        ).strip()
        base = "http://127.0.0.1:" + binding.rsplit(":", 1)[1]
        for _ in range(100):
            try:
                if (
                    httpx.get(
                        base + ("/health/live" if port == 8000 else "/"), timeout=3
                    ).status_code
                    == 200
                ):
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
        else:
            raise RuntimeError("Container readiness failed")
        yield container, base
    finally:
        subprocess.run(["docker", "stop", container], check=True, capture_output=True)


url = make_url(get_settings().database_url.get_secret_value()).set(host="host.docker.internal")
with running(
    "csh-foundry-phase9",
    8000,
    {
        "FOUNDRY_DATABASE_URL": url.render_as_string(hide_password=False),
        "FOUNDRY_AUTH_MODE": "disabled",
        "FOUNDRY_TRUSTED_LOCAL_IDENTITY": "false",
    },
) as (container, base):
    assert httpx.get(base + "/health/ready").json()["status"] == "ready"
    spec = httpx.get(base + "/api/v1/openapi.json").json()
    for path in (
        "/api/v1/ontologies/{ontology_id}/branches",
        "/api/v1/ontologies/{ontology_id}/sdk/generate",
    ):
        assert path in spec["paths"]
    for method, path in (
        ("GET", "/branches"),
        ("POST", "/sdk/generate"),
        ("GET", "/sdk/artifacts"),
    ):
        response = httpx.request(
            method,
            base + "/api/v1/ontologies/manufacturing" + path,
            json={"version": "1.0.0", "language": "python"} if method == "POST" else None,
            headers={
                "Authorization": "Bearer forged",
                "X-Tenant-ID": "00000000-0000-0000-0000-000000000001",
            },
        )
        assert response.status_code == 401
    subprocess.run(
        [
            "docker",
            "exec",
            container,
            "uv",
            "run",
            "--no-sync",
            "python",
            "-c",
            """
from pathlib import Path
from ontology_schema.models import OntologyDefinition
from ontology_platform.main import create_app
from ontology_platform.sdk.generator import generate
schema=OntologyDefinition.model_validate_json(Path('ontologies/examples/manufacturing.json').read_text())
contract=create_app().openapi()
for language in ('python','typescript'):
 first=generate(schema,language,contract)
 assert first.archive()==generate(schema,language,contract).archive()
print('PASS packaged Python/TypeScript generator templates and deterministic archives')
""",
        ],
        check=True,
    )
    print(
        "PASS final API image: migrated PostgreSQL readiness, branch/SDK OpenAPI, "
        "unauthenticated and forged-token denial"
    )
with running("csh-foundry-studio:phase9", 3000) as (container, base):
    response = httpx.get(base)
    assert "Your ontology." in response.text
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "'unsafe-eval'" not in response.headers["content-security-policy"]
    assert httpx.get(base + "/auth/session").status_code == 401
    assert (
        httpx.post(base + "/bff", json={"path": "/api/v1/ontologies", "method": "GET"}).status_code
        == 401
    )
    assert httpx.post(base + "/auth/login", headers={"Origin": base}).status_code == 503
    assert (
        subprocess.check_output(["docker", "exec", container, "id", "-u"], text=True).strip() != "0"
    )
    print(
        "PASS final Studio image: rendered root, security headers, non-root runtime, "
        "private BFF denial and fail-closed unconfigured login"
    )
