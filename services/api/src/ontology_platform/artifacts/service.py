"""Artifact state machine composes Project governance with immutable byte storage."""

import hashlib
import tempfile
from datetime import UTC, datetime, timedelta
from typing import BinaryIO
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ontology_platform.artifacts.config import StorageSettings
from ontology_platform.artifacts.contracts import (
    ArtifactVersionView,
    CleanupResult,
    CreateArtifact,
    InitiateUpload,
    PresignedAccess,
)
from ontology_platform.artifacts.storage import ArtifactStore, Failure, ObjectKey, StorageError
from ontology_platform.branching.service import page
from ontology_platform.db.governance import missing
from ontology_platform.db.models import ArtifactVersion, Resource
from ontology_platform.errors import ApplicationError
from ontology_platform.projects.contracts import ResourceView
from ontology_platform.projects.service import ProjectService, conflict
from ontology_platform.security.interfaces import Authorizer, Principal


class ArtifactService(ProjectService):
    resource_kind = "ARTIFACT"

    def __init__(
        self,
        sessions: sessionmaker[Session],
        authorizer: Authorizer,
        settings: StorageSettings,
        store: ArtifactStore | None,
    ):
        super().__init__(sessions, authorizer)
        self.settings, self.store = settings, store

    def storage(self) -> ArtifactStore:
        if self.store is None:
            raise ApplicationError("storage_disabled", "Artifact storage is unavailable", 503)
        return self.store

    def artifact(self, s: Session, p: Principal, key: UUID, write: bool = False) -> Resource:
        row = self.resource(s, p, key)
        if row.resource_type != self.resource_kind:
            raise missing("Artifact")
        if write:
            self.project(s, p, row.project_id, write=True)
        return row

    def version(self, s: Session, p: Principal, key: UUID, version: UUID) -> ArtifactVersion:
        row = s.get(ArtifactVersion, (p.tenant_id, key, version))
        if row is None:
            raise missing("Artifact version")
        return row

    def key(self, row: ArtifactVersion) -> ObjectKey:
        key = ObjectKey(row.tenant_id, row.artifact_id, row.id)
        # Never read historical objects with a changed backend/bucket configuration.
        if (
            row.backend != self.storage().backend
            or row.bucket != self.settings.bucket
            or row.object_key != str(key)
        ):
            raise StorageError(Failure.CONFIGURATION)
        return key

    def create(self, p: Principal, project: UUID, body: CreateArtifact) -> ResourceView:
        return self.create_preallocated(p, project, uuid4(), body)

    def create_preallocated(
        self, p: Principal, project: UUID, identity: UUID, body: CreateArtifact
    ) -> ResourceView:
        if self.resource_kind not in {"FUNCTION", "AUTOMATION", "PIPELINE"}:
            self.storage()
        with self.scope(p) as s:
            from ontology_platform.security.job_grants import resource_check

            resource_check(s, p, identity)
            self.project(s, p, project, write=True)
            self.destination(s, p, project, body.folder_id)
            row = Resource(
                tenant_id=p.tenant_id,
                id=identity,
                project_id=project,
                resource_type=self.resource_kind,
                **body.model_dump(),
                created_by=p.principal_id,
                updated_by=p.principal_id,
            )
            s.add(row)
            s.flush()
            self.audit(s, p, "artifact_create", row.id)
            return ResourceView.model_validate(row)

    def initiate(self, p: Principal, key: UUID, body: InitiateUpload) -> ArtifactVersionView:
        self.storage()
        if body.size > self.settings.max_bytes:
            raise ApplicationError("upload_too_large", "Artifact exceeds upload limit", 413)
        with self.scope(p) as s:
            self.artifact(s, p, key, True)
            sequence = (
                s.scalar(
                    select(func.max(ArtifactVersion.sequence)).where(
                        ArtifactVersion.tenant_id == p.tenant_id, ArtifactVersion.artifact_id == key
                    )
                )
                or 0
            )
            version = uuid4()
            row = ArtifactVersion(
                tenant_id=p.tenant_id,
                artifact_id=key,
                id=version,
                sequence=sequence + 1,
                backend=self.storage().backend,
                bucket=self.settings.bucket,
                object_key=str(ObjectKey(p.tenant_id, key, version)),
                size=body.size,
                checksum=body.checksum,
                filename=body.filename,
                created_by=p.principal_id,
                provenance={"source": body.source},
            )
            s.add(row)
            s.flush()
            self.audit(s, p, "artifact_upload_initiate", version)
            return ArtifactVersionView.model_validate(row)

    def prepare_upload(self, p: Principal, key: UUID, version: UUID) -> ArtifactVersionView:
        with self.scope(p) as s:
            self.artifact(s, p, key, True)
            row = self.version(s, p, key, version)
            if row.state != "PENDING":
                raise conflict("Only pending versions accept bytes")
            self.key(row)
            return ArtifactVersionView.model_validate(row)

    def upload(
        self, p: Principal, key: UUID, version: UUID, source: BinaryIO, size: int, checksum: str
    ) -> ArtifactVersionView:
        with self.scope(p) as s:
            self.artifact(s, p, key, True)
            row = self.version(s, p, key, version)
            if row.state != "PENDING":
                raise conflict("Only pending versions accept bytes")
            if row.size != size or row.checksum != checksum:
                raise StorageError(Failure.INTEGRITY)
            obj = self.key(row)
        # Immutable addresses make transfer retry safe without a broad governance lock.
        self.storage().abort_pending(obj)
        if self.storage().exists(obj):
            self.storage().verify(obj, size, checksum)
        else:
            try:
                self.storage().put(obj, source, size, checksum)
            except StorageError as exc:
                if exc.category != Failure.EXISTS:
                    raise
                self.storage().verify(obj, size, checksum)
        with self.scope(p) as s:
            self.artifact(s, p, key, True)
            row = self.version(s, p, key, version)
            if row.state not in {"PENDING", "COMMITTED"}:
                raise conflict("Version no longer accepts bytes")
            self.audit(s, p, "artifact_bytes_verified", version)
            return ArtifactVersionView.model_validate(row)

    def finalize(self, p: Principal, key: UUID, version: UUID) -> ArtifactVersionView:
        with self.scope(p) as s:
            self.artifact(s, p, key, True)
            row = self.version(s, p, key, version)
            if row.state == "COMMITTED":
                return ArtifactVersionView.model_validate(row)
            if row.state != "PENDING":
                raise conflict("Version cannot be finalized")
            obj, size, checksum = self.key(row), row.size, row.checksum
        self.storage().verify(obj, size, checksum)
        self.storage().abort_pending(obj)
        with self.scope(p) as s:
            self.artifact(s, p, key, True)
            row = self.version(s, p, key, version)
            if row.state == "COMMITTED":
                return ArtifactVersionView.model_validate(row)
            if row.state != "PENDING":
                raise conflict("Version cannot be finalized")
            row.state, row.committed_at = "COMMITTED", datetime.now(UTC)
            s.flush()
            self.audit(s, p, "artifact_commit", version)
            return ArtifactVersionView.model_validate(row)

    def versions(
        self, p: Principal, key: UUID, limit: int = 50, offset: int = 0
    ) -> list[ArtifactVersionView]:
        page(limit, offset)
        with self.scope(p) as s:
            self.artifact(s, p, key)
            rows = s.scalars(
                select(ArtifactVersion)
                .where(ArtifactVersion.tenant_id == p.tenant_id, ArtifactVersion.artifact_id == key)
                .order_by(ArtifactVersion.sequence.desc())
                .limit(limit)
                .offset(offset)
            )
            return [ArtifactVersionView.model_validate(row) for row in rows]

    def metadata(self, p: Principal, key: UUID, version: UUID) -> ArtifactVersionView:
        with self.scope(p) as s:
            self.artifact(s, p, key)
            return ArtifactVersionView.model_validate(self.version(s, p, key, version))

    def download(self, p: Principal, key: UUID, version: UUID) -> tuple[BinaryIO, int]:
        with self.scope(p) as s:
            self.artifact(s, p, key)
            row = self.version(s, p, key, version)
            if row.state != "COMMITTED":
                raise missing("Committed artifact version")
            obj, expected_size, checksum = self.key(row), row.size, row.checksum
        result = tempfile.TemporaryFile(mode="w+b")
        try:
            digest, size = hashlib.sha256(), 0
            for chunk in self.storage().chunks(obj):
                size += len(chunk)
                if size > expected_size or size > self.settings.max_bytes:
                    raise StorageError(Failure.INTEGRITY)
                digest.update(chunk)
                result.write(chunk)
            if size != expected_size or digest.hexdigest() != checksum:
                raise StorageError(Failure.INTEGRITY)
            with self.scope(p) as s:
                self.artifact(s, p, key)
                self.audit(s, p, "artifact_download", version)
            result.seek(0)
            return result, size
        except BaseException:
            result.close()
            raise

    def presigned(self, p: Principal, key: UUID, version: UUID) -> PresignedAccess:
        with self.scope(p) as s:
            self.artifact(s, p, key)
            row = self.version(s, p, key, version)
            if row.state != "COMMITTED":
                raise missing("Committed artifact version")
            obj, size, checksum = self.key(row), row.size, row.checksum
        self.storage().verify(obj, size, checksum)
        with self.scope(p) as s:
            self.artifact(s, p, key)
            url = self.storage().presign(obj)
            self.audit(
                s, p, "artifact_capability", version, {"expires_in": self.settings.presign_seconds}
            )
            return PresignedAccess(url=url, expires_in=self.settings.presign_seconds)

    def cleanup(self, p: Principal, key: UUID, dry_run: bool = True) -> list[CleanupResult]:
        # Archived resources need an explicit owner-only maintenance path. No share access.
        with self.scope(p) as s:
            resource = s.get(Resource, (p.tenant_id, key))
            if resource is None or resource.resource_type != self.resource_kind:
                raise missing("Artifact")
            try:
                _, member = self.project(s, p, resource.project_id)
            except ApplicationError as exc:
                if exc.status_code == 404:
                    raise missing("Artifact") from exc
                raise
            self.authorizer.require(
                p, "project:manage", f"{p.tenant_id}/projects/{resource.project_id}"
            )
            if member.role != "owner":
                raise ApplicationError("forbidden", "Operation is not authorized", 403)
            cutoff = datetime.now(UTC) - timedelta(seconds=self.settings.abandoned_seconds)
            rows = list(
                s.scalars(
                    select(ArtifactVersion)
                    .where(
                        ArtifactVersion.tenant_id == p.tenant_id,
                        ArtifactVersion.artifact_id == key,
                        ArtifactVersion.state.in_(["PENDING", "FAILED"]),
                        ArtifactVersion.created_at < cutoff,
                    )
                    .order_by(ArtifactVersion.sequence)
                    .limit(100)
                )
            )
            result = []
            for row in rows:
                obj = self.key(row)
                if dry_run:
                    result.append(CleanupResult(version_id=row.id, outcome="eligible"))
                    continue
                # Only noncommitted metadata is eligible. The tenant lock excludes finalization.
                if row.state == "PENDING":
                    row.state = "FAILED"
                    s.flush()
                self.audit(s, p, "artifact_delete_decision", row.id)
                try:
                    self.storage().abort_pending(obj)
                    self.storage().delete(obj)
                except StorageError as exc:
                    self.audit(s, p, "artifact_delete_failure", row.id, str(exc.category))
                    result.append(CleanupResult(version_id=row.id, outcome="retry"))
                else:
                    row.state = "DELETED"
                    s.flush()
                    self.audit(s, p, "artifact_delete_complete", row.id)
                    result.append(CleanupResult(version_id=row.id, outcome="deleted"))
            return result
