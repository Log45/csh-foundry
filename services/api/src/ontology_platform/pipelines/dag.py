"""Version two portable DAG contracts and deterministic structural planning."""

import hashlib
import json
from typing import Any

from ontology_platform.pipelines.contracts import (
    DAGDefinition as DAGDefinition,
)
from ontology_platform.pipelines.contracts import (
    DAGInput as DAGInput,
)
from ontology_platform.pipelines.contracts import (
    DAGNode as DAGNode,
)
from ontology_platform.pipelines.contracts import (
    DAGOutput as DAGOutput,
)
from ontology_platform.pipelines.contracts import (
    Definition,
)


def topology(spec: DAGDefinition) -> list[str]:
    """Stable Kahn order; all declared nodes/inputs must contribute to an output."""
    names = [i.name for i in spec.inputs] + [n.id for n in spec.nodes]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate input/node identity")
    if len({o.id for o in spec.outputs}) != len(spec.outputs):
        raise ValueError("Duplicate output identity")
    targets = [o.dataset_id for o in spec.outputs if o.dataset_id is not None]
    if len(targets) != len(set(targets)):
        raise ValueError("Duplicate output target")
    dependencies = {n.id: set(n.inputs.values()) for n in spec.nodes}
    if any(ref not in names for deps in dependencies.values() for ref in deps):
        raise ValueError("Unknown node dependency")
    if any(o.source not in names for o in spec.outputs):
        raise ValueError("Unknown output source")
    consumers: dict[str, int] = dict.fromkeys(names, 0)
    edges = 0
    for node in spec.nodes:
        for ref in node.inputs.values():
            consumers[ref] += 1
            edges += 1
    for output in spec.outputs:
        consumers[output.source] += 1
    if edges + len(spec.outputs) > 216 or max(consumers.values()) > 16:
        raise ValueError("DAG edge/fan-out limit exceeded")
    done = {i.name for i in spec.inputs}
    depths = dict.fromkeys(done, 0)
    ordered: list[str] = []
    while len(ordered) < len(spec.nodes):
        ready = sorted(k for k, deps in dependencies.items() if k not in done and deps <= done)
        if not ready:
            raise ValueError("DAG cycle or self-loop")
        if len(ready) > 32:
            raise ValueError("DAG width exceeds 32")
        for key in ready:
            depths[key] = 1 + max(depths[d] for d in dependencies[key])
            if depths[key] > 64:
                raise ValueError("DAG depth exceeds 64")
            ordered.append(key)
            done.add(key)
    reachable = {o.source for o in spec.outputs}
    pending = list(reachable)
    while pending:
        for dep in dependencies.get(pending.pop(), set()):
            if dep not in reachable:
                reachable.add(dep)
                pending.append(dep)
    if set(names) != reachable:
        raise ValueError("Disconnected node or input")
    return ordered


def canonical(spec: DAGDefinition) -> dict[str, Any]:
    body = spec.model_dump(mode="json")
    for field, key in [("inputs", "name"), ("nodes", "id"), ("outputs", "id")]:
        body[field] = sorted(body[field], key=lambda row: row[key])
    return body


def semantic_digest(spec: DAGDefinition) -> str:
    return hashlib.sha256(
        json.dumps(canonical(spec), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def parse_definition(body: dict[str, Any]) -> Definition | DAGDefinition:
    return (
        DAGDefinition.model_validate(body)
        if "format_version" in body
        else Definition.model_validate(body)
    )
