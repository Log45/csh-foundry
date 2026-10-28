"""Phase 1 public application contracts; tenant identity comes from the principal."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from ontology_schema.models import OntologyDefinition
from pydantic import BaseModel, ConfigDict, Field, JsonValue


class APIModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", from_attributes=True, str_min_length=1, allow_inf_nan=False
    )


class TenantRequest(APIModel):
    name: str = Field(max_length=200)


class TenantView(TenantRequest):
    id: UUID
    created_at: datetime


class OntologyView(APIModel):
    tenant_id: UUID
    id: str
    namespace: str
    active_version: str | None


class VersionView(APIModel):
    definition: OntologyDefinition
    status: Literal["DRAFT", "PUBLISHED"]
    content_hash: str
    published_at: datetime | None
    published_by: str | None


class CreateObject(APIModel):
    object_type_id: str
    object_id: str
    properties: dict[str, JsonValue]


class ObjectInput(APIModel):
    object_id: str
    properties: dict[str, JsonValue]


class ObjectPatch(APIModel):
    expected_version: int = Field(strict=True, ge=1)
    properties: dict[str, JsonValue]


class ObjectView(CreateObject):
    tenant_id: UUID
    ontology_id: str
    schema_version: str
    version: int
    created_at: datetime
    updated_at: datetime


class LinkInput(APIModel):
    link_type_id: str
    source_object_type_id: str
    source_object_id: str
    target_object_type_id: str
    target_object_id: str


class LinkView(LinkInput):
    tenant_id: UUID
    ontology_id: str
    schema_version: str
    created_at: datetime


class MigrationUpdate(CreateObject):
    expected_version: int = Field(strict=True, ge=1)


class PlanInput(APIModel):
    updates: list[MigrationUpdate] = Field(default_factory=list, max_length=1000)


class PlanView(APIModel):
    id: UUID
    tenant_id: UUID
    ontology_id: str
    target_version: str
    base_version: str | None
    content_hash: str
    updates: list[MigrationUpdate]
    created_by: str
    approved_by: str | None
    approved_at: datetime | None


class LifecycleInput(APIModel):
    plan_id: UUID | None = None


class Compatibility(APIModel):
    classification: Literal["additive", "breaking"]
    reasons: list[str]
