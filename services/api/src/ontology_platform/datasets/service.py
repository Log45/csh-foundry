"""Dataset metadata publication composes the governed immutable artifact transport."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from ontology_platform.artifacts.contracts import ArtifactVersionView, InitiateUpload
from ontology_platform.artifacts.service import ArtifactService
from ontology_platform.branching.service import page
from ontology_platform.datasets.contracts import DatasetPreview, DatasetVersionView, InitiateDataset
from ontology_platform.datasets.parser import validate
from ontology_platform.db.governance import missing
from ontology_platform.db.models import DatasetVersion
from ontology_platform.projects.service import conflict
from ontology_platform.security.interfaces import Principal


class DatasetService(ArtifactService):
    resource_kind = "DATASET"

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

    def finalize_dataset(self, p: Principal, key: UUID, version: UUID) -> DatasetVersionView:
        # Artifact commit is deliberately durable before validation; retry resumes this boundary.
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
