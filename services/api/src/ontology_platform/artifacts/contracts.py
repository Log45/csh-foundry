from datetime import datetime
from uuid import UUID

from pydantic import Field

from ontology_platform.projects.contracts import Model, Name


class CreateArtifact(Model):
    name: Name
    description: str = Field(default="", max_length=4000)
    folder_id: UUID | None = None


class InitiateUpload(Model):
    filename: Name
    size: int = Field(ge=0, le=1073741824)
    checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    # Restricted provenance, never arbitrary unbounded client JSON or execution definitions.
    source: str = Field(default="user-upload", min_length=1, max_length=200)


class ArtifactVersionView(Model):
    artifact_id: UUID
    id: UUID
    sequence: int
    size: int
    checksum: str
    media_type: str
    filename: str
    state: str
    created_by: str
    created_at: datetime
    committed_at: datetime | None
    provenance: dict[str, str]


class Cleanup(Model):
    dry_run: bool = True


class CleanupResult(Model):
    version_id: UUID
    outcome: str


class PresignedAccess(Model):
    url: str
    expires_in: int
