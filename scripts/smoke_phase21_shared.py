"""Authenticated non-destructive shared development acceptance through existing Keycloak/API.

Prompts for the existing development password; never stores tokens or credentials. Creates a named
validation Project/resources and retains them for operator review. No realm/configuration mutations.
"""

import base64
import getpass
import hashlib
import html
import json
import re
import secrets
import ssl
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
ISSUER = "https://keycloak.localhost/realms/foundry"
CALLBACK = "http://127.0.0.1:3000/auth/callback"
password = getpass.getpass("Existing development password: ")
verifier = secrets.token_urlsafe(48)
state = secrets.token_urlsafe(32)
context = ssl.create_default_context(cafile=str(ROOT / "artifacts/keycloak-local/ca.pem"))


class LocalIdentityTransport(httpx.HTTPTransport):
    """Pin the known local issuer to loopback, retaining verified TLS hostname/SNI.

    Uses the installed httpcore sni_hostname extension, verified against actual source.
    The original request remains unchanged so httpx scopes cookies to the real issuer.
    """

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "keycloak.localhost"
        mapped = httpx.Request(
            request.method,
            request.url.copy_with(host="127.0.0.1"),
            headers=request.headers,
            stream=request.stream,
            extensions=request.extensions | {"sni_hostname": "keycloak.localhost"},
        )
        return super().handle_request(mapped)


with httpx.Client(
    transport=LocalIdentityTransport(verify=context), trust_env=False, timeout=20
) as identity:
    parameters = {
        "client_id": "studio",
        "redirect_uri": CALLBACK,
        "response_type": "code",
        "scope": "openid",
        "state": state,
        "nonce": secrets.token_urlsafe(32),
        "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("="),
        "code_challenge_method": "S256",
        "audience": "foundry-api",
    }
    page = identity.get(ISSUER + "/protocol/openid-connect/auth?" + urlencode(parameters))
    form = re.search(r'<form[^>]*action="([^"]+)"', page.text)
    assert form, "Keycloak login form unavailable"
    action = html.unescape(form[1])
    assert urlsplit(action).netloc == "keycloak.localhost"
    login = identity.post(action, data={"username": "dev", "password": password})
    del password
    location = login.headers.get("location", "")
    assert location.startswith(CALLBACK + "?"), "Existing authentication did not complete"
    callback = parse_qs(urlsplit(location).query)
    assert callback["state"] == [state]
    tokens = identity.post(
        ISSUER + "/protocol/openid-connect/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "studio",
            "code": callback["code"][0],
            "redirect_uri": CALLBACK,
            "code_verifier": verifier,
        },
    )
    assert tokens.status_code == 200, "Code exchange failed"
    token = tokens.json()["access_token"]

with httpx.Client(
    base_url="http://127.0.0.1:8000/api/v1",
    headers={"Authorization": "Bearer " + token},
    timeout=30,
    trust_env=False,
) as api:

    def call(method, path, body=None, **kwargs):
        result = api.request(method, path, json=body, **kwargs)
        assert 200 <= result.status_code < 300, f"{method} {path}: status {result.status_code}"
        return result.json()

    tenants = call("GET", "/security/tenants")
    assert tenants
    api.headers["x-tenant-id"] = tenants[0]["id"]
    existing = call("GET", "/projects?limit=100&offset=0")
    project = call(
        "POST",
        "/projects",
        {"name": "Phase 21 shared validation " + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")},
    )

    def dataset(name):
        return call("POST", f"/projects/{project['id']}/datasets", {"name": name})

    source = dataset("Observed source")
    outputs = [dataset("Atomic output A"), dataset("Atomic output B")]
    legacy = dataset("Legacy output")
    data = b"id,value\n1,10\n2,20\n"
    version = call(
        "POST",
        f"/datasets/{source['id']}/uploads",
        {
            "filename": "phase21.csv",
            "format": "csv",
            "size": len(data),
            "checksum": hashlib.sha256(data).hexdigest(),
        },
    )
    content = api.put(
        f"/datasets/{source['id']}/versions/{version['id']}/content",
        content=data,
        headers={"content-type": "application/octet-stream"},
    )
    assert content.status_code == 200
    committed = call("POST", f"/datasets/{source['id']}/versions/{version['id']}/finalize")
    assert committed["state"] == "COMMITTED"
    pipeline = call(
        "POST", f"/projects/{project['id']}/pipelines", {"name": "Shared governed pipelines"}
    )
    pins = [{"name": "source", "dataset_id": source["id"], "version_id": version["id"]}]

    def wait(run):
        for _ in range(120):
            current = call("GET", f"/execution/jobs/{run['id']}")
            if current["state"] in ["SUCCEEDED", "FAILED", "CANCELLED"]:
                assert current["state"] == "SUCCEEDED", current["error"]
                return current
            time.sleep(0.5)
        raise RuntimeError("Execution did not finish in bounded smoke window")

    linear = call(
        "POST",
        f"/pipelines/{pipeline['id']}/definitions",
        {"inputs": [{"name": "source"}], "steps": [{"op": "select", "columns": ["id", "value"]}]},
    )
    historical = wait(
        call(
            "POST",
            f"/pipelines/{pipeline['id']}/runs",
            {"definition_id": linear["id"], "inputs": pins, "output_dataset_id": legacy["id"]},
        )
    )
    spec = {
        "format_version": 2,
        "inputs": pins,
        "nodes": [
            {
                "id": "shared",
                "inputs": {"input": "source"},
                "config": {"op": "select", "columns": ["id", "value"]},
            }
        ],
        "outputs": [
            {"id": str(i), "source": "shared", "dataset_id": out["id"]}
            for i, out in enumerate(outputs)
        ],
    }
    definition = call("POST", f"/pipelines/{pipeline['id']}/definitions", spec)
    run = wait(
        call(
            "POST",
            f"/pipelines/{pipeline['id']}/runs",
            {"definition_id": definition["id"], "inputs": pins},
        )
    )
    assert run["publication_state"] == "COMMITTED" and len(run["outputs"]) == 2
    for output in run["outputs"]:
        preview = call(
            "GET", f"/datasets/{output['dataset_id']}/versions/{output['version_id']}/preview"
        )
        assert len(preview["rows"]) == 2
    for _ in range(40):
        if call("GET", f"/resources/{pipeline['id']}/lineage/index")["complete"]:
            break
        time.sleep(0.5)
    out = run["outputs"][0]
    root = {
        "key": f"DATASET_VERSION:{out['dataset_id']}:{out['version_id']}:",
        "kind": "DATASET_VERSION",
        "resource_id": out["dataset_id"],
        "version_id": out["version_id"],
    }
    graph = call(
        "POST",
        "/lineage/traverse",
        {"root": root, "direction": "upstream", "depth": 8, "max_nodes": 100, "max_edges": 200},
    )
    assert any(e["relation"] == "PRODUCES" for e in graph["edges"])
    freshness = call("PUT", f"/datasets/{out['dataset_id']}/freshness", {"max_age_seconds": 3600})
    assert freshness["state"] == "FRESH"
    observation = call("GET", f"/observability/executions/{run['id']}")
    assert observation["execution"]["publication_state"] == "COMMITTED"
    assert (
        call("GET", f"/pipelines/{pipeline['id']}/definitions/{definition['id']}/columns")["status"]
        == "EXACT"
    )
    assert call("GET", f"/resources/{pipeline['id']}/events?limit=100&offset=0")
    remaining = call("GET", "/projects?limit=100&offset=0")
    assert {p["id"] for p in existing}.issubset({p["id"] for p in remaining})
    evidence = {
        "result": "PASS",
        "authentication": "existing Keycloak Code/PKCE",
        "project": project["id"],
        "project_name": project["name"],
        "preserved_projects": [p["id"] for p in existing],
        "source_dataset": source["id"],
        "source_version": version["id"],
        "pipeline": pipeline["id"],
        "legacy_run": historical["id"],
        "dag_run": run["id"],
        "outputs": run["outputs"],
        "publication": "COMMITTED",
        "lineage_nodes": len(graph["nodes"]),
        "lineage_edges": len(graph["edges"]),
        "index_complete": graph["indexing"]["complete"],
        "freshness": freshness["state"],
        "columns": "EXACT",
    }
    (ROOT / "artifacts/phase21/shared-smoke.json").write_text(json.dumps(evidence, indent=2))
    print(
        "PASS existing authentication, preserved Projects, source upload, legacy run, "
        "atomic two-output DAG, previews, lineage, freshness, columns and events"
    )
