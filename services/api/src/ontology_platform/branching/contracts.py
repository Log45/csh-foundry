"""Bounded canonical branch contracts. Revisions are always explicit mutation preconditions."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from ontology_schema.models import OntologyDefinition
from pydantic import Field, JsonValue

from ontology_platform.contracts import APIModel, Compatibility

Revision = Annotated[int, Field(strict=True, ge=1)]
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class BranchCreate(APIModel):
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")
    description: str | None = Field(default=None, max_length=2000)
    base_version: str | None = None


class BranchView(APIModel):
    tenant_id: UUID
    ontology_id: str
    id: UUID
    name: str
    description: str | None
    base_version: str
    base_hash: str
    head_revision: int
    head_hash: str
    state: Literal["ACTIVE", "MERGED", "ABANDONED"]
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime


class RevisionView(APIModel):
    branch_id: UUID
    revision: int
    parent_revision: int | None
    content_hash: str
    definition: OntologyDefinition
    author: str
    summary: str
    provenance: dict[str, JsonValue]
    created_at: datetime


class ExpectedRevision(APIModel):
    expected_revision: Revision


class BranchEdit(ExpectedRevision):
    definition: OntologyDefinition
    summary: str = Field(min_length=1, max_length=500)


class DraftHandoff(ExpectedRevision):
    version: str = Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class ComparisonInput(APIModel):
    source_revision: Revision | None = None
    target_branch: UUID | None = None
    target_revision: Revision | None = None
    target_version: str | None = None
    active: bool = False


class SchemaChange(APIModel):
    path: str
    stable_definition_id: str = "schema"
    compatibility: Literal["additive", "breaking"] = "additive"
    category: Literal["added", "removed", "modified"]
    previous: JsonValue
    proposed: JsonValue


class ComparisonView(APIModel):
    source: str
    target: str
    source_hash: str
    target_hash: str
    changes: list[SchemaChange]
    compatibility: Compatibility


class Resolution(APIModel):
    conflict: str = Field(max_length=2000)
    strategy: Literal["target", "source", "manual"]
    value: JsonValue = None
    delete: bool = False


class MergeInput(APIModel):
    source_branch: UUID
    source_revision: Revision
    target_revision: Revision
    resolutions: list[Resolution] = Field(default_factory=list, max_length=128)
    preview_hash: Hash | None = None


class MergeConflict(APIModel):
    id: str
    category: str
    base: JsonValue
    target: JsonValue
    source: JsonValue
    base_present: bool
    target_present: bool
    source_present: bool
    resolved: bool


class MergePreview(APIModel):
    source_branch: UUID
    target_branch: UUID
    source_revision: int
    target_revision: int
    source_hash: str
    target_hash: str
    base_version: str
    base_hash: str
    preview_hash: str
    conflicts: list[MergeConflict]
    resolutions: list[Resolution]
    changes: list[SchemaChange]
    definition: OntologyDefinition | None
    diagnostics: list[str]
    compatibility: Compatibility | None
    migration_required: bool
    publication: str = "Explicit draft handoff, publication and separate activation required"


class MergeView(APIModel):
    id: UUID
    source_id: UUID
    source_revision: int
    target_id: UUID
    target_revision: int
    result_revision: int
    provenance: dict[str, JsonValue]
    author: str
    created_at: datetime
