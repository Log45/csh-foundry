"""Execute built TypeScript wrappers against real governed PostgreSQL/MinIO APIs.

The JSON-line fetch adapter is test-only, not an alternative production BFF. Browser tests
separately execute the actual HttpOnly/OIDC/CSRF BFF. No dependency overrides are used.
"""

import json
import subprocess
from contextlib import ExitStack
from pathlib import Path

from fastapi.testclient import TestClient
from ontology_platform.artifacts.contracts import CreateArtifact
from ontology_platform.execution.worker import ExecutionWorker
from ontology_platform.main import create_app
from ontology_platform.pipelines.contracts import Definition, StartRun
from ontology_platform.pipelines.service import PipelineService
from ontology_platform.projects.contracts import CreateProject, MemberChange, ShareChange
from ontology_platform.security.service import PlatformAuthorizer
from test_actions import world as action_world  # noqa: F401
from test_artifacts import store  # noqa: F401
from test_mappings import setup_mapping
from test_phase1 import database, world  # noqa: F401
from test_projects import grant_projects
from test_security_platform import ISSUER, security  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]


def test_built_sdk_against_governed_api(security, store):  # noqa: F811
    w, auth, admin, owner, reader, _ = security
    auth = PlatformAuthorizer(w.sessions, test_mode=True)
    grant_projects(admin, owner, reader)
    mapping, resource, _, body = setup_mapping(
        w, store, b"id,name\nSDK1,One\nSDK2,Two\n", prepared=True, actor=owner, auth=auth
    )
    pipes = PipelineService(w.sessions, auth, store.settings, store)
    output = pipes.datasets().create(owner, resource.project_id, CreateArtifact(name="SDK output"))
    pipeline = pipes.create(owner, resource.project_id, CreateArtifact(name="SDK pipeline"))
    definition = pipes.publish(
        owner,
        pipeline.id,
        Definition.model_validate(
            {
                "engine": "polars",
                "inputs": [{"name": "source", "columns": {"id": "String"}}],
                "steps": [{"op": "select", "columns": ["id"]}],
                "output_columns": {"id": "String"},
            }
        ),
    )
    run = StartRun(
        definition_id=definition.id,
        inputs=[{"name": "source", "dataset_id": body.dataset_id, "version_id": body.version_id}],
        output_dataset_id=output.id,
    )
    consumer = pipes.create_project(owner, CreateProject(name="SDK consumer"))
    pipes.member(
        owner,
        consumer.id,
        MemberChange(
            principal_id=reader.principal_id, role="viewer", expected_revision=consumer.revision
        ),
    )
    for key in (body.dataset_id, resource.id):
        pipes.share(
            owner,
            key,
            ShareChange(
                project_id=consumer.id,
                enabled=True,
                expected_revision=pipes.get_resource(owner, key).revision,
            ),
        )
    with ExitStack() as stack:
        clients = {}
        for subject in ("admin", "alice"):
            settings = w.settings.model_copy(
                update={
                    "auth_mode": "test",
                    "trusted_local_identity": False,
                    "test_issuer": ISSUER,
                    "test_subject": subject,
                }
            )
            app = create_app(settings)
            app.state.sessions = w.sessions
            app.state.authorizer = auth
            clients[subject] = stack.enter_context(TestClient(app))
        config = {
            "tenant": str(owner.tenant_id),
            "dataset": str(body.dataset_id),
            "version": str(body.version_id),
            "mapping": str(resource.id),
            "project": str(resource.project_id),
            "pipeline": str(pipeline.id),
            "pipelineBody": run.model_dump(mode="json"),
            "mappingBody": body.model_dump(mode="json"),
        }
        exercise(config, clients, ExecutionWorker(pipes))


def exercise(config, clients, worker=None):
    process = subprocess.Popen(
        ["node", "tests/sdk/integration.mjs"],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin and process.stdout
    process.stdin.write(json.dumps(config) + "\n")
    process.stdin.flush()
    done = False
    try:
        for line in process.stdout:
            message = json.loads(line)
            if message.get("done"):
                done = True
                response = {}
            elif message.get("work"):
                assert worker.run_one() is not None
                response = {}
            else:
                envelope = message["envelope"]
                assert message["headers"]["x-csrf-token"] == "test-csrf"
                result = clients[message["actor"]].request(
                    envelope["method"],
                    envelope["path"],
                    json=envelope.get("body"),
                    headers={"x-tenant-id": envelope["expected_tenant"]},
                )
                response = {"status": result.status_code, "body": result.json()}
            process.stdin.write(json.dumps(response) + "\n")
            process.stdin.flush()
        code = process.wait(timeout=30)
        assert code == 0, process.stderr.read() if process.stderr else "node failed"
        assert done
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_built_sdk_actions(action_world):  # noqa: F811
    w = action_world
    app = create_app(w.settings)
    app.state.sessions = w.sessions
    with TestClient(app) as client:
        exercise({"tenant": str(w.actor.tenant_id), "scenario": "actions"}, {"admin": client})


def test_sdk_observes_partial_cancelled_materialization(world, store, monkeypatch):  # noqa: F811
    from test_mappings_recovery import boundary, content

    svc, resource, _, body = setup_mapping(world, store, content())
    run = svc.start(world.actor, resource.id, body)
    boundary(svc, run, lambda: svc.change(world.actor, run.id), monkeypatch)
    ExecutionWorker(svc).run_one()
    app = create_app(world.settings)
    app.state.sessions = world.sessions
    with TestClient(app) as client:
        exercise(
            {"tenant": str(world.actor.tenant_id), "scenario": "partial", "job": str(run.id)},
            {"admin": client},
        )
