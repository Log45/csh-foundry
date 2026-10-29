"""Versioned semantic contracts. No operational mutation or arbitrary SPARQL."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from ontology_platform.contracts import APIModel
from ontology_platform.queries.ast import QueryRequest

COMPILER_VERSION = "1.0.0"
MAX_BYTES = 4 * 1024 * 1024
MAX_TRIPLES = 20000
Kind = Literal[
    "ontology", "shapes", "asserted", "validation", "reasoning", "derived", "change", "proof"
]
Profile = Literal["owl-rl", "owl-rl-ext"]


class Diagnostic(APIModel):
    code: str
    construct_path: str = Field(alias="construct")
    message: str


class CompileInput(APIModel):
    schema_version: str


class ExportInput(CompileInput):
    selections: tuple[QueryRequest, ...] = Field(min_length=1, max_length=8)
    links: tuple[str, ...] = Field(default=(), max_length=16)


class ArtifactManifest(APIModel):
    format_version: Literal[1] = 1
    id: UUID
    tenant_id: UUID
    ontology_id: str
    schema_version: str
    kind: Kind
    compiler_version: str = COMPILER_VERSION
    engine_version: str
    engine_commit: str
    created_at: datetime
    principal_id: str
    status: Literal["COMPLETED"] = "COMPLETED"
    input_hashes: dict[str, str] = Field(default_factory=dict)
    output_hash: str
    provenance: dict[str, object] = Field(default_factory=dict)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class ArtifactView(APIModel):
    manifest: ArtifactManifest
    content: str
    freshness: Literal["SCHEMA_ONLY", "SNAPSHOT", "CURRENT", "STALE", "UNKNOWN"]


class JobInput(APIModel):
    operation: Literal["validation", "reasoning", "change"]
    primary_artifact: UUID
    secondary_artifact: UUID
    profile: Profile = "owl-rl-ext"


class JobView(APIModel):
    id: UUID
    schema_version: str
    principal_id: str
    request: JobInput
    status: Literal["PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
    attempts: int
    created_at: datetime
    completed_at: datetime | None
    last_error: str | None
    outputs: list[UUID]
    history: list[dict[str, object]]


class ApprovalInput(APIModel):
    state: Literal["APPROVED", "REJECTED"]


class FactView(APIModel):
    id: str
    subject: str
    predicate: str
    object: str
    reasoning_job: UUID
    asserted_hash: str
    schema_version: str
    engine_version: str
    profile: Profile
    derived_at: datetime
    approval: Literal["PENDING", "APPROVED", "REJECTED"]
    freshness: Literal["CURRENT", "STALE", "UNKNOWN"]


class NativeInput(CompileInput):
    kind: Literal["ontology", "shapes"]
    content: str = Field(max_length=MAX_BYTES)


class ApprovalEvent(APIModel):
    id: UUID
    principal_id: str
    state: Literal["APPROVED", "REJECTED"]
    created_at: datetime
