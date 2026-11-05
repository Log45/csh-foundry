"""Phase 18 graph contracts, deterministic compilation and governed real execution."""

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from ontology_platform.artifacts.contracts import CreateArtifact
from ontology_platform.db.models import PipelineDraft, PipelineGraph
from ontology_platform.errors import ApplicationError
from ontology_platform.execution.worker import ExecutionWorker
from ontology_platform.pipelines.authoring import AuthoringService
from ontology_platform.pipelines.contracts import Definition, StartRun
from ontology_platform.pipelines.graph import (
    Graph,
    SaveDraft,
    Visualize,
    compile_graph,
    reconstruct,
)
from pydantic import ValidationError
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from test_artifacts import store  # noqa: F401
from test_datasets import commit, dataset, make_service
from test_phase1 import ROOT, database, historical_database, migrate, world  # noqa: F401


def uid(value: int) -> str:
    return str(UUID(int=value))


def linear(*, position: int = 0) -> dict[str, object]:
    return {
        "format_version": 1,
        "nodes": [
            {
                "id": "source",
                "kind": "dataset_source",
                "position": {"x": position, "y": 0},
                "config": {
                    "name": "source",
                    "dataset_id": uid(1),
                    "version_id": uid(2),
                    "columns": {"id": "Int64", "value": "String"},
                },
            },
            {
                "id": "select",
                "kind": "transform",
                "position": {"x": 200, "y": 0},
                "config": {"op": "select", "columns": ["id"]},
            },
            {
                "id": "output",
                "kind": "dataset_output",
                "position": {"x": 400, "y": 0},
                "config": {"dataset_id": uid(3), "columns": {"id": "Int64"}},
            },
        ],
        "edges": [
            {"id": "a", "source": "source", "target": "select"},
            {"id": "b", "source": "select", "target": "output"},
        ],
    }


def codes(value: dict[str, object]) -> set[str]:
    return {item.code for item in compile_graph(Graph.model_validate(value)).diagnostics}


def test_linear_graph_is_deterministic_and_layout_is_nonsemantic():
    first = Graph.model_validate(linear())
    reordered = linear(position=999)
    reordered["nodes"] = list(reversed(reordered["nodes"]))  # type: ignore[index]
    reordered["edges"] = list(reversed(reordered["edges"]))  # type: ignore[index]
    left, right = compile_graph(first), compile_graph(Graph.model_validate(reordered))
    assert left.valid and right.valid
    assert left.specification == right.specification
    assert left.semantic_digest == right.semantic_digest
    assert left.inputs == right.inputs


@pytest.mark.parametrize(
    "mutate,code",
    [
        (
            lambda value: value["edges"].append(
                {"id": "loop", "source": "select", "target": "select"}
            ),
            "cycle",
        ),  # type: ignore[union-attr,index]
        (lambda value: value["edges"].pop(), "missing_input"),  # type: ignore[union-attr,index]
        (lambda value: value["edges"].append(deepcopy(value["edges"][0])), "duplicate_edge"),  # type: ignore[union-attr,index]
        (lambda value: value["nodes"].append(deepcopy(value["nodes"][0])), "duplicate_node"),  # type: ignore[union-attr,index]
        (
            lambda value: value["nodes"].append(
                {"id": "output2", "kind": "dataset_output", "config": {"dataset_id": uid(4)}}
            ),
            "output_count",
        ),  # type: ignore[union-attr,index]
        (
            lambda value: value["edges"].append(
                {"id": "bad", "source": "output", "target": "source"}
            ),
            "port_type",
        ),  # type: ignore[union-attr,index]
        (
            lambda value: value["edges"].append(
                {"id": "missing", "source": "absent", "target": "output"}
            ),
            "missing_node",
        ),  # type: ignore[union-attr,index]
    ],
)
def test_structural_diagnostics(mutate, code):
    value = linear()
    mutate(value)
    assert code in codes(value)


def test_function_and_transformed_branch_are_explicitly_unsupported():
    value = linear()
    value["nodes"].append(  # type: ignore[union-attr,index]
        {
            "id": "function",
            "kind": "function_reference",
            "config": {"function_id": uid(8), "definition_id": uid(9)},
        }
    )
    assert {"function_execution_unsupported", "disconnected"} <= codes(value)
    value = linear()
    value["nodes"].append(  # type: ignore[union-attr,index]
        {"id": "extra", "kind": "transform", "config": {"op": "drop", "columns": ["value"]}}
    )
    value["edges"].extend(  # type: ignore[union-attr,index]
        [
            {"id": "branch", "source": "select", "target": "extra"},
            {"id": "branch-out", "source": "extra", "target": "output"},
        ]
    )
    assert "unsupported_branch" in codes(value)


def test_join_compiles_right_source_to_existing_named_input_contract():
    value = linear()
    value["nodes"][1]["config"] = {  # type: ignore[index]
        "op": "join",
        "input": "right",
        "columns": ["id"],
        "how": "left",
    }
    value["nodes"].insert(  # type: ignore[union-attr,index]
        1,
        {
            "id": "right",
            "kind": "dataset_source",
            "config": {
                "name": "right",
                "dataset_id": uid(4),
                "version_id": uid(5),
                "columns": {"id": "Int64", "other": "String"},
            },
        },
    )
    value["edges"].append(  # type: ignore[union-attr,index]
        {"id": "right-edge", "source": "right", "target": "select", "target_port": "right"}
    )
    result = compile_graph(Graph.model_validate(value))
    assert result.valid
    assert [item.name for item in result.specification.inputs] == ["source", "right"]  # type: ignore[union-attr]
    assert result.specification.steps[0].input == "right"  # type: ignore[union-attr]


def test_contract_limits_and_no_executable_payloads():
    with pytest.raises(ValidationError):
        Graph.model_validate({"format_version": 2, "nodes": [], "edges": []})
    with pytest.raises(ValidationError):
        Graph.model_validate(
            {
                "format_version": 1,
                "nodes": [{"id": "x", "kind": "python", "config": {"code": "import os"}}],
                "edges": [],
            }
        )
    oversized = linear()
    oversized["nodes"] = [deepcopy(oversized["nodes"][0]) for _ in range(119)]  # type: ignore[index]
    with pytest.raises(ValidationError):
        Graph.model_validate(oversized)


def test_existing_definition_round_trip_preserves_canonical_semantics():
    spec = Definition.model_validate(
        {
            "inputs": [{"name": "source", "columns": {"id": "Int64", "value": "String"}}],
            "steps": [{"op": "select", "columns": ["id"]}],
            "output_columns": {"id": "Int64"},
        }
    )
    bindings = Visualize.model_validate(
        {
            "inputs": [{"name": "source", "dataset_id": uid(1), "version_id": uid(2)}],
            "output_dataset_id": uid(3),
        }
    )
    graph = reconstruct(spec, bindings).graph
    assert graph is not None
    assert compile_graph(graph).specification == spec
    missing = bindings.model_copy(update={"inputs": []})
    assert reconstruct(spec, missing).graph is None


def test_visual_graph_publishes_executes_and_records_lineage(world, store):  # noqa: F811
    datasets, principal = make_service(world, store), world.actor
    source = dataset(datasets, principal)
    version = commit(datasets, principal, source.id)
    output = datasets.create(
        principal, source.project_id, CreateArtifact(name="Visual output " + uuid4().hex)
    )
    service = AuthoringService(world.sessions, world.registry.authorizer, store.settings, store)
    pipeline = service.create(
        principal, source.project_id, CreateArtifact(name="Visual pipeline " + uuid4().hex)
    )
    value = linear()
    source_node = value["nodes"][0]  # type: ignore[index]
    source_node["config"] = {  # type: ignore[index]
        "name": "source",
        "dataset_id": str(source.id),
        "version_id": str(version.id),
        "columns": {"id": "Int64", "value": "String"},
    }
    value["nodes"][2]["config"] = {  # type: ignore[index]
        "dataset_id": str(output.id),
        "columns": {"id": "Int64"},
    }
    graph = Graph.model_validate(value)
    compiled = service.compile(principal, pipeline.id, graph)
    assert compiled.valid and compiled.schemas["output"] == {"id": "Int64"}
    draft = service.save(
        principal,
        pipeline.id,
        SaveDraft(expected_revision=0, graph=graph),
    )
    assert service.draft(principal, pipeline.id) == draft
    with pytest.raises(ApplicationError, match="reopen"):
        service.save(
            principal,
            pipeline.id,
            SaveDraft(expected_revision=0, graph=graph),
        )
    definition = service.publish_graph(principal, pipeline.id, graph)
    assert service.published_graph(principal, pipeline.id, definition.id) == graph
    run = service.start(
        principal,
        pipeline.id,
        StartRun(
            definition_id=definition.id,
            inputs=compiled.inputs,
            output_dataset_id=output.id,
        ),
    )
    assert ExecutionWorker(service).run_one() == run.id
    result = service.status(principal, run.id)
    assert result.state == "SUCCEEDED" and result.output_version_id is not None
    metadata = datasets.dataset_metadata(principal, output.id, result.output_version_id)
    assert metadata.result["row_count"] == 2
    lineage = service.lineage(principal, output.id, result.output_version_id)
    assert lineage[0]["definition_id"] == str(definition.id)
    assert lineage[0]["inputs"][0]["version_id"] == str(version.id)  # type: ignore[index]
    with pytest.raises(ApplicationError, match="immutable bindings"):
        service.start(
            principal,
            pipeline.id,
            StartRun(
                definition_id=definition.id,
                inputs=compiled.inputs,
                output_dataset_id=source.id,
            ),
        )
    with world.sessions.begin() as session:
        assert session.scalar(
            select(PipelineGraph).where(PipelineGraph.definition_id == definition.id)
        )
        row = session.scalar(select(PipelineDraft).where(PipelineDraft.pipeline_id == pipeline.id))
        assert row is not None and row.actor_id == principal.principal_id
    with pytest.raises(DBAPIError):
        with world.sessions.begin() as session:
            session.execute(
                update(PipelineGraph)
                .where(PipelineGraph.definition_id == definition.id)
                .values(semantic_digest="0" * 64)
            )


def test_phase18_migration_preserves_previous_head_and_has_no_drift(
    historical_database,  # noqa: F811
):
    engine, _, _ = historical_database
    migrate(engine, "0023_media_functions")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE phase18_sentinel (value TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO phase18_sentinel VALUES ('preserved')"))
    migrate(engine)
    with engine.begin() as connection:
        assert connection.scalar(text("SELECT value FROM phase18_sentinel")) == "preserved"
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0024_pipeline_graphs"
        )
        assert connection.scalar(text("SELECT to_regclass('pipeline_drafts')")) == (
            "pipeline_drafts"
        )
        assert connection.scalar(text("SELECT to_regclass('pipeline_graphs')")) == (
            "pipeline_graphs"
        )
        connection.execute(text("DROP TABLE phase18_sentinel"))
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["connection"] = connection
        command.check(config)
