"""Real PostgreSQL/MinIO lineage, durable events and privacy regressions."""

# ruff: noqa: F811
from uuid import uuid4

import polars as pl
import pytest
from alembic import command
from alembic.config import Config
from ontology_platform.db.models import LineageEdge, LineagePending
from ontology_platform.execution.worker import ExecutionWorker
from ontology_platform.observability.columns import FrameLineage, apply, records
from ontology_platform.observability.contracts import FreshnessInput, Traversal
from ontology_platform.observability.index import node, tick
from ontology_platform.observability.service import ObservabilityService
from ontology_platform.pipelines.contracts import Step
from sqlalchemy import func, select
from test_artifacts import store  # noqa: F401
from test_datasets import commit, dataset, make_service
from test_phase1 import ROOT, database, historical_database, world  # noqa: F401
from test_pipeline_dag import setup_run
from test_projects import raises
from test_security_platform import security  # noqa: F401


def observer(w, backend):
    return ObservabilityService(w.sessions, w.registry.authorizer, backend.settings, backend)


def drain(w):
    for _ in range(100):
        tick(w.sessions)
        with w.sessions() as s:
            if not s.scalar(
                select(func.count())
                .select_from(LineagePending)
                .where(LineagePending.generation != LineagePending.indexed_generation)
            ):
                return
    pytest.fail("Index did not converge")


def test_real_dag_observability(world, store):
    pipelines, datasets, run, spec, targets = setup_run(world, store)
    svc, p = observer(world, store), world.actor
    before = svc.graph(p, Traversal(root=node("RESOURCE", targets[0].id)))
    assert not before.indexing.complete
    # No successful output provenance is recorded for prepared/queued results.
    assert not before.edges
    assert ExecutionWorker(pipelines).run_one() == run.id
    drain(world)
    status = pipelines.status(p, run.id)
    assert status.state == "SUCCEEDED", status
    output = status.outputs[0]
    root = node("DATASET_VERSION", output.dataset_id, output.version_id)
    graph = svc.graph(p, Traversal(root=root, depth=8))
    assert graph.indexing.complete
    assert any(e.relation == "PRODUCES" for e in graph.edges)
    assert any(n.kind == "EXECUTION" for n in graph.nodes)
    assert any(n.kind == "TRANSFORM_NODE" for n in graph.nodes)
    assert len({n.key for n in graph.nodes}) == len(graph.nodes)
    assert svc.graph(p, Traversal(root=root, depth=8)) == graph
    observed = svc.execution(p, run.id)
    assert observed.execution.publication_state == "COMMITTED"
    assert observed.duration_seconds is not None
    assert len(observed.execution.outputs) == 2
    assert svc.events(p, run.resource_id, 100, 0)
    assert svc.dashboard(p).execution_counts["SUCCEEDED"] == 1
    assert svc.health(p, run.resource_id).last_success_id == run.id
    assert svc.freshness(p, output.dataset_id).last_successful_run_id == run.id
    assert svc.freshness_dependencies(p, output.dataset_id).statuses
    assert svc.freshness(p, output.dataset_id).state == "DISABLED"
    assert svc.policy(p, output.dataset_id, FreshnessInput(max_age_seconds=3600)).state == "FRESH"
    with world.sessions() as s:
        from ontology_platform.db.models import ExecutionJob

        job = s.get(ExecutionJob, (p.tenant_id, run.id))
        assert svc.columns(p, run.resource_id, job.definition_id).status == "EXACT"
        count = s.scalar(select(func.count()).select_from(LineageEdge))
    drain(world)
    with world.sessions() as s:
        assert s.scalar(select(func.count()).select_from(LineageEdge)) == count
    with world.engine.begin() as c:
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["connection"] = c
        command.check(config)


def test_backfill_resume_and_tenant_boundary(world, store):
    datasets, p = make_service(world, store), world.actor
    source = dataset(datasets, p)
    versions = [commit(datasets, p, source.id) for _ in range(3)]
    svc = observer(world, store)
    assert not svc.backfill(p, source.id, 1).complete
    restarted = observer(world, store)
    for _ in range(20):
        if restarted.backfill(p, source.id, 1).complete:
            break
    assert restarted.status_index(p, source.id).complete
    # Completed checkpoints from the earlier unversioned projection must also be reconciled.
    with world.sessions.begin() as session:
        checkpoint = session.get(LineagePending, (p.tenant_id, source.id))
        checkpoint.cursor = checkpoint.cursor.removeprefix("v1|")
    assert not restarted.status_index(p, source.id).complete
    tick(world.sessions)
    assert restarted.status_index(p, source.id).complete
    assert svc.freshness(p, source.id).last_version_id == versions[-1].id
    foreign = p.model_copy(update={"tenant_id": uuid4()})
    raises(403, lambda: svc.graph(foreign, Traversal(root=node("RESOURCE", source.id))))
    raises(404, lambda: svc.graph(p, Traversal(root=node("RESOURCE", uuid4()))))
    raises(422, lambda: svc.backfill(p, source.id, 101))


@pytest.mark.parametrize(
    "op",
    [
        {"op": "select", "columns": ["id"]},
        {"op": "rename", "mapping": {"value": "renamed"}},
        {"op": "drop", "columns": ["value"]},
        {"op": "cast", "mapping": {"value": "Float64"}},
        {"op": "fill_null", "name": "value", "value": 0},
        {
            "op": "derive",
            "name": "sum",
            "expression": {
                "op": "add",
                "args": [{"op": "column", "column": "id"}, {"op": "column", "column": "value"}],
            },
        },
        {
            "op": "aggregate",
            "columns": ["id"],
            "aggregates": [{"column": "value", "function": "sum", "alias": "total"}],
        },
        {
            "op": "filter",
            "expression": {
                "op": "gt",
                "args": [{"op": "column", "column": "value"}, {"op": "literal", "value": 0}],
            },
        },
        {"op": "sort", "columns": ["value"]},
        {"op": "deduplicate", "columns": ["id"]},
        {"op": "union", "input": "right"},
        {"op": "join", "input": "right", "columns": ["id"]},
    ],
)
def test_column_semantics(op):
    left = FrameLineage(
        pl.LazyFrame(schema={"id": pl.Int64, "value": pl.Int64}),
        {"id": {("source", "id")}, "value": {("source", "value")}},
    )
    right = FrameLineage(
        pl.LazyFrame(schema={"id": pl.Int64, "value": pl.Int64}),
        {"id": {("right", "id")}, "value": {("right", "value")}},
    )
    if op["op"] == "join":
        right = apply(Step(op="rename", mapping={"value": "other"}), right)
    result = apply(Step.model_validate(op), left, right if op["op"] in {"join", "union"} else None)
    dependencies, truncated = records(result)
    assert not truncated
    assert result.frame.collect_schema().names() == list(result.values)
    assert all(d.input_name in {"source", "right"} for d in dependencies)
    if op["op"] == "filter":
        assert ("source", "value") in result.rows
        assert result.values["id"] == {("source", "id")}
    if op["op"] == "derive":
        assert result.values["sum"] == {("source", "id"), ("source", "value")}
    if op["op"] == "join":
        assert ("right", "id") in result.rows


def test_real_authorization_prunes_private_sources_and_siblings(security, store):
    from types import SimpleNamespace

    from ontology_platform.projects.contracts import CreateProject, MemberChange, ShareChange
    from ontology_platform.projects.service import ProjectService
    from test_projects import grant_projects

    w, auth, administration, admin, reader, _ = security
    grant_projects(administration, admin, reader)
    secured = SimpleNamespace(
        sessions=w.sessions, registry=SimpleNamespace(authorizer=auth), actor=admin
    )
    pipelines, datasets, run, spec, targets = setup_run(secured, store)
    from worker_support import provision_worker

    assert ExecutionWorker(pipelines, provision_worker(pipelines, admin)).run_one() == run.id
    drain(w)
    projects = ProjectService(w.sessions, auth)
    destination = projects.create_project(admin, CreateProject(name="Reader observations"))
    projects.member(
        admin,
        destination.id,
        MemberChange(
            principal_id=reader.principal_id, role="viewer", expected_revision=destination.revision
        ),
    )
    projects.share(
        admin,
        targets[0].id,
        ShareChange(project_id=destination.id, enabled=True, expected_revision=1),
    )
    svc = ObservabilityService(w.sessions, auth, store.settings, store)
    status = pipelines.status(admin, run.id)
    output = next(o for o in status.outputs if o.dataset_id == targets[0].id)
    root = node("DATASET_VERSION", output.dataset_id, output.version_id)
    graph = svc.graph(reader, Traversal(root=root, depth=8))
    text_result = graph.model_dump_json()
    assert str(targets[1].id) not in text_result
    assert str(spec.inputs[0].dataset_id) not in text_result
    assert not any(n.kind == "EXECUTION" for n in graph.nodes)
    assert svc.dashboard(reader).execution_counts == {}
    raises(404, lambda: svc.health(reader, run.resource_id))
    projects.share(
        admin,
        run.resource_id,
        ShareChange(project_id=destination.id, enabled=True, expected_revision=1),
    )
    graph = svc.graph(reader, Traversal(root=root, depth=8))
    text_result = graph.model_dump_json()
    assert str(targets[1].id) not in text_result
    assert str(spec.inputs[0].dataset_id) not in text_result
    detail = svc.execution(reader, run.id)
    assert not detail.execution.nodes
    assert all(o.dataset_id == targets[0].id for o in detail.execution.outputs)


def test_mapping_observed_types_and_published_application(world, store):
    from test_mappings import setup_mapping

    mappings, mapping, spec, body = setup_mapping(world, store)
    p = world.actor
    run = mappings.start(p, mapping.id, body)
    from ontology_platform.pipelines.service import PipelineService

    assert (
        ExecutionWorker(
            PipelineService(world.sessions, mappings.authorizer, store.settings, store)
        ).run_one()
        == run.id
    )
    drain(world)
    svc = observer(world, store)
    graph = svc.graph(
        p,
        Traversal(
            root=node("DATASET_VERSION", body.dataset_id, body.version_id),
            direction="downstream",
            depth=8,
        ),
    )
    assert any(e.relation == "MATERIALIZES_INTO" for e in graph.edges)
    assert any(n.kind == "ONTOLOGY_OBJECT_TYPE" and n.local_id == "Factory" for n in graph.nodes)


def test_application_pins_are_indexed_without_drafts(world, store):
    from ontology_platform.applications.contracts import Publish, Save
    from test_applications import setup

    apps, project, app, doc = setup(world)
    draft = apps.save(world.actor, app.id, Save(expected_revision=0, document=doc))
    publication = apps.publish(world.actor, app.id, Publish(expected_revision=draft.revision))
    drain(world)
    svc = observer(world, store)
    graph = svc.graph(
        world.actor, Traversal(root=node("APPLICATION_VERSION", app.id, publication.id), depth=8)
    )
    assert any(n.kind == "ONTOLOGY_OBJECT_TYPE" and n.local_id == "Machine" for n in graph.nodes)
    assert all(n.kind != "APPLICATION_DRAFT" for n in graph.nodes)


def test_upgrade_24_26_27_preserves_registry(historical_database, store):
    from test_phase1 import make_world, migrate

    engine, sessions, url = historical_database
    migrate(engine, "0024_pipeline_graphs")
    migrate(engine, "0026_pipeline_dag")
    w = make_world(historical_database)
    datasets = make_service(w, store)
    source = dataset(datasets, w.actor)
    version = commit(datasets, w.actor, source.id)
    migrate(engine)
    svc = observer(w, store)
    assert svc.freshness(w.actor, source.id).last_version_id == version.id
    drain(w)
    assert svc.status_index(w.actor, source.id).complete
    with engine.begin() as connection:
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["connection"] = connection
        command.check(config)


@pytest.mark.parametrize("outcome", ["cancelled", "resource_limit"])
def test_unsuccessful_runs_never_index_published_outputs(world, store, monkeypatch, outcome):
    pipelines, datasets, run, spec, targets = setup_run(world, store)
    p, svc = world.actor, observer(world, store)
    if outcome == "cancelled":
        pipelines.change(p, run.id)
    else:
        monkeypatch.setattr(
            "ontology_platform.pipelines.dag_worker.isolated",
            lambda *args, **kwargs: {"error": "resource_limit"},
        )
        assert ExecutionWorker(pipelines).run_one() == run.id
    drain(world)
    observation = svc.execution(p, run.id)
    assert observation.execution.state in {"FAILED", "CANCELLED"}
    assert not observation.execution.outputs
    with world.sessions() as s:
        assert not s.scalar(
            select(LineageEdge.id).where(
                LineageEdge.provenance == f"run:{run.id}", LineageEdge.relation == "PRODUCES"
            )
        )
    assert svc.events(p, run.resource_id, 100, 0)[0].state in {"FAILED", "CANCELLED"}


def test_project_containment_uses_authoritative_registry(world, store):
    datasets, p = make_service(world, store), world.actor
    source = dataset(datasets, p)
    drain(world)
    svc = observer(world, store)
    graph = svc.graph(
        p, Traversal(root=node("PROJECT", source.project_id), direction="downstream", depth=2)
    )
    assert any(e.relation == "CONTAINS" and e.target.resource_id == source.id for e in graph.edges)
    assert graph.indexing.complete


def test_materialization_to_application_connects_canonical_registry_aliases(world, store):
    from ontology_platform.applications.contracts import Document, Publish, Save
    from ontology_platform.applications.service import ApplicationService
    from ontology_platform.artifacts.contracts import CreateArtifact
    from ontology_platform.pipelines.service import PipelineService
    from ontology_platform.projects.contracts import CreateProject, CreateResource
    from test_applications import document
    from test_mappings import setup_mapping

    mappings, mapping, spec, body = setup_mapping(world, store)
    p = world.actor
    run = mappings.start(p, mapping.id, body)
    assert (
        ExecutionWorker(
            PipelineService(world.sessions, mappings.authorizer, store.settings, store)
        ).run_one()
        == run.id
    )
    apps = ApplicationService(world.sessions, world.registry.authorizer)
    project = apps.create_project(p, CreateProject(name="Separate consumer Project"))
    alias = apps.create_resource(
        p,
        project.id,
        CreateResource(
            name="Independent schema reference",
            resource_type="ONTOLOGY_VERSION",
            ontology_id=spec.ontology_id,
            schema_version=spec.schema_version,
            entity_id=spec.schema_version,
        ),
    )
    assert alias.id != spec.target_resource_id
    app = apps.create(p, project.id, CreateArtifact(name="Factories application"))
    raw = document()
    raw["dependencies"] = [
        {
            "id": "schema",
            "resource_id": str(alias.id),
            "ontology_id": spec.ontology_id,
            "schema_version": spec.schema_version,
        }
    ]
    raw["sources"] = [
        {
            "id": "factories",
            "dependency": "schema",
            "query": {
                "object_type": "Factory",
                "select": ["factoryId", "factoryName"],
                "limit": 10,
            },
        }
    ]
    saved = apps.save(p, app.id, Save(expected_revision=0, document=Document.model_validate(raw)))
    publication = apps.publish(p, app.id, Publish(expected_revision=saved.revision))
    drain(world)
    graph = observer(world, store).graph(
        p,
        Traversal(
            root=node("DATASET_VERSION", body.dataset_id, body.version_id),
            direction="downstream",
            depth=8,
        ),
    )
    assert any(
        n.kind == "APPLICATION_VERSION" and n.version_id == publication.id for n in graph.nodes
    )
    types = [n for n in graph.nodes if n.kind == "ONTOLOGY_OBJECT_TYPE" and n.local_id == "Factory"]
    assert len(types) == 1


def test_automation_receipts_establish_observed_execution(world, store):
    from ontology_platform.automations.contracts import Trigger
    from ontology_platform.automations.service import AutomationService
    from test_media_functions_automations import (
        automation,
        definition,
        resource,
        run_worker,
        service,
    )

    p = world.actor
    functions = service(world, store)
    function = resource(functions, p)
    published = functions.publish_function(p, function.id, definition())
    automations = service(world, store, AutomationService)
    automated, version = automation(automations, p, function, published, Trigger(kind="manual"))
    receipt = automations.manual(p, automated.id, "phase21-observed")
    assert run_worker(automations).run_one() == receipt.job_id
    drain(world)
    graph = observer(world, store).graph(
        p,
        Traversal(
            root=node("AUTOMATION", automated.id, version.id), direction="downstream", depth=8
        ),
    )
    assert any(e.relation == "TRIGGERS" and e.mode == "EXECUTION" for e in graph.edges)
    assert any(n.kind == "EXECUTION" and n.version_id == receipt.job_id for n in graph.nodes)


def test_canonical_type_alias_does_not_reveal_private_ontology_binding(security, store):
    from ontology_platform.observability.index import ontology_node
    from ontology_platform.projects.contracts import (
        CreateProject,
        CreateResource,
        MemberChange,
        ShareChange,
    )
    from ontology_platform.projects.service import ProjectService
    from test_mappings import setup_mapping
    from test_projects import grant_projects

    w, auth, administration, admin, reader, _ = security
    grant_projects(administration, admin, reader)
    mappings, mapping, spec, body = setup_mapping(w, store, prepared=True, actor=admin, auth=auth)
    projects = ProjectService(w.sessions, auth)
    public = projects.create_project(admin, CreateProject(name="Visible canonical schema alias"))
    projects.member(
        admin,
        public.id,
        MemberChange(
            principal_id=reader.principal_id, role="viewer", expected_revision=public.revision
        ),
    )
    alias = projects.create_resource(
        admin,
        public.id,
        CreateResource(
            name="Visible schema",
            resource_type="ONTOLOGY_VERSION",
            ontology_id=spec.ontology_id,
            schema_version=spec.schema_version,
            entity_id=spec.schema_version,
        ),
    )
    projects.share(
        admin, mapping.id, ShareChange(project_id=public.id, enabled=True, expected_revision=1)
    )
    drain(w)
    svc = ObservabilityService(w.sessions, auth, store.settings, store)
    root = ontology_node(
        "ONTOLOGY_OBJECT_TYPE", alias.id, spec.ontology_id, spec.schema_version, "Factory"
    )
    graph = svc.graph(reader, Traversal(root=root, depth=8))
    serialized = graph.model_dump_json()
    assert str(spec.target_resource_id) not in serialized
    assert not graph.edges
    assert len(graph.nodes) == 1
