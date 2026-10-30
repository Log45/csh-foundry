"""Generated packages run independently against actual FastAPI/PostgreSQL and signed API tokens."""

import base64
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from ontology_platform.config import Settings
from ontology_platform.contracts import VersionView
from ontology_platform.db.models import Link, Object
from ontology_platform.errors import ApplicationError
from ontology_platform.main import create_app
from ontology_platform.metadata.service import RegistryService
from ontology_platform.metadata.storage import digest
from ontology_platform.sdk.generator import generate, symbol
from ontology_platform.sdk.service import GenerateInput, SDKService
from ontology_schema.models import OntologyDefinition
from sqlalchemy import func, select
from test_phase1 import active, database, make_world  # noqa: F401
from test_queries import load_manufacturing
from test_security_oidc import idp, token  # noqa: F401
from test_security_workflows import secure

ROOT = Path(__file__).resolve().parents[3]


def node_binary():
    candidates = [os.environ.get("FOUNDRY_TEST_NODE"), shutil.which("node")]
    candidates += [str(path) for path in (Path.home() / ".nvm/versions/node").glob("*/bin/node")]
    for candidate in candidates:
        if (
            candidate
            and int(subprocess.check_output([candidate, "--version"], text=True).split(".")[0][1:])
            >= 22
        ):
            return Path(candidate)
    raise RuntimeError("NOT RUN: install Node >=22 for generated SDK package tests")


NODE = node_binary()


def schema():
    data = json.loads((ROOT / "ontologies/examples/manufacturing.json").read_text())
    data["action_types"] = json.loads(
        (ROOT / "ontologies/examples/manufacturing-actions.json").read_text()
    )
    return OntologyDefinition.model_validate(data)


def write_generated(directory, generated):
    for name, value in generated.files.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)


@pytest.mark.parametrize("language", ["python", "typescript"])
def test_sdk_deterministic_and_contract_validation(language, tmp_path):
    contract = create_app().openapi()
    first = generate(schema(), language, contract)
    second = generate(schema(), language, contract)
    assert first.files == second.files and first.archive() == second.archive()
    assert first.manifest["schema_hash"] == digest(schema())
    assert first.manifest["artifact_content_hash"] == second.manifest["artifact_content_hash"]
    assert all(
        secret not in "".join(first.files.values())
        for secret in ("foundry-session", "client_secret", "worker_access_token")
    )
    with pytest.raises(ApplicationError, match="absent"):
        generate(schema(), language, {})
    write_generated(tmp_path, first)


@pytest.mark.parametrize(
    "name",
    [
        "class",
        "constructor",
        "__proto__",
        "with space",
        "hy-phen",
        "1first",
        "机器",
        "model_dump",
        "get",
    ],
)
def test_identifier_safety(name):
    import keyword

    result = symbol(name)
    assert result.isidentifier() and not keyword.iskeyword(result)
    assert result == symbol(name) and result != symbol(name + "!")


def test_generated_sdk_packages_manufacturing(database, idp, tmp_path):  # noqa: F811
    w = make_world(database)
    w.definition = schema().model_copy(update={"tenant_id": w.actor.tenant_id})
    active(w)
    load_manufacturing(w)
    with w.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Object)) == 63
        assert session.scalar(select(func.count()).select_from(Link)) == 70
    auth, administration, principal = secure(w)
    # Full manufacturing branch workflow; the 63 operational identities remain stable.
    from ontology_platform.branching.contracts import (
        BranchCreate,
        BranchEdit,
        DraftHandoff,
        MergeInput,
        Resolution,
    )
    from ontology_platform.branching.service import BranchService

    branches = BranchService(w.sessions, auth)
    a = branches.create(principal, w.definition.id, BranchCreate(name="manufacturing-a"))
    b = branches.create(principal, w.definition.id, BranchCreate(name="manufacturing-b"))
    ours = w.definition.model_dump(mode="json")
    theirs = w.definition.model_dump(mode="json")
    next(t for t in ours["object_types"] if t["id"] == "Machine")["properties"].append(
        {"id": "inspectionDue", "name": "Inspection due", "data_type": "boolean"}
    )
    theirs["object_types"].append(
        {
            "id": "Inspection",
            "name": "Inspection",
            "primary_key": "inspectionId",
            "properties": [
                {
                    "id": "inspectionId",
                    "name": "Inspection ID",
                    "data_type": "string",
                    "required": True,
                }
            ],
        }
    )
    for branch, data in ((a, ours), (b, theirs)):
        branches.edit(
            principal,
            w.definition.id,
            branch.id,
            BranchEdit(
                expected_revision=1,
                definition=OntologyDefinition.model_validate(data),
                summary="Independent manufacturing addition",
            ),
        )
    req = MergeInput(source_branch=a.id, source_revision=2, target_revision=2)
    assert not branches.preview(principal, w.definition.id, b.id, req).conflicts
    for branch, data, name in (
        (a, ours, "Source manufacturing"),
        (b, theirs, "Target manufacturing"),
    ):
        data["name"] = name
        branches.edit(
            principal,
            w.definition.id,
            branch.id,
            BranchEdit(
                expected_revision=2,
                definition=OntologyDefinition.model_validate(data),
                summary="Conflicting display name",
            ),
        )
    req = MergeInput(
        source_branch=a.id,
        source_revision=3,
        target_revision=3,
        resolutions=[Resolution(conflict="/name", strategy="source")],
    )
    preview = branches.preview(principal, w.definition.id, b.id, req)
    assert all(c.resolved for c in preview.conflicts)
    branches.merge(
        principal,
        w.definition.id,
        b.id,
        req.model_copy(update={"preview_hash": preview.preview_hash}),
    )
    assert branches.get(principal, w.definition.id, a.id).state == "MERGED"
    assert len(branches.history(principal, w.definition.id, a.id)) == 3
    registry = RegistryService(w.sessions, auth)
    assert registry.get(principal, w.definition.id).active_version == "1.0.0"
    draft = branches.draft(
        principal, w.definition.id, b.id, DraftHandoff(expected_revision=4, version="1.1.0")
    )
    assert registry.validate(principal, w.definition.id, "1.1.0").classification == "additive"
    registry.publish(principal, w.definition.id, "1.1.0")
    with w.sessions() as session:
        identities = set(session.execute(select(Object.object_type_id, Object.object_id)))
    registry.activate(principal, w.definition.id, "1.1.0")
    with w.sessions() as session:
        assert set(session.execute(select(Object.object_type_id, Object.object_id))) == identities
        assert session.scalar(select(func.count()).select_from(Link)) == 70
    w.definition = draft.definition
    w.registry = RegistryService(w.sessions, auth)
    private, _, verifier = idp
    settings = Settings(
        database_url=w.settings.database_url,
        auth_mode="oidc",
        oidc_providers=verifier.providers,
        trusted_local_identity=False,
        local_tenant_id=None,
        local_principal_id=None,
        _env_file=None,
    )
    app = create_app(settings)
    app.state.sessions, app.state.authorizer, app.state.oidc = w.sessions, auth, verifier
    signed = token(private, claims={"sub": "operator"})
    generated = {
        lang: generate(w.definition, lang, app.openapi()) for lang in ("python", "typescript")
    }
    for lang, artifact in generated.items():
        write_generated(tmp_path / lang, artifact)
    sdk = SDKService(w.sessions, auth)
    artifact = sdk.generate(
        principal, w.definition.id, GenerateInput(version="1.1.0", language="python"), app.openapi()
    )
    assert (
        sdk.generate(
            principal,
            w.definition.id,
            GenerateInput(version="1.1.0", language="python"),
            app.openapi(),
        ).id
        == artifact.id
    )
    assert (
        base64.b64decode(
            sdk.artifact(principal, w.definition.id, artifact.id, download=True).archive_base64
        )
        == generated["python"].archive()
    )
    # Actual independently installed Python package; no repository/backend module import path.
    subprocess.run(
        ["uv", "venv", str(tmp_path / "venv"), "--python", "3.12"], check=True, capture_output=False
    )
    python = tmp_path / "venv/bin/python"
    subprocess.run(
        ["uv", "pip", "install", "--python", str(python), str(tmp_path / "python")],
        check=True,
        capture_output=False,
    )
    subprocess.run(
        ["uv", "run", "mypy", "--strict", str(tmp_path / "python/ontology_sdk")],
        check=True,
        capture_output=False,
    )
    subprocess.run(
        [
            str(NODE),
            str(ROOT / "apps/studio/node_modules/typescript/bin/tsc"),
            "-p",
            str(tmp_path / "typescript/tsconfig.json"),
        ],
        check=True,
        capture_output=False,
    )
    # Live HTTP server on an OS-assigned loopback socket; real JWT signature verification and DB.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.02)
    assert server.started
    env = os.environ | {
        "SDK_URL": f"http://127.0.0.1:{port}",
        "SDK_TOKEN": signed,
        "SDK_TENANT": str(w.actor.tenant_id),
    }
    try:
        pycheck = tmp_path / "python-check.py"
        pycheck.write_text((Path(__file__).parent / "sdk_acceptance" / "python.py.txt").read_text())
        subprocess.run(
            [str(python), str(pycheck)], cwd=tmp_path, env=env, check=True, capture_output=False
        )
        tscheck = tmp_path / "typescript/check.mjs"
        tscheck.write_text(
            (Path(__file__).parent / "sdk_acceptance" / "typescript.mjs").read_text()
        )
        subprocess.run(
            [str(NODE), str(tscheck)], cwd=tmp_path, env=env, check=True, capture_output=False
        )
        assert w.registry.get(w.actor, w.definition.id).active_version == "1.1.0"
        # Permission revocation is enforced for both generated packages after issuance.
        from ontology_platform.security.contracts import AssignmentInput

        administration.assign(
            principal, AssignmentInput(principal_id=principal.principal_id, role_id="data-reader")
        )
        administration.assign(
            principal,
            AssignmentInput(principal_id=principal.principal_id, role_id="tenant-administrator"),
            revoke=True,
        )
        with httpx.Client(
            base_url=env["SDK_URL"], headers={"Authorization": "Bearer " + signed}
        ) as client:
            assert (
                client.post(
                    "/api/v1/ontologies/manufacturing/actions/UpdateMachineStatus/execute",
                    json={"parameters": {}, "idempotency_key": "denied"},
                ).status_code
                == 403
            )

        denied_python = tmp_path / "denied.py"
        denied_python.write_text("""import asyncio, os
from ontology_sdk import OntologyClient, SDKError
from ontology_sdk.models import UpdateMachineStatusParameters
async def token(): return os.environ['SDK_TOKEN']
async def main():
 c=OntologyClient(os.environ['SDK_URL'], token, os.environ['SDK_TENANT'])
 try: await c.actions.UpdateMachineStatus.execute(UpdateMachineStatusParameters(
  machineId='MCH-005',newStatus='STOPPED',expectedRevision=1),idempotency_key='denied')
 except SDKError as exc: assert exc.status == 403
 else: raise AssertionError('revoked SDK action allowed')
 await c.close()
asyncio.run(main())
""")
        subprocess.run([str(python), str(denied_python)], cwd=tmp_path, env=env, check=True)
        denied_ts = tmp_path / "typescript/denied.mjs"
        denied_ts.write_text("""import assert from 'node:assert/strict';
import {OntologyClient, SDKError} from './dist/index.js';
const c=new OntologyClient({baseUrl:process.env.SDK_URL,tenantId:process.env.SDK_TENANT,
 tokenProvider:async()=>process.env.SDK_TOKEN});
await assert.rejects(c.actions.UpdateMachineStatus.execute({machineId:'MCH-005',newStatus:'STOPPED',
 expectedRevision:1},'denied'), e=>e instanceof SDKError && e.status===403);
""")
        subprocess.run([str(NODE), str(denied_ts)], cwd=tmp_path, env=env, check=True)
    finally:
        server.should_exit = True
        thread.join(10)
        sock.close()


def test_cli_regeneration_and_all_type_mappings(tmp_path):
    data = schema().model_dump(mode="json")
    properties = next(t for t in data["object_types"] if t["id"] == "Machine")["properties"]
    properties.extend(
        [
            {"id": "class", "name": "Reserved", "data_type": "string", "nullable": True},
            {"id": "counter", "name": "Count", "data_type": "integer"},
            {"id": "fraction", "name": "Fraction", "data_type": "float"},
            {"id": "flag", "name": "Flag", "data_type": "boolean"},
            {"id": "day", "name": "Day", "data_type": "date"},
            {"id": "instant", "name": "Instant", "data_type": "timestamp"},
            {"id": "identity", "name": "Identity", "data_type": "uuid"},
            {"id": "document", "name": "Document", "data_type": "json", "nullable": True},
            {"id": "tags", "name": "Tags", "data_type": "string", "array": True},
        ]
    )
    definition = OntologyDefinition.model_validate(data)
    from datetime import UTC, datetime

    export = tmp_path / "published.json"
    export.write_text(
        VersionView(
            definition=definition,
            status="PUBLISHED",
            content_hash=digest(definition),
            published_at=datetime.now(UTC),
            published_by="test",
        ).model_dump_json()
    )
    contract = tmp_path / "openapi.json"
    contract.write_text(json.dumps(create_app().openapi()))
    for language in ("python", "typescript"):
        directory = tmp_path / language
        command = [
            "uv",
            "run",
            "python",
            "-m",
            "ontology_platform.sdk",
            "--input",
            str(export),
            "--openapi",
            str(contract),
            "--tenant",
            str(definition.tenant_id),
            "--ontology",
            definition.id,
            "--version",
            definition.version,
            "--language",
            language,
            "--output",
            str(directory),
        ]
        subprocess.run(command, check=True, capture_output=True)
        subprocess.run(command + ["--check"], check=True, capture_output=True)
        if language == "typescript":
            subprocess.run(
                [
                    str(NODE),
                    str(ROOT / "apps/studio/node_modules/typescript/bin/tsc"),
                    "-p",
                    str(directory / "tsconfig.json"),
                ],
                check=True,
                capture_output=True,
            )
        else:
            env = os.environ | {"PYTHONPATH": str(directory)}
            code = """from ontology_sdk.models import MachinePatch
from datetime import datetime
from decimal import Decimal
from pydantic import ValidationError
model=MachinePatch.model_validate({"class":None,"tags":["x"],"day":"2026-11-01",
"instant":"2026-11-01T00:00:00Z","identity":"00000000-0000-0000-0000-000000000001",
"counter":1,"fraction":1.5,"flag":True,"document":{"x":[1]},"temperatureCelsius":"2.50"})
assert model.temperatureCelsius == Decimal("2.50")
assert model.model_dump(mode="json",by_alias=True,exclude_unset=True)["class"] is None
for bad in ({"instant":"2026-11-01T00:00:00"},{"temperatureCelsius":1.3},{"counter":True}):
 try: MachinePatch.model_validate(bad)
 except ValidationError: pass
 else: raise AssertionError("invalid serialization input accepted")
"""
            subprocess.run(
                ["uv", "run", "python", "-c", code], env=env, check=True, capture_output=True
            )
        next(iter(directory.glob("**/*.*"))).write_text("changed")
        assert subprocess.run(command + ["--check"], capture_output=True).returncode != 0


def test_sdk_artifact_denies_unpublished_cross_tenant_and_missing_authority(database):  # noqa: F811
    w = make_world(database)
    w.registry.create(w.actor, w.definition)
    service = SDKService(w.sessions, w.registry.authorizer)
    with pytest.raises(ApplicationError, match="published"):
        service.generate(
            w.actor,
            w.definition.id,
            GenerateInput(version="1.0.0", language="python"),
            create_app().openapi(),
        )
    w.registry.publish(w.actor, w.definition.id, "1.0.0")
    artifact = service.generate(
        w.actor,
        w.definition.id,
        GenerateInput(version="1.0.0", language="python"),
        create_app().openapi(),
    )
    other = make_world(database)
    active(other)
    with pytest.raises(ApplicationError, match="not found"):
        SDKService(other.sessions, other.registry.authorizer).artifact(
            other.actor, other.definition.id, artifact.id, download=True
        )

    class Deny:
        def require(self, principal, operation, resource):
            raise ApplicationError("forbidden", "Schema permission revoked", 403)

    with pytest.raises(ApplicationError, match="revoked"):
        SDKService(w.sessions, Deny()).artifact(
            w.actor, w.definition.id, artifact.id, download=True
        )


@pytest.mark.parametrize("language", ["python", "typescript"])
def test_generated_type_checker_rejects_invalid_property_and_operator(language, tmp_path):
    generated = generate(schema(), language, create_app().openapi())
    write_generated(tmp_path, generated)
    if language == "python":
        check = tmp_path / "type_check.py"
        check.write_text("""from ontology_sdk.client import MachineFields
MachineFields.machineName.gt("invalid")
MachineFields.temperatureCelsius.eq(1.5)
MachineFields.missing.eq("unknown")
""")
        result = subprocess.run(
            ["uv", "run", "mypy", "--strict", str(check)],
            env=os.environ | {"MYPYPATH": str(tmp_path)},
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0 and "Found 3 errors" in result.stdout
    else:
        check = tmp_path / "src/type_check.ts"
        check.write_text("""import {OntologyClient} from "./index.js";
const c = new OntologyClient({baseUrl:"https://example.invalid",tenantId:"test",tokenProvider:async()=>"test"});
c.Machine.fields.machineName.gt("invalid");
c.Machine.fields.temperatureCelsius.eq(1.5);
c.Machine.fields.missing.eq("unknown");
""")
        result = subprocess.run(
            [
                str(NODE),
                str(ROOT / "apps/studio/node_modules/typescript/bin/tsc"),
                "-p",
                str(tmp_path / "tsconfig.json"),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0 and result.stdout.count("error TS") == 3
