import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from ontology_schema.models import (
    OntologyDefinition,
    OntologyVersion,
    OperationalIdentity,
    PropertyDefinition,
    RDFMapping,
)
from pydantic import ValidationError

TENANT = "00000000-0000-0000-0000-000000000001"


def definition():
    return {
        "id": "manufacturing",
        "name": "Manufacturing",
        "tenant_id": TENANT,
        "namespace": "https://example.org/manufacturing#",
        "version": "1.0.0",
        "object_types": [
            {
                "id": "Machine",
                "name": "Machine",
                "primary_key": "machineId",
                "properties": [
                    {
                        "id": "machineId",
                        "name": "Machine ID",
                        "data_type": "string",
                        "required": True,
                    }
                ],
            }
        ],
    }


def test_canonical_roundtrip_and_published_snapshot():
    model = OntologyDefinition.model_validate(definition())
    assert OntologyDefinition.model_validate_json(model.canonical_json()) == model
    published = OntologyVersion(
        ontology_id=model.id,
        tenant_id=model.tenant_id,
        version=model.version,
        status="PUBLISHED",
        definition_json=model.canonical_json(),
        published_at=datetime.now(UTC),
    )
    with pytest.raises(ValidationError):
        published.definition_json = "{}"
    assert (
        model.canonical_json()
        == OntologyDefinition.model_validate_json(model.canonical_json()).canonical_json()
    )
    json.loads(model.model_json_schema().get("title") and model.canonical_json())


@pytest.mark.parametrize("mutation", ["duplicate", "primary", "link", "action", "unknown"])
def test_reject_invalid_definitions(mutation):
    data = definition()
    if mutation == "duplicate":
        data["object_types"] *= 2
    elif mutation == "primary":
        data["object_types"][0]["primary_key"] = "missing"
    elif mutation == "link":
        data["link_types"] = [
            {
                "id": "link",
                "name": "link",
                "source_type": "Machine",
                "target_type": "missing",
                "cardinality": "many_to_one",
            }
        ]
    elif mutation == "action":
        data["action_types"] = [
            {
                "id": "action",
                "name": "action",
                "operations": [{"type": "CREATE_OBJECT", "target": "missing"}],
            }
        ]
    else:
        data["unexpected"] = "forbidden"
    with pytest.raises(ValidationError):
        OntologyDefinition.model_validate(data)


@pytest.mark.parametrize(
    "kind,good,bad,extra",
    [
        ("string", "text", 4, {}),
        ("integer", 3, True, {}),
        ("float", 2.5, "2.5", {}),
        ("boolean", True, 1, {}),
        ("date", "2026-10-28", "2026-99-01", {}),
        ("timestamp", "2026-10-28T12:00:00Z", "2026-10-28T12:00:00", {}),
        ("uuid", TENANT, "invalid", {}),
        ("decimal", "12.30", "1234.56", {"precision": 5, "scale": 2}),
    ],
)
def test_strict_values(kind, good, bad, extra):
    prop = PropertyDefinition(id="p", name="P", data_type=kind, default=good, **extra)
    prop.validate_value(good)
    with pytest.raises(ValueError):
        prop.validate_value(bad)
    with pytest.raises(ValidationError):
        PropertyDefinition(id="p", name="P", data_type=kind, default=bad, **extra)


def test_identity_roundtrip_and_collision_resistance():
    mapping = RDFMapping(namespace="https://example.org/mfg#")
    iris = set()
    for tenant in (TENANT, "00000000-0000-0000-0000-000000000002"):
        for obj_type in ("Machine", "Factory"):
            for key in ("a/b", "a%2Fb", "a#b", "机器", "/", " "):
                identity = OperationalIdentity(
                    tenant_id=UUID(tenant),
                    ontology_id="ontology/1",
                    object_type_id=obj_type,
                    object_id=key,
                )
                iri = mapping.individual_iri(identity)
                assert mapping.identity_from_iri(iri) == identity
                assert iri not in iris
                iris.add(iri)
    with pytest.raises(ValueError):
        mapping.identity_from_iri("https://other.example/individual/v1/a")


def test_nullable_arrays_json_and_strict_metadata():
    scalar = PropertyDefinition(
        id="p", name="P", data_type="string", nullable=True, default=None, has_default=True
    )
    scalar.validate_value(None)
    with pytest.raises(ValidationError):
        PropertyDefinition(id="p", name="P", data_type="string", has_default=True)
    with pytest.raises(ValidationError):
        PropertyDefinition(id="p", name="P", data_type="string", required="true")
    array = PropertyDefinition(id="p", name="P", data_type="integer", array=True)
    array.validate_value([1, 2])
    with pytest.raises(ValueError):
        array.validate_value([1, "2"])
    with pytest.raises(ValueError):
        array.validate_value([None])
    document = PropertyDefinition(id="p", name="P", data_type="json")
    document.validate_value({"nested": [1, True, None]})
    with pytest.raises(ValueError):
        document.validate_value({"number": float("nan")})


def test_version_identity_and_breaking_activation_guards():
    from ontology_schema.models import SchemaActivation

    model = OntologyDefinition.model_validate(definition())
    with pytest.raises(ValidationError):
        OntologyVersion(
            ontology_id="other",
            tenant_id=model.tenant_id,
            version=model.version,
            status="DRAFT",
            definition_json=model.canonical_json(),
        )
    with pytest.raises(ValidationError):
        OntologyVersion(
            ontology_id=model.id,
            tenant_id=model.tenant_id,
            version=model.version,
            status="PUBLISHED",
            definition_json=model.canonical_json(),
        )
    with pytest.raises(ValidationError):
        SchemaActivation(
            tenant_id=model.tenant_id,
            ontology_id=model.id,
            version=model.version,
            actor="tester",
            activated_at=datetime.now(UTC),
            compatibility="breaking",
        )


def test_checked_in_manufacturing_contract_and_json_schema():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    model = OntologyDefinition.model_validate_json(
        (root / "ontologies/examples/manufacturing.json").read_text()
    )
    assert {obj.id for obj in model.object_types} == {
        "Factory",
        "Machine",
        "Employee",
        "MaintenanceTask",
    }
    assert (
        json.loads((root / "ontologies/schemas/ontology.schema.json").read_text())
        == model.model_json_schema()
    )
