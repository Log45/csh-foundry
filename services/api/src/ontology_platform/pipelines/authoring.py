"""Graph authoring uses the same governed transactions and canonical publication service."""

from typing import Any, cast
from uuid import UUID

import polars as pl
from sqlalchemy.orm import Session

from ontology_platform.db.models import PipelineDraft, PipelineGraph
from ontology_platform.errors import ApplicationError
from ontology_platform.functions.service import FunctionService
from ontology_platform.pipelines.contracts import Definition, DefinitionView
from ontology_platform.pipelines.engine import TYPES, plan
from ontology_platform.pipelines.graph import (
    Compilation,
    Diagnostic,
    DraftView,
    FunctionNode,
    Graph,
    SaveDraft,
    SourceNode,
    TransformNode,
    Visualization,
    Visualize,
    compile_graph,
    reconstruct,
)
from ontology_platform.pipelines.service import PipelineService
from ontology_platform.projects.service import conflict
from ontology_platform.security.interfaces import Principal


class AuthoringService(PipelineService):
    def references(self, s: Session, p: Principal, graph: Graph) -> dict[str, pl.LazyFrame]:
        frames = {}
        for node in graph.nodes:
            if isinstance(node, SourceNode):
                if node.config.dataset_id is None or node.config.version_id is None:
                    continue
                source = self.datasets().artifact(s, p, node.config.dataset_id)
                row = self.datasets().record(s, p, node.config.dataset_id, node.config.version_id)
                physical = self.datasets().version(
                    s, p, node.config.dataset_id, node.config.version_id
                )
                if (
                    source.state != "ACTIVE"
                    or row.state != "COMMITTED"
                    or physical.state != "COMMITTED"
                ):
                    raise conflict("Sources must be active committed immutable versions")
                schema = {
                    c["name"]: c["logical_type"]
                    for c in cast(list[dict[str, Any]], row.result["schema"])
                }
                if any(schema.get(c) != t for c, t in node.config.columns.items()):
                    raise conflict("Source schema contract mismatch")
                supported = TYPES | {
                    "Null": pl.Null,
                    "Int32": pl.Int32,
                    "UInt32": pl.UInt32,
                    "Float32": pl.Float32,
                }
                if any(t not in supported for t in schema.values()):
                    raise conflict("Source schema type is not supported by visual planning")
                frames[node.config.name] = pl.LazyFrame(
                    schema={c: supported[t] for c, t in schema.items()}
                )
            elif isinstance(node, FunctionNode):
                if node.config.function_id is None or node.config.definition_id is None:
                    continue
                functions = FunctionService(
                    self.sessions, self.authorizer, self.settings, self.store
                )
                functions.governed_definition(
                    s, p, node.config.function_id, node.config.definition_id
                )
            elif node.kind == "dataset_output":
                if node.config.dataset_id is None:
                    continue
                output = self.datasets().artifact(s, p, node.config.dataset_id)
                if output.state != "ACTIVE":
                    raise conflict("Output dataset is archived")
        return frames

    def compile_in(self, s: Session, p: Principal, key: UUID, graph: Graph) -> Compilation:
        self.artifact(s, p, key)
        result = compile_graph(graph)
        # Reference authority is checked even for structurally invalid drafts; fixed messages
        # never include private source names, schemas, Function contracts or identities.
        try:
            frames = self.references(s, p, graph)
        except ApplicationError:
            return Compilation(
                diagnostics=[
                    Diagnostic(
                        code="reference_unavailable",
                        message=(
                            "A referenced resource/version is unavailable or unauthorized; "
                            "reselect it"
                        ),
                    )
                ]
            )
        if not result.valid:
            return result
        assert result.specification is not None
        try:
            schema = plan(result.specification, frames).collect_schema()
            result.schemas = {
                n.id: {c: str(t) for c, t in frames[n.config.name].collect_schema().items()}
                for n in graph.nodes
                if isinstance(n, SourceNode)
            }
            # Prefix planning reuses exactly the engine's semantics, with metadata only.
            ordered = self.operation_order(graph)
            for index, node in enumerate(ordered):
                prefix = result.specification.model_copy(
                    update={"steps": result.specification.steps[: index + 1], "output_columns": {}}
                )
                result.schemas[node.id] = {
                    c: str(t) for c, t in plan(prefix, frames).collect_schema().items()
                }
            for output_node in graph.nodes:
                if output_node.kind == "dataset_output":
                    result.schemas[output_node.id] = {c: str(t) for c, t in schema.items()}
        except (ValueError, pl.exceptions.PolarsError):
            return Compilation(
                diagnostics=[
                    Diagnostic(
                        code="schema_invalid",
                        message=(
                            "Column, type or output contract is incompatible; "
                            "inspect node configuration"
                        ),
                    )
                ]
            )
        return result

    @staticmethod
    def operation_order(graph: Graph) -> list[TransformNode]:
        incoming = {e.target: e.source for e in graph.edges if e.target_port == "input"}
        nodes = {n.id: n for n in graph.nodes}
        current = next(n.id for n in graph.nodes if n.kind == "dataset_output")
        ordered = []
        while current in incoming:
            current = incoming[current]
            node = nodes[current]
            if isinstance(node, TransformNode):
                ordered.append(node)
        return list(reversed(ordered))

    def compile(self, p: Principal, key: UUID, graph: Graph) -> Compilation:
        with self.scope(p) as s:
            return self.compile_in(s, p, key, graph)

    def publish_graph(self, p: Principal, key: UUID, graph: Graph) -> DefinitionView:
        with self.scope(p) as s:
            self.artifact(s, p, key, True)
            compiled = self.compile_in(s, p, key, graph)
            if not compiled.valid:
                raise ApplicationError(
                    "graph_invalid", "Compile and resolve graph diagnostics before publication", 422
                )
            assert compiled.specification is not None and compiled.output_dataset_id is not None
            self.datasets().artifact(s, p, compiled.output_dataset_id, True)
            view = self.publish_in(s, p, key, compiled.specification)
            s.add(
                PipelineGraph(
                    tenant_id=p.tenant_id,
                    pipeline_id=key,
                    definition_id=view.id,
                    graph=graph.model_dump(mode="json"),
                    semantic_digest=compiled.semantic_digest,
                )
            )
            s.flush()
            return view

    def draft(self, p: Principal, key: UUID) -> DraftView | None:
        with self.scope(p) as s:
            self.artifact(s, p, key)
            row = s.get(PipelineDraft, (p.tenant_id, key, p.principal_id))
            if row is None:
                return None
            graph = Graph.model_validate(row.graph)
            return DraftView(revision=row.revision, graph=graph)

    def save(self, p: Principal, key: UUID, body: SaveDraft) -> DraftView:
        with self.scope(p) as s:
            self.artifact(s, p, key, True)
            self.references(s, p, body.graph)
            row = s.get(PipelineDraft, (p.tenant_id, key, p.principal_id), with_for_update=True)
            if (row.revision if row else 0) != body.expected_revision:
                raise ApplicationError(
                    "draft_conflict",
                    "Draft changed; reopen before saving again (keep a copy of local edits)",
                    409,
                )
            if row is None:
                row = PipelineDraft(
                    tenant_id=p.tenant_id,
                    pipeline_id=key,
                    actor_id=p.principal_id,
                    revision=1,
                    graph=body.graph.model_dump(mode="json"),
                )
                s.add(row)
            else:
                row.revision += 1
                row.graph = body.graph.model_dump(mode="json")
            self.audit(s, p, "pipeline_draft_save", key)
            s.flush()
            return DraftView(revision=row.revision, graph=body.graph)

    def published_graph(self, p: Principal, key: UUID, definition: UUID) -> Graph | None:
        with self.scope(p) as s:
            self.definition(s, p, key, definition)
            row = s.get(PipelineGraph, (p.tenant_id, key, definition))
            if row is None:
                return None
            graph = Graph.model_validate(row.graph)
            self.references(s, p, graph)
            return graph

    def visualize(
        self, p: Principal, key: UUID, definition: UUID, body: Visualize
    ) -> Visualization:
        with self.scope(p) as s:
            row = self.definition(s, p, key, definition)
            result = reconstruct(Definition.model_validate(row.specification), body)
            if result.graph:
                compiled = self.compile_in(s, p, key, result.graph)
                if not compiled.valid:
                    return Visualization(diagnostics=compiled.diagnostics)
            return result
