"""Strict, inert ingestion configuration. Execution requests contain registered IDs only."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import ConfigDict, Field, JsonValue, model_validator

from ontology_platform.contracts import APIModel

Name = str
Kind = Literal["csv", "parquet", "json", "postgres"]
Policy = Literal["reject_run", "reject_batch", "quarantine"]


class SourceInput(APIModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "Factory",
                    "name": "Factories",
                    "binding": "Factory",
                    "identity_namespace": "Factory",
                    "version": 1,
                }
            ]
        }
    )
    id: str = Field(max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    version: int = Field(default=1, strict=True, ge=1, le=2147483647)
    name: str = Field(max_length=200)
    binding: str = Field(max_length=100)
    identity_namespace: str = Field(max_length=100)
    reconciliation: Literal["edit_wins", "source_wins", "reject", "manual"] = "edit_wins"
    owner: Literal["source", "pipeline"] = "source"
    update_policy: Literal["upsert"] = "upsert"
    deletion_policy: Literal["ignore"] = "ignore"


class PropertyMapping(APIModel):
    property: str = Field(max_length=200)
    column: str = Field(max_length=200)
    conversion: Literal[
        "identity", "string", "integer", "float", "boolean", "decimal", "date", "timestamp", "uuid"
    ] = "identity"
    nulls: Literal["reject", "null", "default", "omit"] = "reject"
    default: JsonValue = None


class RelationshipMapping(APIModel):
    link: str = Field(max_length=200)
    target_column: str = Field(max_length=200)
    direction: Literal["forward"] = "forward"


class MappingInput(APIModel):
    id: str = Field(max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    version: int = Field(default=1, strict=True, ge=1, le=2147483647)
    source_id: str = Field(max_length=100)
    source_version: int = Field(strict=True, ge=1, le=2147483647)
    schema_version: str
    object_type: str = Field(max_length=200)
    identity_column: str = Field(max_length=200)
    properties: list[PropertyMapping] = Field(min_length=1, max_length=64)
    relationships: list[RelationshipMapping] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def unique_assignments(self) -> Self:
        for names in ([p.property for p in self.properties], [r.link for r in self.relationships]):
            if len(names) != len(set(names)):
                raise ValueError("Duplicate mapping assignments")
        if len(self.model_dump_json().encode()) > 65536:
            raise ValueError("Mapping exceeds 64 KiB")
        return self


class MappingRef(APIModel):
    id: str = Field(max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    version: int = Field(strict=True, ge=1, le=2147483647)


class RunInput(APIModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "mappings": [
                        {"id": "Factory", "version": 1},
                        {"id": "Machine", "version": 1},
                        {"id": "Employee", "version": 1},
                        {"id": "MaintenanceTask", "version": 1},
                    ],
                    "idempotency_key": "manufacturing-snapshot-001",
                    "validation_policy": "reject_run",
                    "batch_size": 25,
                }
            ]
        }
    )
    mappings: list[MappingRef] = Field(min_length=1, max_length=8)
    idempotency_key: str = Field(max_length=128)
    validation_policy: Policy = "reject_run"
    batch_size: int = Field(default=25, strict=True, ge=1, le=100)

    @model_validator(mode="after")
    def unique_mappings(self) -> Self:
        if len({(r.id, r.version) for r in self.mappings}) != len(self.mappings):
            raise ValueError("Duplicate mapping references")
        return self


class SnapshotView(APIModel):
    tenant_id: UUID
    ontology_id: str
    kind: Kind | None = None
    status: Literal["PUBLISHED"] = "PUBLISHED"
    id: str
    version: int
    definition: dict[str, JsonValue]
    created_by: str
    created_at: datetime


class RunView(APIModel):
    id: UUID
    schema_version: str
    principal_id: str
    status: str
    phase: str
    attempts: int
    cancel_requested: bool
    staged: int
    processed: int
    created: int
    updated: int
    links_created: int
    rejected: int
    checkpoint: int
    staging_purged_at: datetime | None
    last_error: str | None
    created_at: datetime
    completed_at: datetime | None


class DiagnosticView(APIModel):
    mapping_id: str | None = None
    mapping_version: int | None = None
    id: UUID
    run_id: UUID
    row_number: int | None
    code: str
    category: str
    created_at: datetime
