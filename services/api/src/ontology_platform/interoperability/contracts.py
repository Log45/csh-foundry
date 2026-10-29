"""Explicit authoring mappings reuse canonical definitions, never a second schema model."""

from typing import Literal, Self
from uuid import UUID

from ontology_schema.models import LinkTypeDefinition, ObjectTypeDefinition, OntologyDefinition
from pydantic import Field, model_validator

from ontology_platform.contracts import APIModel, Compatibility
from ontology_platform.semantic.contracts import Diagnostic

MAX_INPUT = 256 * 1024
MAX_STATEMENTS = 4000
MAX_BNODES = 512
MAX_NAMESPACES = 64
PARSE_SECONDS = 5


class ClassMapping(APIModel):
    iri: str = Field(max_length=2048)
    definition: ObjectTypeDefinition
    property_iris: dict[str, str] = Field(max_length=64)

    @model_validator(mode="after")
    def complete(self) -> Self:
        if set(self.property_iris) != {p.id for p in self.definition.properties}:
            raise ValueError("Every canonical property requires an explicit source IRI")
        return self


class LinkMapping(APIModel):
    iri: str = Field(max_length=2048)
    definition: LinkTypeDefinition


class MappingInput(APIModel):
    classes: tuple[ClassMapping, ...] = Field(default=(), max_length=32)
    links: tuple[LinkMapping, ...] = Field(default=(), max_length=64)


class ImportInput(APIModel):
    format: Literal["turtle", "rdfxml"]
    mode: Literal["PREVIEW_ONLY", "CREATE_DRAFT"] = "PREVIEW_ONLY"
    content: str = Field(max_length=MAX_INPUT)
    version: str = Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
    base_version: str | None = None
    expected_base_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    namespace_mappings: dict[str, str] = Field(default_factory=dict, max_length=64)
    mappings: MappingInput = Field(default_factory=MappingInput)
    conflict_choices: dict[str, Literal["keep", "replace"]] = Field(
        default_factory=dict, max_length=96
    )
    description: str | None = Field(default=None, max_length=1000)
    source_metadata: dict[str, str] = Field(default_factory=dict, max_length=16)


class ImportView(APIModel):
    id: UUID
    ontology_id: str
    base_version: str
    base_hash: str
    artifact_reference: str
    input_hash: str
    ontology_iri: str | None
    version_iri: str | None
    status: Literal["PREVIEWED", "CONFLICT", "DRAFT_CREATED"]
    supported_construct_count: int
    preserved_semantic_construct_count: int
    unsupported_construct_count: int
    conflict_count: int
    diagnostic_count: int
    diagnostics: list[Diagnostic]
    diagnostics_truncated: bool
    diagnostic_reference: str
    compatibility: Compatibility | None
    proposed_definition: OntologyDefinition | None
    changes: list[str]
    draft_version: str | None


class VocabularyTerm(APIModel):
    iri: str
    kinds: list[str]


class ExportView(APIModel):
    format: Literal["turtle"] = "turtle"
    content: str
    output_hash: str
    canonical_hash: str
    mappings: MappingInput
    diagnostics: list[Diagnostic]
    # Operational actions remain in the registry; never imported from RDF or mapping metadata.
