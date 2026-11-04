from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue, model_validator

from ontology_platform.pipelines.contracts import Column
from ontology_platform.projects.contracts import Model, Name

Scalar = Literal["string", "integer", "float", "decimal", "boolean", "date", "timestamp", "uuid"]


class Value(Model):
    column: Column | None = None
    constant: JsonValue = None
    conversion: Scalar
    nulls: Literal["reject", "allow", "default"] = "reject"
    default: JsonValue = None

    @model_validator(mode="after")
    def source(self) -> "Value":
        if (self.column is None and "constant" not in self.model_fields_set) or (
            self.column is not None and self.constant is not None
        ):
            raise ValueError("Specify exactly one column or constant")
        if self.nulls == "default" and self.default is None:
            raise ValueError("A nonnull default is required")
        return self


class Identity(Model):
    components: list[Value] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def keys(self) -> "Identity":
        if any(v.column is None or v.nulls != "reject" for v in self.components):
            raise ValueError("Identity requires nonnull source columns")
        return self


class ObjectMapping(Model):
    object_type: Name
    identity: Identity
    properties: dict[Name, Value] = Field(default_factory=dict, max_length=64)


class Endpoint(Model):
    object_type: Name
    identity: Identity


class RelationshipMapping(Model):
    link_type: Name
    source: Endpoint
    target: Endpoint


class MappingSpec(Model):
    format_version: Literal[1] = 1
    target_resource_id: UUID
    ontology_id: Name
    schema_version: Name
    columns: dict[Column, str] = Field(min_length=1, max_length=256)
    objects: list[ObjectMapping] = Field(min_length=1, max_length=16)
    relationships: list[RelationshipMapping] = Field(default_factory=list, max_length=32)
    write_policy: Literal["insert_only", "upsert_owned"] = "upsert_owned"
    duplicates: Literal["reject", "coalesce_identical"] = "reject"
    max_objects: int = Field(default=100000, ge=1, le=1000000)
    max_links: int = Field(default=100000, ge=0, le=1000000)

    @model_validator(mode="after")
    def references(self) -> "MappingSpec":
        values = [
            v for o in self.objects for v in o.identity.components + list(o.properties.values())
        ]
        values += [
            v
            for r in self.relationships
            for e in (r.source, r.target)
            for v in e.identity.components
        ]
        if any(v.column is not None and v.column not in self.columns for v in values):
            raise ValueError("Every referenced column requires an exact source type contract")
        if len({o.object_type for o in self.objects}) != len(self.objects):
            raise ValueError("One object mapping per type")
        return self


class MappingDefinitionView(Model):
    id: UUID
    mapping_id: UUID
    sequence: int
    specification: MappingSpec
    created_by: str
    created_at: datetime


class MappingRun(Model):
    definition_id: UUID
    dataset_id: UUID
    version_id: UUID
    mode: Literal["materialize", "full_validation"] = "materialize"


class MappingPreview(Model):
    dataset_id: UUID
    version_id: UUID
    specification: MappingSpec
