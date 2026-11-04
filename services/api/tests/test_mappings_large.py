"""Explicit representative 1 GiB materialization; generated files never enter Git."""

import hashlib
import json
import os
import subprocess
import threading
import time

import pytest
from ontology_platform.artifacts.contracts import CreateArtifact
from ontology_platform.datasets.contracts import InitiateDataset
from ontology_platform.execution.config import ExecutionSettings
from ontology_platform.execution.worker import ExecutionWorker
from ontology_platform.mappings.contracts import MappingRun
from test_artifacts import store  # noqa: F401
from test_mappings import machine_spec, setup_mapping
from test_phase1 import database, historical_database, world  # noqa: F401


@pytest.fixture
def controller_memory():
    stop = threading.Event()
    measured = {"peak_rss_bytes": 0}

    def sample():
        while not stop.is_set():
            output = subprocess.run(
                ["/bin/ps", "-o", "rss=", "-p", str(os.getpid())],
                capture_output=True,
                text=True,
                check=True,
            )
            measured["peak_rss_bytes"] = max(
                measured["peak_rss_bytes"], int(output.stdout.strip()) * 1024
            )
            stop.wait(0.5)

    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    try:
        yield measured
    finally:
        stop.set()
        thread.join(2)


def test_representative_gib_materialization(world, store, tmp_path, monkeypatch, controller_memory):  # noqa: F811
    svc, resource, spec, _ = setup_mapping(world, store)
    datasets = svc.datasets()
    source = datasets.create(world.actor, resource.project_id, CreateArtifact(name="1 GiB source"))
    path = tmp_path / "representative.csv"
    size = 1024**3
    header = b"id,name,padding\n"
    count = (size - len(header)) // 4096
    remainder = (size - len(header)) % 4096
    digest = hashlib.sha256()
    with path.open("wb") as file:
        file.write(header)
        digest.update(header)
        for i in range(count):
            prefix = f"F{i % 256},Factory {i % 256},".encode()
            length = 4096 + (remainder if i == count - 1 else 0)
            row = prefix + b"x" * (length - len(prefix) - 1) + b"\n"
            file.write(row)
            digest.update(row)
    assert path.stat().st_size == size
    version = datasets.initiate_dataset(
        world.actor,
        source.id,
        InitiateDataset(
            filename="representative.csv", size=size, checksum=digest.hexdigest(), format="csv"
        ),
    )
    started = time.monotonic()
    with path.open("rb") as file:
        datasets.upload(world.actor, source.id, version.id, file, size, version.checksum)
    worker = ExecutionWorker(svc)
    validation = datasets.enqueue_validation(world.actor, source.id, version.id)
    worker.run_one()
    assert svc.status(world.actor, validation.id).state == "SUCCEEDED"
    assert (
        datasets.dataset_metadata(world.actor, source.id, version.id).result["row_count"] == count
    )
    definition = svc.publish(
        world.actor,
        resource.id,
        machine_spec(spec).model_copy(
            update={"duplicates": "coalesce_identical", "max_objects": 512, "max_links": 256}
        ),
    )
    body = MappingRun(definition_id=definition.id, dataset_id=source.id, version_id=version.id)
    run = svc.start(world.actor, resource.id, body)
    worker.run_one()
    status = svc.status(world.actor, run.id)
    assert status.state == "SUCCEEDED", status
    assert status.metrics["rows"] == count
    assert status.metrics["objects"] == 512 and status.metrics["links"] == 256
    assert status.metrics["created"] == 768
    assert status.metrics["peak_memory_bytes"] <= ExecutionSettings().memory_bytes
    assert status.metrics["temporary_bytes"] <= ExecutionSettings().temporary_bytes
    assert world.objects.count(world.actor, spec.ontology_id, "Factory") == 256
    assert world.objects.count(world.actor, spec.ontology_id, "Machine") == 256
    assert len(svc.provenance(world.actor, run.id, 100)) == 100
    from ontology_platform.db.models import Link, MaterializationRecord
    from sqlalchemy import func, select

    with world.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Link)
                .where(
                    Link.tenant_id == world.actor.tenant_id, Link.ontology_id == spec.ontology_id
                )
            )
            == 256
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(MaterializationRecord)
                .where(
                    MaterializationRecord.tenant_id == world.actor.tenant_id,
                    MaterializationRecord.run_id == run.id,
                )
            )
            == 768
        )
    # Exact same immutable source and definition converge without duplicate canonical edges.
    replay = svc.start(world.actor, resource.id, body)
    ExecutionWorker(svc).run_one()
    repeated = svc.status(world.actor, replay.id)
    assert repeated.state == "SUCCEEDED" and repeated.metrics.get("created", 0) == 0, repeated
    assert repeated.metrics["preserved"] == 512 and repeated.metrics["observed"] == 256
    # Cancel a real spawned mapping child after downloading the full pinned source, then
    # recover with a new run of the same contract; terminal cancellation itself is immutable.
    import ontology_platform.mappings.worker as mapping_worker

    isolated = mapping_worker.isolated
    interrupted = svc.start(world.actor, resource.id, body)

    def cancel_child(operation, request, directory, limits, heartbeat):
        cancelled = False

        def renew():
            nonlocal cancelled
            if not cancelled:
                cancelled = True
                svc.change(world.actor, interrupted.id)
            return heartbeat()

        return isolated(operation, request, directory, limits, renew)

    monkeypatch.setattr(mapping_worker, "isolated", cancel_child)
    ExecutionWorker(svc).run_one()
    assert svc.status(world.actor, interrupted.id).state == "CANCELLED"
    assert svc.provenance(world.actor, interrupted.id) == []
    monkeypatch.setattr(mapping_worker, "isolated", isolated)
    recovered = svc.start(world.actor, resource.id, body)
    ExecutionWorker(svc).run_one()
    recovery = svc.status(world.actor, recovered.id)
    assert recovery.state == "SUCCEEDED" and recovery.metrics.get("created", 0) == 0, recovery
    assert controller_memory["peak_rss_bytes"] > 0
    conservative_peak = controller_memory["peak_rss_bytes"] + max(
        int(s.metrics["peak_memory_bytes"]) for s in (status, repeated, recovery)
    )
    assert conservative_peak <= ExecutionSettings().memory_bytes
    print(
        "MATERIALIZATION_MEASUREMENT "
        + json.dumps(
            {
                "source_bytes": size,
                "source_rows": count,
                "checksum": digest.hexdigest(),
                "end_to_end_seconds": time.monotonic() - started,
                "run": status.model_dump(mode="json"),
                "replay": repeated.model_dump(mode="json"),
                "recovery": recovery.model_dump(mode="json"),
                "controller_peak_rss_bytes": controller_memory["peak_rss_bytes"],
                "conservative_combined_peak_bytes": conservative_peak,
            },
            sort_keys=True,
        ),
        flush=True,
    )
