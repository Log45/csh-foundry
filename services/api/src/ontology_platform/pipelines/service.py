"""Governed definitions, run admission and visibility-filtered provenance."""

from typing import Any, cast
from uuid import UUID, uuid4

import polars as pl
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ontology_platform.artifacts.service import ArtifactService
from ontology_platform.branching.service import page
from ontology_platform.datasets.service import DatasetService
from ontology_platform.db.governance import missing
from ontology_platform.db.models import ExecutionInput, ExecutionJob, PipelineDefinition
from ontology_platform.errors import ApplicationError
from ontology_platform.execution.config import ExecutionSettings
from ontology_platform.pipelines.contracts import (
    Definition,
    DefinitionView,
    ExecutionJobView,
    InputVersion,
    StartRun,
)
from ontology_platform.projects.service import conflict
from ontology_platform.security.interfaces import Principal


class PipelineService(ArtifactService):
    resource_kind = "PIPELINE"

    def datasets(self) -> DatasetService:
        return DatasetService(self.sessions, self.authorizer, self.settings, self.store)

    def definition(self, s: Session, p: Principal, key: UUID, version: UUID) -> PipelineDefinition:
        self.artifact(s, p, key)
        row = s.get(PipelineDefinition, (p.tenant_id, key, version))
        if row is None:
            raise missing("Pipeline definition")
        return row

    def publish(self, p: Principal, key: UUID, spec: Definition) -> DefinitionView:
        with self.scope(p) as s:
            return self.publish_in(s, p, key, spec)

    def publish_in(self, s: Session, p: Principal, key: UUID, spec: Definition) -> DefinitionView:
        self.artifact(s, p, key, True)
        sequence = (
            s.scalar(
                select(func.max(PipelineDefinition.sequence)).where(
                    PipelineDefinition.tenant_id == p.tenant_id,
                    PipelineDefinition.pipeline_id == key,
                )
            )
            or 0
        )
        row = PipelineDefinition(
            tenant_id=p.tenant_id,
            pipeline_id=key,
            id=uuid4(),
            sequence=sequence + 1,
            specification=spec.model_dump(mode="json"),
            created_by=p.principal_id,
        )
        s.add(row)
        s.flush()
        self.audit(s, p, "pipeline_publish", row.id)
        return DefinitionView.model_validate(row)

    def definitions(
        self, p: Principal, key: UUID, limit: int = 50, offset: int = 0
    ) -> list[DefinitionView]:
        page(limit, offset)
        with self.scope(p) as s:
            self.artifact(s, p, key)
            return [
                DefinitionView.model_validate(r)
                for r in s.scalars(
                    select(PipelineDefinition)
                    .where(
                        PipelineDefinition.tenant_id == p.tenant_id,
                        PipelineDefinition.pipeline_id == key,
                    )
                    .order_by(PipelineDefinition.sequence.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ]

    def capacity(self, s: Session, p: Principal, limits: ExecutionSettings) -> None:
        # Tenant lock is already held; advisory lock serializes global admission with workers.
        from sqlalchemy import text

        s.execute(text("SELECT pg_advisory_xact_lock(14214001)"))
        count = (
            s.scalar(
                select(func.count())
                .select_from(ExecutionJob)
                .where(ExecutionJob.state.in_(["QUEUED", "ADMITTED", "RUNNING", "CANCELLING"]))
            )
            or 0
        )
        if count >= limits.queue_jobs:
            raise ApplicationError("queue_capacity", "Execution queue is full", 503)

    def start(self, p: Principal, key: UUID, body: StartRun) -> ExecutionJobView:
        limits = ExecutionSettings()
        datasets = self.datasets()
        with self.scope(p) as s:
            resource = self.artifact(s, p, key, True)
            definition = self.definition(s, p, key, body.definition_id)
            spec = Definition.model_validate(definition.specification)
            # Visual publications are executable only with their immutable authoring bindings.
            from ontology_platform.db.models import PipelineGraph
            from ontology_platform.pipelines.graph import Graph, compile_graph

            visual = s.get(PipelineGraph, (p.tenant_id, key, definition.id))
            if visual is not None:
                compiled = compile_graph(Graph.model_validate(visual.graph))

                def pins(items: list[InputVersion]) -> list[tuple[str, UUID, UUID]]:
                    return sorted((i.name, i.dataset_id, i.version_id) for i in items)

                if (
                    pins(body.inputs) != pins(compiled.inputs)
                    or body.output_dataset_id != compiled.output_dataset_id
                ):
                    raise conflict("Visual definition requires its published immutable bindings")

            if sorted(i.name for i in body.inputs) != sorted(i.name for i in spec.inputs):
                raise conflict("Inputs must match definition contracts exactly")
            datasets.artifact(s, p, body.output_dataset_id, True)
            self.capacity(s, p, limits)
            job = ExecutionJob(
                tenant_id=p.tenant_id,
                id=uuid4(),
                resource_id=key,
                project_id=resource.project_id,
                kind="PIPELINE",
                definition_id=definition.id,
                output_dataset_id=body.output_dataset_id,
                request=body.model_dump(mode="json")
                | {"engine": "polars", "engine_version": pl.__version__},
                principal=p.model_dump(mode="json"),
                limits=limits.model_dump(mode="json"),
            )
            s.add(job)
            s.flush()
            for item in body.inputs:
                row = datasets.record(s, p, item.dataset_id, item.version_id)
                physical = datasets.version(s, p, item.dataset_id, item.version_id)
                if row.state != "COMMITTED" or physical.state != "COMMITTED":
                    raise conflict("Inputs must be committed immutable versions")
                contract = next(c for c in spec.inputs if c.name == item.name)
                columns = {
                    c["name"]: c["logical_type"]
                    for c in cast(list[dict[str, Any]], row.result["schema"])
                }
                if any(columns.get(c) != t for c, t in contract.columns.items()):
                    raise conflict("Input schema contract mismatch")
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
            self.audit(s, p, "pipeline_run_queue", job.id)
            return ExecutionJobView.model_validate(job)

    def job(self, s: Session, p: Principal, key: UUID) -> ExecutionJob:
        row = s.get(ExecutionJob, (p.tenant_id, key))
        if row is None:
            raise missing("Execution job")
        self.resource(s, p, row.resource_id)
        return row

    def job_view(self, s: Session, p: Principal, row: ExecutionJob) -> ExecutionJobView:
        view = ExecutionJobView.model_validate(row)
        if row.output_dataset_id is not None:
            try:
                self.datasets().artifact(s, p, row.output_dataset_id)
            except ApplicationError as exc:
                if exc.status_code not in {403, 404}:
                    raise
                view.output_dataset_id, view.output_version_id = None, None
        return view

    def status(self, p: Principal, key: UUID) -> ExecutionJobView:
        with self.scope(p) as s:
            return self.job_view(s, p, self.job(s, p, key))

    def history(self, p: Principal, key: UUID, limit: int, offset: int) -> list[ExecutionJobView]:
        page(limit, offset)
        with self.scope(p) as s:
            self.resource(s, p, key)
            return [
                self.job_view(s, p, j)
                for j in s.scalars(
                    select(ExecutionJob)
                    .where(ExecutionJob.tenant_id == p.tenant_id, ExecutionJob.resource_id == key)
                    .order_by(ExecutionJob.created_at.desc(), ExecutionJob.id)
                    .limit(limit)
                    .offset(offset)
                )
            ]

    def change(self, p: Principal, key: UUID, retry: bool = False) -> ExecutionJobView:
        from ontology_platform.db.session import clock

        with self.scope(p) as s:
            row = self.job(s, p, key)
            resource = self.resource(s, p, row.resource_id)
            self.project(s, p, resource.project_id, write=True)
            if row.principal["principal_id"] != p.principal_id:
                raise ApplicationError(
                    "forbidden", "Only the initiating principal can change a job", 403
                )
            if retry:
                if row.error not in {
                    "infrastructure",
                    "storage_transient",
                    "storage_missing",
                    "lease_expired",
                    "execution_limit",
                    "memory_limit",
                    "temporary_limit",
                }:
                    raise conflict("Permanent failures require corrected inputs or a new run")
                if row.state != "FAILED" or row.attempts >= ExecutionSettings().attempts:
                    raise conflict("Run is not retryable")
                self.capacity(s, p, ExecutionSettings())
                row.state, row.completed_at, row.error = "QUEUED", None, None
            elif row.state == "QUEUED":
                row.state, row.completed_at = "CANCELLED", clock(s)
            elif row.state in {"ADMITTED", "RUNNING"}:
                row.state = "CANCELLING"
            self.audit(s, p, "execution_retry" if retry else "execution_cancel", row.id)
            s.flush()
            return self.job_view(s, p, row)

    def lineage(
        self, p: Principal, dataset: UUID, version: UUID, limit: int = 50
    ) -> list[dict[str, object]]:
        page(limit, 0)
        with self.scope(p) as s:
            self.datasets().record(s, p, dataset, version)
            jobs = list(
                s.scalars(
                    select(ExecutionJob)
                    .where(
                        ExecutionJob.tenant_id == p.tenant_id,
                        ExecutionJob.output_dataset_id == dataset,
                        ExecutionJob.output_version_id == version,
                        ExecutionJob.state == "SUCCEEDED",
                    )
                    .limit(limit)
                )
            )
            result = []
            for job in jobs:
                inputs = []
                for item in s.scalars(
                    select(ExecutionInput)
                    .where(ExecutionInput.tenant_id == p.tenant_id, ExecutionInput.job_id == job.id)
                    .limit(16)
                ):
                    try:
                        self.datasets().record(s, p, item.dataset_id, item.version_id)
                    except ApplicationError as exc:
                        if exc.status_code in {403, 404}:
                            continue
                        raise
                    inputs.append(
                        {
                            "dataset_id": str(item.dataset_id),
                            "version_id": str(item.version_id),
                            "artifact_version_id": str(item.version_id),
                            "checksum": item.checksum,
                        }
                    )
                entry: dict[str, object] = {
                    "run_id": str(job.id),
                    "inputs": inputs,
                    "output_version_id": str(version),
                    "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                }
                try:
                    self.artifact(s, p, job.resource_id)
                except ApplicationError as exc:
                    if exc.status_code not in {403, 404}:
                        raise
                else:
                    entry["pipeline_id"], entry["definition_id"] = (
                        str(job.resource_id),
                        str(job.definition_id),
                    )
                    definition = self.definition(s, p, job.resource_id, job.definition_id)  # type: ignore[arg-type]
                    entry["specification"] = definition.specification
                    entry["engine"] = job.request.get("engine")
                    entry["engine_version"] = job.request.get("engine_version")
                    entry["initiating_principal"] = job.principal.get("principal_id")
                    entry["created_at"] = job.created_at.isoformat()
                    entry["started_at"] = job.started_at.isoformat() if job.started_at else None
                entry["output_artifact_version_id"] = str(version)
                result.append(entry)
            return result
