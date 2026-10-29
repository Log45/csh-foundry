import json
from copy import deepcopy
from pathlib import Path

import pytest
from ontology_platform.actions.contracts import ActionRequest
from ontology_schema.models import OntologyDefinition, ParameterDefinition
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[3]


def definition():
    schema = json.loads((ROOT / "ontologies/examples/manufacturing.json").read_text())
    schema["action_types"] = json.loads(
        (ROOT / "ontologies/examples/manufacturing-actions.json").read_text()
    )
    return schema


def test_valid_examples_roundtrip():
    schema = OntologyDefinition.model_validate(definition())
    assert OntologyDefinition.model_validate_json(schema.canonical_json()) == schema


@pytest.mark.parametrize(
    "case",
    [
        "operation",
        "type",
        "link",
        "parameter",
        "property",
        "binding",
        "forward",
        "circular",
        "count",
        "parameter_count",
        "binding_count",
        "expression",
        "shape",
        "precondition",
        "duplicate_binding",
        "endpoint",
        "property_reference",
    ],
)
def test_invalid_action_definitions(case):
    data = definition()
    action = data["action_types"][0]
    operation = action["operations"][0]
    if case == "operation":
        operation["type"] = "EXECUTE_SQL"
    elif case == "type":
        operation["target"] = "Absent"
    elif case == "link":
        data["action_types"][1]["operations"][1]["target"] = "Absent"
    elif case == "parameter":
        operation["properties"]["operationalStatus"]["parameter"] = "unknown"
    elif case == "property":
        operation["properties"]["unknown"] = operation["properties"].pop("operationalStatus")
    elif case == "binding":
        operation["binding"] = "unknown"
    elif case in {"forward", "circular"}:
        action["bindings"][0]["object_id"] = {
            "kind": "object",
            "binding": "machine" if case == "circular" else "later",
        }
    elif case == "count":
        action["operations"] *= 65
    elif case == "parameter_count":
        action["parameters"] = [dict(id=str(i), name=str(i), data_type="string") for i in range(33)]
    elif case == "binding_count":
        action["bindings"] *= 65
    elif case == "expression":
        operation["properties"]["operationalStatus"] = {"kind": "expression", "code": "1+1"}
    elif case == "shape":
        operation["object_id"] = {"kind": "literal", "value": "extra"}
    elif case == "precondition":
        action["preconditions"] = [dict(type="EXISTS", value={"kind": "literal", "value": 1})]
    elif case == "duplicate_binding":
        action["bindings"] *= 2
    elif case == "endpoint":
        data["action_types"][1]["operations"][1]["destination"] = "employee"
    else:
        operation["properties"]["operationalStatus"] = {
            "kind": "object",
            "binding": "machine",
            "property": "secret",
        }
    with pytest.raises(ValidationError):
        OntologyDefinition.model_validate(data)


@pytest.mark.parametrize(
    "kind,good,bad,extra",
    [
        ("string", "x", 1, {}),
        ("integer", 1, True, {}),
        ("float", 1.0, 1, {}),
        ("boolean", True, "true", {}),
        ("date", "2026-10-28", "28/10/2026", {}),
        ("timestamp", "2026-10-28T00:00:00Z", "2026-10-28T00:00:00", {}),
        ("uuid", "00000000-0000-0000-0000-000000000001", "unknown", {}),
        ("decimal", "12.30", 12.3, dict(precision=6, scale=2)),
        ("string", "OPEN", "UNKNOWN", dict(enum=["OPEN", "COMPLETED"])),
    ],
)
def test_parameter_types_reuse_canonical_validation(kind, good, bad, extra):
    parameter = ParameterDefinition(id="value", name="value", data_type=kind, **extra)
    parameter.validate_value(good)
    with pytest.raises(ValueError):
        parameter.validate_value(bad)


def test_payload_limits_and_unknown_fields():
    for body in (
        {"parameters": {"x": "x" * 65536}},
        {"parameters": {}, "tenant_id": "spoofed"},
        {"parameters": {str(i): i for i in range(33)}},
    ):
        with pytest.raises(ValidationError):
            ActionRequest.model_validate(body)
    data = deepcopy(definition())
    data["action_types"][0]["parameters"][0]["data_type"] = "executable"
    with pytest.raises(ValidationError):
        OntologyDefinition.model_validate(data)
