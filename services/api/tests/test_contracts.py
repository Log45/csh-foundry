import pytest
from ontology_platform.contracts import CreateObject, PlanInput
from pydantic import ValidationError


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_object_and_plan_contracts_reject_nonfinite_nested_json(value):
    payload = {
        "object_type_id": "Factory",
        "object_id": "FAC-001",
        "properties": {"nested": [value]},
    }
    with pytest.raises(ValidationError):
        CreateObject.model_validate(payload)
    with pytest.raises(ValidationError):
        PlanInput.model_validate({"updates": [payload | {"expected_version": 1}]})
