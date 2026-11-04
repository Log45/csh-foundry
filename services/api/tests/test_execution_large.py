"""Explicit performance acceptance suite: invoked by validate_phase14.py --large.

Real file -> existing artifact transport -> real MinIO -> restarted validation controller
-> immutable PostgreSQL publication. Every source has exactly the requested number of bytes.
"""

import json
import platform
import time

import pytest
from large_sources import generate
from ontology_platform.artifacts.contracts import CreateArtifact
from ontology_platform.datasets.contracts import InitiateDataset
from ontology_platform.execution.config import ExecutionSettings
from ontology_platform.execution.worker import ExecutionWorker
from ontology_platform.pipelines.contracts import StartRun
from ontology_platform.pipelines.service import PipelineService
from test_artifacts import store  # noqa: F401
from test_datasets import dataset, make_service
from test_execution import spec
from test_phase1 import database, historical_database, world  # noqa: F401


@pytest.mark.parametrize("size", [8 * 1024**2, 100 * 1024**2, 500 * 1024**2, 1024**3])
@pytest.mark.parametrize("format", ["csv", "ndjson", "json", "parquet"])
def test_exact_source_tiers(world, store, tmp_path, size, format):  # noqa: F811
    path = tmp_path / "generated"
    count, checksum = generate(path, format, size)
    datasets, p = make_service(world, store), world.actor
    resource = dataset(datasets, p)
    v = datasets.initiate_dataset(
        p,
        resource.id,
        InitiateDataset(
            filename="generated." + format, size=size, checksum=checksum, format=format
        ),
    )
    started = time.monotonic()
    with path.open("rb") as source:
        datasets.upload(p, resource.id, v.id, source, size, checksum)
    uploaded = time.monotonic() - started
    job = datasets.enqueue_validation(p, resource.id, v.id)
    service = PipelineService(world.sessions, world.registry.authorizer, store.settings, store)
    worker = ExecutionWorker(service)
    assert worker.run_one() == job.id
    status = service.status(p, job.id)
    assert status.state == "SUCCEEDED", status
    committed = datasets.dataset_metadata(p, resource.id, v.id)
    assert committed.state == committed.artifact_state == "COMMITTED"
    assert committed.checksum == checksum
    assert committed.result["row_count"] == count
    assert committed.result["schema"][0]["name"] == ("id" if format == "parquet" else "payload")
    assert len(datasets.preview(p, resource.id, v.id, 100).rows) == 100
    assert datasets.enqueue_validation(p, resource.id, v.id).id == job.id
    assert status.metrics["peak_memory_bytes"] <= ExecutionSettings().memory_bytes
    print(
        "MEASUREMENT "
        + json.dumps(
            {
                "format": format,
                "source_bytes": size,
                "rows": count,
                "checksum": checksum,
                "upload_seconds": uploaded,
                "upload_mib_per_second": size / 1024**2 / uploaded,
                "worker": status.metrics,
                "hardware": platform.platform(),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    if size == 1024**3 and format == "csv":
        output = datasets.create(p, resource.project_id, CreateArtifact(name="Large output"))
        pipeline = service.create(
            p, resource.project_id, CreateArtifact(name="Large transformation")
        )
        definition = service.publish(
            p, pipeline.id, spec([{"op": "select", "columns": ["payload"]}])
        )
        run = service.start(
            p,
            pipeline.id,
            StartRun(
                definition_id=definition.id,
                inputs=[{"name": "source", "dataset_id": resource.id, "version_id": v.id}],
                output_dataset_id=output.id,
            ),
        )
        assert ExecutionWorker(service).run_one() == run.id
        status = service.status(p, run.id)
        assert status.state == "SUCCEEDED", status
        assert (
            datasets.dataset_metadata(p, output.id, status.output_version_id).result["row_count"]
            == count
        )
        print(
            "TRANSFORMATION " + json.dumps(status.model_dump(mode="json"), sort_keys=True),
            flush=True,
        )
