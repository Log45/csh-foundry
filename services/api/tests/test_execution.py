"""Phase 14 bounded validation, portable plans and real durable publication."""

import csv
import hashlib
from datetime import timedelta

import polars as pl
import pytest
from ontology_platform.artifacts.contracts import CreateArtifact
from ontology_platform.datasets.parser import InvalidDataset
from ontology_platform.datasets.streaming import validate_path
from ontology_platform.db.models import ExecutionJob, PipelineDefinition
from ontology_platform.db.session import clock
from ontology_platform.execution.config import ExecutionSettings
from ontology_platform.execution.isolation import isolated
from ontology_platform.execution.worker import ExecutionWorker
from ontology_platform.pipelines.contracts import Definition, StartRun
from ontology_platform.pipelines.engine import plan
from ontology_platform.pipelines.service import PipelineService
from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from test_artifacts import store  # noqa: F401
from test_datasets import commit, dataset, initiate, make_service
from test_phase1 import database, historical_database, world  # noqa: F401
from test_security_platform import security  # noqa: F401


def spec(steps=None, inputs=None):
    return Definition.model_validate(
        {"inputs": inputs or [{"name": "source"}], "steps": steps or []}
    )


@pytest.mark.parametrize(
    "format,data",
    [
        ("csv", b"a,b\n1,x\n2,\n"),
        ("json", b'[{"a":1,"b":"x"},{"a":2,"b":null}]'),
        ("ndjson", b'{"a":1,"b":"x"}\n{"a":2,"b":null}'),
    ],
)
def test_streaming_matches_preview(tmp_path, format, data):
    path = tmp_path / "source"
    path.write_bytes(data)
    result = validate_path(path, format, ExecutionSettings())
    assert result["row_count"] == 2
    assert result["preview"] == [[1, "x"], [2, None]]
    assert result["schema"][1]["nullable"]


@pytest.mark.parametrize(
    "format,data",
    [
        ("csv", b"a,a\n1,2"),
        ("csv", b"a\n1,2"),
        ("csv", b'a\n"unclosed'),
        ("json", b'[{"a":1,"a":2}]'),
        ("json", b'[{"a":1},{"b":2}]'),
        ("json", b'[{"a":1},{"a":"x"}]'),
        ("json", b'[{"a":1},]'),
        ("json", b'[{"a":1}] garbage'),
        ("json", b'[{"a":NaN}]'),
        ("ndjson", b'{"a":1}\n{"a":2,"a":3}'),
    ],
)
def test_streaming_rejects_late_errors(tmp_path, format, data):
    path = tmp_path / "source"
    path.write_bytes(data)
    with pytest.raises((ValueError, csv.Error, pl.exceptions.PolarsError)):
        validate_path(path, format, ExecutionSettings())


def test_streaming_cross_batch_schema_and_limits(tmp_path):
    path = tmp_path / "source"
    path.write_text("a\n" + "1\n" * 8192 + "text\n")
    result = validate_path(path, "csv", ExecutionSettings())
    assert result["schema"][0]["logical_type"] == "String"
    assert result["preview"][0] == ["1"]
    for limits in [
        ExecutionSettings(rows=8192),
        ExecutionSettings(source_bytes=10),
        ExecutionSettings(decoded_bytes=10),
    ]:
        with pytest.raises(InvalidDataset):
            validate_path(path, "csv", limits)


@pytest.mark.parametrize(
    "steps,expected",
    [
        ([{"op": "select", "columns": ["a"]}], {"a": [1, 2, 2]}),
        (
            [{"op": "rename", "mapping": {"a": "id"}}, {"op": "drop", "columns": ["b"]}],
            {"id": [1, 2, 2]},
        ),
        (
            [{"op": "cast", "mapping": {"a": "String"}}, {"op": "select", "columns": ["a"]}],
            {"a": ["1", "2", "2"]},
        ),
        (
            [
                {
                    "op": "filter",
                    "expression": {
                        "op": "gt",
                        "args": [{"op": "column", "column": "a"}, {"op": "literal", "value": 1}],
                    },
                },
                {"op": "select", "columns": ["a"]},
            ],
            {"a": [2, 2]},
        ),
        ([{"op": "fill_null", "name": "b", "value": 0}], {"a": [1, 2, 2], "b": [0, 4, 4]}),
        ([{"op": "deduplicate", "columns": ["a"]}], {"a": [1, 2], "b": [None, 4]}),
        (
            [{"op": "sort", "columns": ["a"], "descending": True}],
            {"a": [2, 2, 1], "b": [4, 4, None]},
        ),
        (
            [
                {
                    "op": "aggregate",
                    "columns": ["a"],
                    "aggregates": [{"column": "b", "function": "sum", "alias": "total"}],
                }
            ],
            {"a": [1, 2], "total": [0, 8]},
        ),
    ],
)
def test_portable_operations(steps, expected):
    frame = pl.DataFrame({"a": [1, 2, 2], "b": [None, 4, 4]}).lazy()
    assert plan(spec(steps), {"source": frame}).collect().to_dict(as_series=False) == expected


def test_derive_join_union_and_reject_collisions():
    a = pl.DataFrame({"id": [1, 2], "a": [3, 4]}).lazy()
    b = pl.DataFrame({"id": [1], "b": [5]}).lazy()
    definition = spec(
        [{"op": "join", "input": "right", "columns": ["id"]}],
        [{"name": "source"}, {"name": "right"}],
    )
    assert plan(definition, {"source": a, "right": b}).collect().to_dict(as_series=False) == {
        "id": [1],
        "a": [3],
        "b": [5],
    }
    definition = spec([{"op": "union", "input": "right"}], [{"name": "source"}, {"name": "right"}])
    assert plan(definition, {"source": a, "right": a}).collect().height == 4
    with pytest.raises(InvalidDataset):
        plan(definition, {"source": a, "right": b})
    definition = spec(
        [
            {
                "op": "derive",
                "name": "c",
                "expression": {
                    "op": "add",
                    "args": [{"op": "column", "column": "a"}, {"op": "literal", "value": 2}],
                },
            }
        ]
    )
    assert plan(definition, {"source": a}).collect()["c"].to_list() == [5, 6]


@pytest.mark.parametrize(
    "body",
    [
        {"inputs": [{"name": "source"}], "steps": [{"op": "python", "code": "import os"}]},
        {
            "inputs": [{"name": "source"}],
            "steps": [{"op": "select", "columns": ["a"], "path": "/etc/passwd"}],
        },
        {
            "inputs": [{"name": "source"}],
            "steps": [{"op": "filter", "expression": {"op": "eval", "value": "1"}}],
        },
    ],
)
def test_no_executable_definitions(body):
    with pytest.raises(ValidationError):
        Definition.model_validate(body)


def test_isolated_validation_and_sanitized_failure(tmp_path):
    path = tmp_path / "source"
    path.write_bytes(b"a\n1\n")
    result = isolated(
        "validation", {"path": str(path), "format": "csv"}, tmp_path, ExecutionSettings()
    )
    assert result["row_count"] == 1
    assert result["metrics"]["peak_memory_bytes"] < ExecutionSettings().memory_bytes
    path.write_bytes(b"a\nprivate,secret")
    result = isolated(
        "validation", {"path": str(path), "format": "csv"}, tmp_path, ExecutionSettings()
    )
    assert "error" in result and "secret" not in str(result)


def pipeline(world, store):  # noqa: F811
    datasets = make_service(world, store)
    resource = dataset(datasets, world.actor)
    version = commit(datasets, world.actor, resource.id)
    output = datasets.create(world.actor, resource.project_id, CreateArtifact(name="Output"))
    service = PipelineService(world.sessions, world.registry.authorizer, store.settings, store)
    pipe = service.create(world.actor, resource.project_id, CreateArtifact(name="Pipeline"))
    definition = service.publish(world.actor, pipe.id, spec([{"op": "select", "columns": ["id"]}]))
    body = StartRun(
        definition_id=definition.id,
        inputs=[{"name": "source", "dataset_id": resource.id, "version_id": version.id}],
        output_dataset_id=output.id,
    )
    return service, datasets, pipe, definition, body


def test_durable_pipeline_publication_and_lineage(world, store):  # noqa: F811
    svc, datasets, pipe, definition, body = pipeline(world, store)
    job = svc.start(world.actor, pipe.id, body)
    worker = ExecutionWorker(svc)
    assert worker.run_one() == job.id
    status = svc.status(world.actor, job.id)
    assert status.state == "SUCCEEDED", status
    output = datasets.dataset_metadata(
        world.actor, body.output_dataset_id, status.output_version_id
    )
    assert output.state == output.artifact_state == "COMMITTED"
    assert datasets.preview(world.actor, body.output_dataset_id, output.id).rows == [[1], [2]]
    assert svc.lineage(world.actor, body.output_dataset_id, output.id)[0]["inputs"][0][
        "version_id"
    ] == str(body.inputs[0].version_id)
    assert worker.run_one() is None
    with world.sessions.begin() as s, pytest.raises(IntegrityError):
        s.execute(
            update(PipelineDefinition)
            .where(PipelineDefinition.id == definition.id)
            .values(sequence=9)
        )


def test_async_validation_and_idempotent_queue(world, store):  # noqa: F811
    svc = make_service(world, store)
    d = dataset(svc, world.actor)
    data = b"a\n1\n2"
    v = initiate(svc, world.actor, d.id, data)
    import io

    svc.upload(
        world.actor, d.id, v.id, io.BytesIO(data), len(data), hashlib.sha256(data).hexdigest()
    )
    first = svc.enqueue_validation(world.actor, d.id, v.id)
    assert svc.enqueue_validation(world.actor, d.id, v.id).id == first.id
    ps = PipelineService(world.sessions, world.registry.authorizer, store.settings, store)
    assert ExecutionWorker(ps).run_one() == first.id
    assert ps.status(world.actor, first.id).state == "SUCCEEDED"
    assert svc.preview(world.actor, d.id, v.id).rows == [[1], [2]]


def test_restart_fencing_cancel_and_retry(world, store):  # noqa: F811
    svc, _, pipe, _, body = pipeline(world, store)
    job = svc.start(world.actor, pipe.id, body)
    worker = ExecutionWorker(svc)
    tenant, key, old = worker.claim()
    assert worker.claim() is None
    with world.sessions.begin() as s:
        row = s.get(ExecutionJob, (tenant, key))
        row.lease_until = clock(s) - timedelta(seconds=1)
    _, _, new = worker.claim()
    assert new != old
    assert not worker.heartbeat(tenant, key, old)
    worker.execute(tenant, key, new)
    assert svc.status(world.actor, job.id).state == "SUCCEEDED"
    cancelled = svc.start(world.actor, pipe.id, body)
    assert svc.change(world.actor, cancelled.id).state == "CANCELLED"
    assert worker.run_one() is None


def test_integer_overflow_rejected_and_null_filter():
    source = pl.DataFrame({"a": [2**63 - 1, None]}).lazy()
    definition = spec(
        [
            {
                "op": "derive",
                "name": "b",
                "expression": {
                    "op": "add",
                    "args": [{"op": "column", "column": "a"}, {"op": "literal", "value": 1}],
                },
            }
        ]
    )
    with pytest.raises(pl.exceptions.PolarsError):
        plan(definition, {"source": source}).collect()
    filtered = spec(
        [
            {
                "op": "filter",
                "expression": {
                    "op": "gt",
                    "args": [{"op": "column", "column": "a"}, {"op": "literal", "value": 0}],
                },
            }
        ]
    )
    assert plan(filtered, {"source": source}).collect().height == 1


def test_resource_intensive_sort_stops_cleanly(tmp_path):
    source = tmp_path / "source.parquet"
    pl.DataFrame({"id": range(2_000_000)}).write_parquet(source, row_group_size=8192)
    request = {
        "specification": spec([{"op": "sort", "columns": ["id"], "descending": True}]).model_dump(
            mode="json"
        ),
        "inputs": [{"name": "source", "path": str(source), "format": "parquet"}],
    }
    result = isolated("pipeline", request, tmp_path, ExecutionSettings(memory_bytes=128 * 1024**2))
    assert result.get("error") == "memory_limit", result


def test_cancelling_running_lease_and_retry_infrastructure(world, store):  # noqa: F811
    svc, _, pipe, _, body = pipeline(world, store)
    job = svc.start(world.actor, pipe.id, body)
    worker = ExecutionWorker(svc)
    tenant, key, token = worker.claim()
    assert svc.change(world.actor, job.id).state == "CANCELLING"
    assert not worker.heartbeat(tenant, key, token)
    worker.fail(tenant, key, token, "cancelled", False)
    assert svc.status(world.actor, job.id).state == "CANCELLED"
    job = svc.start(world.actor, pipe.id, body)
    tenant, key, token = worker.claim()
    worker.fail(tenant, key, token, "infrastructure", True)
    assert svc.status(world.actor, job.id).state == "QUEUED"
    assert worker.run_one() == job.id
    assert svc.status(world.actor, job.id).state == "SUCCEEDED"


def test_validation_permanent_failure_is_terminal(world, store):  # noqa: F811
    import io

    datasets, p = make_service(world, store), world.actor
    d = dataset(datasets, p)
    data = b"a,a\nprivate,secret"
    v = initiate(datasets, p, d.id, data)
    datasets.upload(p, d.id, v.id, io.BytesIO(data), len(data), v.checksum)
    job = datasets.enqueue_validation(p, d.id, v.id)
    svc = PipelineService(world.sessions, world.registry.authorizer, store.settings, store)
    ExecutionWorker(svc).run_one()
    assert svc.status(p, job.id).state == "FAILED"
    assert datasets.dataset_metadata(p, d.id, v.id).state == "FAILED"
    assert "private" not in str(svc.status(p, job.id))


def test_storage_success_before_metadata_recovers_same_output(world, store, monkeypatch):  # noqa: F811
    from ontology_platform.artifacts.storage import Failure, StorageError

    svc, datasets, pipe, _, body = pipeline(world, store)
    run = svc.start(world.actor, pipe.id, body)
    original = store.put
    failed = False

    def interrupted(key, source, size, checksum):
        nonlocal failed
        original(key, source, size, checksum)
        if not failed:
            failed = True
            raise StorageError(Failure.TRANSIENT)

    monkeypatch.setattr(store, "put", interrupted)
    worker = ExecutionWorker(svc)
    assert worker.run_one() == run.id
    first = svc.status(world.actor, run.id)
    assert first.state == "QUEUED" and first.output_version_id is not None
    assert worker.run_one() == run.id
    final = svc.status(world.actor, run.id)
    assert final.state == "SUCCEEDED"
    assert final.output_version_id == first.output_version_id
    assert len(datasets.dataset_versions(world.actor, body.output_dataset_id, 50, 0)) == 1


def test_revoked_input_prevents_execution(world, store):  # noqa: F811
    svc, datasets, pipe, _, body = pipeline(world, store)
    job = svc.start(world.actor, pipe.id, body)
    source = datasets.get_resource(world.actor, body.inputs[0].dataset_id)
    datasets.update_resource(world.actor, source.id, None, source.revision)
    assert ExecutionWorker(svc).run_one() == job.id
    assert svc.status(world.actor, job.id).state == "FAILED"
    assert datasets.dataset_versions(world.actor, body.output_dataset_id, 50, 0) == []


def test_admission_slots_release_on_disconnect(world):  # noqa: F811
    from ontology_platform.artifacts.admission import TransferSlot
    from ontology_platform.errors import ApplicationError

    a = TransferSlot(world.sessions, world.actor.tenant_id, 1, 1)
    b = TransferSlot(world.sessions, world.actor.tenant_id, 1, 1)
    try:
        a.acquire()
        with pytest.raises(ApplicationError, match="capacity"):
            b.acquire()
    finally:
        a.release()
    b.acquire()
    b.release()


def test_private_lineage_filters_input_and_definition(security, store):  # noqa: F811
    from ontology_platform.projects.contracts import CreateProject, MemberChange, ShareChange
    from test_projects import grant_projects

    w, auth, administration, owner, other, _ = security
    grant_projects(administration, owner, other)
    datasets = make_service(w, store, auth)
    resource = dataset(datasets, owner)
    version = commit(datasets, owner, resource.id)
    output = datasets.create(owner, resource.project_id, CreateArtifact(name="Shared output"))
    svc = PipelineService(w.sessions, auth, store.settings, store)
    pipe = svc.create(owner, resource.project_id, CreateArtifact(name="Private pipeline"))
    definition = svc.publish(owner, pipe.id, spec([{"op": "select", "columns": ["id"]}]))
    run = svc.start(
        owner,
        pipe.id,
        StartRun(
            definition_id=definition.id,
            inputs=[{"name": "source", "dataset_id": resource.id, "version_id": version.id}],
            output_dataset_id=output.id,
        ),
    )
    from worker_support import provision_worker

    ExecutionWorker(svc, provision_worker(svc, owner)).run_one()
    done = svc.status(owner, run.id)
    assert done.state == "SUCCEEDED", done
    consumer = svc.create_project(owner, CreateProject(name="Lineage consumer"))
    svc.member(
        owner,
        consumer.id,
        MemberChange(
            principal_id=other.principal_id, role="viewer", expected_revision=consumer.revision
        ),
    )
    svc.share(
        owner,
        output.id,
        ShareChange(project_id=consumer.id, enabled=True, expected_revision=output.revision),
    )
    lineage = svc.lineage(other, output.id, done.output_version_id)
    assert lineage[0]["inputs"] == []
    assert "pipeline_id" not in lineage[0] and "specification" not in lineage[0]
    assert str(resource.id) not in str(lineage) and str(version.id) not in str(lineage)
    assert svc.lineage(owner, output.id, done.output_version_id)[0]["inputs"]
    current_output = svc.get_resource(owner, output.id)
    svc.share(
        owner,
        output.id,
        ShareChange(
            project_id=consumer.id, enabled=False, expected_revision=current_output.revision
        ),
    )
    svc.share(
        owner,
        pipe.id,
        ShareChange(
            project_id=consumer.id,
            enabled=True,
            expected_revision=svc.get_resource(owner, pipe.id).revision,
        ),
    )
    private_output = svc.status(other, run.id)
    assert private_output.output_dataset_id is None and private_output.output_version_id is None
    assert svc.history(other, pipe.id, 50, 0)[0].output_dataset_id is None


def crash_after_claim(url, schema, settings, storage, pipe):
    import os

    from ontology_platform.artifacts.s3 import S3ArtifactStore
    from ontology_platform.security.local import LocalAuthorizer
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(url, connect_args={"options": "-c search_path=" + schema})
    worker = ExecutionWorker(
        PipelineService(
            sessionmaker(engine, expire_on_commit=False),
            LocalAuthorizer(settings),
            storage,
            S3ArtifactStore(storage),
        )
    )
    pipe.send(worker.claim())
    pipe.close()
    os._exit(91)


def test_real_controller_crash_recovers_one_output(world, store):  # noqa: F811
    import multiprocessing

    from sqlalchemy import text

    svc, datasets, pipeline_resource, _, body = pipeline(world, store)
    run = svc.start(world.actor, pipeline_resource.id, body)
    with world.sessions() as session:
        schema = session.scalar(text("SELECT current_schema()"))
    receive, send = multiprocessing.get_context("spawn").Pipe(duplex=False)
    process = multiprocessing.get_context("spawn").Process(
        target=crash_after_claim,
        args=(
            world.settings.database_url.get_secret_value(),
            schema,
            world.settings,
            store.settings,
            send,
        ),
    )
    process.start()
    assert receive.poll(20), "Crashed controller did not persist admission"
    tenant, key, stale = receive.recv()
    process.join(20)
    assert process.exitcode == 91
    receive.close()
    send.close()
    with world.sessions.begin() as session:
        row = session.get(ExecutionJob, (tenant, key))
        row.lease_until = clock(session) - timedelta(seconds=1)
    restarted = ExecutionWorker(svc)
    assert not restarted.heartbeat(tenant, key, stale)
    assert restarted.run_one() == run.id
    done = svc.status(world.actor, run.id)
    assert done.state == "SUCCEEDED" and done.attempts == 2
    assert len(datasets.dataset_versions(world.actor, body.output_dataset_id, 50, 0)) == 1


def test_upgrade_from_phase13_preserves_dataset_snapshot(historical_database, store):  # noqa: F811
    from test_phase1 import make_world, migrate

    engine, _, _ = historical_database
    migrate(engine, "0020_datasets")
    w = make_world(historical_database)
    datasets = make_service(w, store)
    resource = dataset(datasets, w.actor)
    version = commit(datasets, w.actor, resource.id)
    preview = datasets.preview(w.actor, resource.id, version.id)
    migrate(engine)
    assert datasets.get_resource(w.actor, resource.id) == resource
    assert datasets.dataset_metadata(w.actor, resource.id, version.id) == version
    assert datasets.preview(w.actor, resource.id, version.id) == preview
    with datasets.download(w.actor, resource.id, version.id)[0] as source:
        assert source.read() == b"id,value\n1,hello\n2,\n"
    from alembic import command
    from alembic.config import Config
    from test_phase1 import ROOT

    config = Config(str(ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.check(config)


def test_json_key_order_is_not_a_schema_change(tmp_path):
    source = tmp_path / "source"
    source.write_text('{"a":1,"b":"x"}\n' * 8192 + '{"b":"y","a":2}\n')
    result = validate_path(source, "ndjson", ExecutionSettings())
    assert [c["name"] for c in result["schema"]] == ["a", "b"]
    assert result["row_count"] == 8193


def test_memory_failure_does_not_publish_dataset(world, store, monkeypatch):  # noqa: F811
    import io

    datasets, p = make_service(world, store), world.actor
    resource = dataset(datasets, p)
    content = io.BytesIO()
    pl.DataFrame({"id": range(2_000_000)}).write_parquet(content, row_group_size=8192)
    version = commit(datasets, p, resource.id, content.getvalue(), "parquet")
    assert version.state == "COMMITTED"
    output = datasets.create(
        p, resource.project_id, CreateArtifact(name="Resource constrained output")
    )
    svc = PipelineService(world.sessions, world.registry.authorizer, store.settings, store)
    pipe = svc.create(p, resource.project_id, CreateArtifact(name="Resource constrained sort"))
    definition = svc.publish(
        p, pipe.id, spec([{"op": "sort", "columns": ["id"], "descending": True}])
    )
    monkeypatch.setenv("FOUNDRY_EXECUTION_MEMORY_BYTES", str(128 * 1024**2))
    run = svc.start(
        p,
        pipe.id,
        StartRun(
            definition_id=definition.id,
            inputs=[{"name": "source", "dataset_id": resource.id, "version_id": version.id}],
            output_dataset_id=output.id,
        ),
    )
    ExecutionWorker(svc).run_one()
    status = svc.status(p, run.id)
    assert status.state == "FAILED" and status.error == "memory_limit", status
    assert datasets.dataset_versions(p, output.id, 50, 0) == []
    assert datasets.dataset_metadata(p, resource.id, version.id).checksum == version.checksum


def test_end_to_end_deadline_fences_publication(world, store):  # noqa: F811
    svc, datasets, resource, _, body = pipeline(world, store)
    run = svc.start(world.actor, resource.id, body)
    worker = ExecutionWorker(svc)
    tenant, key, token = worker.claim()
    with world.sessions.begin() as session:
        row = session.get(ExecutionJob, (tenant, key))
        row.state = "RUNNING"
        row.started_at = clock(session) - timedelta(seconds=1801)
    assert not worker.heartbeat(tenant, key, token)
    status = svc.status(world.actor, run.id)
    assert status.state == "FAILED" and status.error == "execution_limit"
    assert datasets.dataset_versions(world.actor, body.output_dataset_id, 50, 0) == []


def test_empty_parquet_still_enforces_schema_depth(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    dtype = pa.int64()
    for _ in range(9):
        dtype = pa.list_(dtype)
    schema = pa.schema([("nested", dtype)])
    source = tmp_path / "empty.parquet"
    pq.write_table(schema.empty_table(), source)
    with pytest.raises(InvalidDataset, match="Nesting"):
        validate_path(source, "parquet", ExecutionSettings())


def test_column_references_are_literal_and_preserve_valid_dataset_names():
    frame = pl.DataFrame({"price/unit": [1, 2], "^x$": [3, 4], "x": [9, 9]}).lazy()
    assert plan(
        spec([{"op": "select", "columns": ["^x$", "price/unit"]}]), {"source": frame}
    ).collect().columns == ["^x$", "price/unit"]
    derived = spec(
        [{"op": "derive", "name": "new/value", "expression": {"op": "column", "column": "^x$"}}]
    )
    assert plan(derived, {"source": frame}).collect()["new/value"].to_list() == [3, 4]
    joined = spec(
        [{"op": "join", "columns": ["^x$"], "input": "right"}],
        [{"name": "source"}, {"name": "right"}],
    )
    right = pl.DataFrame({"^x$": [3], "other": [5]}).lazy()
    assert plan(joined, {"source": frame, "right": right}).collect().columns == [
        "price/unit",
        "^x$",
        "x",
        "other",
    ]
    with pytest.raises(InvalidDataset, match="Missing"):
        plan(
            spec(
                [{"op": "derive", "name": "bad", "expression": {"op": "column", "column": "^.*$"}}]
            ),
            {"source": frame},
        )


def test_conditional_output_race_verifies_existing_bytes(world, store, monkeypatch):  # noqa: F811
    from ontology_platform.artifacts.storage import Failure, StorageError

    svc, datasets, resource, _, body = pipeline(world, store)
    run = svc.start(world.actor, resource.id, body)
    original = store.put

    def already_written(key, source, size, checksum):
        original(key, source, size, checksum)
        raise StorageError(Failure.EXISTS)

    monkeypatch.setattr(store, "put", already_written)
    assert ExecutionWorker(svc).run_one() == run.id
    status = svc.status(world.actor, run.id)
    assert status.state == "SUCCEEDED" and status.attempts == 1, status
    assert len(datasets.dataset_versions(world.actor, body.output_dataset_id, 50, 0)) == 1


def test_staged_output_cannot_bypass_run_publication(world, store, monkeypatch):  # noqa: F811
    from ontology_platform.db.models import ArtifactVersion
    from ontology_platform.errors import ApplicationError

    svc, datasets, resource, _, body = pipeline(world, store)
    run = svc.start(world.actor, resource.id, body)
    original = store.put
    checked = False

    def staged(key, source, size, checksum):
        nonlocal checked
        original(key, source, size, checksum)
        if key.artifact == body.output_dataset_id:
            checked = True
            for mutation in [
                lambda: datasets.finalize_dataset(world.actor, key.artifact, key.version),
                lambda: datasets.enqueue_validation(world.actor, key.artifact, key.version),
                lambda: datasets.prepare_upload(world.actor, key.artifact, key.version),
            ]:
                with pytest.raises(ApplicationError) as denied:
                    mutation()
                assert denied.value.status_code == 409
            with world.sessions.begin() as session, pytest.raises(IntegrityError):
                session.execute(
                    update(ArtifactVersion)
                    .where(
                        ArtifactVersion.tenant_id == world.actor.tenant_id,
                        ArtifactVersion.artifact_id == key.artifact,
                        ArtifactVersion.id == key.version,
                    )
                    .values(state="COMMITTED", committed_at=clock(session))
                )

    monkeypatch.setattr(store, "put", staged)
    ExecutionWorker(svc).run_one()
    assert checked
    assert svc.status(world.actor, run.id).state == "SUCCEEDED"


def test_cancelled_staged_output_stays_unpublished(world, store, monkeypatch):  # noqa: F811
    from ontology_platform.errors import ApplicationError

    svc, datasets, resource, _, body = pipeline(world, store)
    run = svc.start(world.actor, resource.id, body)
    original = store.put

    def cancel_after_storage(key, source, size, checksum):
        original(key, source, size, checksum)
        svc.change(world.actor, run.id)
        with pytest.raises(ApplicationError) as denied:
            datasets.finalize_dataset(world.actor, key.artifact, key.version)
        assert denied.value.status_code == 409

    monkeypatch.setattr(store, "put", cancel_after_storage)
    ExecutionWorker(svc).run_one()
    status = svc.status(world.actor, run.id)
    assert status.state == "CANCELLED", status
    with pytest.raises(ApplicationError):
        datasets.preview(world.actor, body.output_dataset_id, status.output_version_id)
