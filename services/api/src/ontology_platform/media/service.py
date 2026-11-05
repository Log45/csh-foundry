"""Immutable media assets and snapshots; registry and ArtifactStore remain authoritative."""

import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ontology_platform.artifacts.contracts import InitiateUpload
from ontology_platform.artifacts.service import ArtifactService
from ontology_platform.branching.service import page
from ontology_platform.db.governance import missing
from ontology_platform.db.models import MediaItem, MediaMembership, Resource
from ontology_platform.errors import ApplicationError
from ontology_platform.execution.config import ExecutionSettings
from ontology_platform.execution.isolation import isolated
from ontology_platform.functions.contracts import (
    GovernedDefinitionView,
    GSettings,
)
from ontology_platform.functions.service import FunctionService
from ontology_platform.media.contracts import AttachMedia, ItemView, Snapshot
from ontology_platform.projects.service import conflict
from ontology_platform.security.interfaces import Principal


class MediaService(FunctionService):
    resource_kind = "MEDIA_SET"

    def artifacts(self) -> ArtifactService:
        return ArtifactService(self.sessions, self.authorizer, self.settings, self.store)

    def item(self, s: Session, p: Principal, key: UUID, ident: UUID) -> MediaItem:
        self.artifact(s, p, key)
        row = s.get(MediaItem, (p.tenant_id, key, ident))
        if row is None:
            raise missing("Media item")
        self.artifacts().artifact(s, p, row.artifact_id)
        return row

    @staticmethod
    def view(row: MediaItem) -> ItemView:
        return ItemView(
            **{
                k: getattr(row, k)
                for k in ItemView.model_fields
                if k not in {"metadata", "validation_status"}
            },
            metadata=row.extracted,
        )

    def quota(self, s: Session, p: Principal, key: UUID, size: int) -> None:
        limits = GSettings()
        resource = self.artifact(s, p, key, True)
        count = (
            s.scalar(
                select(func.count())
                .select_from(MediaItem)
                .where(MediaItem.tenant_id == p.tenant_id, MediaItem.set_id == key)
            )
            or 0
        )
        tenant = (
            s.scalar(select(func.sum(MediaItem.size)).where(MediaItem.tenant_id == p.tenant_id))
            or 0
        )
        project = (
            s.scalar(
                select(func.sum(MediaItem.size))
                .join(
                    Resource,
                    (Resource.tenant_id == MediaItem.tenant_id) & (Resource.id == MediaItem.set_id),
                )
                .where(
                    MediaItem.tenant_id == p.tenant_id, Resource.project_id == resource.project_id
                )
            )
            or 0
        )
        if (
            size > limits.media_bytes
            or count >= limits.media_items
            or tenant + size > limits.tenant_media_bytes
            or project + size > limits.project_media_bytes
        ):
            raise ApplicationError("media_capacity", "Media quota exceeded", 413)

    def attach(self, p: Principal, key: UUID, body: AttachMedia) -> ItemView:
        artifacts = self.artifacts()
        with self.scope(p) as s:
            self.artifact(s, p, key, True)
            artifacts.artifact(s, p, body.artifact_id)
            physical = artifacts.version(s, p, body.artifact_id, body.artifact_version_id)
            previous = s.scalar(
                select(MediaItem).where(
                    MediaItem.tenant_id == p.tenant_id,
                    MediaItem.set_id == key,
                    MediaItem.artifact_id == body.artifact_id,
                    MediaItem.artifact_version_id == body.artifact_version_id,
                )
            )
            if previous:
                if previous.media_type != body.media_type:
                    raise conflict("Media source already attached with another declared type")
                return self.view(previous)
            if physical.state != "COMMITTED":
                raise conflict("Media source must be committed")
            self.quota(s, p, key, physical.size)
            size, checksum, filename = physical.size, physical.checksum, physical.filename
        limits = GSettings()
        preview_artifact, preview_version = None, None
        with tempfile.TemporaryDirectory(prefix="foundry-media-") as temporary:
            directory = Path(temporary)
            original, _ = artifacts.download(p, body.artifact_id, body.artifact_version_id)
            try:
                with (directory / "source").open("wb") as target:
                    shutil.copyfileobj(original, target, 1024**2)
            finally:
                original.close()
            execution = ExecutionSettings(
                wall_seconds=limits.parse_seconds,
                cpu_seconds=limits.parse_seconds,
                temporary_bytes=limits.media_bytes + limits.preview_bytes + 1024**2,
                memory_bytes=512 * 1024**2,
            )
            result = isolated(
                "media",
                {"media_type": body.media_type, "media_limits": limits.model_dump(mode="json")},
                directory,
                execution,
            )
            if "error" in result:
                raise ApplicationError(
                    "invalid_media", "Unsupported, corrupt or over-budget media", 422
                )
            if "preview" in result:
                # Publication rechecks set and source authority before derived storage reservation.
                with self.scope(p) as s:
                    self.artifact(s, p, key, True)
                    artifacts.artifact(s, p, body.artifact_id)
                version = self.initiate(
                    p,
                    key,
                    InitiateUpload(
                        filename="preview.jpg",
                        size=result["preview"]["size"],
                        checksum=result["preview"]["checksum"],
                        source=f"media-source:{body.artifact_id}:{body.artifact_version_id}",
                    ),
                )
                with (directory / "preview.jpg").open("rb") as handle:
                    self.upload(p, key, version.id, handle, version.size, version.checksum)
                self.finalize(p, key, version.id)
                preview_artifact, preview_version = key, version.id
        with self.scope(p) as s:
            self.artifact(s, p, key, True)
            artifacts.artifact(s, p, body.artifact_id)
            previous = s.scalar(
                select(MediaItem).where(
                    MediaItem.tenant_id == p.tenant_id,
                    MediaItem.set_id == key,
                    MediaItem.artifact_id == body.artifact_id,
                    MediaItem.artifact_version_id == body.artifact_version_id,
                )
            )
            if previous:
                if previous.media_type != body.media_type:
                    raise conflict("Concurrent attachment type differs")
                return self.view(previous)
            self.quota(s, p, key, size)
            row = MediaItem(
                tenant_id=p.tenant_id,
                set_id=key,
                id=uuid4(),
                **body.model_dump(),
                size=size,
                checksum=checksum,
                filename=filename,
                extracted=result["metadata"] | {"processing_metrics": result.get("metrics", {})},
                preview_artifact_id=preview_artifact,
                preview_version_id=preview_version,
                created_by=p.principal_id,
            )
            s.add(row)
            s.flush()
            self.audit(s, p, "media_attach", row.id)
            return self.view(row)

    def items(
        self, p: Principal, key: UUID, limit: int, offset: int, version: UUID | None = None
    ) -> list[ItemView]:
        page(limit, offset)
        with self.scope(p) as s:
            self.artifact(s, p, key)
            if version:
                return self.snapshot_items(s, p, key, version, limit, offset)
            rows = s.scalars(
                select(MediaItem)
                .where(MediaItem.tenant_id == p.tenant_id, MediaItem.set_id == key)
                .order_by(MediaItem.created_at, MediaItem.id)
                .limit(limit)
                .offset(offset)
            )
            return self.visible_items(s, p, rows)

    def visible_items(self, s: Session, p: Principal, rows: Iterable[MediaItem]) -> list[ItemView]:
        result = []
        for row in rows:
            try:
                self.artifacts().artifact(s, p, row.artifact_id)
            except ApplicationError as exc:
                if exc.status_code in {403, 404}:
                    continue
                raise
            result.append(self.view(row))
        return result

    def snapshot_items(
        self, s: Session, p: Principal, key: UUID, version: UUID, limit: int, offset: int
    ) -> list[ItemView]:
        self.governed_definition(s, p, key, version)
        rows = s.scalars(
            select(MediaItem)
            .join(
                MediaMembership,
                (MediaMembership.tenant_id == MediaItem.tenant_id)
                & (MediaMembership.set_id == MediaItem.set_id)
                & (MediaMembership.item_id == MediaItem.id),
            )
            .where(
                MediaMembership.tenant_id == p.tenant_id,
                MediaMembership.set_id == key,
                MediaMembership.version_id == version,
            )
            .order_by(MediaItem.created_at, MediaItem.id)
            .limit(limit)
            .offset(offset)
        )
        return self.visible_items(s, p, rows)

    def publish_snapshot(self, p: Principal, key: UUID, body: Snapshot) -> GovernedDefinitionView:
        if len(body.items) > GSettings().media_items:
            raise conflict("Snapshot item count exceeds budget")
        with self.scope(p) as s:
            self.artifact(s, p, key, True)
            for ident in body.items:
                self.item(s, p, key, ident)
            result = self.publish_spec(s, p, key, body.model_dump(mode="json"))
            for ident in body.items:
                s.add(
                    MediaMembership(
                        tenant_id=p.tenant_id, set_id=key, version_id=result.id, item_id=ident
                    )
                )
            s.flush()
            return result

    def content(self, p: Principal, key: UUID, ident: UUID, preview: bool) -> tuple[BinaryIO, int]:
        with self.scope(p) as s:
            row = self.item(s, p, key, ident)
            artifact_id = row.preview_artifact_id if preview else row.artifact_id
            version_id = row.preview_version_id if preview else row.artifact_version_id
            if artifact_id is None or version_id is None:
                raise missing("Supported preview")
        transport = self if preview else self.artifacts()
        result, size = transport.download(p, artifact_id, version_id)
        try:
            with self.scope(p) as s:
                self.item(s, p, key, ident)
                self.audit(s, p, "media_preview" if preview else "media_download", ident)
        except BaseException:
            result.close()
            raise
        return result, size
