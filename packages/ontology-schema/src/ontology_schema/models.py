import base64
import json
import math
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, Self
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
    # Existing identity inside the server-derived tenant and requested ontology.
    object_type_id: str | None = None

    @model_validator(mode="after")
    def identity_parameter(self) -> Self:
        if self.object_type_id is not None and (
            self.array or self.data_type not in {"string", "uuid"}
        ):
            raise ValueError("Object identities require scalar string/UUID parameters")
        return self


class LiteralValue(Contract):
    kind: Literal["literal"]
    value: JsonValue


class ParameterValue(Contract):
    kind: Literal["parameter"]
    parameter: str


class ObjectValue(Contract):
    kind: Literal["object"]
    binding: str
    # Omitting property returns the stable object ID, never the entire document.
    property: str | None = None


ActionValue = Annotated[LiteralValue | ParameterValue | ObjectValue, Field(discriminator="kind")]


class ActionBinding(Contract):
    id: str
    object_type: str
    object_id: ActionValue


class ActionPrecondition(Contract):
    type: Literal[
        "EXISTS",
        "NOT_EXISTS",
        "PROPERTY_EQUALS",
        "REVISION_EQUALS",
        "LINK_EXISTS",
        "LINK_NOT_EXISTS",
        "PARAMETER_PRESENT",
    ]
    binding: str | None = None
    property: str | None = None
    value: ActionValue | None = None
    link: str | None = None
    source: str | None = None
    target: str | None = None
    parameter: str | None = None

    @model_validator(mode="after")
    def shape(self) -> Self:
        expected = {
            "EXISTS": {"binding"},
            "NOT_EXISTS": {"binding"},
            "PROPERTY_EQUALS": {"binding", "property", "value"},
            "REVISION_EQUALS": {"binding", "value"},
            "LINK_EXISTS": {"link", "source", "target"},
            "LINK_NOT_EXISTS": {"link", "source", "target"},
            "PARAMETER_PRESENT": {"parameter"},
        }[self.type]
        present = {k for k, v in self.model_dump().items() if v is not None and k != "type"}
        if present != expected:
            raise ValueError("Invalid precondition fields")
        return self


class ActionOperation(Contract):
    type: Literal["CREATE_OBJECT", "UPDATE_OBJECT", "DELETE_OBJECT", "CREATE_LINK", "DELETE_LINK"]
    target: Identifier
    # Legacy Phase 0 target-only declarations remain readable but are inert at runtime.
    binding: str | None = None
    object_id: ActionValue | None = None
    properties: dict[str, ActionValue] = Field(default_factory=dict, max_length=64)
    expected_version: ActionValue | None = None
    source: str | None = None
    destination: str | None = None

    @model_validator(mode="after")
    def shape(self) -> Self:
        if (
            self.binding is None
            and self.object_id is None
            and not self.properties
            and (self.expected_version is None and self.source is None and self.destination is None)
        ):
            return self
        if self.type.endswith("LINK"):
            valid = bool(self.source and self.destination) and not (
                self.binding or self.object_id or self.properties or self.expected_version
            )
        elif self.type == "CREATE_OBJECT":
            valid = bool(self.binding and self.object_id) and not (
                self.source or self.destination or self.expected_version
            )
        else:
            valid = bool(self.binding and self.expected_version) and not (
                self.object_id
                or self.source
                or self.destination
                or (self.type == "DELETE_OBJECT" and self.properties)
            )
        if not valid:
            raise ValueError("Invalid operation fields")
        return self


class ActionTypeDefinition(Contract):
    id: Identifier
    name: str
    parameters: tuple[ParameterDefinition, ...] = Field(default=(), max_length=32)
    operations: tuple[ActionOperation, ...] = Field(default=(), max_length=64)
    bindings: tuple[ActionBinding, ...] = Field(default=(), max_length=64)
    preconditions: tuple[ActionPrecondition, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def parameters_unique(self) -> Self:
        unique([p.id for p in self.parameters])
        unique(
            [b.id for b in self.bindings]
            + [o.binding for o in self.operations if o.type == "CREATE_OBJECT" and o.binding]
        )
        if len(self.canonical_json().encode()) > 65536:
            raise ValueError("Action definition exceeds 64 KiB")
        return self

    def validate_schema(self, schema: "OntologyDefinition") -> None:
        parameters = {p.id: p for p in self.parameters}
        types = {o.id: o for o in schema.object_types}
        links = {o.id: o for o in schema.link_types}
        resolved: dict[str, str] = {}
        for parameter in self.parameters:
            if parameter.object_type_id is not None and parameter.object_type_id not in types:
                raise ValueError("Unknown parameter object type")

        def value(ref: ActionValue | None) -> None:
            if isinstance(ref, ParameterValue) and ref.parameter not in parameters:
                raise ValueError("Unknown parameter reference")
            if isinstance(ref, ObjectValue):
                if ref.binding not in resolved:
                    raise ValueError("Unknown, forward or circular object reference")
                if ref.property and ref.property not in {
                    p.id for p in types[resolved[ref.binding]].properties
                }:
                    raise ValueError("Unknown referenced property")

        def compatible(ref: ActionValue | None, expected: PropertyDefinition) -> None:
            value(ref)
            if isinstance(ref, LiteralValue):
                expected.validate_value(ref.value)
            elif isinstance(ref, ParameterValue):
                parameter = parameters[ref.parameter]
                if (parameter.data_type, parameter.array) != (expected.data_type, expected.array):
                    raise ValueError("Parameter and target property types differ")
            elif isinstance(ref, ObjectValue) and ref.property is not None:
                source = next(
                    p for p in types[resolved[ref.binding]].properties if p.id == ref.property
                )
                if (source.data_type, source.array) != (expected.data_type, expected.array):
                    raise ValueError("Referenced property and target types differ")

        def binding(name: str | None) -> str:
            if name not in resolved:
                raise ValueError("Unknown object binding")
            assert name is not None
            return resolved[name]

        def link(name: str | None, source: str | None, target: str | None) -> None:
            if name not in links:
                raise ValueError("Unknown link")
            assert name is not None
            typed = links[name]
            if (binding(source), binding(target)) != (typed.source_type, typed.target_type):
                raise ValueError("Link endpoint types differ")

        for item in self.bindings:
            if item.object_type not in types:
                raise ValueError("Unknown binding type")
            value(item.object_id)
            if isinstance(item.object_id, ParameterValue):
                target_type = parameters[item.object_id.parameter].object_type_id
                if target_type is not None and target_type != item.object_type:
                    raise ValueError("Identity parameter type differs from binding")
            resolved[item.id] = item.object_type
        for condition in self.preconditions:
            value(condition.value)
            if condition.binding:
                typed = types[binding(condition.binding)]
                if condition.property and condition.property not in {
                    p.id for p in typed.properties
                }:
                    raise ValueError("Unknown precondition property")
            if condition.parameter and condition.parameter not in parameters:
                raise ValueError("Unknown precondition parameter")
            if condition.link:
                link(condition.link, condition.source, condition.target)
        for operation in self.operations:
            if operation.type.endswith("LINK"):
                if operation.target not in links:
                    raise ValueError("Unknown operation link")
                if operation.source is not None:
                    link(operation.target, operation.source, operation.destination)
            else:
                if operation.target not in types:
                    raise ValueError("Unknown operation type")
                value(operation.object_id)
                value(operation.expected_version)
                for key, ref in operation.properties.items():
                    if key not in {p.id for p in types[operation.target].properties}:
                        raise ValueError("Unknown operation property")
                    compatible(
                        ref, next(p for p in types[operation.target].properties if p.id == key)
                    )
                if operation.type == "CREATE_OBJECT" and operation.binding:
                    resolved[operation.binding] = operation.target
                elif operation.binding and binding(operation.binding) != operation.target:
                    raise ValueError("Binding type differs from operation target")
        if len(resolved) + sum(p.object_type_id is not None for p in self.parameters) > 64:
            raise ValueError("At most 64 referenced objects")


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
        for link in self.link_types:
            if link.source_type not in objects or link.target_type not in objects:
                raise ValueError("Link references unknown object type")
        for action in self.action_types:
            action.validate_schema(self)
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
