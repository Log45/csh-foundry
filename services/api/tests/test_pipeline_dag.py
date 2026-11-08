"""General DAG semantics and real atomic multi-output publication."""
# ruff: noqa: F811 -- pytest fixtures imported from shared integration modules

from uuid import uuid4

import polars as pl
import pytest
from ontology_platform.artifacts.contracts import CreateArtifact
from ontology_platform.db.models import DAGPreparedOutput, DAGRun, ExecutionJob
from ontology_platform.execution.worker import ExecutionWorker
from ontology_platform.pipelines.contracts import InputVersion, StartRun
from ontology_platform.pipelines.dag import DAGDefinition, semantic_digest, topology
from ontology_platform.pipelines.engine import dag_frames
from ontology_platform.pipelines.service import PipelineService
from pydantic import ValidationError
from sqlalchemy import select
from test_artifacts import store  # noqa: F401, F811
from test_datasets import commit, dataset, make_service
from test_phase1 import database, historical_database, world  # noqa: F401, F811
from test_security_platform import security  # noqa: F401


def specification(source=None, version=None, targets=None):
    targets = targets or [uuid4(), uuid4()]
    return DAGDefinition.model_validate(
        {
            "format_version": 2,
            "inputs": [
                {
                    "name": "source",
                    "dataset_id": str(source or uuid4()),
                    "version_id": str(version or uuid4()),
                }
            ],
            "nodes": [
                {
                    "id": "shared",
                    "inputs": {"input": "source"},
                    "config": {"op": "select", "columns": ["id", "value"]},
                },
                {
                    "id": "left",
                    "inputs": {"input": "shared"},
                    "config": {"op": "select", "columns": ["id"]},
                },
                {
                    "id": "right",
                    "inputs": {"input": "shared"},
                    "config": {"op": "rename", "mapping": {"value": "renamed"}},
                },
                {
                    "id": "joined",
                    "inputs": {"input": "left", "right": "right"},
                    "config": {"op": "join", "input": "right", "columns": ["id"]},
                },
                {
                    "id": "union",
                    "inputs": {"input": "joined", "right": "right"},
                    "config": {"op": "union", "input": "right"},
                },
            ],
            "outputs": [
                {"id": "one", "source": "shared", "dataset_id": str(targets[0])},
                {"id": "two", "source": "union", "dataset_id": str(targets[1])},
            ],
        }
    )


def test_dag_determinism_and_transformed_convergence():
    spec = specification()
    other = spec.model_dump(mode="json")
    other["nodes"].reverse()
    other["outputs"].reverse()
    assert semantic_digest(spec) == semantic_digest(DAGDefinition.model_validate(other))
    assert topology(spec) == ["shared", "left", "right", "joined", "union"]
    frames = dag_frames(spec, {"source": pl.DataFrame({"id": [1, 2], "value": [10, 20]}).lazy()})
    assert frames["union"].collect().to_dict(as_series=False) == {
        "id": [1, 2, 1, 2],
        "renamed": [10, 20, 10, 20],
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "cycle",
        "self",
        "missing",
        "port",
        "duplicate",
        "disconnected",
        "version",
        "executable",
        "fanout",
    ],
)
def test_invalid_dags_fail_closed(mutation):
    body = specification().model_dump(mode="json")
    if mutation == "cycle":
        body["nodes"][0]["inputs"]["input"] = "union"
    elif mutation == "self":
        body["nodes"][0]["inputs"]["input"] = "shared"
    elif mutation == "missing":
        body["nodes"][0]["inputs"]["input"] = "missing"
    elif mutation == "port":
        body["nodes"][0]["inputs"] = {"right": "source"}
    elif mutation == "duplicate":
        body["outputs"][1]["id"] = "one"
    elif mutation == "disconnected":
        body["nodes"].append(
            {
                "id": "unused",
                "inputs": {"input": "source"},
                "config": {"op": "select", "columns": ["id"]},
            }
        )
    elif mutation == "version":
        body["format_version"] = 3
    elif mutation == "executable":
        body["nodes"][0]["config"] = {"op": "python", "code": "print(1)"}
    else:
        body["outputs"] = [
            {"id": f"out{i}", "source": "shared", "dataset_id": str(uuid4())} for i in range(16)
        ]
    with pytest.raises(ValidationError):
        DAGDefinition.model_validate(body)


def setup_run(world, store, new=False):
    datasets = make_service(world, store)
    source = dataset(datasets, world.actor)
    version = commit(datasets, world.actor, source.id, b"id,value\n1,10\n2,20\n")
    targets = [dataset(datasets, world.actor), dataset(datasets, world.actor)]
    pipelines = PipelineService(world.sessions, world.registry.authorizer, store.settings, store)
    pipeline = pipelines.create(world.actor, source.project_id, CreateArtifact(name="DAG"))
    spec = specification(source.id, version.id, [t.id for t in targets])
    if new:
        body = spec.model_dump(mode="json")
        body["outputs"][1].pop("dataset_id")
        body["outputs"][1].update(project_id=str(source.project_id), name="New atomic output")
        spec = DAGDefinition.model_validate(body)
    definition = pipelines.publish(world.actor, pipeline.id, spec)
    run = pipelines.start(
        world.actor,
        pipeline.id,
        StartRun(
            definition_id=definition.id,
            inputs=[InputVersion(name="source", dataset_id=source.id, version_id=version.id)],
        ),
    )
    return pipelines, datasets, run, spec, targets


@pytest.mark.parametrize("new", [False, True])
def test_real_dag_atomic_outputs_and_reuse(world, store, new):
    svc, datasets, run, spec, targets = setup_run(world, store, new)
    worker = ExecutionWorker(svc)
    assert worker.run_one() == run.id
    status = svc.status(world.actor, run.id)
    assert status.state == "SUCCEEDED", status
    assert status.publication_state == "COMMITTED"
    assert len(status.outputs) == 2
    assert len(status.nodes) == 5
    assert all(n.state == "COMPLETED" and n.attempt == 1 for n in status.nodes)
    with world.sessions() as s:
        prepared = list(
            s.scalars(select(DAGPreparedOutput).where(DAGPreparedOutput.job_id == run.id))
        )
        assert all(o.state == "COMMITTED" for o in prepared)
        for output in prepared:
            assert (
                datasets.dataset_metadata(world.actor, output.dataset_id, output.version_id).state
                == "COMMITTED"
            )
        assert s.get(DAGRun, (world.actor.tenant_id, run.id)).commit_id is not None
    assert worker.run_one() is None


def test_atomic_publication_rolls_back_audit_failure(world, store, monkeypatch):
    svc, datasets, run, spec, targets = setup_run(world, store)
    original = svc.audit

    def fail(s, p, event, key, details=None):
        if event == "pipeline_dag_committed":
            raise RuntimeError("test-only commit barrier")
        return original(s, p, event, key, details)

    monkeypatch.setattr(svc, "audit", fail)
    worker = ExecutionWorker(svc)
    worker.run_one()
    assert svc.status(world.actor, run.id).state == "FAILED"
    assert all(datasets.dataset_versions(world.actor, t.id, 50, 0) == [] for t in targets)
    with world.sessions() as s:
        assert s.get(DAGRun, (world.actor.tenant_id, run.id)).commit_id is None


def test_staged_outputs_invisible_before_commit(world, store, monkeypatch):
    svc, datasets, run, spec, targets = setup_run(world, store)
    from ontology_platform.pipelines import dag_worker

    original = dag_worker.commit

    def barrier(worker, p, key, token, spec, metrics):
        assert all(datasets.dataset_versions(p, t.id, 50, 0) == [] for t in targets)
        with world.sessions() as s:
            rows = list(s.scalars(select(DAGPreparedOutput).where(DAGPreparedOutput.job_id == key)))
            assert len(rows) == 2 and all(o.state == "PREPARED" for o in rows)
        return original(worker, p, key, token, spec, metrics)

    monkeypatch.setattr(dag_worker, "commit", barrier)
    ExecutionWorker(svc).run_one()
    assert svc.status(world.actor, run.id).state == "SUCCEEDED"


def test_dag_visual_compile_and_layout_independence():
    from ontology_platform.pipelines.graph import Graph, compile_graph

    spec = specification()
    refs = {"source": "source-node"}
    refs.update({n.id: n.id for n in spec.nodes})
    nodes = [
        {
            "id": "source-node",
            "kind": "dataset_source",
            "config": spec.inputs[0].model_dump(mode="json"),
        }
    ]
    nodes += [
        {"id": n.id, "kind": "transform", "config": n.config.model_dump(mode="json")}
        for n in spec.nodes
    ]
    nodes += [
        {"id": o.id, "kind": "dataset_output", "config": {"dataset_id": str(o.dataset_id)}}
        for o in spec.outputs
    ]
    edges = [
        {"id": f"{n.id}-{port}", "source": refs[source], "target": n.id, "target_port": port}
        for n in spec.nodes
        for port, source in n.inputs.items()
    ]
    edges += [
        {"id": f"{o.id}-edge", "source": refs[o.source], "target": o.id} for o in spec.outputs
    ]
    graph = Graph.model_validate({"format_version": 2, "nodes": nodes, "edges": edges})
    first = compile_graph(graph)
    assert first.valid, first
    assert first.semantic_digest == semantic_digest(spec)
    body = graph.model_dump(mode="json")
    body["nodes"].reverse()
    body["edges"].reverse()
    for node in body["nodes"]:
        node["position"] = {"x": 130, "y": 350}
    assert compile_graph(Graph.model_validate(body)).semantic_digest == first.semantic_digest


def test_dag_recovery_after_all_prepared_and_stale_fencing(world, store, monkeypatch):
    from datetime import timedelta

    from ontology_platform.db.session import clock
    from ontology_platform.errors import ApplicationError
    from ontology_platform.pipelines import dag_worker
    from sqlalchemy import update

    svc, datasets, run, spec, targets = setup_run(world, store)
    worker = ExecutionWorker(svc)
    claim = worker.claim()
    assert claim is not None
    original = dag_worker.commit

    def stop(*args, **kwargs):
        raise RuntimeError("test-only worker interruption")

    monkeypatch.setattr(dag_worker, "commit", stop)
    with pytest.raises(RuntimeError):
        worker.execute(*claim)
    assert all(datasets.dataset_versions(world.actor, t.id, 50, 0) == [] for t in targets)
    with world.sessions.begin() as s:
        s.execute(
            update(ExecutionJob)
            .where(ExecutionJob.id == run.id)
            .values(lease_until=clock(s) - timedelta(seconds=1))
        )
    replacement = worker.claim()
    assert replacement is not None and replacement[2] != claim[2]
    monkeypatch.setattr(dag_worker, "commit", original)
    with pytest.raises(ApplicationError):
        original(worker, world.actor, run.id, claim[2], spec, {})
    worker.execute(*replacement)
    status = svc.status(world.actor, run.id)
    assert status.state == "SUCCEEDED"
    # Recovery reuses every verified completed intermediate; no node executed twice.
    assert all(n.attempt == 1 for n in status.nodes)
    assert all(len(datasets.dataset_versions(world.actor, t.id, 50, 0)) == 1 for t in targets)
    dag_worker.cleanup(worker, world.actor.tenant_id, run.id)


def test_cancel_wins_before_publication(world, store, monkeypatch):
    from ontology_platform.pipelines import dag_worker

    svc, datasets, run, spec, targets = setup_run(world, store)
    original = dag_worker.commit

    def cancel(worker, p, key, token, spec, metrics):
        svc.change(p, key)
        return original(worker, p, key, token, spec, metrics)

    monkeypatch.setattr(dag_worker, "commit", cancel)
    ExecutionWorker(svc).run_one()
    assert svc.status(world.actor, run.id).state == "CANCELLED"
    assert all(datasets.dataset_versions(world.actor, t.id, 50, 0) == [] for t in targets)


def test_lineage_excludes_siblings_and_preserves_ancestors(world, store):
    svc, datasets, run, spec, targets = setup_run(world, store)
    ExecutionWorker(svc).run_one()
    status = svc.status(world.actor, run.id)
    output = next(o for o in status.outputs if o.output_id == "one")
    lineage = svc.lineage(world.actor, output.dataset_id, output.version_id)
    assert len(lineage) == 1
    assert [n["id"] for n in lineage[0]["nodes"]] == ["shared"]
    assert str(targets[1].id) not in str(lineage)


def test_three_outputs_and_formats(world, store):
    svc, datasets, _, spec, targets = setup_run(world, store)
    # Cancel the queued setup run before publishing a different explicit definition.
    with world.sessions() as s:
        queued = s.scalar(select(ExecutionJob).where(ExecutionJob.resource_id.is_not(None)))
        pipeline_id = queued.resource_id
    svc.change(world.actor, queued.id)
    body = spec.model_dump(mode="json")
    body["outputs"][0]["format"] = "csv"
    body["outputs"][1]["format"] = "ndjson"
    third = dataset(datasets, world.actor)
    body["outputs"].append({"id": "third", "source": "left", "dataset_id": str(third.id)})
    spec = DAGDefinition.model_validate(body)
    definition = svc.publish(world.actor, pipeline_id, spec)
    run = svc.start(
        world.actor,
        pipeline_id,
        StartRun(
            definition_id=definition.id,
            inputs=[
                InputVersion(name=i.name, dataset_id=i.dataset_id, version_id=i.version_id)
                for i in spec.inputs
            ],
        ),
    )
    ExecutionWorker(svc).run_one()
    assert svc.status(world.actor, run.id).state == "SUCCEEDED"
    assert len(svc.status(world.actor, run.id).outputs) == 3


@pytest.mark.parametrize("boundary", ["one_output", "after_commit"])
def test_crash_boundaries_recover_idempotently(world, store, monkeypatch, boundary):
    from datetime import timedelta

    from ontology_platform.db.session import clock
    from ontology_platform.pipelines import dag_worker
    from sqlalchemy import update

    svc, datasets, run, spec, targets = setup_run(world, store)
    worker = ExecutionWorker(svc)
    claim = worker.claim()
    assert claim is not None
    if boundary == "one_output":
        original = dag_worker.put

        def crash(storage, obj, path, result):
            original(storage, obj, path, result)
            if obj.artifact != run.id:
                raise RuntimeError("test-only crash after staging output bytes")

        monkeypatch.setattr(dag_worker, "put", crash)
    else:
        original = dag_worker.commit

        def crash(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("test-only lost acknowledgement")

        monkeypatch.setattr(dag_worker, "commit", crash)
    with pytest.raises(RuntimeError):
        worker.execute(*claim)
    if boundary == "after_commit":
        worker.fail(*claim, "infrastructure", True)
        assert svc.status(world.actor, run.id).state == "SUCCEEDED"
        assert worker.claim() is None
    else:
        assert all(datasets.dataset_versions(world.actor, t.id, 50, 0) == [] for t in targets)
        with world.sessions.begin() as s:
            s.execute(
                update(ExecutionJob)
                .where(ExecutionJob.id == run.id)
                .values(lease_until=clock(s) - timedelta(seconds=1))
            )
        monkeypatch.setattr(dag_worker, "put", original)
        worker.run_one()
        assert svc.status(world.actor, run.id).state == "SUCCEEDED"
    assert all(len(datasets.dataset_versions(world.actor, t.id, 50, 0)) == 1 for t in targets)


def test_private_sibling_and_upstream_lineage(security, store):
    from ontology_platform.projects.contracts import CreateProject, MemberChange, ShareChange
    from test_projects import grant_projects

    w, auth, administration, owner, other, _ = security
    grant_projects(administration, owner, other)
    datasets = make_service(w, store, auth)
    source = dataset(datasets, owner)
    version = commit(datasets, owner, source.id, b"id,value\n1,10\n2,20\n")
    targets = [dataset(datasets, owner), dataset(datasets, owner)]
    svc = PipelineService(w.sessions, auth, store.settings, store)
    pipe = svc.create(owner, source.project_id, CreateArtifact(name="Private DAG"))
    spec = specification(source.id, version.id, [t.id for t in targets])
    definition = svc.publish(owner, pipe.id, spec)
    run = svc.start(
        owner,
        pipe.id,
        StartRun(
            definition_id=definition.id,
            inputs=[InputVersion(name="source", dataset_id=source.id, version_id=version.id)],
        ),
    )
    from worker_support import provision_worker

    ExecutionWorker(svc, provision_worker(svc, owner)).run_one()
    status = svc.status(owner, run.id)
    assert status.state == "SUCCEEDED"
    consumer = svc.create_project(owner, CreateProject(name="Output reader"))
    svc.member(
        owner,
        consumer.id,
        MemberChange(
            principal_id=other.principal_id, role="viewer", expected_revision=consumer.revision
        ),
    )
    svc.share(
        owner,
        targets[0].id,
        ShareChange(project_id=consumer.id, enabled=True, expected_revision=targets[0].revision),
    )
    output = next(o for o in status.outputs if o.output_id == "one")
    result = svc.lineage(other, output.dataset_id, output.version_id)
    assert len(result) == 1 and result[0]["inputs"] == []
    assert "nodes" not in result[0] and "pipeline_id" not in result[0]
    assert str(targets[1].id) not in str(result) and str(source.id) not in str(result)
    # A pipeline share does not expose its private output targets in status.
    svc.share(
        owner,
        pipe.id,
        ShareChange(project_id=consumer.id, enabled=True, expected_revision=pipe.revision),
    )
    assert svc.definitions(other, pipe.id) == []
    from ontology_platform.errors import ApplicationError

    with pytest.raises(ApplicationError):
        with svc.scope(other) as s:
            svc.definition(s, other, pipe.id, definition.id)
    reader_status = svc.status(other, run.id)
    assert reader_status.metrics == {}
    assert svc.status(owner, run.id).metrics["output_rows"] == 6
    assert len(reader_status.outputs) == 1 and reader_status.outputs[0].dataset_id == targets[0].id


def test_cross_tenant_input_rejected(world, store, database):
    from ontology_platform.errors import ApplicationError
    from test_phase1 import make_world

    other = make_world(database)
    private = make_service(other, store)
    source = dataset(private, other.actor)
    version = commit(private, other.actor, source.id, b"id,value\n1,10\n")
    datasets = make_service(world, store)
    target = dataset(datasets, world.actor)
    svc = PipelineService(world.sessions, world.registry.authorizer, store.settings, store)
    pipe = svc.create(world.actor, target.project_id, CreateArtifact(name="Unauthorized input"))
    spec = specification(source.id, version.id, [target.id, uuid4()])
    with pytest.raises(ApplicationError):
        svc.publish(world.actor, pipe.id, spec)


@pytest.mark.parametrize(
    "budget", ["intermediate_bytes", "staged_bytes", "cumulative_output_rows", "manifest_bytes"]
)
def test_aggregate_limits_publish_nothing(world, store, monkeypatch, budget):
    # Limits are operator settings captured before admission; caller payloads cannot override.
    monkeypatch.setenv(
        "FOUNDRY_EXECUTION_" + budget.upper(), "1024" if budget == "manifest_bytes" else "1"
    )
    svc, datasets, run, spec, targets = setup_run(world, store)
    ExecutionWorker(svc).run_one()
    assert svc.status(world.actor, run.id).state == "FAILED"
    assert all(datasets.dataset_versions(world.actor, t.id, 50, 0) == [] for t in targets)


def test_database_rejects_individual_output_visibility(world, store, monkeypatch):
    from ontology_platform.errors import ApplicationError
    from ontology_platform.pipelines import dag_worker

    svc, datasets, run, spec, targets = setup_run(world, store)
    original = dag_worker.commit

    def assert_guard(worker, p, key, token, spec, metrics):
        with world.sessions() as s:
            prepared = s.scalar(select(DAGPreparedOutput).where(DAGPreparedOutput.job_id == key))
        # Even a live worker token cannot commit one output in its own transaction.
        with pytest.raises(ApplicationError):
            with svc.scope(p) as s:
                dag_worker.fence(worker, s, p, key, token)
                config = next(o for o in spec.outputs if o.id == prepared.output_id)
                datasets.publish_prepared(
                    s,
                    p,
                    prepared.dataset_id,
                    prepared.version_id,
                    config.format,
                    prepared.result["size"],
                    prepared.result["checksum"],
                    prepared.result["dataset"],
                    key,
                )
        assert all(datasets.dataset_versions(p, t.id, 50, 0) == [] for t in targets)
        return original(worker, p, key, token, spec, metrics)

    monkeypatch.setattr(dag_worker, "commit", assert_guard)
    ExecutionWorker(svc).run_one()
    assert svc.status(world.actor, run.id).state == "SUCCEEDED"
    assert svc.change(world.actor, run.id).state == "SUCCEEDED"


def test_raw_pipeline_payload_bounded_before_authentication():
    from fastapi.testclient import TestClient
    from ontology_platform.main import create_app

    client = TestClient(create_app())
    result = client.post(
        f"/api/v1/pipelines/{uuid4()}/graph/compile",
        content=b"x" * 524289,
        headers={"content-type": "application/json"},
    )
    assert result.status_code == 413
    assert result.json()["error"]["code"] == "pipeline_payload_too_large"


def test_legacy_engine_checksums_match_base_revision(tmp_path):
    import json
    from pathlib import Path

    from ontology_platform.execution.config import ExecutionSettings
    from ontology_platform.pipelines.engine import PolarsEngine

    fixture = json.loads(
        (Path(__file__).parent / "fixtures/phase20-legacy-checksums.json").read_text()
    )
    assert fixture["polars_version"] == pl.__version__
    for index, case in enumerate(fixture["cases"]):
        directory = tmp_path / str(index)
        directory.mkdir()
        inputs = []
        for name, data in case["inputs"].items():
            path = directory / (name + ".parquet")
            pl.DataFrame(data).write_parquet(path)
            inputs.append({"name": name, "path": str(path), "format": "parquet"})
        result = PolarsEngine().execute(
            {
                "specification": {
                    "inputs": [{"name": name} for name in case["inputs"]],
                    "steps": case["steps"],
                },
                "inputs": inputs,
            },
            directory,
            ExecutionSettings(),
        )
        assert result["checksum"] == case["checksum"]
        assert result["dataset"]["row_count"] == case["row_count"]


def test_phase19_upgrade_preserves_application_pipeline_dataset(historical_database, store):
    from ontology_platform.applications.contracts import Document, Publish, Save
    from ontology_platform.applications.service import ApplicationService
    from ontology_platform.pipelines.contracts import Definition
    from test_phase1 import make_world, migrate

    engine, _, _ = historical_database
    migrate(engine, "0025_applications")
    w = make_world(historical_database)
    datasets = make_service(w, store)
    source = dataset(datasets, w.actor)
    version = commit(datasets, w.actor, source.id, b"id\n1\n2\n")
    pipelines = PipelineService(w.sessions, w.registry.authorizer, store.settings, store)
    pipeline = pipelines.create(
        w.actor, source.project_id, CreateArtifact(name="Historical pipeline")
    )
    definition = pipelines.publish(
        w.actor,
        pipeline.id,
        Definition.model_validate({"inputs": [{"name": "source"}], "steps": []}),
    )
    apps = ApplicationService(w.sessions, w.registry.authorizer)
    app = apps.create(w.actor, source.project_id, CreateArtifact(name="Historical application"))
    document = Document.model_validate(
        {
            "title": "Preserved",
            "home": "home",
            "pages": [
                {
                    "id": "home",
                    "title": "Home",
                    "widgets": [{"id": "text", "kind": "text", "text": "Historical content"}],
                }
            ],
        }
    )
    apps.save(w.actor, app.id, Save(expected_revision=0, document=document))
    published = apps.publish(w.actor, app.id, Publish(expected_revision=1))
    migrate(engine)
    assert apps.version(w.actor, app.id, published.id) == published
    assert pipelines.definitions(w.actor, pipeline.id)[0] == definition
    preserved = datasets.dataset_metadata(w.actor, source.id, version.id)
    assert preserved.checksum == version.checksum and preserved.result["row_count"] == 2


@pytest.mark.parametrize("failure", ["second_upload", "second_verify", "revoked_output"])
def test_precommit_failure_publishes_zero(world, store, monkeypatch, failure):
    from ontology_platform.artifacts.storage import Failure, StorageError
    from ontology_platform.pipelines import dag_worker

    svc, datasets, run, spec, targets = setup_run(world, store)
    target_ids = {t.id for t in targets}
    if failure == "revoked_output":
        original = dag_worker.commit

        def revoke(worker, p, key, token, spec, metrics):
            datasets.update_resource(p, targets[1].id, None, targets[1].revision)
            return original(worker, p, key, token, spec, metrics)

        monkeypatch.setattr(dag_worker, "commit", revoke)
    else:
        name = "put" if failure == "second_upload" else "verify"
        original = getattr(store, name)
        seen = set()

        def fail(obj, *args, **kwargs):
            if obj.artifact in target_ids:
                seen.add(obj.artifact)
                if len(seen) == 2:
                    raise StorageError(
                        Failure.PERMANENT if failure == "second_upload" else Failure.INTEGRITY
                    )
            return original(obj, *args, **kwargs)

        monkeypatch.setattr(store, name, fail)
    ExecutionWorker(svc).run_one()
    assert svc.status(world.actor, run.id).state == "FAILED"
    # Read direct metadata for archived target without changing its authorization state.
    from ontology_platform.db.models import DatasetVersion

    with world.sessions() as s:
        assert (
            list(
                s.scalars(select(DatasetVersion).where(DatasetVersion.artifact_id.in_(target_ids)))
            )
            == []
        )


def test_interrupted_put_retries_same_intermediate_and_output_identities(world, store, monkeypatch):
    from ontology_platform.artifacts.storage import Failure, StorageError

    svc, datasets, run, spec, targets = setup_run(world, store)
    original = store.put
    failed = False

    def interrupted(*args, **kwargs):
        nonlocal failed
        original(*args, **kwargs)
        if not failed:
            failed = True
            raise StorageError(Failure.TRANSIENT)

    monkeypatch.setattr(store, "put", interrupted)
    worker = ExecutionWorker(svc)
    worker.run_one()
    assert svc.status(world.actor, run.id).state == "QUEUED"
    with world.sessions() as s:
        identities = [
            (o.output_id, o.version_id)
            for o in s.scalars(
                select(DAGPreparedOutput)
                .where(DAGPreparedOutput.job_id == run.id)
                .order_by(DAGPreparedOutput.output_id)
            )
        ]
    worker.run_one()
    result = svc.status(world.actor, run.id)
    assert result.state == "SUCCEEDED" and result.attempts == 2
    assert [(o.output_id, o.version_id) for o in result.outputs] == identities


@pytest.mark.parametrize("overlap", [True, False])
def test_concurrent_target_sets_append_without_partial_visibility(
    world, store, monkeypatch, overlap
):
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setenv("FOUNDRY_EXECUTION_PROJECT_JOBS", "2")
    svc, datasets, first, spec, targets = setup_run(world, store)
    with world.sessions() as s:
        pipeline_id = s.get(ExecutionJob, (world.actor.tenant_id, first.id)).resource_id
    if not overlap:
        other_targets = [dataset(datasets, world.actor), dataset(datasets, world.actor)]
        body = spec.model_dump(mode="json")
        for output, target in zip(body["outputs"], other_targets, strict=True):
            output["dataset_id"] = str(target.id)
        spec = DAGDefinition.model_validate(body)
    definition = svc.publish(world.actor, pipeline_id, spec)
    second = svc.start(
        world.actor,
        pipeline_id,
        StartRun(
            definition_id=definition.id,
            inputs=[
                InputVersion(name=i.name, dataset_id=i.dataset_id, version_id=i.version_id)
                for i in spec.inputs
            ],
        ),
    )
    worker = ExecutionWorker(svc)
    claims = [worker.claim(), worker.claim()]
    assert all(claim is not None for claim in claims)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker.execute, *claim) for claim in claims]
        for future in futures:
            future.result(timeout=1800)
    assert (
        svc.status(world.actor, first.id).state
        == svc.status(world.actor, second.id).state
        == "SUCCEEDED"
    )
    assert all(
        len(datasets.dataset_versions(world.actor, t.id, 50, 0)) == (2 if overlap else 1)
        for t in targets
    )
    for run in [first, second]:
        status = svc.status(world.actor, run.id)
        assert len(status.outputs) == 2 and status.publication_state == "COMMITTED"
    from ontology_platform.pipelines.dag_worker import cleanup

    cleanup(worker, world.actor.tenant_id, first.id)
    cleanup(worker, world.actor.tenant_id, second.id)


def test_recovery_rejects_corrupt_private_intermediate(world, store, monkeypatch):
    import hashlib
    import io
    from datetime import timedelta

    from ontology_platform.artifacts.storage import ObjectKey
    from ontology_platform.db.models import DAGNodeExecution
    from ontology_platform.db.session import clock
    from ontology_platform.errors import ApplicationError
    from ontology_platform.pipelines import dag_worker
    from sqlalchemy import update

    svc, datasets, run, spec, targets = setup_run(world, store)
    worker = ExecutionWorker(svc)
    claim = worker.claim()
    original = dag_worker.commit

    def interrupt(*args, **kwargs):
        raise RuntimeError("test-only precommit crash")

    monkeypatch.setattr(dag_worker, "commit", interrupt)
    with pytest.raises(RuntimeError):
        worker.execute(*claim)
    with world.sessions() as s:
        node = s.scalar(
            select(DAGNodeExecution).where(
                DAGNodeExecution.job_id == run.id, DAGNodeExecution.node_id == "shared"
            )
        )
    with pytest.raises(ApplicationError):
        datasets.dataset_metadata(world.actor, run.id, node.result_id)
    obj = ObjectKey(world.actor.tenant_id, run.id, node.result_id)
    store.delete(obj)
    corrupt = b"corrupt"
    store.put(obj, io.BytesIO(corrupt), len(corrupt), hashlib.sha256(corrupt).hexdigest())
    with world.sessions.begin() as s:
        s.execute(
            update(ExecutionJob)
            .where(ExecutionJob.id == run.id)
            .values(lease_until=clock(s) - timedelta(seconds=1))
        )
    monkeypatch.setattr(dag_worker, "commit", original)
    worker.run_one()
    status = svc.status(world.actor, run.id)
    assert status.state == "FAILED" and status.error == "storage_integrity"
    assert all(datasets.dataset_versions(world.actor, t.id, 50, 0) == [] for t in targets)


def test_depth_and_schema_mismatch_diagnostics():
    body = specification().model_dump(mode="json")
    body["nodes"] = [
        {
            "id": f"n{i}",
            "inputs": {"input": "source" if i == 0 else f"n{i - 1}"},
            "config": {"op": "select", "columns": ["id"]},
        }
        for i in range(65)
    ]
    body["outputs"] = [{"id": "out", "source": "n64", "dataset_id": str(uuid4())}]
    with pytest.raises(ValidationError, match="depth"):
        DAGDefinition.model_validate(body)
    spec = specification()
    with pytest.raises(ValueError):
        dag_frames(spec, {"source": pl.DataFrame({"missing": [1]}).lazy()})


def test_pipeline_metadata_creation_does_not_require_object_storage(world):
    from ontology_platform.artifacts.config import StorageSettings
    from ontology_platform.projects.contracts import CreateProject

    svc = PipelineService(
        world.sessions,
        world.registry.authorizer,
        StorageSettings(backend="disabled", _env_file=None),
        None,
    )
    project = svc.create_project(world.actor, CreateProject(name="Metadata-only pipelines"))
    pipeline = svc.create(
        world.actor, project.id, CreateArtifact(name="Pipeline without configured storage")
    )
    assert pipeline.resource_type == "PIPELINE"
    assert svc.get_resource(world.actor, pipeline.id).name == "Pipeline without configured storage"


def test_visual_invalid_source_identity_is_a_diagnostic_and_v1_outputs_fail_closed():
    from ontology_platform.pipelines.graph import Graph, compile_graph

    body = {
        "format_version": 2,
        "nodes": [
            {
                "id": "source",
                "kind": "dataset_source",
                "config": {
                    "name": "invalid source name",
                    "dataset_id": str(uuid4()),
                    "version_id": str(uuid4()),
                },
            },
            {"id": "out", "kind": "dataset_output", "config": {"dataset_id": str(uuid4())}},
        ],
        "edges": [{"id": "edge", "source": "source", "target": "out"}],
    }
    result = compile_graph(Graph.model_validate(body))
    assert not result.valid and result.diagnostics[0].code == "input_identity_invalid"
    body["format_version"] = 1
    body["nodes"][1]["config"]["format"] = "csv"
    with pytest.raises(ValidationError, match="format 2"):
        Graph.model_validate(body)


def test_legacy_job_contract_still_requires_output_dataset(world):
    from ontology_platform.artifacts.config import StorageSettings
    from ontology_platform.execution.config import ExecutionSettings
    from ontology_platform.pipelines.contracts import Definition, InputContract
    from ontology_platform.projects.contracts import CreateProject
    from sqlalchemy.exc import IntegrityError

    svc = PipelineService(
        world.sessions,
        world.registry.authorizer,
        StorageSettings(backend="disabled", _env_file=None),
        None,
    )
    project = svc.create_project(world.actor, CreateProject(name="Legacy contract"))
    pipeline = svc.create(world.actor, project.id, CreateArtifact(name="Legacy pipeline"))
    definition = svc.publish(
        world.actor, pipeline.id, Definition(inputs=[InputContract(name="source")])
    )
    with pytest.raises(IntegrityError):
        with world.sessions.begin() as s:
            s.add(
                ExecutionJob(
                    tenant_id=world.actor.tenant_id,
                    id=uuid4(),
                    resource_id=pipeline.id,
                    project_id=project.id,
                    kind="PIPELINE",
                    definition_id=definition.id,
                    request={},
                    principal=world.actor.model_dump(mode="json"),
                    limits=ExecutionSettings().model_dump(mode="json"),
                )
            )
            s.flush()


def test_cleanup_rechecks_late_stale_bytes_without_deleting_committed_outputs(world, store):
    import hashlib
    import io

    from ontology_platform.artifacts.storage import ObjectKey
    from ontology_platform.db.models import DAGNodeExecution
    from ontology_platform.pipelines import dag_worker

    svc, datasets, run, _, _ = setup_run(world, store)
    worker = ExecutionWorker(svc)
    worker.run_one()
    with world.sessions() as s:
        node = s.scalar(select(DAGNodeExecution).where(DAGNodeExecution.job_id == run.id))
        before = s.get(DAGRun, (world.actor.tenant_id, run.id)).cleaned_at
    assert before is not None
    # A stale transfer can finish after a prior cleanup. The key remains private and known.
    obj = ObjectKey(world.actor.tenant_id, run.id, node.result_id)
    late = b"late private bytes"
    store.put(obj, io.BytesIO(late), len(late), hashlib.sha256(late).hexdigest())
    dag_worker.cleanup(worker, world.actor.tenant_id, run.id, repeat=True)
    assert not store.exists(obj)
    for output in svc.status(world.actor, run.id).outputs:
        committed = datasets.dataset_metadata(world.actor, output.dataset_id, output.version_id)
        store.verify(
            ObjectKey(world.actor.tenant_id, output.dataset_id, output.version_id),
            committed.size,
            committed.checksum,
        )


def test_recovery_does_not_reset_total_dag_deadline(world, store, monkeypatch):
    from datetime import timedelta

    from ontology_platform.db.session import clock
    from ontology_platform.pipelines import dag_worker
    from sqlalchemy import update

    svc, datasets, run, spec, targets = setup_run(world, store)
    worker = ExecutionWorker(svc)
    claim = worker.claim()
    original = dag_worker.commit

    def interrupt(*args, **kwargs):
        raise RuntimeError("test-only interruption before commit")

    monkeypatch.setattr(dag_worker, "commit", interrupt)
    with pytest.raises(RuntimeError):
        worker.execute(*claim)
    with world.sessions.begin() as s:
        s.execute(
            update(ExecutionJob)
            .where(ExecutionJob.id == run.id)
            .values(lease_until=clock(s) - timedelta(seconds=1))
        )
    monkeypatch.setattr(dag_worker, "commit", original)
    # Advance only the DAG deadline clock deterministically; do not sleep or alter shared clocks.
    monkeypatch.setattr(dag_worker, "clock", lambda s: clock(s) + timedelta(seconds=1801))
    worker.run_one()
    status = svc.status(world.actor, run.id)
    assert status.state == "FAILED" and status.error == "execution_limit"
    assert all(datasets.dataset_versions(world.actor, t.id, 50, 0) == [] for t in targets)


@pytest.mark.parametrize("format", ["json", "ndjson"])
def test_raw_text_source_fanout_and_multiple_direct_outputs(world, store, format):
    import json

    rows = [{"id": 1, "value": "a"}, {"id": 2, "value": "b"}]
    data = (
        json.dumps(rows) if format == "json" else "\n".join(json.dumps(row) for row in rows)
    ).encode()
    datasets = make_service(world, store)
    source = dataset(datasets, world.actor)
    version = commit(datasets, world.actor, source.id, data, format=format)
    targets = [dataset(datasets, world.actor) for _ in range(4)]
    svc = PipelineService(world.sessions, world.registry.authorizer, store.settings, store)
    pipe = svc.create(world.actor, source.project_id, CreateArtifact(name="Raw text branches"))
    spec = DAGDefinition.model_validate(
        {
            "format_version": 2,
            "inputs": [
                {"name": "source", "dataset_id": str(source.id), "version_id": str(version.id)}
            ],
            "nodes": [
                {
                    "id": "left",
                    "inputs": {"input": "source"},
                    "config": {"op": "select", "columns": ["id", "value"]},
                },
                {
                    "id": "right",
                    "inputs": {"input": "source"},
                    "config": {"op": "select", "columns": ["id"]},
                },
            ],
            "outputs": [
                {"id": f"out{i}", "source": ref, "dataset_id": str(target.id)}
                for i, (ref, target) in enumerate(
                    zip(["left", "right", "source", "source"], targets, strict=True)
                )
            ],
        }
    )
    definition = svc.publish(world.actor, pipe.id, spec)
    run = svc.start(
        world.actor,
        pipe.id,
        StartRun(
            definition_id=definition.id,
            inputs=[InputVersion(name="source", dataset_id=source.id, version_id=version.id)],
        ),
    )
    ExecutionWorker(svc).run_one()
    status = svc.status(world.actor, run.id)
    assert status.state == "SUCCEEDED", status
    assert len(status.outputs) == 4
    assert all(
        datasets.dataset_metadata(world.actor, o.dataset_id, o.version_id).result["row_count"] == 2
        for o in status.outputs
    )


def test_repeated_source_pin_aliases_keep_one_physical_lineage_identity(world, store):
    svc, datasets, first, spec, targets = setup_run(world, store)
    with world.sessions() as s:
        pipeline = s.get(ExecutionJob, (world.actor.tenant_id, first.id)).resource_id
    svc.change(world.actor, first.id)
    body = spec.model_dump(mode="json")
    body["inputs"].append(body["inputs"][0] | {"name": "alias"})
    next(n for n in body["nodes"] if n["id"] == "right")["inputs"]["input"] = "alias"
    spec = DAGDefinition.model_validate(body)
    definition = svc.publish(world.actor, pipeline, spec)
    run = svc.start(
        world.actor,
        pipeline,
        StartRun(
            definition_id=definition.id,
            inputs=[
                InputVersion(name=i.name, dataset_id=i.dataset_id, version_id=i.version_id)
                for i in spec.inputs
            ],
        ),
    )
    ExecutionWorker(svc).run_one()
    status = svc.status(world.actor, run.id)
    assert status.state == "SUCCEEDED", status
    output = next(o for o in status.outputs if o.output_id == "two")
    assert len(svc.lineage(world.actor, output.dataset_id, output.version_id)[0]["inputs"]) == 1


def test_parameterized_temporal_decimal_schema_preserved_in_dag(world, store):
    import io
    from datetime import UTC, datetime
    from decimal import Decimal

    data = io.BytesIO()
    pl.DataFrame(
        {
            "id": [1, 2],
            "when": [datetime(2026, 11, 6, tzinfo=UTC), datetime(2026, 11, 7, tzinfo=UTC)],
            "amount": [Decimal("1.25"), Decimal("2.50")],
        },
        schema_overrides={"when": pl.Datetime("us", "UTC"), "amount": pl.Decimal(18, 2)},
    ).write_parquet(data)
    datasets = make_service(world, store)
    source = dataset(datasets, world.actor)
    version = commit(datasets, world.actor, source.id, data.getvalue(), format="parquet")
    targets = [dataset(datasets, world.actor), dataset(datasets, world.actor)]
    svc = PipelineService(world.sessions, world.registry.authorizer, store.settings, store)
    pipe = svc.create(world.actor, source.project_id, CreateArtifact(name="Scalar schemas"))
    spec = DAGDefinition.model_validate(
        {
            "format_version": 2,
            "inputs": [
                {"name": "source", "dataset_id": str(source.id), "version_id": str(version.id)}
            ],
            "nodes": [
                {
                    "id": "select",
                    "inputs": {"input": "source"},
                    "config": {"op": "select", "columns": ["id", "when", "amount"]},
                }
            ],
            "outputs": [
                {"id": f"out{i}", "source": "select", "dataset_id": str(target.id)}
                for i, target in enumerate(targets)
            ],
        }
    )
    definition = svc.publish(world.actor, pipe.id, spec)
    run = svc.start(
        world.actor,
        pipe.id,
        StartRun(
            definition_id=definition.id,
            inputs=[InputVersion(name="source", dataset_id=source.id, version_id=version.id)],
        ),
    )
    ExecutionWorker(svc).run_one()
    status = svc.status(world.actor, run.id)
    assert status.state == "SUCCEEDED", status
    for output in status.outputs:
        schema = datasets.dataset_metadata(
            world.actor, output.dataset_id, output.version_id
        ).result["schema"]
        assert schema[1]["logical_type"] == "Datetime(time_unit='us', time_zone='UTC')"
        assert schema[2]["logical_type"] == "Decimal(precision=18, scale=2)"


def test_legacy_repeated_source_pins_still_execute(world, store):
    from ontology_platform.pipelines.contracts import Definition

    svc, datasets, first, spec, targets = setup_run(world, store)
    with world.sessions() as s:
        pipeline = s.get(ExecutionJob, (world.actor.tenant_id, first.id)).resource_id
    svc.change(world.actor, first.id)
    definition = svc.publish(
        world.actor,
        pipeline,
        Definition.model_validate(
            {
                "inputs": [{"name": "source"}, {"name": "right"}],
                "steps": [
                    {"op": "select", "columns": ["id"]},
                    {"op": "join", "input": "right", "columns": ["id"]},
                ],
            }
        ),
    )
    pin = spec.inputs[0]
    run = svc.start(
        world.actor,
        pipeline,
        StartRun(
            definition_id=definition.id,
            inputs=[
                InputVersion(name=name, dataset_id=pin.dataset_id, version_id=pin.version_id)
                for name in ["source", "right"]
            ],
            output_dataset_id=targets[0].id,
        ),
    )
    ExecutionWorker(svc).run_one()
    status = svc.status(world.actor, run.id)
    assert status.state == "SUCCEEDED", status
    assert (
        datasets.dataset_metadata(world.actor, targets[0].id, status.output_version_id).result[
            "row_count"
        ]
        == 2
    )


@pytest.mark.parametrize(
    "value",
    [
        "List(Int64)",
        "Decimal(precision=99, scale=2)",
        "Datetime(time_unit='ps', time_zone=None)",
        "__import__('os')",
    ],
)
def test_schema_metadata_parser_fails_closed(value):
    from ontology_platform.pipelines.engine import schema_dtype

    with pytest.raises(ValueError):
        schema_dtype(value)
