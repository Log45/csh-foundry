"""Explicit exact 1 GiB real PostgreSQL/MinIO multi-output regression."""

# ruff: noqa: F811
import json

from large_sources import generate
from ontology_platform.artifacts.contracts import CreateArtifact
from ontology_platform.artifacts.storage import ObjectKey
from ontology_platform.datasets.contracts import InitiateDataset
from ontology_platform.db.models import DAGNodeExecution
from ontology_platform.execution.config import ExecutionSettings
from ontology_platform.execution.worker import ExecutionWorker
from ontology_platform.pipelines.contracts import InputVersion, StartRun
from ontology_platform.pipelines.dag import DAGDefinition
from ontology_platform.pipelines.service import PipelineService
from sqlalchemy import select
from test_artifacts import store  # noqa: F401
from test_datasets import dataset, make_service
from test_phase1 import database, world  # noqa: F401


def test_exact_gib_shared_branch_multi_output(world, store, tmp_path):
    size = 1024**3
    path = tmp_path / "source.csv"
    count, checksum = generate(path, "csv", size)
    datasets, p = make_service(world, store), world.actor
    source = dataset(datasets, p)
    version = datasets.initiate_dataset(
        p,
        source.id,
        InitiateDataset(filename="source.csv", size=size, checksum=checksum, format="csv"),
    )
    with path.open("rb") as file:
        datasets.upload(p, source.id, version.id, file, size, checksum)
    svc = PipelineService(world.sessions, world.registry.authorizer, store.settings, store)
    job = datasets.enqueue_validation(p, source.id, version.id)
    worker = ExecutionWorker(svc)
    assert worker.run_one() == job.id
    assert svc.status(p, job.id).state == "SUCCEEDED"
    outputs = [dataset(datasets, p), dataset(datasets, p)]
    pipeline = svc.create(p, source.project_id, CreateArtifact(name="1 GiB DAG"))
    spec = DAGDefinition.model_validate(
        {
            "format_version": 2,
            "inputs": [
                {"name": "source", "dataset_id": str(source.id), "version_id": str(version.id)}
            ],
            "nodes": [
                {
                    "id": "shared",
                    "inputs": {"input": "source"},
                    "config": {"op": "select", "columns": ["payload"]},
                },
                {
                    "id": "left",
                    "inputs": {"input": "shared"},
                    "config": {"op": "select", "columns": ["payload"]},
                },
                {
                    "id": "right",
                    "inputs": {"input": "shared"},
                    "config": {"op": "filter", "expression": {"op": "literal", "value": True}},
                },
            ],
            "outputs": [
                {"id": str(index), "source": branch, "dataset_id": str(target.id)}
                for index, (branch, target) in enumerate(
                    zip(["left", "right"], outputs, strict=True)
                )
            ],
        }
    )
    definition = svc.publish(p, pipeline.id, spec)
    run = svc.start(
        p,
        pipeline.id,
        StartRun(
            definition_id=definition.id,
            inputs=[InputVersion(name="source", dataset_id=source.id, version_id=version.id)],
        ),
    )
    assert worker.run_one() == run.id
    status = svc.status(p, run.id)
    assert status.state == "SUCCEEDED", status
    assert status.publication_state == "COMMITTED" and len(status.outputs) == 2
    assert status.metrics["peak_memory_bytes"] <= ExecutionSettings().memory_bytes
    assert status.metrics["temporary_bytes"] <= ExecutionSettings().temporary_bytes
    checksums = []
    for output in status.outputs:
        committed = datasets.dataset_metadata(p, output.dataset_id, output.version_id)
        assert committed.result["row_count"] == count
        store.verify(
            ObjectKey(p.tenant_id, output.dataset_id, output.version_id),
            committed.size,
            committed.checksum,
        )
        checksums.append(committed.checksum)
    assert checksums[0] == checksums[1]
    with world.sessions() as s:
        nodes = list(s.scalars(select(DAGNodeExecution).where(DAGNodeExecution.job_id == run.id)))
        assert all(
            n.attempt == 1 and not store.exists(ObjectKey(p.tenant_id, run.id, n.result_id))
            for n in nodes
        )
    print(
        "DAG_LARGE "
        + json.dumps(
            {
                "source_bytes": size,
                "source_rows": count,
                "source_checksum": checksum,
                "output_checksums": checksums,
                "metrics": status.metrics,
                "cleanup": "PASS",
            },
            sort_keys=True,
        ),
        flush=True,
    )
