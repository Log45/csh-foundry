"""Only these reviewed pure implementations can execute. No imports from definitions."""

from typing import Any

from ontology_platform.functions.contracts import FunctionDefinition, GSettings, typed


def execute(request: dict[str, Any]) -> dict[str, Any]:
    spec = FunctionDefinition.model_validate(request["specification"])
    inputs = request["inputs"]
    typed(
        inputs,
        spec.input_schema,
        min(int(request.get("input_limit", GSettings().input_bytes)), 32768),
    )
    if spec.implementation == "identity.v1":
        values = dict(inputs)
    elif spec.implementation == "text.normalize.v1":
        values = {"result": " ".join(inputs["text"].split()).casefold()}
    elif spec.implementation == "number.add.v1":
        values = {"result": inputs["left"] + inputs["right"]}
    else:
        raise ValueError("Unsupported pinned implementation")
    typed(
        values,
        spec.output_schema,
        min(int(request.get("output_limit", GSettings().output_bytes)), 32768),
    )
    return {"values": values}
