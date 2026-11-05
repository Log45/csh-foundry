from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue, model_validator

from ontology_platform.functions.contracts import DefinitionIdentityView
from ontology_platform.projects.contracts import Model

MediaType = Literal["image/png", "image/jpeg", "audio/wav", "video/mp4", "application/pdf"]


class AttachMedia(Model):
    artifact_id: UUID
    artifact_version_id: UUID
    media_type: MediaType


class Snapshot(Model):
    items: list[UUID] = Field(max_length=10000)

    @model_validator(mode="after")
    def unique(self) -> "Snapshot":
        if len(set(self.items)) != len(self.items):
            raise ValueError("Duplicate membership")
        return self


class ItemView(Model):
    set_id: UUID
    id: UUID
    artifact_id: UUID
    artifact_version_id: UUID
    media_type: str
    size: int
    checksum: str
    filename: str
    metadata: dict[str, JsonValue]
    preview_artifact_id: UUID | None
    preview_version_id: UUID | None
    validation_status: Literal["VALID"] = "VALID"
    created_by: str
    created_at: datetime


class MediaSnapshotView(DefinitionIdentityView):
    specification: Snapshot
