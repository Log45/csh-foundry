"""Dataset metadata publication composes the governed immutable artifact transport."""

from datetime import UTC, datetime
from typing import Any, BinaryIO
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ontology_platform.artifacts.contracts import ArtifactVersionView, InitiateUpload
from ontology_platform.artifacts.service import ArtifactService
from ontology_platform.branching.service import page
from ontology_platform.datasets.contracts import DatasetPreview, DatasetVersionView, InitiateDataset
from ontology_platform.datasets.parser import validate
from ontology_platform.db.governance import missing
from ontology_platform.db.models import DatasetVersion, ExecutionJob
from ontology_platform.pipelines.contracts import ExecutionJobView
from ontology_platform.projects.service import conflict
from ontology_platform.security.interfaces import Principal


class DatasetService(ArtifactService):
    resource_kind = "DATASET"

    def user_version(self, s: Session, p: Principal, key: UUID, version: UUID) -> None:
        # Prior-head upgrade tests have no execution tables and cannot contain reserved outputs.
        if (
            s.scalar(text("SELECT to_regclass(format('%I.execution_jobs', current_schema()))"))
            is None
        ):
            return
        reserved = s.scalar(
            select(ExecutionJob.id).where(
                ExecutionJob.tenant_id == p.tenant_id,
                ExecutionJob.output_dataset_id == key,
                ExecutionJob.output_version_id == version,
            )
        )
        if reserved is not None:
            raise conflict("Pipeline outputs can only be published by their fenced run")

    def prepare_upload(self, p: Principal, key: UUID, version: UUID) -> ArtifactVersionView:
        with self.scope(p) as s:
            self.artifact(s, p, key, True)
            self.user_version(s, p, key, version)
        return super().prepare_upload(p, key, version)

    def upload(
        self, p: Principal, key: UUID, version: UUID, source: BinaryIO, size: int, checksum: str
    ) -> ArtifactVersionView:
        with self.scope(p) as s:
            self.artifact(s, p, key, True)
            self.user_version(s, p, key, version)
        return super().upload(p, key, version, source, size, checksum)

    def finalize(self, p: Principal, key: UUID, version: UUID) -> ArtifactVersionView:
        with self.scope(p) as s:
            self.artifact(s, p, key, True)
            physical = self.version(s, p, key, version)
            if physical.state == "COMMITTED":
                return ArtifactVersionView.model_validate(physical)
            self.user_version(s, p, key, version)
        return super().finalize(p, key, version)

    def record(self, s: Session, p: Principal, key: UUID, version: UUID) -> DatasetVersion:
        self.artifact(s, p, key)
        row = s.get(DatasetVersion, (p.tenant_id, key, version))
        if row is None:
            raise missing("Dataset version")
        return row

    def view(self, s: Session, p: Principal, key: UUID, version: UUID) -> DatasetVersionView:
        row = self.record(s, p, key, version)
        artifact = ArtifactVersionView.model_validate(self.version(s, p, key, version))
        return DatasetVersionView(
            **(
                artifact.model_dump()
                | {
                    "state": row.state,
                    "artifact_state": artifact.state,
                    "format": row.format,
                    "result": {k: v for k, v in row.result.items() if k != "preview"},
                    "validated_at": row.finalized_at,
                }
            )
        )

    def initiate_dataset(
        self, p: Principal, key: UUID, body: InitiateDataset
    ) -> DatasetVersionView:
        from ontology_platform.errors import ApplicationError
        from ontology_platform.execution.config import ExecutionSettings

        if body.size > ExecutionSettings().source_bytes:
            raise ApplicationError(
                "upload_too_large", "Dataset exceeds configured source limit", 413
            )
        # One transaction reserves both records. Reuse artifact sequence/storage implementation
        # with a session bound to the existing governed transaction, avoiding an orphan window.
        with self.scope(p) as s:
            self.artifact(s, p, key, True)
            nested = DatasetService(self.sessions, self.authorizer, self.settings, self.store)
            nested.transaction_session = s
            artifact = nested.initiate(
                p, key, InitiateUpload(**body.model_dump(exclude={"format"}))
            )
            s.add(
                DatasetVersion(
                    tenant_id=p.tenant_id, artifact_id=key, id=artifact.id, format=body.format
                )
            )
            s.flush()
            self.audit(s, p, "dataset_version_initiate", artifact.id)
            return self.view(s, p, key, artifact.id)

    def enqueue_validation(self, p: Principal, key: UUID, version: UUID) -> ExecutionJobView:
        from ontology_platform.execution.config import ExecutionSettings
        from ontology_platform.pipelines.contracts import ExecutionJobView
        from ontology_platform.pipelines.service import PipelineService

        limits = ExecutionSettings()
        with self.scope(p) as s:
            resource = self.artifact(s, p, key, True)
            self.user_version(s, p, key, version)
            logical = self.record(s, p, key, version)
            previous = s.scalar(
                select(ExecutionJob).where(
                    ExecutionJob.tenant_id == p.tenant_id,
                    ExecutionJob.resource_id == key,
                    ExecutionJob.validation_version_id == version,
                )
            )
            if previous is not None:
                return ExecutionJobView.model_validate(previous)
            if logical.state != "PENDING":
                raise conflict("Dataset already has a terminal validation result")
            PipelineService(self.sessions, self.authorizer, self.settings, self.store).capacity(
                s, p, limits
            )
            row = ExecutionJob(
                tenant_id=p.tenant_id,
                id=uuid4(),
                resource_id=key,
                project_id=resource.project_id,
                kind="VALIDATION",
                validation_version_id=version,
                request={},
                principal=p.model_dump(mode="json"),
                limits=limits.model_dump(mode="json"),
            )
            s.add(row)
            s.flush()
            from ontology_platform.security.job_grants import create as create_job_grant

            create_job_grant(s, self.authorizer, p, row)
            self.audit(s, p, "dataset_validation_queued", row.id)
            return ExecutionJobView.model_validate(row)

    def finalize_dataset(self, p: Principal, key: UUID, version: UUID) -> DatasetVersionView:
        with self.scope(p) as s:
            self.artifact(s, p, key, True)
            previous = self.view(s, p, key, version)
            if previous.state != "PENDING":
                return previous
            self.user_version(s, p, key, version)
        if previous.size > 8 * 1024**2:
            self.enqueue_validation(p, key, version)
            return self.dataset_metadata(p, key, version)
        # Small-file compatibility remains available; explicit /validate always queues.
        self.finalize(p, key, version)
        previous = self.dataset_metadata(p, key, version)
        if previous.state != "PENDING":
            return previous
        source, _ = self.download(p, key, version)
        with source:
            result = validate(source, previous.format)
        with self.scope(p) as s:
            self.artifact(s, p, key, True)
            row = self.record(s, p, key, version)
            if row.state != "PENDING":
                return self.view(s, p, key, version)
            row.result = result
            row.state = "FAILED" if "error" in result else "COMMITTED"
            row.finalized_at = datetime.now(UTC)
            s.flush()
            self.audit(s, p, "dataset_validation_" + row.state.lower(), version)
            return self.view(s, p, key, version)

    def dataset_versions(
        self, p: Principal, key: UUID, limit: int, offset: int
    ) -> list[DatasetVersionView]:
        page(limit, offset)
        versions = self.versions(p, key, limit, offset)
        with self.scope(p) as s:
            self.artifact(s, p, key)
            return [self.view(s, p, key, item.id) for item in versions]

    def dataset_metadata(self, p: Principal, key: UUID, version: UUID) -> DatasetVersionView:
        with self.scope(p) as s:
            return self.view(s, p, key, version)

    def preview(self, p: Principal, key: UUID, version: UUID, limit: int = 20) -> DatasetPreview:
        if not 1 <= limit <= 100:
            raise conflict("Preview limit must be between 1 and 100")
        with self.scope(p) as s:
            row = self.record(s, p, key, version)
            if row.state != "COMMITTED":
                raise conflict("Only validated committed dataset versions have previews")
            result = row.result
            preview = DatasetPreview.model_validate(
                {
                    "columns": result["schema"],
                    "rows": result["preview"],
                    "row_count": result["row_count"],
                }
            )
            self.audit(s, p, "dataset_preview", version)
            preview.rows = preview.rows[:limit]
            return preview

    def publish_prepared(
        self,
        s: Session,
        p: Principal,
        dataset_id: UUID,
        version_id: UUID,
        output_format: str,
        size: int,
        checksum: str,
        result: dict[str, Any],
        run_id: UUID,
    ) -> None:
        """Register already verified immutable bytes inside the caller's fenced transaction."""
        from sqlalchemy import func

        from ontology_platform.artifacts.storage import ObjectKey
        from ontology_platform.db.models import ArtifactVersion
        from ontology_platform.db.session import clock

        self.artifact(s, p, dataset_id, True)
        sequence = (
            s.scalar(
                select(func.max(ArtifactVersion.sequence)).where(
                    ArtifactVersion.tenant_id == p.tenant_id,
                    ArtifactVersion.artifact_id == dataset_id,
                )
            )
            or 0
        )
        physical = ArtifactVersion(
            tenant_id=p.tenant_id,
            artifact_id=dataset_id,
            id=version_id,
            sequence=sequence + 1,
            backend=self.storage().backend,
            bucket=self.settings.bucket,
            object_key=str(ObjectKey(p.tenant_id, dataset_id, version_id)),
            size=size,
            checksum=checksum,
            filename=f"pipeline-output.{output_format}",
            created_by=p.principal_id,
            provenance={"source": "pipeline-run:" + str(run_id)},
        )
        s.add(physical)
        s.flush()
        logical = DatasetVersion(
            tenant_id=p.tenant_id, artifact_id=dataset_id, id=version_id, format=output_format
        )
        s.add(logical)
        s.flush()
        physical.state, physical.committed_at = "COMMITTED", clock(s)
        s.flush()
        logical.state, logical.result, logical.finalized_at = "COMMITTED", result, clock(s)
        s.flush()
        self.audit(s, p, "dataset_pipeline_committed", version_id)
