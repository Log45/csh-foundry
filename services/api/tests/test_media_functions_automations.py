# ruff: noqa: F811
"""Milestone G: real PostgreSQL/MinIO, immutable contracts and denied authority."""

import io
import json
import wave
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from ontology_platform.artifacts.contracts import CreateArtifact
from ontology_platform.automations.contracts import AutomationDefinition, Enable, Trigger
from ontology_platform.automations.service import AutomationService, next_instant
from ontology_platform.db.models import (
    AutomationState,
    ExecutionJob,
    FunctionResult,
    GovernedDefinition,
    MediaItem,
    MediaMembership,
)
from ontology_platform.db.session import clock
from ontology_platform.errors import ApplicationError
from ontology_platform.execution.config import ExecutionSettings
from ontology_platform.execution.isolation import isolated
from ontology_platform.execution.worker import ExecutionWorker
from ontology_platform.functions.contracts import FunctionDefinition, Invoke, ValueType, typed
from ontology_platform.functions.engine import execute
from ontology_platform.functions.service import FunctionService
from ontology_platform.media.contracts import AttachMedia, Snapshot
from ontology_platform.media.service import MediaService
from ontology_platform.pipelines.service import PipelineService
from ontology_platform.projects.contracts import CreateProject, MemberChange, ShareChange
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError
from test_actions import world as action_world  # noqa: F401
from test_artifacts import commit, store  # noqa: F401
from test_phase1 import ROOT, client_for, database, historical_database, migrate, world  # noqa: F401
from test_projects import grant_projects
from test_security_platform import security  # noqa: F401


def definition(implementation="identity.v1"):
    if implementation == "number.add.v1":
        return FunctionDefinition(
            implementation=implementation,
            input_schema={"left": ValueType(type="number"), "right": ValueType(type="number")},
            output_schema={"result": ValueType(type="number")},
        )
    return FunctionDefinition(
        implementation=implementation,
        input_schema={"text": ValueType(type="string")},
        output_schema={
            "text" if implementation == "identity.v1" else "result": ValueType(type="string")
        },
    )


def service(w, store, cls=FunctionService, auth=None):
    return cls(w.sessions, auth or w.registry.authorizer, store.settings, store)


def resource(svc, actor, name="Resource", project=None):
    if project is None:
        project = svc.create_project(actor, CreateProject(name="Project " + uuid4().hex)).id
    return svc.create(actor, project, CreateArtifact(name=name))


def run_worker(svc):
    return ExecutionWorker(PipelineService(svc.sessions, svc.authorizer, svc.settings, svc.store))


def png():
    file = io.BytesIO()
    Image.new("RGB", (30, 20), "red").save(file, format="PNG")
    return file.getvalue()


@pytest.mark.parametrize(
    "inputs",
    [
        {"text": 4},
        {"text": ["x"]},
        {"text": "x" * 9000},
        {"text": "x", "extra": True},
        {"left": True, "right": 1},
    ],
)
def test_strict_function_types(inputs):
    with pytest.raises(ValueError):
        execute({"specification": definition().model_dump(mode="json"), "inputs": inputs})


@pytest.mark.parametrize(
    "injection", ["os.system", "python", "identity.v2", "eval", "../../tmp/code"]
)
def test_implementation_injection(injection):
    data = definition().model_dump(mode="json") | {"implementation": injection}
    with pytest.raises(ValidationError):
        FunctionDefinition.model_validate(data)


def test_no_executable_schema_configuration_and_output_overflow():
    for change in [
        {"configuration": {"code": "import os"}},
        {"code": "print(1)"},
        {"input_schema": {"text": {"type": "object"}}},
        {"idempotent": False},
    ]:
        with pytest.raises(ValidationError):
            FunctionDefinition.model_validate(definition().model_dump(mode="json") | change)
    with pytest.raises(ValueError):
        execute(
            {
                "specification": definition("number.add.v1").model_dump(mode="json"),
                "inputs": {"left": 2**53 - 1, "right": 2**53 - 1},
            }
        )
    with pytest.raises(ValueError):
        typed({"x": float("nan")}, {"x": ValueType(type="number")}, 100)


@pytest.mark.parametrize(
    "trigger",
    [
        {"kind": "cron"},
        {"kind": "interval", "interval_seconds": 1},
        {"kind": "manual", "hour": 1},
        {"kind": "daily", "hour": 0, "minute": 0, "timezone": "America/New_York"},
        {"kind": "action.committed"},
        {"kind": "manual", "expression": "eval(x)"},
    ],
)
def test_trigger_allowlist_and_bounds(trigger):
    with pytest.raises(ValidationError):
        Trigger.model_validate(trigger)


def test_utc_calendar_dst_and_clock_semantics():
    trigger = Trigger(kind="daily", hour=2, minute=30)
    for day in [datetime(2026, 3, 8, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC)]:
        result = next_instant(trigger, day)
        assert result == day.replace(hour=2, minute=30)
        assert next_instant(trigger, result) == result + timedelta(days=1)


def test_real_function_execution_result_idempotency_and_immutability(world, store):
    svc, p = service(world, store), world.actor
    fn = resource(svc, p)
    published = svc.publish_function(p, fn.id, definition("text.normalize.v1"))
    invocation = Invoke(
        definition_id=published.id, inputs={"text": " HELLO  World "}, idempotency_key="one"
    )
    job = svc.invoke(p, fn.id, invocation)
    assert job.state == "QUEUED"
    assert svc.invoke(p, fn.id, invocation).id == job.id
    with pytest.raises(ApplicationError):
        svc.invoke(p, fn.id, invocation.model_copy(update={"inputs": {"text": "different"}}))
    worker = run_worker(svc)
    assert worker.run_one() == job.id
    assert svc.status(p, job.id).state == "SUCCEEDED"
    assert svc.result(p, job.id).values == {"result": "hello world"}
    assert svc.provenance(p, job.id)["definition_id"] == str(published.id)
    assert svc.history(p, fn.id, 50, 0)[0].id == job.id
    for model, values in [
        (GovernedDefinition, {"specification": {}}),
        (FunctionResult, {"values": {}}),
    ]:
        with pytest.raises(IntegrityError), world.sessions.begin() as s:
            s.execute(update(model).values(**values))
    with pytest.raises(IntegrityError), world.sessions.begin() as s:
        s.execute(delete(FunctionResult))


def test_worker_lease_recovery_cancel_stale_fence_and_unpublished_result(world, store):
    svc, p = service(world, store), world.actor
    fn = resource(svc, p)
    version = svc.publish_function(p, fn.id, definition())
    job = svc.invoke(
        p, fn.id, Invoke(definition_id=version.id, inputs={"text": "x"}, idempotency_key="k")
    )
    worker = run_worker(svc)
    tenant, key, token = worker.claim()
    assert key == job.id
    with world.sessions.begin() as s:
        row = s.get(ExecutionJob, (tenant, key))
        row.lease_until = clock(s) - timedelta(seconds=1)
    new_claim = worker.claim()
    assert new_claim[1] == key and new_claim[2] != token
    with pytest.raises(ApplicationError), world.sessions.begin() as s:
        worker.fenced(s, tenant, key, token)
    svc.change(p, key)
    worker.fail(*new_claim, "cancelled", False)
    assert svc.status(p, key).state == "CANCELLED"
    with pytest.raises(ApplicationError):
        svc.result(p, key)


def test_media_real_preview_snapshot_source_and_immutable_membership(world, store):
    svc, p = service(world, store, MediaService), world.actor
    media = resource(svc, p)
    artifacts = svc.artifacts()
    source = resource(artifacts, p, "Image", media.project_id)
    version = commit(artifacts, p, source.id, png())
    body = AttachMedia(
        artifact_id=source.id, artifact_version_id=version.id, media_type="image/png"
    )
    item = svc.attach(p, media.id, body)
    assert svc.attach(p, media.id, body).id == item.id
    assert item.metadata["width"] == 30 and item.validation_status == "VALID"
    first = svc.publish_snapshot(p, media.id, Snapshot(items=[item.id]))
    second = svc.publish_snapshot(p, media.id, Snapshot(items=[]))
    assert len(svc.items(p, media.id, 50, 0, first.id)) == 1
    assert svc.items(p, media.id, 50, 0, second.id) == []
    for preview in [False, True]:
        file, size = svc.content(p, media.id, item.id, preview)
        try:
            data = file.read()
            assert size == len(data)
            if preview:
                assert Image.open(io.BytesIO(data)).format == "JPEG"
            else:
                assert data == png()
        finally:
            file.close()
    with pytest.raises(IntegrityError), world.sessions.begin() as s:
        s.execute(update(MediaItem).values(filename="renamed"))
    with pytest.raises(IntegrityError), world.sessions.begin() as s:
        s.add(
            MediaMembership(
                tenant_id=p.tenant_id, set_id=media.id, version_id=second.id, item_id=item.id
            )
        )
    with pytest.raises(ValidationError):
        Snapshot(items=[item.id, item.id])
    with pytest.raises(ApplicationError):
        svc.publish_snapshot(p, media.id, Snapshot(items=[uuid4()]))
    with pytest.raises(ApplicationError):
        svc.attach(p, media.id, body.model_copy(update={"media_type": "image/jpeg"}))


@pytest.mark.parametrize(
    "media_type,data",
    [
        ("image/png", b"not PNG"),
        ("application/pdf", b"%PDF-1.7\ncorrupt"),
        ("audio/wav", b"RIFF0000WAVEcorrupt"),
        ("video/mp4", b"\0\0\0\x10ftypisomcorrupt"),
    ],
)
def test_corrupt_media_safe_failure(tmp_path, media_type, data):
    from ontology_platform.functions.contracts import GSettings

    (tmp_path / "source").write_bytes(data)
    result = isolated(
        "media",
        {"media_type": media_type, "media_limits": GSettings().model_dump()},
        tmp_path,
        ExecutionSettings(wall_seconds=10),
    )
    assert result["error"] == "invalid_data_or_plan"
    assert "corrupt" not in json.dumps(result)


def test_wav_pdf_video_metadata_and_image_pixel_budget(tmp_path):
    import av
    from ontology_platform.functions.contracts import GSettings
    from ontology_platform.media.parser import extract
    from pypdf import PdfWriter

    source = tmp_path / "source"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 8000)
    request = {"media_type": "audio/wav", "media_limits": GSettings().model_dump()}
    assert extract(request, tmp_path)["metadata"]["duration"] == 1
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with source.open("wb") as handle:
        writer.write(handle)
    assert extract(request | {"media_type": "application/pdf"}, tmp_path)["metadata"]["pages"] == 1
    with av.open(str(source), mode="w", format="mp4") as container:
        stream = container.add_stream("libx264", rate=24)
        stream.width, stream.height, stream.pix_fmt = 32, 32, "yuv420p"
        for _ in range(24):
            frame = av.VideoFrame.from_image(Image.new("RGB", (32, 32), "blue"))
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    result = extract(request | {"media_type": "video/mp4"}, tmp_path)
    assert result["metadata"]["codec"] == "h264" and result["preview"]["size"] > 0
    source.write_bytes(png())
    with pytest.raises((ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning)):
        extract(
            {"media_type": "image/png", "media_limits": GSettings(pixels=10).model_dump()}, tmp_path
        )


def automation(svc, p, fn, target, trigger):
    row = resource(svc, p, "Automation", fn.project_id)
    spec = AutomationDefinition(
        trigger=trigger,
        function_id=fn.id,
        function_definition_id=target.id,
        inputs={"text": "scheduled"},
    )
    version = svc.publish_automation(p, row.id, spec)
    svc.enable(p, row.id, Enable(definition_id=version.id, enabled=True))
    return row, version


def test_manual_automation_duplicate_disable_and_execution(world, store):
    fn_svc, p = service(world, store), world.actor
    fn = resource(fn_svc, p)
    target = fn_svc.publish_function(p, fn.id, definition())
    svc = service(world, store, AutomationService)
    row, version = automation(svc, p, fn, target, Trigger(kind="manual"))
    first = svc.manual(p, row.id, "x" * 200)
    assert svc.manual(p, row.id, "x" * 200).id == first.id
    worker = run_worker(svc)
    worker.run_one()
    assert fn_svc.result(p, first.job_id).values == {"text": "scheduled"}
    second = svc.manual(p, row.id, "twice")
    svc.enable(p, row.id, Enable(definition_id=version.id, enabled=False))
    worker.run_one()
    assert fn_svc.status(p, second.job_id).state == "FAILED"
    with pytest.raises(ApplicationError):
        svc.manual(p, row.id, "disabled")
    assert len(svc.history_receipts(p, row.id, 50, 0)) == 2


def test_durable_interval_restart_multiple_dispatchers_coalesce(world, store):
    fn_svc, p = service(world, store), world.actor
    fn = resource(fn_svc, p)
    target = fn_svc.publish_function(p, fn.id, definition())
    svc = service(world, store, AutomationService)
    row, version = automation(svc, p, fn, target, Trigger(kind="interval", interval_seconds=60))
    with world.sessions.begin() as s:
        state = s.get(AutomationState, (p.tenant_id, row.id))
        due = clock(s) - timedelta(days=1)
        state.next_run_at = due

    def tick(_):
        return service(world, store, AutomationService).tick()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(tick, range(2))) == 1
    history = svc.history_receipts(p, row.id, 50, 0)
    assert len(history) == 1 and history[0].trigger_at == due
    assert svc.schedule(p, row.id).next_run_at > datetime.now(UTC)
    assert tick(0) == 0
    run_worker(fn_svc).run_one()
    assert fn_svc.result(p, history[0].job_id).values == {"text": "scheduled"}


def test_g_migration_upgrade_preserves_previous_data_and_drift(historical_database):
    engine, sessions, _ = historical_database
    migrate(engine, "0022_materialization")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE phase17_sentinel (value TEXT)"))
        c.execute(text("INSERT INTO phase17_sentinel VALUES ('preserved')"))
    migrate(engine)
    with engine.begin() as c:
        assert c.scalar(text("SELECT value FROM phase17_sentinel")) == "preserved"
        c.execute(text("DROP TABLE phase17_sentinel"))
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "0026_pipeline_dag"
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["connection"] = c
        command.check(config)


def test_private_media_shared_set_requires_source_and_revocation(security, store):
    w, auth, administration, owner, reader, _ = security
    grant_projects(administration, owner, reader)
    svc = service(w, store, MediaService, auth)
    media = resource(svc, owner, "Governed media")
    artifacts = svc.artifacts()
    source = resource(artifacts, owner, "Private image")
    version = commit(artifacts, owner, source.id, png())
    item = svc.attach(
        owner,
        media.id,
        AttachMedia(artifact_id=source.id, artifact_version_id=version.id, media_type="image/png"),
    )
    snapshot = svc.publish_snapshot(owner, media.id, Snapshot(items=[item.id]))
    consumer = svc.create_project(owner, CreateProject(name="Consumer"))
    svc.member(
        owner,
        consumer.id,
        MemberChange(
            principal_id=reader.principal_id, role="viewer", expected_revision=consumer.revision
        ),
    )
    svc.share(
        owner,
        media.id,
        ShareChange(
            project_id=consumer.id,
            enabled=True,
            expected_revision=svc.get_resource(owner, media.id).revision,
        ),
    )
    assert svc.items(reader, media.id, 50, 0) == []
    assert svc.published_definitions(reader, media.id)[0].specification == {"items": []}
    with pytest.raises(ApplicationError):
        svc.content(reader, media.id, item.id, True)
    svc.share(
        owner,
        source.id,
        ShareChange(
            project_id=consumer.id,
            enabled=True,
            expected_revision=svc.get_resource(owner, source.id).revision,
        ),
    )
    assert svc.items(reader, media.id, 50, 0, snapshot.id)[0].id == item.id
    file, size = svc.content(reader, media.id, item.id, True)
    assert size > 0
    file.close()
    svc.share(
        owner,
        source.id,
        ShareChange(
            project_id=consumer.id,
            enabled=False,
            expected_revision=svc.get_resource(owner, source.id).revision,
        ),
    )
    assert svc.items(reader, media.id, 50, 0, snapshot.id) == []
    with pytest.raises(ApplicationError):
        svc.content(reader, media.id, item.id, False)
    # Cross-tenant references fail before touching storage, including known valid IDs.
    alien = reader.model_copy(update={"tenant_id": uuid4()})
    with pytest.raises(ApplicationError):
        svc.attach(
            alien,
            media.id,
            AttachMedia(
                artifact_id=source.id, artifact_version_id=version.id, media_type="image/png"
            ),
        )


def test_function_automation_current_owner_revocation_before_worker_and_tick(security, store):
    w, auth, administration, owner, reader, _ = security
    grant_projects(administration, owner, reader)
    fn_svc = service(w, store, FunctionService, auth)
    fn = resource(fn_svc, owner)
    project = fn_svc.get_project(owner, fn.project_id)
    project = fn_svc.member(
        owner,
        fn.project_id,
        MemberChange(
            principal_id=reader.principal_id, role="editor", expected_revision=project.revision
        ),
    )
    target = fn_svc.publish_function(reader, fn.id, definition())
    svc = service(w, store, AutomationService, auth)
    row, version = automation(
        svc, reader, fn, target, Trigger(kind="interval", interval_seconds=60)
    )
    direct = fn_svc.invoke(
        reader,
        fn.id,
        Invoke(
            definition_id=target.id, inputs={"text": "no bypass"}, idempotency_key="before-revoke"
        ),
    )
    fn_svc.member(
        owner,
        fn.project_id,
        MemberChange(
            principal_id=reader.principal_id, role=None, expected_revision=project.revision
        ),
    )
    with w.sessions.begin() as s:
        state = s.get(AutomationState, (owner.tenant_id, row.id))
        state.next_run_at = clock(s) - timedelta(seconds=1)
    assert svc.tick() == 0
    with w.sessions() as s:
        state = s.get(AutomationState, (owner.tenant_id, row.id))
        assert not state.enabled and state.last_error == "authorization_or_contract"
    run_worker(fn_svc).run_one()
    assert fn_svc.status(owner, direct.id).state == "FAILED"
    with pytest.raises(ApplicationError):
        fn_svc.result(owner, direct.id)
    with pytest.raises(ApplicationError):
        fn_svc.invoke(
            reader,
            fn.id,
            Invoke(
                definition_id=target.id,
                inputs={"text": "no bypass"},
                idempotency_key="after-revoke",
            ),
        )


def test_media_quota_corruption_and_pending_membership(world, store, monkeypatch):
    svc, p = service(world, store, MediaService), world.actor
    media = resource(svc, p)
    source = resource(svc.artifacts(), p)
    from test_artifacts import initiate

    pending = initiate(svc.artifacts(), p, source.id, png())
    with pytest.raises(ApplicationError):
        svc.attach(
            p,
            media.id,
            AttachMedia(
                artifact_id=source.id, artifact_version_id=pending.id, media_type="image/png"
            ),
        )
    version = commit(svc.artifacts(), p, source.id, png())
    monkeypatch.setenv("FOUNDRY_G_MEDIA_BYTES", "1")
    with pytest.raises(ApplicationError) as exc:
        svc.attach(
            p,
            media.id,
            AttachMedia(
                artifact_id=source.id, artifact_version_id=version.id, media_type="image/png"
            ),
        )
    assert exc.value.code == "media_capacity"


def test_function_budget_retry_exhaustion_fencing_and_cancel_queued(world, store, monkeypatch):
    svc, p = service(world, store), world.actor
    fn = resource(svc, p)
    version = svc.publish_function(p, fn.id, definition())
    job = svc.invoke(
        p, fn.id, Invoke(definition_id=version.id, inputs={"text": "x"}, idempotency_key="budget")
    )
    monkeypatch.setenv("FOUNDRY_G_FUNCTION_JOBS", "1")
    other = svc.invoke(
        p, fn.id, Invoke(definition_id=version.id, inputs={"text": "x"}, idempotency_key="other")
    )
    worker = run_worker(svc)
    claim = worker.claim()
    assert worker.claim() is None
    # No result can be inserted without a live RUNNING fence, even with a guessed definition.
    with pytest.raises(IntegrityError), world.sessions.begin() as s:
        s.add(
            FunctionResult(
                tenant_id=p.tenant_id, job_id=job.id, definition_id=version.id, values={"text": "x"}
            )
        )
    worker.fail(*claim, "execution_limit", False)
    assert svc.status(p, job.id).state == "FAILED"
    svc.change(p, other.id)
    assert svc.status(p, other.id).state == "CANCELLED"
    svc.change(p, job.id, retry=True)
    for attempt in range(2, ExecutionSettings().attempts + 1):
        claim = worker.claim()
        assert svc.status(p, job.id).attempts == attempt
        worker.fail(*claim, "infrastructure", False)
        if attempt < ExecutionSettings().attempts:
            svc.change(p, job.id, retry=True)
    with pytest.raises(ApplicationError):
        svc.change(p, job.id, retry=True)


def test_actual_api_contracts_and_binary_access(world, store):
    from fastapi.testclient import TestClient
    from ontology_platform.main import create_app

    app = create_app(world.settings)
    app.state.sessions, app.state.authorizer = world.sessions, world.registry.authorizer
    app.state.artifact_store, app.state.artifact_settings = store, store.settings
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "API"}).json()
        function = client.post(
            f"/api/v1/projects/{project['id']}/functions", json={"name": "Normalize"}
        )
        assert function.status_code == 201
        key = function.json()["id"]
        version = client.post(
            f"/api/v1/functions/{key}/definitions", json=definition().model_dump(mode="json")
        )
        assert version.status_code == 201
        body = {
            "definition_id": version.json()["id"],
            "inputs": {"text": "hello"},
            "idempotency_key": "api",
        }
        response = client.post(f"/api/v1/functions/{key}/runs", json=body)
        assert response.status_code == 202 and response.json()["state"] == "QUEUED"
        assert (
            client.post(
                f"/api/v1/functions/{key}/runs", json=body | {"inputs": {"text": 2}}
            ).status_code
            == 422
        )
        assert client.post(f"/api/v1/functions/{key}/runs", content=b"x" * 65537).status_code == 413
        run_worker(service(world, store)).run_one()
        job = response.json()["id"]
        assert client.get(f"/api/v1/function-runs/{job}/result").json()["values"] == {
            "text": "hello"
        }
        assert client.get(f"/api/v1/functions/{key}/definitions?limit=101").status_code == 422


def test_existing_action_outbox_dispatch_is_durable_deduplicated_and_nonrecursive(
    action_world, store
):
    from ontology_platform.projects.contracts import CreateResource
    from test_actions import execute as execute_action

    w, p = action_world, action_world.actor
    fn_svc = service(w, store)
    fn = resource(fn_svc, p)
    target = fn_svc.publish_function(p, fn.id, definition())
    svc = service(w, store, AutomationService)
    source = svc.create_resource(
        p,
        fn.project_id,
        CreateResource(
            resource_type="ONTOLOGY_VERSION",
            ontology_id=w.definition.id,
            schema_version=w.definition.version,
            entity_id=w.definition.version,
            name="Event source",
        ),
    )
    row, _ = automation(
        svc, p, fn, target, Trigger(kind="action.committed", ontology_resource_id=source.id)
    )
    execute_action(w, key="event-one")
    assert svc.tick() == 1
    assert svc.tick() == 0
    receipt = svc.history_receipts(p, row.id, 50, 0)[0]
    assert receipt.trigger_kind == "action.committed"
    run_worker(fn_svc).run_one()
    assert fn_svc.result(p, receipt.job_id).values == {"text": "scheduled"}
    assert svc.tick() == 0  # Pure functions cannot emit another action event or recurse.
    with w.sessions.begin() as s:
        # Recovery does not consume the webhook delivery status/cursor.
        from ontology_platform.db.models import OutboxEvent

        assert s.scalar(select(OutboxEvent)).status == "PENDING"


def test_built_sdk_consumer_real_governed_media_functions_automations(world, store):
    from fastapi.testclient import TestClient
    from ontology_platform.main import create_app
    from test_platform_sdk import exercise

    svc, p = service(world, store), world.actor
    project = svc.create_project(p, CreateProject(name="SDK processing project"))
    from ontology_platform.artifacts.service import ArtifactService

    artifacts = service(world, store, ArtifactService)
    artifact = resource(artifacts, p, "SDK source", project.id)
    version = commit(artifacts, p, artifact.id, png())
    app = create_app(world.settings)
    app.state.sessions, app.state.authorizer = world.sessions, world.registry.authorizer
    app.state.artifact_store, app.state.artifact_settings = store, store.settings
    with TestClient(app) as client:
        exercise(
            {
                "scenario": "governed-processing",
                "tenant": str(p.tenant_id),
                "project": str(project.id),
                "artifact": str(artifact.id),
                "version": str(version.id),
                "checksum": version.checksum,
            },
            {"admin": client},
            run_worker(svc),
        )


def stalled_media_child(operation, request, directory, limits):
    """Test-only real process to exercise deterministic parser watchdog failure."""
    import time

    time.sleep(10)


def test_media_parser_timeout_does_not_publish(world, store, monkeypatch):
    import ontology_platform.execution.isolation as isolation

    svc, p = service(world, store, MediaService), world.actor
    media = resource(svc, p)
    from ontology_platform.artifacts.service import ArtifactService

    artifacts = service(world, store, ArtifactService)
    source = resource(artifacts, p)
    version = commit(artifacts, p, source.id, png())
    monkeypatch.setenv("FOUNDRY_G_PARSE_SECONDS", "1")
    monkeypatch.setattr(isolation, "child", stalled_media_child)
    with pytest.raises(ApplicationError) as exc:
        svc.attach(
            p,
            media.id,
            AttachMedia(
                artifact_id=source.id, artifact_version_id=version.id, media_type="image/png"
            ),
        )
    assert exc.value.code == "invalid_media"
    assert svc.items(p, media.id, 50, 0) == []


def test_disabled_then_reenabled_activation_fences_old_jobs(world, store):
    svc, p = service(world, store, AutomationService), world.actor
    functions = svc.functions()
    fn = resource(functions, p)
    target = functions.publish_function(p, fn.id, definition())
    row, version = automation(svc, p, fn, target, Trigger(kind="manual"))
    old = svc.manual(p, row.id, "old")
    svc.enable(p, row.id, Enable(definition_id=version.id, enabled=False))
    svc.enable(p, row.id, Enable(definition_id=version.id, enabled=True))
    fresh = svc.manual(p, row.id, "new")
    worker = run_worker(functions)
    worker.run_one()
    assert functions.status(p, old.job_id).state == "FAILED"
    worker.run_one()
    assert functions.status(p, fresh.job_id).state == "SUCCEEDED"


def test_daily_schedule_and_dispatch_rate_are_database_durable(world, store, monkeypatch):
    svc, p = service(world, store, AutomationService), world.actor
    functions = svc.functions()
    fn = resource(functions, p)
    target = functions.publish_function(p, fn.id, definition())
    row, _ = automation(svc, p, fn, target, Trigger(kind="daily", hour=3, minute=30))
    with world.sessions.begin() as s:
        state = s.get(AutomationState, (p.tenant_id, row.id))
        state.next_run_at = clock(s) - timedelta(days=2)
    assert svc.tick() == 1
    next_run = svc.schedule(p, row.id).next_run_at
    assert next_run.hour == 3 and next_run.minute == 30 and next_run > datetime.now(UTC)
    monkeypatch.setenv("FOUNDRY_G_DISPATCH_PER_MINUTE", "1")
    with world.sessions.begin() as s:
        state = s.get(AutomationState, (p.tenant_id, row.id))
        state.next_run_at = clock(s) - timedelta(seconds=1)
    assert svc.tick() == 0
    assert svc.schedule(p, row.id).last_error == "capacity"
    assert len(svc.history_receipts(p, row.id, 50, 0)) == 1


def test_large_media_streaming_memory_and_independent_dataset_limit(
    world, store, tmp_path, monkeypatch
):
    import hashlib

    from ontology_platform.artifacts.contracts import InitiateUpload
    from ontology_platform.artifacts.service import ArtifactService

    size = 64 * 1024**2
    path = tmp_path / "large.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(48000)
        remaining = size - 44
        block = b"\0" * (1024**2)
        while remaining:
            count = min(remaining, len(block))
            audio.writeframesraw(block[:count])
            remaining -= count
    assert path.stat().st_size == size
    with path.open("rb") as source:
        checksum = hashlib.file_digest(source, "sha256").hexdigest()
    monkeypatch.setenv("FOUNDRY_G_MEDIA_BYTES", str(size))
    svc, p = service(world, store, MediaService), world.actor
    media = resource(svc, p)
    artifacts = service(world, store, ArtifactService)
    artifact = resource(artifacts, p)
    version = artifacts.initiate(
        p, artifact.id, InitiateUpload(filename="large.wav", size=size, checksum=checksum)
    )
    with path.open("rb") as source:
        artifacts.upload(p, artifact.id, version.id, source, size, checksum)
    artifacts.finalize(p, artifact.id, version.id)
    item = svc.attach(
        p,
        media.id,
        AttachMedia(
            artifact_id=artifact.id, artifact_version_id=version.id, media_type="audio/wav"
        ),
    )
    assert item.size == size and item.checksum == checksum
    assert item.metadata["processing_metrics"]["peak_memory_bytes"] < 512 * 1024**2
    assert ExecutionSettings().source_bytes == 1024**3
    # Exercise actual middleware without a buffering HTTP test transport.
    import asyncio

    from ontology_platform.main import create_app

    app = create_app(world.settings)
    app.state.sessions, app.state.authorizer = world.sessions, world.registry.authorizer
    app.state.artifact_store, app.state.artifact_settings = store, store.settings
    measured = {"size": 0, "chunk": 0, "status": None}
    received = hashlib.sha256()

    async def transfer():
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            if message["type"] == "http.response.start":
                measured["status"] = message["status"]
                assert (b"cache-control", b"no-store") in message["headers"]
            if message["type"] == "http.response.body":
                chunk = message.get("body", b"")
                measured["size"] += len(chunk)
                measured["chunk"] = max(measured["chunk"], len(chunk))
                received.update(chunk)

        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.4"},
                "method": "GET",
                "path": f"/api/v1/media-sets/{media.id}/items/{item.id}/content",
                "root_path": "",
                "query_string": b"",
                "headers": [],
                "scheme": "http",
                "server": ("testserver", 80),
                "client": ("127.0.0.1", 12345),
                "http_version": "1.1",
            },
            receive,
            send,
        )

    asyncio.run(transfer())
    assert measured["status"] == 200
    assert measured["size"] == size and received.hexdigest() == checksum
    assert measured["chunk"] <= 1024**2
