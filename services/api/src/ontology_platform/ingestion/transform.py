"""Polars column projection, null normalization and explicit scalar conversions."""

import time
from dataclasses import dataclass, field

import polars as pl
from ontology_schema.models import OntologyDefinition
from pydantic import JsonValue

from ontology_platform.errors import ApplicationError
from ontology_platform.ingestion.catalog import Binding
from ontology_platform.ingestion.connectors import Record, encode
from ontology_platform.ingestion.contracts import MappingInput
from ontology_platform.objects.relationships import link_type
from ontology_platform.objects.validation import object_type, validate_properties


@dataclass
class Proposed:
    number: int
    source_key: str | None = None
    object_id: str | None = None
    properties: dict[str, JsonValue] = field(default_factory=dict)
    relationships: list[dict[str, JsonValue]] = field(default_factory=list)
    error: str | None = None


def validate_mapping(schema: OntologyDefinition, mapping: MappingInput, binding: Binding) -> None:
    if mapping.schema_version != schema.version:
        raise ApplicationError("stale_schema", "Mapping must use the active schema", 409)
    typed = object_type(schema, mapping.object_type)
    columns = {c.name: c for c in binding.columns}
    properties = {p.id: p for p in typed.properties}
    if mapping.identity_column not in columns:
        raise ApplicationError("invalid_mapping", "Unknown identity column", 422)
    assigned = {p.property: p for p in mapping.properties}
    if (
        typed.primary_key not in assigned
        or assigned[typed.primary_key].column != mapping.identity_column
    ):
        raise ApplicationError("invalid_mapping", "Identity must map the declared primary key", 422)
    for p in typed.properties:
        if p.required and p.id not in assigned and not (p.has_default or p.default is not None):
            raise ApplicationError("invalid_mapping", "Required property is unmapped", 422)
    for item in mapping.properties:
        if item.property not in properties or item.column not in columns:
            raise ApplicationError("invalid_mapping", "Unknown property or source column", 422)
        prop = properties[item.property]
        source_kind = columns[item.column].data_type
        if (
            prop.array
            or prop.data_type == "json"
            or (item.conversion != "identity" and item.conversion != prop.data_type)
        ):
            raise ApplicationError("invalid_mapping", "Unsupported property conversion", 422)
        if item.conversion == "identity" and source_kind != prop.data_type:
            raise ApplicationError("invalid_mapping", "Explicit conversion is required", 422)
        if item.nulls == "default":
            try:
                prop.validate_value(item.default)
            except ValueError as exc:
                raise ApplicationError("invalid_mapping", "Invalid null default", 422) from exc
    for relation in mapping.relationships:
        link = link_type(schema, relation.link)
        if link.source_type != typed.id or relation.target_column not in columns:
            raise ApplicationError(
                "invalid_mapping", "Relationship direction or column differs", 422
            )


def transform(
    records: list[Record], schema: OntologyDefinition, mapping: MappingInput, binding: Binding
) -> list[Proposed]:
    start = time.monotonic()
    valid = [r for r in records if r.error is None]
    results = {r.number: Proposed(r.number, error=r.error) for r in records}
    if not valid:
        return list(results.values())
    # Explicit source schemas avoid batch-dependent inference or implicit conversions.
    dtypes = {
        c.name: {"integer": pl.Int64, "float": pl.Float64, "boolean": pl.Boolean}.get(
            c.data_type, pl.String
        )
        for c in binding.columns
    }
    if binding.kind == "csv":
        dtypes = {c.name: pl.String for c in binding.columns}
    try:
        aliases = {c.name: f"_input_{i}" for i, c in enumerate(binding.columns)}
        frame = pl.DataFrame([r.values for r in valid], schema=dtypes, strict=True).rename(aliases)
        keep = None
        if binding.kind != "postgres" and binding.equals:
            predicates = [
                pl.col(aliases[name]).is_null()
                if value is None
                else pl.col(aliases[name]) == pl.lit(value)
                for name, value in binding.equals.items()
            ]
            keep = frame.select(pl.all_horizontal(predicates)).to_series().to_list()
        expressions = []
        for index, item in enumerate(mapping.properties):
            col = pl.col(aliases[item.column])
            if dtypes[item.column] == pl.String:
                col = pl.when(col == "").then(None).otherwise(col)
            if item.conversion == "integer":
                text_value = col.cast(pl.String)
                col = (
                    pl.when(text_value.str.contains(r"^-?(0|[1-9][0-9]*)$"))
                    .then(text_value.cast(pl.Int64, strict=False))
                    .otherwise(None)
                )
            elif item.conversion == "float":
                col = col.cast(pl.Float64, strict=False)
            elif item.conversion == "boolean":
                col = (
                    pl.when(col.cast(pl.String) == "true")
                    .then(True)
                    .when(col.cast(pl.String) == "false")
                    .then(False)
                    .otherwise(None)
                )
            elif item.conversion != "identity":
                col = col.cast(pl.String, strict=False)
            expressions.append(col.alias(str(index)))
        converted = frame.select(expressions).to_dicts()
    except (pl.exceptions.PolarsError, TypeError) as exc:
        raise ApplicationError("source_type_error", "Registered source types differ", 422) from exc
    typed = object_type(schema, mapping.object_type)
    for position, (raw, row) in enumerate(zip(valid, converted, strict=True)):
        if keep is not None and not keep[position]:
            results.pop(raw.number)
            continue
        proposal = results[raw.number]
        try:
            source_key = raw.values[binding.source_key_column]
            object_key = raw.values[mapping.identity_column]
            if (
                type(source_key) not in (str, int)
                or not str(source_key)
                or type(object_key) not in (str, int)
                or not str(object_key)
            ):
                raise ApplicationError(
                    "missing_identity", "Stable source and object identities are required", 422
                )
            proposal.source_key, proposal.object_id = str(source_key), str(object_key)
            for index, item in enumerate(mapping.properties):
                original = raw.values[item.column]
                value = row[str(index)]
                missing = original is None or original == ""
                if missing:
                    if item.nulls == "omit":
                        continue
                    if item.nulls == "reject":
                        raise ApplicationError(
                            "missing_required_value", "Source value is required", 422
                        )
                    value = item.default if item.nulls == "default" else None
                elif value is None:
                    raise ApplicationError("invalid_conversion", "Explicit conversion failed", 422)
                prop = next(p for p in typed.properties if p.id == item.property)
                try:
                    prop.validate_value(value)
                except ValueError as exc:
                    code = (
                        "invalid_enum"
                        if prop.enum and value not in prop.enum
                        else "invalid_" + prop.data_type
                    )
                    raise ApplicationError(
                        code, "Canonical property validation failed", 422
                    ) from exc
                proposal.properties[item.property] = value
            proposal.properties = validate_properties(
                typed, proposal.object_id, proposal.properties, defaults=True
            )
            for relation in mapping.relationships:
                target = raw.values[relation.target_column]
                if type(target) not in (str, int) or not str(target):
                    raise ApplicationError(
                        "missing_relationship_identity", "Relationship endpoint is required", 422
                    )
                proposal.relationships.append({"link": relation.link, "target": str(target)})
            if len(encode(proposal.properties)) > 16384:
                raise ApplicationError(
                    "target_row_too_wide", "Canonical record exceeds row bound", 422
                )
        except ApplicationError as exc:
            proposal.error = exc.code
    if time.monotonic() - start > 3:
        raise ApplicationError(
            "transformation_timeout", "Transformation exceeded three seconds", 503
        )
    return list(results.values())
