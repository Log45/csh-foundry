import base64
import json
import math
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    field_validator,
    model_validator,
)

Identifier = str
ScalarType = Literal[
    "string", "integer", "float", "boolean", "date", "timestamp", "uuid", "decimal", "json"
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_min_length=1, allow_inf_nan=False)

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )


def unique(ids: list[str]) -> None:
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate identifiers")


class TenantIdentity(Contract):
    tenant_id: UUID


class OperationalIdentity(TenantIdentity):
    ontology_id: Identifier
    object_type_id: Identifier
    object_id: str


class ObjectRevision(OperationalIdentity):
    version: int = Field(ge=1, strict=True)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def timestamps(self) -> Self:
        if any(t.utcoffset() is None for t in (self.created_at, self.updated_at)):
            raise ValueError("Timestamps require time zones")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at precedes created_at")
        return self


class RDFMapping(Contract):
    namespace: str
    mapping_version: Literal[1] = 1

    @field_validator("namespace")
    @classmethod
    def absolute_namespace(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or any(c.isspace() for c in value)
            or not value.endswith(("/", "#"))
            or parsed.query
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Namespace must be an absolute HTTP(S) IRI ending in / or #")
        return value

    def individual_iri(self, identity: OperationalIdentity) -> str:
        # A single base64url JSON tuple avoids separator and percent-encoding collisions.
        values = [
            str(identity.tenant_id),
            identity.ontology_id,
            identity.object_type_id,
            identity.object_id,
        ]
        payload = json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()
        return (
            self.namespace
            + "individual/v1/"
            + base64.urlsafe_b64encode(payload).decode().rstrip("=")
        )

    def identity_from_iri(self, iri: str) -> OperationalIdentity:
        prefix = self.namespace + "individual/v1/"
        if not iri.startswith(prefix):
            raise ValueError("Unknown namespace or mapping version")
        token = iri[len(prefix) :]
        try:
            values = json.loads(
                base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
            )
            if not isinstance(values, list) or len(values) != 4:
                raise ValueError("Invalid identity tuple")
            identity = OperationalIdentity(
                tenant_id=values[0],
                ontology_id=values[1],
                object_type_id=values[2],
                object_id=values[3],
            )
            if self.individual_iri(identity) != iri:
                raise ValueError("Noncanonical IRI encoding")
            return identity
        except (ValueError, TypeError, UnicodeError) as exc:
            raise ValueError("Invalid individual IRI") from exc


class ImportedIRIMapping(Contract):
    original_iri: str
    identity: OperationalIdentity
    provenance: str
    conflict_status: Literal["unreviewed", "accepted", "rejected"] = "unreviewed"
    # Registry persistence and ambiguity detection belong to Phase 6.


class PropertyDefinition(Contract):
    id: Identifier
    name: str
    data_type: ScalarType
    array: StrictBool = False
    required: StrictBool = False
    nullable: StrictBool = False
    indexed: StrictBool = False
    unique: StrictBool = False
    default: JsonValue = None
    has_default: StrictBool = False
    enum: tuple[JsonValue, ...] = ()
    max_length: int | None = Field(default=None, ge=1, strict=True)
    precision: int | None = Field(default=None, ge=1, strict=True)
    scale: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode="after")
    def constraints(self) -> Self:
        if self.array and self.data_type == "json":
            raise ValueError("Arrays support scalar types only")
        if self.max_length is not None and self.data_type != "string":
            raise ValueError("max_length requires string")
        if self.data_type != "decimal" and (self.precision is not None or self.scale is not None):
            raise ValueError("precision/scale require decimal")
        if self.data_type == "decimal" and (self.precision is None or self.scale is None):
            raise ValueError("Decimal requires precision and scale")
        if self.precision is not None and self.scale is not None and self.scale > self.precision:
            raise ValueError("Scale exceeds precision")
        if self.unique and not self.indexed:
            raise ValueError("Unique properties must be indexed")
        if self.has_default or self.default is not None:
            self.validate_value(self.default)
        for value in self.enum:
            self._validate_scalar(value)
        if self.array and self.enum:
            raise ValueError("Array enumeration is deferred")
        return self

    def _validate_scalar(self, value: JsonValue) -> None:
        kind = self.data_type
        valid = True
        if kind == "string":
            valid = isinstance(value, str) and (
                self.max_length is None or len(value) <= self.max_length
            )
        elif kind == "integer":
            valid = type(value) is int and -(2**63) <= value < 2**63
        elif kind == "float":
            valid = type(value) is float and math.isfinite(value)
        elif kind == "boolean":
            valid = type(value) is bool
        elif kind in {"date", "timestamp", "uuid", "decimal"}:
            valid = isinstance(value, str)
            if valid:
                try:
                    assert isinstance(value, str)
                    if kind == "date":
                        valid = date.fromisoformat(value).isoformat() == value
                    elif kind == "timestamp":
                        valid = datetime.fromisoformat(value).utcoffset() is not None
                    elif kind == "uuid":
                        valid = str(UUID(value)) == value
                    else:
                        number = Decimal(value)
                        valid = number.is_finite()
                        if valid:
                            assert self.scale is not None and self.precision is not None
                            exponent = number.as_tuple().exponent
                            assert isinstance(exponent, int)
                            fraction = max(0, -exponent)
                            integer = max(0, number.adjusted() + 1) if number else 0
                            valid = (
                                fraction <= self.scale and integer <= self.precision - self.scale
                            )
                except (ValueError, InvalidOperation):
                    valid = False
        if not valid:
            raise ValueError(f"Invalid {kind} value for {self.id}; coercion is disabled")
        # Also reject nonfinite JSON numbers recursively.
        json.dumps(value, allow_nan=False)

    def validate_value(self, value: JsonValue) -> None:
        if value is None:
            if not self.nullable:
                raise ValueError(f"{self.id} is not nullable")
            return
        if self.array:
            if not isinstance(value, list):
                raise ValueError("Array value requires a JSON list")
            for item in value:
                self._validate_scalar(item)
        else:
            self._validate_scalar(value)
            if self.enum and value not in self.enum:
                raise ValueError(f"{self.id} is outside enum")


class ObjectTypeDefinition(Contract):
    id: Identifier
    name: str
    description: str | None = None
    properties: tuple[PropertyDefinition, ...]
    primary_key: str

    @model_validator(mode="after")
    def property_references(self) -> Self:
        unique([p.id for p in self.properties])
        primary = next((p for p in self.properties if p.id == self.primary_key), None)
        if (
            primary is None
            or not primary.required
            or primary.nullable
            or primary.array
            or primary.data_type not in {"string", "uuid", "integer"}
        ):
            raise ValueError(
                "Primary key must reference a required nonnullable scalar string/UUID/integer"
            )
        return self


class LinkTypeDefinition(Contract):
    id: Identifier
    name: str
    source_type: Identifier
    target_type: Identifier
    cardinality: Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"]
    inverse_name: str | None = None


class ParameterDefinition(PropertyDefinition):
    pass


class ActionOperation(Contract):
    type: Literal["CREATE_OBJECT", "UPDATE_OBJECT", "DELETE_OBJECT", "CREATE_LINK", "DELETE_LINK"]
    target: Identifier
    # Deliberately no executable expressions or parameter binding language in Phase 0.


class ActionTypeDefinition(Contract):
    id: Identifier
    name: str
    parameters: tuple[ParameterDefinition, ...] = ()
    operations: tuple[ActionOperation, ...] = ()

    @model_validator(mode="after")
    def parameters_unique(self) -> Self:
        unique([p.id for p in self.parameters])
        return self


class OntologyDefinition(Contract):
    format_version: Literal[1] = 1
    tenant_id: UUID
    id: Identifier
    name: str
    namespace: str
    version: str = Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
    object_types: tuple[ObjectTypeDefinition, ...] = ()
    link_types: tuple[LinkTypeDefinition, ...] = ()
    action_types: tuple[ActionTypeDefinition, ...] = ()

    @model_validator(mode="after")
    def references(self) -> Self:
        RDFMapping(namespace=self.namespace)
        for definitions in (self.object_types, self.link_types, self.action_types):
            unique([d.id for d in definitions])
        objects = {o.id for o in self.object_types}
        links = {link.id for link in self.link_types}
        for link in self.link_types:
            if link.source_type not in objects or link.target_type not in objects:
                raise ValueError("Link references unknown object type")
        for action in self.action_types:
            for operation in action.operations:
                allowed = links if operation.type.endswith("LINK") else objects
                if operation.target not in allowed:
                    raise ValueError("Action operation references unknown target")
        return self


class OntologyVersion(Contract):
    ontology_id: Identifier
    tenant_id: UUID
    version: str
    status: Literal["DRAFT", "VALIDATING", "PUBLISHED", "DEPRECATED"]
    # Snapshot text avoids mutable nested JSON in immutable published contracts.
    definition_json: str
    published_at: datetime | None = None

    @model_validator(mode="after")
    def snapshot(self) -> Self:
        definition = OntologyDefinition.model_validate_json(self.definition_json)
        if (definition.id, definition.tenant_id, definition.version) != (
            self.ontology_id,
            self.tenant_id,
            self.version,
        ):
            raise ValueError("Version identity differs from definition")
        if definition.canonical_json() != self.definition_json:
            raise ValueError("Version snapshot must use canonical JSON")
        if self.status in {"PUBLISHED", "DEPRECATED"} and (
            self.published_at is None or self.published_at.utcoffset() is None
        ):
            raise ValueError("Published versions require a timezone-aware publication timestamp")
        return self


class SchemaActivation(Contract):
    tenant_id: UUID
    ontology_id: Identifier
    version: str
    actor: str
    activated_at: datetime
    compatibility: Literal["additive", "breaking"]
    migration_plan_id: str | None = None

    @model_validator(mode="after")
    def activation(self) -> Self:
        if self.activated_at.utcoffset() is None:
            raise ValueError("Activation requires timezone")
        if self.compatibility == "breaking" and not self.migration_plan_id:
            raise ValueError("Breaking activation requires migration plan")
        return self
