from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def valid_name(value: str) -> str:
    value = value.strip()
    if (
        not value
        or value in {".", ".."}
        or any(ord(c) < 32 or ord(c) == 127 or c in "/\\" for c in value)
    ):
        raise ValueError("Invalid logical name")
    return value


Name = Annotated[str, Field(min_length=1, max_length=200), AfterValidator(valid_name)]
Kind = Literal["ONTOLOGY_OBJECT_TYPE", "ONTOLOGY_LINK_TYPE", "ONTOLOGY_ACTION", "ONTOLOGY_VERSION"]
RoleName = Literal["owner", "editor", "viewer"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class CreateProject(Model):
    name: Name
    description: str = Field(default="", max_length=4000)


class Expected(Model):
    expected_revision: int = Field(ge=1)


class UpdateProject(Expected):
    name: Name
    description: str = Field(default="", max_length=4000)


class MemberChange(Expected):
    principal_id: str = Field(min_length=1, max_length=200)
    role: RoleName | None


class MemberView(Model):
    principal_id: str
    role: RoleName


class ProjectView(CreateProject):
    id: UUID
    state: str
    revision: int
    role: RoleName
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime


class CreateFolder(Model):
    name: Name
    parent_id: UUID | None = None


class UpdateFolder(CreateFolder, Expected):
    pass


class FolderView(CreateFolder):
    id: UUID
    project_id: UUID
    state: str
    revision: int


class CreateResource(Model):
    resource_type: Kind
    ontology_id: str = Field(min_length=1, max_length=200)
    schema_version: str = Field(min_length=1, max_length=200)
    entity_id: str = Field(min_length=1, max_length=200)
    name: Name
    description: str = Field(default="", max_length=4000)
    folder_id: UUID | None = None


class UpdateResource(Expected):
    name: Name
    description: str = Field(default="", max_length=4000)
    folder_id: UUID | None = None


class ResourceView(Model):
    resource_type: Kind | Literal["ARTIFACT", "DATASET", "PIPELINE", "MAPPING"]
    ontology_id: str | None
    schema_version: str | None
    entity_id: str | None
    name: Name
    description: str
    folder_id: UUID | None
    id: UUID
    project_id: UUID
    state: str
    revision: int
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime


class ShareChange(Expected):
    project_id: UUID
    enabled: bool


class ShareView(Model):
    project_id: UUID


class CatalogImport(Model):
    ontology_id: str = Field(min_length=1, max_length=200)
    schema_version: str = Field(min_length=1, max_length=200)
    offset: int = Field(default=0, ge=0, le=10000)
    limit: int = Field(default=50, ge=1, le=100)
    folder_id: UUID | None = None
