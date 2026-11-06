"""Bounded visual authoring documents; compilation targets the existing ordered IR only."""

import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, FiniteFloat, model_validator

from ontology_platform.pipelines.contracts import Definition, InputContract, InputVersion, Step
from ontology_platform.pipelines.dag import (
    DAGDefinition,
    DAGInput,
    DAGNode,
    DAGOutput,
    semantic_digest,
)
from ontology_platform.projects.contracts import Model, Name

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")]


class Position(Model):
    x: Annotated[FiniteFloat, Field(ge=-100000, le=100000)] = 0
    y: Annotated[FiniteFloat, Field(ge=-100000, le=100000)] = 0


class SourceConfig(Model):
    name: Name
    dataset_id: UUID | None = None
    version_id: UUID | None = None
    columns: dict[str, str] = Field(default_factory=dict, max_length=256)


class OutputConfig(Model):
    format: Literal["parquet", "csv", "ndjson"] = "parquet"
    project_id: UUID | None = None
    name: Name | None = None
    dataset_id: UUID | None = None
    columns: dict[str, str] = Field(default_factory=dict, max_length=256)


class FunctionReference(Model):
    function_id: UUID | None = None
    definition_id: UUID | None = None


class SourceNode(Model):
    id: Identifier
    kind: Literal["dataset_source"]
    position: Position = Field(default_factory=Position)
    config: SourceConfig


class TransformNode(Model):
    id: Identifier
    kind: Literal["transform"]
    position: Position = Field(default_factory=Position)
    config: Step


class OutputNode(Model):
    id: Identifier
    kind: Literal["dataset_output"]
    position: Position = Field(default_factory=Position)
    config: OutputConfig


class FunctionNode(Model):
    id: Identifier
    kind: Literal["function_reference"]
    position: Position = Field(default_factory=Position)
    config: FunctionReference


Node = Annotated[
    SourceNode | TransformNode | OutputNode | FunctionNode, Field(discriminator="kind")
]


class Edge(Model):
    id: Identifier
    source: Identifier
    source_port: Literal["output", "scalar_output"] = "output"
    target: Identifier
    target_port: Literal["input", "right", "scalar_input"] = "input"


class Graph(Model):
    format_version: Literal[1, 2] = 1
    nodes: list[Node] = Field(max_length=118)
    edges: list[Edge] = Field(max_length=216)

    @model_validator(mode="after")
    def budget(self) -> "Graph":
        payload = self.model_dump(mode="json")
        if self.format_version == 1:
            for node in payload["nodes"]:
                if node["kind"] == "dataset_output":
                    config = node["config"]
                    if (
                        config["format"] != "parquet"
                        or config["project_id"] is not None
                        or config["name"] is not None
                    ):
                        raise ValueError("Output formats and new targets require graph format 2")
                    for field in ("format", "project_id", "name"):
                        del config[field]
        if len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()) > 262144:
            raise ValueError("Graph exceeds 256 KiB")
        if any(len(n.config.model_dump_json().encode()) > 16384 for n in self.nodes):
            raise ValueError("Node configuration exceeds 16 KiB")
        for node in self.nodes:
            if isinstance(node, TransformNode) and node.config.expression:
                # Canonical validator enforces depth even for disconnected draft expressions.
                Definition(
                    inputs=[InputContract(name=node.config.input or "source")], steps=[node.config]
                )
        return self


class Diagnostic(Model):
    code: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None


class Compilation(Model):
    valid: bool = False
    diagnostics: list[Diagnostic] = Field(default_factory=list, max_length=256)
    specification: Definition | DAGDefinition | None = None
    outputs: list[DAGOutput] = Field(default_factory=list)
    inputs: list[InputVersion] = Field(default_factory=list)
    output_dataset_id: UUID | None = None
    semantic_digest: str | None = None
    schemas: dict[str, dict[str, str]] = Field(default_factory=dict)


def compile_graph(graph: Graph) -> Compilation:
    """Structural compilation, without I/O. Resource and schema checks are service-owned."""
    if graph.format_version == 2:
        return compile_dag_graph(graph)
    errors: list[Diagnostic] = []

    def error(code: str, message: str, node: str | None = None, edge: str | None = None) -> None:
        if len(errors) < 256:
            errors.append(Diagnostic(code=code, message=message, node_id=node, edge_id=edge))

    nodes = {n.id: n for n in graph.nodes}
    if len(nodes) != len(graph.nodes):
        error("duplicate_node", "Node IDs must be unique")
    if len({e.id for e in graph.edges}) != len(graph.edges):
        error("duplicate_edge", "Edge IDs must be unique")
    incoming: dict[tuple[str, str], str] = {}
    adjacency: dict[str, list[str]] = {n: [] for n in nodes}
    for edge in graph.edges:
        source, target = nodes.get(edge.source), nodes.get(edge.target)
        if source is None or target is None:
            error("missing_node", "Connection references a missing node", edge=edge.id)
            continue
        right = isinstance(target, TransformNode) and target.config.op in {"join", "union"}
        if (
            isinstance(source, (OutputNode, FunctionNode))
            or isinstance(target, (SourceNode, FunctionNode))
            or edge.source_port != "output"
            or edge.target_port not in ({"input", "right"} if right else {"input"})
        ):
            error("port_type", "Connect dataset output to a compatible dataset input", edge=edge.id)
        if edge.target_port == "right" and not isinstance(source, SourceNode):
            error(
                "unsupported_branch",
                "Right input must be an untransformed dataset source",
                edge=edge.id,
            )
        port_key = (edge.target, edge.target_port)
        if port_key in incoming:
            error("duplicate_port", "Only one connection is allowed per input port", edge=edge.id)
        incoming[port_key] = edge.source
        adjacency[edge.source].append(edge.target)
    # Deterministic Kahn ordering detects cycles, including disconnected cycles/self loops.
    indegree = {n: 0 for n in nodes}
    for targets in adjacency.values():
        for target_id in targets:
            indegree[target_id] += 1
    ready = sorted(n for n in nodes if indegree[n] == 0)
    visited = []
    while ready:
        key = ready.pop(0)
        visited.append(key)
        for target_id in sorted(adjacency[key]):
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                ready.append(target_id)
                ready.sort()
    if len(visited) != len(nodes):
        error("cycle", "Graph must be acyclic")
    outputs = [n for n in graph.nodes if isinstance(n, OutputNode)]
    if len(outputs) != 1:
        error("output_count", "Exactly one dataset output is required")
    else:
        predecessors: dict[str, list[str]] = {node_id: [] for node_id in nodes}
        for edge in graph.edges:
            if edge.source in nodes and edge.target in nodes:
                predecessors[edge.target].append(edge.source)
        reachable = {outputs[0].id}
        pending = [outputs[0].id]
        while pending:
            for predecessor in predecessors[pending.pop()]:
                if predecessor not in reachable:
                    reachable.add(predecessor)
                    pending.append(predecessor)
        for node_id in sorted(nodes.keys() - reachable):
            error("disconnected", "Node does not contribute to the output", node_id)
    for node in graph.nodes:
        if isinstance(node, SourceNode) and (
            node.config.dataset_id is None or node.config.version_id is None
        ):
            error(
                "source_reference_required",
                "Select an exact dataset and immutable version",
                node.id,
            )
        if isinstance(node, OutputNode) and node.config.dataset_id is None:
            error("output_reference_required", "Select an output dataset", node.id)
        if isinstance(node, FunctionNode):
            error(
                "function_execution_unsupported",
                "Scalar Functions cannot execute in dataset pipelines; remove this node",
                node.id,
            )
        if isinstance(node, (OutputNode, TransformNode)):
            for port in (
                ["input", "right"]
                if isinstance(node, TransformNode) and node.config.op in {"join", "union"}
                else ["input"]
            ):
                if (node.id, port) not in incoming:
                    error("missing_input", f"Required {port} connection is missing", node.id)
        if isinstance(node, TransformNode) and len(adjacency[node.id]) > 1:
            error(
                "unsupported_branch",
                "Transformed streams cannot branch in the canonical engine",
                node.id,
            )
    if errors:
        return Compilation(diagnostics=errors)
    output = outputs[0]
    used = {output.id}
    steps = []
    current = incoming[(output.id, "input")]
    while isinstance(nodes[current], TransformNode):
        node = nodes[current]
        assert isinstance(node, TransformNode)
        used.add(current)
        step = node.config.model_copy(deep=True)
        if step.op in {"join", "union"}:
            source = nodes[incoming[(current, "right")]]
            assert isinstance(source, SourceNode)
            if step.input != source.config.name:
                error("input_binding", "Operation input name must match its right source", current)
            used.add(source.id)
        steps.append(step)
        current = incoming[(current, "input")]
    main = nodes[current]
    if not isinstance(main, SourceNode):
        error("source_required", "The main chain must begin with a dataset source", current)
        return Compilation(diagnostics=errors)
    used.add(main.id)
    sources = [main] + sorted(
        [n for n in graph.nodes if isinstance(n, SourceNode) and n.id != main.id],
        key=lambda n: n.config.name,
    )
    for node in graph.nodes:
        if node.id not in used:
            error("disconnected", "Node does not contribute to the output", node.id)
    if len({n.config.name for n in sources}) != len(sources):
        error("duplicate_input_name", "Source input names must be unique")
    if len(sources) > 16 or len(steps) > 100:
        error("canonical_budget", "Canonical limit: sixteen inputs and one hundred operations")
    if errors:
        return Compilation(diagnostics=errors)
    spec = Definition(
        inputs=[InputContract(name=n.config.name, columns=n.config.columns) for n in sources],
        steps=list(reversed(steps)),
        output_columns=output.config.columns,
    )
    pins = []
    for source_node in sources:
        assert source_node.config.dataset_id is not None
        assert source_node.config.version_id is not None
        pins.append(
            InputVersion(
                name=source_node.config.name,
                dataset_id=source_node.config.dataset_id,
                version_id=source_node.config.version_id,
            )
        )
    assert output.config.dataset_id is not None
    semantic = {
        "specification": spec.model_dump(mode="json"),
        "inputs": [p.model_dump(mode="json") for p in pins],
        "output_dataset_id": str(output.config.dataset_id),
    }
    digest = hashlib.sha256(
        json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return Compilation(
        valid=True,
        specification=spec,
        inputs=pins,
        output_dataset_id=output.config.dataset_id,
        semantic_digest=digest,
    )


class Visualize(Model):
    inputs: list[InputVersion] = Field(min_length=1, max_length=16)
    output_dataset_id: UUID


class Visualization(Model):
    graph: Graph | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)


def reconstruct(spec: Definition, bindings: Visualize) -> Visualization:
    pins = {p.name: p for p in bindings.inputs}
    if len(pins) != len(bindings.inputs) or set(pins) != {i.name for i in spec.inputs}:
        return Visualization(
            diagnostics=[
                Diagnostic(
                    code="pins_required", message="Supply exact pins for every canonical input"
                )
            ]
        )
    nodes: list[Node] = []
    edges = []
    sources = {}
    for index, contract in enumerate(spec.inputs):
        key = f"source-{index}"
        sources[contract.name] = key
        nodes.append(
            SourceNode(
                id=key,
                kind="dataset_source",
                position=Position(x=0, y=index * 160),
                config=SourceConfig(**pins[contract.name].model_dump(), columns=contract.columns),
            )
        )
    previous = sources[spec.inputs[0].name]
    for index, step in enumerate(spec.steps):
        key = f"step-{index}"
        nodes.append(
            TransformNode(
                id=key, kind="transform", position=Position(x=(index + 1) * 240, y=0), config=step
            )
        )
        edges.append(Edge(id=f"edge-{index}", source=previous, target=key))
        if step.input:
            edges.append(
                Edge(
                    id=f"right-{index}", source=sources[step.input], target=key, target_port="right"
                )
            )
        previous = key
    nodes.append(
        OutputNode(
            id="output",
            kind="dataset_output",
            position=Position(x=(len(spec.steps) + 1) * 240, y=0),
            config=OutputConfig(dataset_id=bindings.output_dataset_id, columns=spec.output_columns),
        )
    )
    edges.append(Edge(id="output-edge", source=previous, target="output"))
    graph = Graph(nodes=nodes, edges=edges)
    result = compile_graph(graph)
    return Visualization(graph=graph if result.valid else None, diagnostics=result.diagnostics)


class SaveDraft(Model):
    expected_revision: int = Field(ge=0)
    graph: Graph


class DraftView(Model):
    revision: int
    graph: Graph


def compile_dag_graph(graph: Graph) -> Compilation:
    """Canvas-independent v2 compilation, retaining v1 historical compilation unchanged."""
    from pydantic import ValidationError

    errors: list[Diagnostic] = []

    def error(code: str, message: str, node: str | None = None, edge: str | None = None) -> None:
        if len(errors) < 256:
            errors.append(Diagnostic(code=code, message=message, node_id=node, edge_id=edge))

    nodes = {n.id: n for n in graph.nodes}
    if len(nodes) != len(graph.nodes):
        error("duplicate_node", "Node IDs must be unique")
    if len({e.id for e in graph.edges}) != len(graph.edges):
        error("duplicate_edge", "Edge IDs must be unique")
    incoming: dict[str, dict[str, str]] = {key: {} for key in nodes}
    refs = {n.id: n.config.name if isinstance(n, SourceNode) else n.id for n in graph.nodes}
    for edge in graph.edges:
        source, target = nodes.get(edge.source), nodes.get(edge.target)
        if source is None or target is None:
            error("missing_node", "Connection references a missing node", edge=edge.id)
            continue
        ports = (
            {"input", "right"}
            if isinstance(target, TransformNode) and target.config.op in {"join", "union"}
            else {"input"}
        )
        if (
            isinstance(source, (OutputNode, FunctionNode))
            or isinstance(target, (SourceNode, FunctionNode))
            or edge.source_port != "output"
            or edge.target_port not in ports
        ):
            error("port_type", "Connect compatible dataset ports", edge=edge.id)
            continue
        if edge.target_port in incoming[target.id]:
            error("duplicate_port", "One edge is allowed per input port", target.id, edge.id)
        incoming[target.id][edge.target_port] = refs[source.id]
    inputs = []
    transforms = []
    outputs = []
    for node in graph.nodes:
        if isinstance(node, SourceNode):
            if node.config.dataset_id is None or node.config.version_id is None:
                error("source_reference_required", "Select exact dataset/version", node.id)
            else:
                try:
                    inputs.append(DAGInput(**node.config.model_dump()))
                except ValidationError:
                    error(
                        "input_identity_invalid",
                        "Use a stable source name with letters, numbers, underscores or hyphens",
                        node.id,
                    )
        elif isinstance(node, FunctionNode):
            error(
                "function_execution_unsupported",
                "Scalar Functions cannot execute in pipelines",
                node.id,
            )
        elif isinstance(node, TransformNode):
            step = (
                node.config.model_copy(update={"input": "right"})
                if node.config.op in {"join", "union"}
                else node.config
            )
            try:
                transforms.append(DAGNode(id=node.id, inputs=incoming[node.id], config=step))
            except ValidationError:
                error("missing_input", "Required operation input ports are missing", node.id)
        elif isinstance(node, OutputNode):
            if "input" not in incoming[node.id]:
                error("missing_input", "Connect an output source", node.id)
            else:
                try:
                    outputs.append(
                        DAGOutput(
                            id=node.id,
                            source=incoming[node.id]["input"],
                            **node.config.model_dump(),
                        )
                    )
                except ValidationError:
                    error(
                        "output_reference_required",
                        "Select output dataset or new Project/name",
                        node.id,
                    )
    if errors:
        return Compilation(diagnostics=errors)
    try:
        spec = DAGDefinition(format_version=2, inputs=inputs, nodes=transforms, outputs=outputs)
    except ValidationError as exc:
        return Compilation(
            diagnostics=[
                Diagnostic(code="dag_invalid", message=e["msg"])
                for e in exc.errors(include_input=False)
            ][:256]
        )
    return Compilation(
        valid=True,
        specification=spec,
        inputs=[
            InputVersion(name=i.name, dataset_id=i.dataset_id, version_id=i.version_id)
            for i in spec.inputs
        ],
        outputs=spec.outputs,
        semantic_digest=semantic_digest(spec),
    )
