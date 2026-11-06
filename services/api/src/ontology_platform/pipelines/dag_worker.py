"""DAG execution units remain under ExecutionWorker leases, isolation and admission."""

import hashlib
import json
import shutil
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import select, text

from ontology_platform.artifacts.contracts import CreateArtifact
from ontology_platform.artifacts.storage import Failure, ObjectKey, StorageError
from ontology_platform.db.models import (
    DAGNodeExecution,
    DAGPreparedOutput,
    DAGRun,
    ExecutionInput,
    ExecutionJob,
    Resource,
)
from ontology_platform.db.session import clock
from ontology_platform.errors import ApplicationError
from ontology_platform.execution.config import ExecutionSettings
from ontology_platform.execution.isolation import isolated
from ontology_platform.pipelines.contracts import Definition, InputContract
from ontology_platform.pipelines.dag import DAGDefinition, parse_definition, topology
from ontology_platform.pipelines.dag_service import validate_in
from ontology_platform.security.interfaces import Principal


def fence(worker: Any, s: Any, p: Principal, key: UUID, token: UUID) -> Any:
    job = worker.fenced(s, p.tenant_id, key, token)
    run = s.get(DAGRun, (p.tenant_id, key))
    if (
        run is not None
        and run.execution_started_at is not None
        and clock(s)
        >= run.execution_started_at
        + timedelta(seconds=ExecutionSettings.model_validate(job.limits).wall_seconds)
    ):
        raise ApplicationError("execution_limit", "Total DAG execution deadline exceeded", 409)
    s.execute(
        text("SELECT set_config('foundry.execution_token', :token, true)"), {"token": str(token)}
    )
    return job


def put(store: Any, obj: ObjectKey, path: Path, result: dict[str, Any]) -> None:
    if not store.exists(obj):
        try:
            with path.open("rb") as file:
                store.put(obj, file, result["size"], result["checksum"])
        except StorageError as exc:
            if exc.category != Failure.EXISTS:
                raise
    store.verify(obj, result["size"], result["checksum"])


def download(store: Any, obj: ObjectKey, path: Path, result: dict[str, Any]) -> None:
    digest, size = hashlib.sha256(), 0
    with path.open("wb") as file:
        for chunk in store.chunks(obj):
            size += len(chunk)
            if size > result["size"]:
                raise StorageError(Failure.INTEGRITY)
            digest.update(chunk)
            file.write(chunk)
    if size != result["size"] or digest.hexdigest() != result["checksum"]:
        raise StorageError(Failure.INTEGRITY)


def clear_normalized(directory: Path) -> None:
    # Children are sequential and fully exited. Their output Parquet is self-contained;
    # raw-text normalization pieces must not collide with the next child or retain disk.
    for path in directory.glob("normalized-*"):
        if path.is_dir():
            shutil.rmtree(path)


def execute(
    worker: Any, tenant: UUID, key: UUID, token: UUID, p: Principal, limits: ExecutionSettings
) -> None:
    svc, datasets = worker.service, worker.service.datasets()
    store = datasets.storage()
    with svc.scope(p) as s:
        job = worker.fenced(s, tenant, key, token)
        assert job.definition_id is not None
        spec = parse_definition(
            svc.definition(s, p, job.resource_id, job.definition_id).specification
        )
        assert isinstance(spec, DAGDefinition)
        validate_in(svc, s, p, spec)
        versions = worker.authorize(s, p, job)
        if job.request.get("engine_version") != __import__("polars").__version__:
            raise ApplicationError("engine_version", "Pinned execution engine unavailable", 503)
        run = s.get(DAGRun, (tenant, key))
        assert run is not None
        if (
            run.plan_digest
            != hashlib.sha256(
                json.dumps(run.plan, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        ):
            raise ApplicationError("plan_integrity", "Execution plan verification failed", 409)
        job.state, job.started_at = "RUNNING", job.started_at or clock(s)
        s.flush()
        fence(worker, s, p, key, token)
        run.cleaned_at = None
        run.state = "EXECUTING"
        run.execution_started_at = run.execution_started_at or clock(s)
        s.flush()
        deadline = run.execution_started_at + timedelta(seconds=limits.wall_seconds)
        inputs = list(
            s.scalars(
                select(ExecutionInput)
                .where(ExecutionInput.tenant_id == tenant, ExecutionInput.job_id == key)
                .order_by(ExecutionInput.name)
            )
        )
        for row in versions:
            if row in s:
                s.expunge(row)

    def renew() -> bool:
        return bool(worker.heartbeat(tenant, key, token))

    intermediate_bytes = 0
    manifest_bytes = 0
    started = time.monotonic()
    peak_memory, peak_disk = 0, 0
    with tempfile.TemporaryDirectory(prefix="foundry-dag-") as temporary:
        directory = Path(temporary)
        if sum(v.size for v in versions) > limits.temporary_bytes:
            raise ApplicationError("temporary_limit", "Input disk budget exceeded", 413)
        paths: dict[str, Path] = {}
        metadata: dict[str, Any] = {}
        for item, physical in zip(inputs, versions, strict=True):
            path = directory / ("input-" + str(len(paths)))
            worker.spool(physical, path, limits, renew)
            logical = datasets.dataset_metadata(p, item.dataset_id, item.version_id)
            paths[item.name] = path
            metadata[item.name] = {
                "format": logical.format,
                "schema": logical.result["schema"],
                "row_count": logical.result["row_count"],
                "checksum": physical.checksum,
            }
        nodes = {n.id: n for n in spec.nodes}
        consumers = dict.fromkeys([i.name for i in spec.inputs] + list(nodes), 0)
        for node in spec.nodes:
            for ref in node.inputs.values():
                consumers[ref] += 1
        for output in spec.outputs:
            consumers[output.source] += 1

        def release(ref: str) -> None:
            consumers[ref] -= 1
            if consumers[ref] == 0:
                paths[ref].unlink(missing_ok=True)

        for index, node_id in enumerate(topology(spec)):
            node = nodes[node_id]
            unit = directory / f"node-{index}"
            unit.mkdir()
            path = unit / "output.parquet"
            with svc.scope(p) as s:
                job = fence(worker, s, p, key, token)
                row = s.get(DAGNodeExecution, (tenant, key, node_id))
                assert row is not None
                previous = dict(row.result) if row.state == "COMPLETED" else None
                result_id = row.result_id
            if (
                previous is not None
                and result_id is not None
                and store.exists(ObjectKey(tenant, key, result_id))
            ):
                # Exact definition/checksums are fixed in immutable plan and input rows.
                if previous.get("input_checksums") != {
                    port: metadata[source]["checksum"] for port, source in node.inputs.items()
                }:
                    raise ApplicationError(
                        "intermediate_integrity", "Intermediate inputs do not match plan", 409
                    )
                download(store, ObjectKey(tenant, key, result_id), path, previous)
                result = previous
            else:
                with svc.scope(p) as s:
                    job = fence(worker, s, p, key, token)
                    row = s.get(DAGNodeExecution, (tenant, key, node_id))
                    assert row is not None
                    row.state, row.attempt, row.token = "RUNNING", job.attempts, token
                    row.started_at, row.completed_at, row.error = clock(s), None, None
                    # Persist key before I/O so interrupted uploads can be safely recovered/cleaned.
                    row.result_id = row.result_id or uuid5(key, node_id + run.plan_digest)
                    result_id = row.result_id
                body = Definition(
                    inputs=[
                        InputContract(name=port)
                        for port in ("input", "right")
                        if port in node.inputs
                    ],
                    steps=[node.config],
                )
                request = {
                    "specification": body.model_dump(mode="json"),
                    "inputs": [
                        {"name": port, "path": str(paths[source]), **metadata[source]}
                        for port, source in node.inputs.items()
                    ],
                }
                # Isolation watchdog measures the entire run directory, including sibling nodes.
                with worker.sessions.begin() as s:
                    remaining = int((deadline - clock(s)).total_seconds())
                child_limits = limits.model_copy(
                    update={"wall_seconds": max(1, min(limits.node_seconds, remaining))}
                )
                # All children use the run root for aggregate scratch accounting. Their own output
                # is moved immediately into this unit before another child is launched.
                result = isolated("pipeline", request, directory, child_limits, renew)
                if "error" in result:
                    with svc.scope(p) as s:
                        fence(worker, s, p, key, token)
                        row = s.get(DAGNodeExecution, (tenant, key, node_id))
                        assert row is not None
                        row.state, row.error, row.completed_at = (
                            "FAILED",
                            str(result["error"]),
                            clock(s),
                        )
                    raise ApplicationError(str(result["error"]), "DAG node execution failed", 409)
                clear_normalized(directory)
                (directory / "output.parquet").replace(path)
                result["dataset"]["preview"] = []
                result["input_checksums"] = {
                    port: metadata[source]["checksum"] for port, source in node.inputs.items()
                }
                if intermediate_bytes + result["size"] > limits.intermediate_bytes:
                    raise ApplicationError(
                        "intermediate_limit", "Intermediate budget exceeded", 413
                    )
                if manifest_bytes + len(json.dumps(result).encode()) > limits.manifest_bytes:
                    raise ApplicationError("manifest_limit", "DAG manifest budget exceeded", 413)
                assert result_id is not None
                put(store, ObjectKey(tenant, key, result_id), path, result)
                with svc.scope(p) as s:
                    fence(worker, s, p, key, token)
                    row = s.get(DAGNodeExecution, (tenant, key, node_id))
                    assert row is not None
                    row.state, row.result, row.completed_at = "COMPLETED", result, clock(s)
            peak_memory = max(peak_memory, result.get("metrics", {}).get("peak_memory_bytes", 0))
            peak_disk = max(peak_disk, result.get("metrics", {}).get("temporary_bytes", 0))
            intermediate_bytes += result["size"]
            manifest_bytes += len(json.dumps(result).encode())
            if intermediate_bytes > limits.intermediate_bytes:
                raise ApplicationError(
                    "intermediate_limit", "Intermediate storage budget exceeded", 413
                )
            paths[node_id] = path
            metadata[node_id] = {
                "format": "parquet",
                "schema": result["dataset"]["schema"],
                "row_count": result["dataset"]["row_count"],
                "checksum": result["checksum"],
            }
            for ref in node.inputs.values():
                release(ref)
        with svc.scope(p) as s:
            fence(worker, s, p, key, token)
            run = s.get(DAGRun, (tenant, key))
            assert run is not None
            run.state = "PREPARING"
        staged_bytes, rows = 0, 0
        for output in sorted(spec.outputs, key=lambda o: o.id):
            with svc.scope(p) as s:
                fence(worker, s, p, key, token)
                prepared = s.get(DAGPreparedOutput, (tenant, key, output.id))
                assert prepared is not None
                obj = ObjectKey(tenant, prepared.dataset_id, prepared.version_id)
                prepared_result = (
                    dict(prepared.result)
                    if prepared.state == "PREPARED" and store.exists(obj)
                    else None
                )
            if prepared_result is None:
                request = {
                    "specification": Definition(
                        inputs=[InputContract(name="source")], output_columns=output.columns
                    ).model_dump(mode="json"),
                    "inputs": [
                        {
                            "name": "source",
                            "path": str(paths[output.source]),
                            **metadata[output.source],
                        }
                    ],
                    "output_format": output.format,
                }
                with worker.sessions.begin() as s:
                    remaining = int((deadline - clock(s)).total_seconds())
                child_limits = limits.model_copy(
                    update={"wall_seconds": max(1, min(limits.node_seconds, remaining))}
                )
                result = isolated("pipeline", request, directory, child_limits, renew)
                if "error" in result:
                    raise ApplicationError(
                        "output_serialization", "Output serialization failed", 409
                    )
                clear_normalized(directory)
                file = directory / ("output." + output.format)
                if (
                    staged_bytes + result["size"] > limits.staged_bytes
                    or rows + result["dataset"]["row_count"] > limits.cumulative_output_rows
                ):
                    raise ApplicationError("output_limit", "Aggregate output budget exceeded", 413)
                if manifest_bytes + len(json.dumps(result).encode()) > limits.manifest_bytes:
                    raise ApplicationError("manifest_limit", "DAG manifest budget exceeded", 413)
                put(store, obj, file, result)
                file.unlink()
                with svc.scope(p) as s:
                    fence(worker, s, p, key, token)
                    prepared = s.get(DAGPreparedOutput, (tenant, key, output.id))
                    assert prepared is not None
                    prepared.state, prepared.result = "PREPARED", result
            else:
                result = prepared_result
                store.verify(obj, result["size"], result["checksum"])
            peak_memory = max(peak_memory, result.get("metrics", {}).get("peak_memory_bytes", 0))
            peak_disk = max(peak_disk, result.get("metrics", {}).get("temporary_bytes", 0))
            staged_bytes += result["size"]
            manifest_bytes += len(json.dumps(result).encode())
            rows += result["dataset"]["row_count"]
            if staged_bytes > limits.staged_bytes or rows > limits.cumulative_output_rows:
                raise ApplicationError("output_limit", "Aggregate output budget exceeded", 413)
            release(output.source)
        with svc.scope(p) as s:
            fence(worker, s, p, key, token)
            run = s.get(DAGRun, (tenant, key))
            assert run is not None
            run.state = "PREPARED"
        commit(
            worker,
            p,
            key,
            token,
            spec,
            {
                "intermediate_bytes": intermediate_bytes,
                "staged_output_bytes": staged_bytes,
                "output_rows": rows,
                "peak_memory_bytes": peak_memory,
                "temporary_bytes": peak_disk,
                "seconds": time.monotonic() - started,
            },
        )


def commit(
    worker: Any, p: Principal, key: UUID, token: UUID, spec: DAGDefinition, metrics: dict[str, Any]
) -> None:
    svc, datasets = worker.service, worker.service.datasets()
    # Objects are final immutable identities already; there is no unreliable post-commit move.
    with svc.scope(p) as s:
        job = fence(worker, s, p, key, token)
        worker.authorize(s, p, job)
        validate_in(svc, s, p, spec)
        run = s.get(DAGRun, (p.tenant_id, key))
        assert run is not None
        outputs = list(
            s.scalars(
                select(DAGPreparedOutput)
                .where(DAGPreparedOutput.tenant_id == p.tenant_id, DAGPreparedOutput.job_id == key)
                .order_by(DAGPreparedOutput.dataset_id)
                .with_for_update()
            )
        )
        if (
            run.state != "PREPARED"
            or len(outputs) != len(spec.outputs)
            or any(o.state != "PREPARED" for o in outputs)
        ):
            raise ApplicationError("publication_incomplete", "All outputs must be prepared", 409)
        for output in outputs:
            # Existing governed tenant/security transaction already serializes mutation; explicit
            # sorted resource locks document the append-version conflict policy.
            s.scalar(
                select(Resource)
                .where(Resource.tenant_id == p.tenant_id, Resource.id == output.dataset_id)
                .with_for_update()
            )
            datasets.storage().verify(
                ObjectKey(p.tenant_id, output.dataset_id, output.version_id),
                output.result["size"],
                output.result["checksum"],
            )
        for output in outputs:
            config = next(o for o in spec.outputs if o.id == output.output_id)
            if config.dataset_id is None:
                assert config.project_id is not None and config.name is not None
                # Governed resource creation remains in the same transaction as all versions.
                nested = datasets.__class__(
                    datasets.sessions, datasets.authorizer, datasets.settings, datasets.store
                )
                nested.transaction_session = s
                nested.create_preallocated(
                    p, config.project_id, output.dataset_id, CreateArtifact(name=config.name)
                )
            datasets.publish_prepared(
                s,
                p,
                output.dataset_id,
                output.version_id,
                config.format,
                output.result["size"],
                output.result["checksum"],
                output.result["dataset"],
                key,
            )
            output.state = "COMMITTED"
        run.state, run.commit_id = "COMMITTED", uuid4()
        s.flush()
        # Recheck the DB clock after storage verification/metadata work before decision.
        fence(worker, s, p, key, token)
        job.state, job.completed_at, job.metrics = "SUCCEEDED", clock(s), metrics
        job.token, job.lease_until = None, None
        svc.audit(s, p, "pipeline_dag_committed", key)
        s.flush()


def cleanup(worker: Any, tenant: UUID, key: UUID, *, repeat: bool = False) -> None:
    """Only terminal jobs; run-scoped intermediates never overlap committed artifacts."""
    with worker.sessions.begin() as s:
        job = s.get(ExecutionJob, (tenant, key), with_for_update=True)
        if job is None or job.state not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return
        run = s.get(DAGRun, (tenant, key))
        if run is None or (run.cleaned_at is not None and not repeat):
            return
        objects = [
            ObjectKey(tenant, key, n.result_id)
            for n in s.scalars(
                select(DAGNodeExecution).where(
                    DAGNodeExecution.tenant_id == tenant, DAGNodeExecution.job_id == key
                )
            )
            if n.result_id is not None
        ]
        if job.state != "SUCCEEDED":
            objects += [
                ObjectKey(tenant, o.dataset_id, o.version_id)
                for o in s.scalars(
                    select(DAGPreparedOutput).where(
                        DAGPreparedOutput.tenant_id == tenant, DAGPreparedOutput.job_id == key
                    )
                )
                if o.state != "COMMITTED"
            ]
        for obj in objects:
            worker.service.datasets().storage().delete(obj)
        run.cleaned_at = clock(s)
        if job.state != "SUCCEEDED":
            run.state = "ABANDONED"


def sweep(worker: Any) -> None:
    with worker.sessions() as s:
        rows = list(
            s.execute(
                select(DAGRun.tenant_id, DAGRun.job_id)
                .join(
                    ExecutionJob,
                    (ExecutionJob.tenant_id == DAGRun.tenant_id)
                    & (ExecutionJob.id == DAGRun.job_id),
                )
                .where(
                    (
                        DAGRun.cleaned_at.is_(None)
                        | (DAGRun.cleaned_at < clock(s) - timedelta(seconds=86400))
                    ),
                    ExecutionJob.state.in_(["SUCCEEDED", "FAILED", "CANCELLED"]),
                )
                .order_by(DAGRun.cleaned_at.asc().nulls_last())
                .limit(10)
            )
        )
    for tenant, key in rows:
        cleanup(worker, tenant, key, repeat=True)
