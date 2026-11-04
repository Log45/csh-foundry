"""Bounded full-source conversion with a disposable disk index for duplicate detection."""

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from ontology_schema.models import OntologyDefinition

from ontology_platform.datasets.streaming import batches
from ontology_platform.execution.config import ExecutionSettings
from ontology_platform.mappings.contracts import MappingSpec
from ontology_platform.mappings.conversion import evaluate, identity
from ontology_platform.objects.relationships import link_type
from ontology_platform.objects.validation import object_type, validate_properties


def encode(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def target_key(value: Any) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


def mapped(
    spec: MappingSpec, schema: OntologyDefinition, row: dict[str, Any]
) -> list[dict[str, Any]]:
    result = []
    for item in spec.objects:
        typed = object_type(schema, item.object_type)
        key = identity(item.identity, row)
        properties = {name: evaluate(value, row) for name, value in item.properties.items()}
        if len(item.identity.components) == 1:
            primary = evaluate(item.identity.components[0], row)
        else:
            primary = key
        properties[typed.primary_key] = primary
        properties = validate_properties(typed, key, properties, defaults=True)
        result.append({"kind": "object", "type": typed.id, "id": key, "properties": properties})
    for link in spec.relationships:
        result.append(
            {
                "kind": "link",
                "link_type": link.link_type,
                "source_type": link.source.object_type,
                "source_id": identity(link.source.identity, row),
                "target_type": link.target.object_type,
                "target_id": identity(link.target.identity, row),
            }
        )
    return result


def stage(request: dict[str, Any], directory: Path, limits: ExecutionSettings) -> dict[str, Any]:
    spec = MappingSpec.model_validate(request["specification"])
    schema = OntologyDefinition.model_validate(request["ontology"])
    path = Path(request["path"])
    if path.stat().st_size > limits.source_bytes:
        raise ValueError("Source limit")
    count = decoded = objects = links = 0
    preview: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    invalid = 0
    with sqlite3.connect(directory / "mapping.sqlite") as db:
        db.execute("PRAGMA cache_size=-2048")
        db.execute("PRAGMA journal_mode=OFF")
        db.execute(
            "CREATE TABLE targets (key TEXT PRIMARY KEY, kind TEXT, payload TEXT, record INTEGER)"
        )
        db.execute(
            "CREATE TABLE cardinality (link TEXT, direction TEXT, type TEXT, id TEXT, "
            "PRIMARY KEY(link,direction,type,id))"
        )
        for frame in batches(
            path,
            request["format"],
            limits,
            string_columns=tuple(name for name, dtype in spec.columns.items() if dtype == "String"),
        ):
            decoded += int(frame.estimated_size())
            if decoded > limits.decoded_bytes or frame.estimated_size() > limits.batch_bytes * 4:
                raise ValueError("Decoded limit")
            # CSV batch inference can differ from the committed, full-source schema. Preserve
            # strings by casting numeric batches to the declared full-source string type.
            import polars as pl

            frame = frame.with_columns(
                [
                    pl.selectors.by_name(name).as_expr().cast(pl.String, strict=True)
                    for name, dtype in spec.columns.items()
                    if dtype == "String"
                ]
            )
            for row in frame.iter_rows(named=True):
                count += 1
                if count > limits.rows:
                    raise ValueError("Row limit")
                try:
                    values = mapped(spec, schema, row)
                    for value in values:
                        kind = value["kind"]
                        identity_value = {k: v for k, v in value.items() if k != "properties"}
                        key, payload = target_key(identity_value), encode(value)
                        old = db.execute(
                            "SELECT payload FROM targets WHERE key=?", (key,)
                        ).fetchone()
                        if old:
                            if old[0] != payload or (
                                kind == "object" and spec.duplicates == "reject"
                            ):
                                raise ValueError("Duplicate identity")
                            continue
                        if kind == "link":
                            typed_link = link_type(schema, value["link_type"])
                            for direction, restricted in (
                                ("source", typed_link.cardinality in {"one_to_one", "many_to_one"}),
                                ("target", typed_link.cardinality in {"one_to_one", "one_to_many"}),
                            ):
                                if restricted:
                                    db.execute(
                                        "INSERT INTO cardinality VALUES (?,?,?,?)",
                                        (
                                            value["link_type"],
                                            direction,
                                            value[direction + "_type"],
                                            value[direction + "_id"],
                                        ),
                                    )
                        db.execute(
                            "INSERT INTO targets VALUES (?,?,?,?)", (key, kind, payload, count)
                        )
                        objects += kind == "object"
                        links += kind == "link"
                        if objects > spec.max_objects or links > spec.max_links:
                            raise ValueError("Target capacity")
                        if len(preview) < 20 and len(encode(preview + [value]).encode()) <= 65536:
                            preview.append(value)
                except Exception:
                    invalid += 1
                    if len(diagnostics) < 20:
                        diagnostics.append({"record": count, "code": "invalid_mapping_record"})
                if objects > spec.max_objects or links > spec.max_links:
                    raise ValueError("Target capacity")
            db.commit()
            if (
                sum(p.stat().st_size for p in directory.rglob("*") if p.is_file())
                > limits.temporary_bytes
            ):
                raise ValueError("Temporary limit")
        if count != request["row_count"]:
            raise ValueError("Source row count changed")
    return {
        "validation": "full-source",
        "rows": count,
        "objects": objects,
        "links": links,
        "invalid_records": invalid,
        "diagnostics": diagnostics,
        "preview": preview,
    }
