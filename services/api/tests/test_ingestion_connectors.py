import json
from uuid import uuid4

import polars as pl
import pytest
from ontology_platform.errors import ApplicationError
from ontology_platform.ingestion.catalog import Binding, InputColumn, SourceCatalog
from ontology_platform.ingestion.connectors import extract
from ontology_platform.ingestion.contracts import PropertyMapping, RunInput
from pydantic import ValidationError


@pytest.mark.parametrize("kind", ["csv", "json", "parquet"])
def test_bounded_connectors(kind, tmp_path):
    columns = [InputColumn(name="id"), InputColumn(name="name")]
    binding = Binding(
        tenant_id=uuid4(),
        key="test",
        kind=kind,
        root=str(tmp_path),
        file_name="source",
        source_key_column="id",
        columns=columns,
    )
    if kind == "csv":
        (tmp_path / "source").write_text("id,name\na,A\nb,B\nc,C\n")
    elif kind == "json":
        (tmp_path / "source").write_text(
            "\n".join(json.dumps({"id": k, "name": k.upper()}) for k in "abc") + "\n"
        )
    else:
        pl.DataFrame({"id": list("abc"), "name": list("ABC")}).write_parquet(tmp_path / "source")
    first = extract(binding, 0, 2)
    second = extract(binding, 2, 2)
    assert len(first.rows) == 2 and not first.eof
    assert len(second.rows) == 1 and second.eof and first.fingerprint == second.fingerprint
    assert [r.number for r in first.rows + second.rows] == [1, 2, 3]


@pytest.mark.parametrize("path", ["../outside", "/etc/passwd"])
def test_filesystem_escape_rejected(path, tmp_path):
    binding = Binding(
        tenant_id=uuid4(),
        key="test",
        kind="csv",
        root=str(tmp_path),
        file_name=path,
        source_key_column="id",
        columns=[InputColumn(name="id")],
    )
    with pytest.raises(ApplicationError):
        extract(binding, 0, 10)


def test_symlink_escape_rejected(tmp_path):
    (tmp_path / "link").symlink_to("/etc/passwd")
    binding = Binding(
        tenant_id=uuid4(),
        key="test",
        kind="csv",
        root=str(tmp_path),
        file_name="link",
        source_key_column="id",
        columns=[InputColumn(name="id")],
    )
    with pytest.raises(ApplicationError):
        extract(binding, 0, 10)


def test_catalog_tenant_scope_and_secret_config(tmp_path):
    actor = uuid4()
    binding = Binding(
        tenant_id=actor,
        key="registered",
        kind="csv",
        root=str(tmp_path),
        file_name="test",
        source_key_column="id",
        columns=[InputColumn(name="id")],
    )
    catalog = SourceCatalog([binding])
    assert catalog.get(actor, "registered") == binding
    with pytest.raises(ApplicationError):
        catalog.get(uuid4(), "registered")


@pytest.mark.parametrize(
    "body", [{"expression": "eval(1)"}, {"conversion": "sql"}, {"nulls": "guess"}]
)
def test_executable_or_unknown_mapping_fields_rejected(body):
    with pytest.raises(ValidationError):
        PropertyMapping.model_validate({"property": "x", "column": "y"} | body)


@pytest.mark.parametrize("size", [0, 101, True, "10"])
def test_batch_size_bounds(size):
    with pytest.raises(ValidationError):
        RunInput(mappings=[{"id": "mapping", "version": 1}], idempotency_key="key", batch_size=size)


def test_ndjson_malformed_and_unknown_columns(tmp_path):
    binding = Binding(
        tenant_id=uuid4(),
        key="json",
        kind="json",
        root=str(tmp_path),
        file_name="data",
        source_key_column="id",
        columns=[InputColumn(name="id")],
    )
    (tmp_path / "data").write_text('{"id":"ok"}\n[1,2]\n{"secret":"unknown"}\nnot json\n')
    rows = extract(binding, 0, 10).rows
    assert rows[0].error is None
    assert [r.error for r in rows[1:]] == [
        "source_parse_error",
        "source_type_error",
        "source_parse_error",
    ]


@pytest.mark.parametrize(
    "kind,value,expected",
    [
        ("integer", "12", 12),
        ("float", "12.5", 12.5),
        ("boolean", "true", True),
        ("decimal", "12.30", "12.30"),
        ("date", "2026-11-01", "2026-11-01"),
        ("timestamp", "2026-11-01T00:00:00Z", "2026-11-01T00:00:00Z"),
        ("uuid", "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000001"),
    ],
)
def test_explicit_polars_conversions(kind, value, expected):
    from ontology_platform.ingestion.connectors import Record
    from ontology_platform.ingestion.contracts import MappingInput
    from ontology_platform.ingestion.transform import transform, validate_mapping
    from ontology_schema.models import OntologyDefinition

    schema = OntologyDefinition.model_validate(
        {
            "tenant_id": str(uuid4()),
            "id": "typed",
            "name": "Typed",
            "namespace": "https://example.org/typed#",
            "version": "1.0.0",
            "object_types": [
                {
                    "id": "Item",
                    "name": "Item",
                    "primary_key": "key",
                    "properties": [
                        {"id": "key", "name": "key", "data_type": "string", "required": True},
                        {
                            "id": "value",
                            "name": "Value",
                            "data_type": kind,
                            **({"precision": 8, "scale": 2} if kind == "decimal" else {}),
                        },
                    ],
                }
            ],
        }
    )
    binding = Binding(
        tenant_id=schema.tenant_id,
        key="csv",
        kind="csv",
        source_key_column="key",
        columns=[InputColumn(name="key"), InputColumn(name="value")],
    )
    mapping = MappingInput(
        id="map",
        source_id="source",
        source_version=1,
        schema_version="1.0.0",
        object_type="Item",
        identity_column="key",
        properties=[
            PropertyMapping(property="key", column="key"),
            PropertyMapping(property="value", column="value", conversion=kind),
        ],
    )
    validate_mapping(schema, mapping, binding)
    row = transform([Record(1, {"key": "one", "value": value})], schema, mapping, binding)[0]
    assert row.error is None and row.properties["value"] == expected
    invalid = transform([Record(1, {"key": "one", "value": "invalid"})], schema, mapping, binding)[
        0
    ]
    assert invalid.error is not None


def test_source_column_names_are_literal_not_polars_expressions():
    from pathlib import Path

    from ontology_platform.ingestion.connectors import Record
    from ontology_platform.ingestion.contracts import MappingInput
    from ontology_platform.ingestion.transform import transform, validate_mapping
    from ontology_schema.models import OntologyDefinition

    schema = OntologyDefinition.model_validate_json(
        (Path(__file__).resolve().parents[3] / "ontologies/examples/manufacturing.json").read_text()
    )
    names = ["factoryId", "^name$", "name", "location"]
    binding = Binding(
        tenant_id=schema.tenant_id,
        key="literal",
        kind="csv",
        source_key_column="factoryId",
        columns=[InputColumn(name=name) for name in names],
        equals={"^name$": "Expected"},
    )
    mapping = MappingInput(
        id="literal",
        source_id="literal",
        source_version=1,
        schema_version=schema.version,
        object_type="Factory",
        identity_column="factoryId",
        properties=[
            PropertyMapping(property="factoryId", column="factoryId"),
            PropertyMapping(property="factoryName", column="^name$"),
            PropertyMapping(property="location", column="location"),
        ],
    )
    validate_mapping(schema, mapping, binding)
    row = transform(
        [
            Record(
                1,
                {
                    "factoryId": "FAC-LITERAL",
                    "^name$": "Expected",
                    "name": "Other",
                    "location": "Local",
                },
            )
        ],
        schema,
        mapping,
        binding,
    )[0]
    assert row.error is None and row.properties["factoryName"] == "Expected"
