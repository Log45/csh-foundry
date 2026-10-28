"""Pure schema-aware object validation shared by CRUD and activation."""

from copy import deepcopy

from ontology_schema.models import ObjectTypeDefinition, OntologyDefinition
from pydantic import JsonValue

from ontology_platform.errors import ApplicationError


def object_type(definition: OntologyDefinition, type_id: str) -> ObjectTypeDefinition:
    result = next((t for t in definition.object_types if t.id == type_id), None)
    if result is None:
        raise ApplicationError("unknown_object_type", "Object type is not in the schema", 422)
    return result


def validate_properties(
    definition: ObjectTypeDefinition,
    object_id: str,
    properties: dict[str, JsonValue],
    *,
    defaults: bool = False,
) -> dict[str, JsonValue]:
    result = deepcopy(properties)
    known = {p.id for p in definition.properties}
    if result.keys() - known:
        raise ApplicationError("invalid_properties", "Unknown properties supplied", 422)
    for prop in definition.properties:
        if prop.id not in result:
            if defaults and (prop.has_default or prop.default is not None):
                result[prop.id] = deepcopy(prop.default)
            elif prop.required:
                raise ApplicationError(
                    "invalid_properties", f"Missing required property: {prop.id}", 422
                )
            else:
                continue
        try:
            prop.validate_value(result[prop.id])
        except ValueError as exc:
            raise ApplicationError(
                "invalid_properties", f"Invalid property: {prop.id}", 422
            ) from exc
    primary = result.get(definition.primary_key)
    if primary is None or str(primary) != object_id:
        raise ApplicationError(
            "identity_mismatch", "Primary key must match the stable object ID", 422
        )
    return result
