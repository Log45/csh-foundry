import json
from pathlib import Path

import pytest
from ontology_platform.metadata.compatibility import compare
from ontology_schema.models import OntologyDefinition

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "change,classification",
    [
        ("optional", "additive"),
        ("new_type", "additive"),
        ("new_link", "additive"),
        ("label", "additive"),
        ("remove_property", "breaking"),
        ("remove_type", "breaking"),
        ("required", "breaking"),
        ("datatype", "breaking"),
        ("primary_key", "breaking"),
        ("cardinality", "breaking"),
        ("namespace", "breaking"),
        ("nullable", "breaking"),
        ("unique", "breaking"),
        ("enum", "breaking"),
    ],
)
def test_compatibility_classification(change, classification):
    data = json.loads((ROOT / "ontologies/examples/manufacturing.json").read_text())
    previous = OntologyDefinition.model_validate(data)
    data["version"] = "2.0.0"
    factory = data["object_types"][0]
    if change == "optional":
        factory["properties"].append({"id": "note", "name": "Note", "data_type": "string"})
    elif change == "new_type":
        data["object_types"].append(
            {
                "id": "Other",
                "name": "Other",
                "primary_key": "id",
                "properties": [{"id": "id", "name": "ID", "data_type": "string", "required": True}],
            }
        )
    elif change == "new_link":
        data["link_types"].append(
            {
                "id": "near",
                "name": "Near",
                "source_type": "Factory",
                "target_type": "Factory",
                "cardinality": "many_to_many",
            }
        )
    elif change == "label":
        factory["name"] = "Changed display label"
    elif change == "remove_property":
        factory["properties"].pop()
    elif change == "remove_type":
        data["object_types"].pop()
        data["link_types"] = data["link_types"][:1]
    elif change == "required":
        factory["properties"].append(
            {"id": "code", "name": "Code", "data_type": "string", "required": True}
        )
    elif change == "datatype":
        factory["properties"][-1]["data_type"] = "integer"
    elif change == "primary_key":
        factory["primary_key"] = "factoryName"
    elif change == "cardinality":
        data["link_types"][0]["cardinality"] = "one_to_one"
    elif change == "namespace":
        data["namespace"] = "https://example.org/changed#"
    elif change == "nullable":
        factory["properties"][-1]["nullable"] = True
    elif change == "unique":
        factory["properties"][-1].update(unique=True, indexed=True)
    elif change == "enum":
        factory["properties"][-1]["enum"] = ["Only allowed"]
    result = compare(previous, OntologyDefinition.model_validate(data))
    assert result.classification == classification
    assert bool(result.reasons) == (classification == "breaking")
