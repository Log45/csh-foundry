"""DAG admission and authorization through the existing pipeline/dataset services."""

import hashlib
import json
from typing import Any, cast
from uuid import UUID, uuid4

import polars as pl
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ontology_platform.db.models import (
    DAGNodeExecution,
    DAGPreparedOutput,
    DAGRun,
    ExecutionInput,
    ExecutionJob,
)
from ontology_platform.errors import ApplicationError
from ontology_platform.execution.config import ExecutionSettings
from ontology_platform.pipelines.contracts import (
    ExecutionJobView,
    NodeExecutionView,
    OutputPublicationView,
    StartRun,
)
from ontology_platform.pipelines.dag import DAGDefinition, canonical, topology
from ontology_platform.pipelines.engine import dag_frames, schema_dtype
from ontology_platform.projects.service import conflict
from ontology_platform.security.interfaces import Principal


def validate_in(svc: Any, s: Session, p: Principal, spec: DAGDefinition) -> dict[str, pl.LazyFrame]:
    datasets = svc.datasets()
    frames = {}
    for item in spec.inputs:
        try:
            datasets.artifact(s, p, item.dataset_id)
            logical = datasets.record(s, p, item.dataset_id, item.version_id)
            physical = datasets.version(s, p, item.dataset_id, item.version_id)
        except ApplicationError as exc:
            if exc.status_code not in {403, 404}:
                raise
            raise ApplicationError(
                "input_unavailable", "Input is missing or unauthorized", 409
            ) from exc
        if logical.state != "COMMITTED" or physical.state != "COMMITTED":
            raise ApplicationError(
                "input_unavailable", "Inputs require committed immutable versions", 409
            )
        columns = logical.result["schema"]
        try:
            frames[item.name] = pl.LazyFrame(
                schema={c["name"]: schema_dtype(c["logical_type"]) for c in columns}
            )
        except (KeyError, ValueError, TypeError, pl.exceptions.PolarsError) as exc:
            raise ApplicationError(
                "schema_mismatch", "Unsupported source schema type", 422
            ) from exc
    for output in spec.outputs:
        try:
            if output.dataset_id is not None:
                datasets.artifact(s, p, output.dataset_id, True)
            else:
                assert output.project_id is not None
                svc.project(s, p, output.project_id, write=True)
        except ApplicationError as exc:
            if exc.status_code not in {403, 404}:
                raise
            raise ApplicationError(
                "output_unavailable", "Output target is unavailable or unauthorized", 409
            ) from exc
    try:
        return dag_frames(spec, frames, schema_only=True)
    except (ValueError, pl.exceptions.PolarsError) as exc:
        raise ApplicationError(
            "schema_mismatch", "DAG schema or column contract mismatch", 422
        ) from exc


def admit(
    svc: Any, s: Session, p: Principal, key: UUID, spec: DAGDefinition, body: StartRun
) -> ExecutionJobView:
    limits = ExecutionSettings()
    if len(spec.nodes) > limits.dag_nodes or len(spec.outputs) > limits.dag_outputs:
        raise conflict("DAG exceeds configured admission limits")
    expected = sorted((i.name, i.dataset_id, i.version_id) for i in spec.inputs)
    actual = sorted((i.name, i.dataset_id, i.version_id) for i in body.inputs)
    if expected != actual or body.output_dataset_id not in {None, spec.outputs[0].dataset_id}:
        raise conflict("DAG execution requires exact published bindings")
    validate_in(svc, s, p, spec)
    resource = svc.artifact(s, p, key, True)
    retained = (
        s.scalar(
            select(func.count())
            .select_from(DAGNodeExecution)
            .where(DAGNodeExecution.tenant_id == p.tenant_id)
        )
        or 0
    )
    if retained + len(spec.nodes) > limits.retained_nodes:
        raise conflict("Tenant node history retention budget exceeded")
    svc.capacity(s, p, limits)
    reservations = {o.id: (o.dataset_id or uuid4(), uuid4()) for o in spec.outputs}
    job = ExecutionJob(
        tenant_id=p.tenant_id,
        id=uuid4(),
        resource_id=key,
        project_id=resource.project_id,
        kind="PIPELINE",
        definition_id=body.definition_id,
        output_dataset_id=None,
        request=body.model_dump(mode="json")
        | {"format_version": 2, "engine": "polars", "engine_version": pl.__version__},
        principal=p.model_dump(mode="json"),
        limits=limits.model_dump(mode="json"),
    )
    # The legacy primary output FK requires an existing target. v2 has no primary target;
    # the additive migration permits NULL specifically for format_version=2 jobs.
    s.add(job)
    s.flush()
    checksums = {}
    for item in spec.inputs:
        physical = svc.datasets().version(s, p, item.dataset_id, item.version_id)
        checksums[item.name] = physical.checksum
        s.add(
            ExecutionInput(
                tenant_id=p.tenant_id,
                job_id=job.id,
                name=item.name,
                dataset_id=item.dataset_id,
                version_id=item.version_id,
                checksum=physical.checksum,
            )
        )
    plan = {
        "specification": canonical(spec),
        "checksums": checksums,
        "order": topology(spec),
        "engine_version": pl.__version__,
        "limits": limits.model_dump(mode="json"),
        "tenant_id": str(p.tenant_id),
    }
    digest = hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    run = DAGRun(tenant_id=p.tenant_id, job_id=job.id, plan_digest=digest, plan=plan)
    s.add(run)
    s.flush()
    for node in spec.nodes:
        s.add(DAGNodeExecution(tenant_id=p.tenant_id, job_id=job.id, node_id=node.id))
    for output in spec.outputs:
        dataset_id, version_id = reservations[output.id]
        s.add(
            DAGPreparedOutput(
                tenant_id=p.tenant_id,
                job_id=job.id,
                output_id=output.id,
                dataset_id=dataset_id,
                version_id=version_id,
            )
        )
    svc.audit(s, p, "pipeline_dag_queued", job.id)
    s.flush()
    return ExecutionJobView.model_validate(job)


def enrich(
    svc: Any, s: Session, p: Principal, job: ExecutionJob, view: ExecutionJobView
) -> ExecutionJobView:
    run = s.get(DAGRun, (p.tenant_id, job.id))
    if run is None:
        return view
    view.plan_digest, view.publication_state = run.plan_digest, run.state
    from ontology_platform.errors import ApplicationError

    bindings_visible = True
    try:
        read_bindings(svc, s, p, DAGDefinition.model_validate(run.plan["specification"]))
    except ApplicationError as exc:
        if exc.status_code not in {403, 404}:
            raise
        bindings_visible = False
    # Node identities and staging counts must not disclose hidden bindings or siblings.
    view.nodes = [
        NodeExecutionView(node_id=n.node_id, state=n.state, attempt=n.attempt, error=n.error)
        for n in s.scalars(
            select(DAGNodeExecution)
            .where(DAGNodeExecution.tenant_id == p.tenant_id, DAGNodeExecution.job_id == job.id)
            .order_by(DAGNodeExecution.node_id)
            .limit(100)
        )
    ]
    if not bindings_visible:
        view.nodes = []
        view.plan_digest = None
    for output in s.scalars(
        select(DAGPreparedOutput)
        .where(DAGPreparedOutput.tenant_id == p.tenant_id, DAGPreparedOutput.job_id == job.id)
        .order_by(DAGPreparedOutput.output_id)
        .limit(16)
    ):
        if bindings_visible and output.state in {"PREPARED", "COMMITTED"}:
            view.prepared_output_count += 1
        if output.state != "COMMITTED":
            continue
        try:
            svc.datasets().artifact(s, p, output.dataset_id)
        except Exception as exc:
            from ontology_platform.errors import ApplicationError

            if isinstance(exc, ApplicationError) and exc.status_code in {403, 404}:
                # Aggregate metrics can otherwise reveal private sibling row counts/sizes.
                view.metrics = {}
                continue
            raise
        view.outputs.append(
            OutputPublicationView(
                output_id=output.output_id,
                dataset_id=output.dataset_id,
                version_id=output.version_id,
                state=output.state,
            )
        )
    return view


def lineage(
    svc: Any, s: Session, p: Principal, dataset: UUID, version: UUID
) -> list[dict[str, object]]:
    """One output's ancestors only; no sibling identity or unauthorized graph disclosure."""
    from ontology_platform.errors import ApplicationError

    rows = s.scalars(
        select(DAGPreparedOutput)
        .where(
            DAGPreparedOutput.tenant_id == p.tenant_id,
            DAGPreparedOutput.dataset_id == dataset,
            DAGPreparedOutput.version_id == version,
            DAGPreparedOutput.state == "COMMITTED",
        )
        .limit(50)
    )
    entries = []
    for output in rows:
        job = s.get(ExecutionJob, (p.tenant_id, output.job_id))
        run = s.get(DAGRun, (p.tenant_id, output.job_id))
        if job is None or run is None or job.state != "SUCCEEDED":
            continue
        spec = DAGDefinition.model_validate(run.plan["specification"])
        config = next(o for o in spec.outputs if o.id == output.output_id)
        nodes = {n.id: n for n in spec.nodes}
        ancestors = {config.source}
        pending = [config.source]
        while pending:
            current = pending.pop()
            for ref in nodes[current].inputs.values() if current in nodes else []:
                if ref not in ancestors:
                    ancestors.add(ref)
                    pending.append(ref)
        inputs = []
        identities: set[tuple[UUID, UUID]] = set()
        all_visible = True
        for item in spec.inputs:
            if item.name not in ancestors:
                continue
            try:
                svc.datasets().record(s, p, item.dataset_id, item.version_id)
            except ApplicationError as exc:
                if exc.status_code not in {403, 404}:
                    raise
                all_visible = False
                continue
            if (item.dataset_id, item.version_id) in identities:
                continue
            identities.add((item.dataset_id, item.version_id))
            inputs.append(
                {
                    "dataset_id": str(item.dataset_id),
                    "version_id": str(item.version_id),
                    "checksum": cast(dict[str, Any], run.plan["checksums"])[item.name],
                }
            )
        entry: dict[str, object] = {
            "run_id": str(job.id),
            "output_version_id": str(version),
            "inputs": inputs,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }
        try:
            svc.artifact(s, p, job.resource_id)
        except ApplicationError as exc:
            if exc.status_code not in {403, 404}:
                raise
        else:
            entry.update(
                {
                    "pipeline_id": str(job.resource_id),
                    "definition_id": str(job.definition_id),
                    "plan_digest": run.plan_digest,
                }
            )
            if all_visible:
                entry["output_id"] = output.output_id
                entry["direct_dependencies"] = [config.source]
                entry["nodes"] = [
                    n.model_dump(mode="json") for n in spec.nodes if n.id in ancestors
                ]
        entries.append(entry)
    return entries


def read_bindings(svc: Any, s: Session, p: Principal, spec: DAGDefinition) -> None:
    """A pipeline share does not grant disclosure of private immutable binding metadata."""
    for item in spec.inputs:
        svc.datasets().record(s, p, item.dataset_id, item.version_id)
    for output in spec.outputs:
        if output.dataset_id is not None:
            svc.datasets().artifact(s, p, output.dataset_id)
        else:
            assert output.project_id is not None
            svc.project(s, p, output.project_id)
