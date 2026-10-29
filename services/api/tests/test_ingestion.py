"""Governed ingestion on real, isolated PostgreSQL schemas."""

import csv
import json
from pathlib import Path
from uuid import uuid4

import pytest
from ontology_platform.actions.contracts import ExecuteRequest
from ontology_platform.actions.service import ActionExecutionService
from ontology_platform.db.models import EditOverlay, IngestionRun, IngestionStage, Link, Object
from ontology_platform.errors import ApplicationError
from ontology_platform.ingestion.catalog import Binding, InputColumn, SourceCatalog
from ontology_platform.ingestion.contracts import (
    MappingInput,
    MappingRef,
    PropertyMapping,
    RelationshipMapping,
    RunInput,
    SourceInput,
)
from ontology_platform.ingestion.service import IngestionService
from ontology_platform.ingestion.worker import IngestionWorker
from ontology_schema.models import OntologyDefinition
from sqlalchemy import func, select
from test_phase1 import active, make_world
from test_phase1 import database as pg_database

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.integration
FILES = {
    "Factory": ("factories.csv", "factoryId"),
    "Machine": ("machines.csv", "machineId"),
    "Employee": ("employees.csv", "employeeId"),
    "MaintenanceTask": ("maintenance_tasks.csv", "taskId"),
}
RELATIONS = {
    "Machine": [("locatedInFactory", "factoryId")],
    "MaintenanceTask": [
        ("taskForMachine", "machineId"),
        ("assignedEmployee", "assignedEmployeeId"),
    ],
}


@pytest.fixture
def database():
    yield from pg_database.__wrapped__()


def setup(database, tmp_path):
    world = make_world(database)
    data = world.definition.model_dump(mode="json")
    data["action_types"] = json.loads(
        (ROOT / "ontologies/examples/manufacturing-actions.json").read_text()
    )
    world.definition = OntologyDefinition.model_validate(data)
    active(world)
    bindings = []
    for kind, (file, key) in FILES.items():
        (tmp_path / file).write_bytes((ROOT / "fixtures" / file).read_bytes())
        headers = next(csv.reader((tmp_path / file).read_text().splitlines()))
        bindings.append(
            Binding(
                tenant_id=world.actor.tenant_id,
                key=kind,
                kind="csv",
                root=str(tmp_path),
                file_name=file,
                source_key_column=key,
                columns=[InputColumn(name=name) for name in headers],
            )
        )
    catalog = SourceCatalog(bindings)
    service = IngestionService(world.sessions, world.objects.authorizer, catalog)
    worker = IngestionWorker(world.sessions, world.objects.authorizer, catalog)
    for kind, (_, key) in FILES.items():
        service.create_source(
            world.actor,
            world.definition.id,
            SourceInput(id=kind, name=kind, binding=kind, identity_namespace=kind),
        )
        typed = next(t for t in world.definition.object_types if t.id == kind)
        service.create_mapping(
            world.actor,
            world.definition.id,
            MappingInput(
                id=kind,
                source_id=kind,
                source_version=1,
                schema_version=world.definition.version,
                object_type=kind,
                identity_column=key,
                properties=[
                    PropertyMapping(
                        property=p.id,
                        column=p.id,
                        conversion="identity" if p.data_type == "string" else p.data_type,
                    )
                    for p in typed.properties
                ],
                relationships=[
                    RelationshipMapping(link=link, target_column=column)
                    for link, column in RELATIONS.get(kind, [])
                ],
            ),
        )
    return world, service, worker


@pytest.fixture
def ingestion(database, tmp_path):
    return setup(database, tmp_path)


def submit(ingestion, key=None, policy="reject_run", size=25, mappings=None):
    world, service, worker = ingestion
    run = service.submit(
        world.actor,
        world.definition.id,
        RunInput(
            idempotency_key=key or uuid4().hex,
            validation_policy=policy,
            batch_size=size,
            mappings=[MappingRef(id=name, version=1) for name in (mappings or FILES)],
        ),
    )
    return run


def finish(ingestion, run):
    world, service, worker = ingestion
    assert worker.run_one(world.actor, world.definition.id) == run.id
    return service.get(world.actor, world.definition.id, run.id)


def count(world, model):
    with world.sessions() as session:
        return session.scalar(select(func.count()).select_from(model))


def test_manufacturing_end_to_end_and_unchanged_repeat(ingestion):
    world, service, worker = ingestion
    result = finish(ingestion, submit(ingestion))
    assert result.status == "COMPLETED", (
        result,
        service.diagnostics(world.actor, world.definition.id, result.id),
    )
    assert result.created == 63 and result.links_created == 70 and result.rejected == 0
    assert (
        count(world, Object) == 63 and count(world, Link) == 70 and count(world, EditOverlay) > 63
    )
    for kind, expected in [
        ("Factory", 6),
        ("Machine", 20),
        ("Employee", 12),
        ("MaintenanceTask", 25),
    ]:
        assert world.objects.count(world.actor, world.definition.id, kind) == expected
    with world.sessions() as session:
        before = {
            (r.object_type_id, r.object_id): r.version for r in session.scalars(select(Object))
        }
        assert set(session.scalars(select(EditOverlay.owner))) == {"source"}
    repeated = finish(ingestion, submit(ingestion))
    assert (
        repeated.status == "COMPLETED"
        and repeated.created == repeated.updated == repeated.links_created == 0
    )
    assert count(world, Object) == 63 and count(world, Link) == 70
    with world.sessions() as session:
        assert before == {
            (r.object_type_id, r.object_id): r.version for r in session.scalars(select(Object))
        }
    assert not service.diagnostics(world.actor, world.definition.id, repeated.id)


def test_changed_source_and_action_edits(ingestion, tmp_path):
    world, service, _ = ingestion
    assert finish(ingestion, submit(ingestion)).status == "COMPLETED"
    ActionExecutionService(world.sessions, world.objects.authorizer).execute(
        world.actor,
        world.definition.id,
        "UpdateMachineStatus",
        ExecuteRequest(
            idempotency_key="governed",
            parameters={"machineId": "MCH-001", "newStatus": "MAINTENANCE", "expectedRevision": 1},
        ),
    )
    path = tmp_path / "machines.csv"
    text = path.read_text().replace(
        "MCH-001,CNC Mill 01,RUNNING,73.9", "MCH-001,Source Rename,STOPPED,74.0"
    )
    path.write_text(text)
    updated = finish(ingestion, submit(ingestion))
    assert updated.status == "COMPLETED" and updated.updated == 1
    row = world.objects.get(world.actor, world.definition.id, "Machine", "MCH-001")
    assert row.properties["operationalStatus"] == "MAINTENANCE"
    assert row.properties["machineName"] == "Source Rename" and row.version == 3


@pytest.mark.parametrize(
    "policy,created,rejected,status",
    [
        ("reject_run", 0, 1, "FAILED"),
        ("reject_batch", 4, 2, "COMPLETED"),
        ("quarantine", 5, 1, "COMPLETED"),
    ],
)
def test_invalid_batch_policies(ingestion, tmp_path, policy, created, rejected, status):
    world, service, _ = ingestion
    path = tmp_path / "factories.csv"
    path.write_text(
        path.read_text().replace(
            'FAC-002,East Fabrication,"Philadelphia, PA"', 'FAC-002,,"Philadelphia, PA"'
        )
    )
    result = finish(ingestion, submit(ingestion, policy=policy, size=2, mappings=["Factory"]))
    assert result.status == status and result.created == created and result.rejected == rejected
    assert count(world, Object) == created
    assert service.diagnostics(world.actor, world.definition.id, result.id)


def test_duplicate_identity_quarantines_both_rows(ingestion, tmp_path):
    world, _, _ = ingestion
    path = tmp_path / "factories.csv"
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines + [lines[1]]) + "\n")
    result = finish(ingestion, submit(ingestion, policy="quarantine", mappings=["Factory"]))
    assert result.status == "COMPLETED" and result.created == 5 and result.rejected == 2
    with pytest.raises(ApplicationError):
        world.objects.get(world.actor, world.definition.id, "Factory", "FAC-001")


def test_failed_whole_run_relationship_has_no_operational_writes(ingestion, tmp_path):
    world, service, _ = ingestion
    path = tmp_path / "machines.csv"
    path.write_text(path.read_text().replace("FAC-001", "FAC-ABSENT"))
    result = finish(ingestion, submit(ingestion))
    assert result.status == "FAILED" and result.last_error == "not_found"
    assert count(world, Object) == count(world, Link) == 0
    assert count(world, EditOverlay) == 0
    assert service.diagnostics(world.actor, world.definition.id, result.id)


def test_durable_claim_fencing_rollback_and_recovery(ingestion):
    from datetime import UTC, datetime, timedelta

    from ontology_platform.errors import ApplicationError
    from sqlalchemy import update

    world, service, worker = ingestion
    run = submit(ingestion, mappings=["Factory"], size=2)
    key, token = worker.claim(world.actor, world.definition.id)
    assert key == run.id and worker.claim(world.actor, world.definition.id) is None

    def crash():
        raise RuntimeError("simulated loss")

    with pytest.raises(RuntimeError):
        worker.step(world.actor, world.definition.id, key, token, before_commit=crash)
    assert (
        service.get(world.actor, world.definition.id, key).checkpoint == 0
        and count(world, IngestionStage) == 0
    )
    worker.step(world.actor, world.definition.id, key, token)
    assert service.get(world.actor, world.definition.id, key).checkpoint == 1
    with world.sessions.begin() as session:
        session.execute(
            update(IngestionRun).values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
        )
    fresh = IngestionWorker(world.sessions, world.objects.authorizer, worker.catalog)
    _, newtoken = fresh.claim(world.actor, world.definition.id)
    assert newtoken != token
    with pytest.raises(ApplicationError, match="no longer owns"):
        worker.step(world.actor, world.definition.id, key, token)
    while fresh.step(world.actor, world.definition.id, key, newtoken):
        pass
    assert service.get(world.actor, world.definition.id, key).created == 6
    assert count(world, Object) == 6


def test_cancellation_preserves_completed_batches(ingestion):
    from ontology_platform.errors import ApplicationError

    world, service, worker = ingestion
    submit(ingestion, mappings=["Factory"], policy="quarantine", size=2)
    key, token = worker.claim(world.actor, world.definition.id)
    while service.get(world.actor, world.definition.id, key).created == 0:
        worker.step(world.actor, world.definition.id, key, token)
    assert count(world, Object) == 2
    assert service.cancel(world.actor, world.definition.id, key).status == "CANCELLED"
    with pytest.raises(ApplicationError):
        worker.step(world.actor, world.definition.id, key, token)
    assert count(world, Object) == 2 and worker.claim(world.actor, world.definition.id) is None


def test_schema_change_stops_job(ingestion):
    from test_phase1 import next_definition

    world, service, worker = ingestion
    run = submit(ingestion, mappings=["Factory"])
    definition = next_definition(world, lambda d: None)
    world.registry.draft(world.actor, definition.id, definition)
    world.registry.publish(world.actor, definition.id, definition.version)
    world.registry.activate(world.actor, definition.id, definition.version)
    result = finish(ingestion, run)
    assert result.status == "FAILED" and result.last_error == "stale_schema"
    assert count(world, Object) == 0


def test_changed_file_during_staging_stops_without_objects(ingestion, tmp_path):
    from ontology_platform.errors import ApplicationError

    world, service, worker = ingestion
    submit(ingestion, mappings=["Factory"], size=2)
    key, token = worker.claim(world.actor, world.definition.id)
    worker.step(world.actor, world.definition.id, key, token)
    path = tmp_path / "factories.csv"
    path.write_text(path.read_text().replace("North Assembly", "Changed"))
    with pytest.raises(ApplicationError, match="content changed"):
        worker.step(world.actor, world.definition.id, key, token)
    assert (
        count(world, Object) == 0
        and service.get(world.actor, world.definition.id, key).checkpoint == 1
    )


def test_http_submission_and_safe_input(ingestion):
    from fastapi.testclient import TestClient
    from ontology_platform.main import create_app

    world, service, worker = ingestion
    app = create_app(world.settings)
    app.state.sessions = world.sessions
    app.state.ingestion_catalog = worker.catalog
    base = f"/api/v1/ontologies/{world.definition.id}"
    with TestClient(app) as client:
        assert client.get(base + "/sources").status_code == 200
        assert client.get(base + "/sources/Factory").status_code == 200
        payload = {"mappings": [{"id": "Factory", "version": 1}], "idempotency_key": "http"}
        response = client.post(base + "/ingestion/runs", json=payload)
        assert response.status_code == 200
        key = response.json()["id"]
        assert client.post(base + "/ingestion/runs", json=payload).json()["id"] == key
        assert (
            client.post(
                base + "/ingestion/runs", json=payload | {"path": "/etc/passwd"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                base + "/ingestion/runs", json=payload | {"sql": "DROP TABLE objects"}
            ).status_code
            == 422
        )
        assert client.get(base + f"/ingestion/runs/{key}/diagnostics").json() == []
        assert client.get(base + f"/ingestion/runs/{key}").status_code == 200
        assert client.post(base + f"/ingestion/runs/{key}/cancel").json()["status"] == "CANCELLED"
    assert service.runs(world.actor, world.definition.id)


def test_permissions_and_tenant_isolation(ingestion):
    from ontology_platform.errors import ApplicationError
    from ontology_platform.security.interfaces import Principal

    world, service, worker = ingestion
    run = submit(ingestion, mappings=["Factory"])
    for actor in [
        None,
        Principal(tenant_id=uuid4(), principal_id=world.actor.principal_id),
        Principal(tenant_id=world.actor.tenant_id, principal_id="spoof"),
    ]:
        for call in [
            lambda actor=actor: service.get(actor, world.definition.id, run.id),
            lambda actor=actor: service.sources(actor, world.definition.id),
            lambda actor=actor: worker.claim(actor, world.definition.id),
        ]:
            with pytest.raises(ApplicationError):
                call()

    class Deny:
        def require(self, p, operation, resource):
            world.objects.authorizer.require(p, operation, resource)
            if operation == "object:create":
                raise ApplicationError("forbidden", "Denied", 403)

    worker = IngestionWorker(world.sessions, Deny(), worker.catalog)
    worker.run_one(world.actor, world.definition.id)
    assert (
        service.get(world.actor, world.definition.id, run.id).last_error == "forbidden"
        and count(world, Object) == 0
    )


@pytest.mark.parametrize(
    "permission",
    [
        "source:create",
        "source:publish",
        "source:use_binding",
        "mapping:create",
        "mapping:publish",
        "ingestion:execute",
        "ingestion:claim",
        "ingestion:history",
        "ingestion:diagnostics",
        "ingestion:cancel",
    ],
)
def test_governed_ingestion_permissions(ingestion, permission):
    from ontology_platform.db.models import IngestionMapping

    world, service, worker = ingestion

    class Deny:
        def require(self, p, operation, resource):
            world.objects.authorizer.require(p, operation, resource)
            if operation == permission:
                raise ApplicationError("forbidden", "Denied", 403)

    restricted = IngestionService(world.sessions, Deny(), worker.catalog)
    run = submit(ingestion, mappings=["Factory"])
    with pytest.raises(ApplicationError) as error:
        if permission.startswith("source:"):
            restricted.create_source(
                world.actor,
                world.definition.id,
                SourceInput(
                    id="Denied", name="Denied", binding="Factory", identity_namespace="deny"
                ),
            )
        elif permission.startswith("mapping:"):
            with world.sessions() as session:
                snapshot = session.get(
                    IngestionMapping, (world.actor.tenant_id, world.definition.id, "Factory", 1)
                )
                definition = MappingInput.model_validate_json(snapshot.definition_json).model_copy(
                    update={"id": "Denied"}
                )
            restricted.create_mapping(world.actor, world.definition.id, definition)
        elif permission == "ingestion:claim":
            IngestionWorker(world.sessions, Deny(), worker.catalog).claim(
                world.actor, world.definition.id
            )
        elif permission == "ingestion:history":
            restricted.get(world.actor, world.definition.id, run.id)
        elif permission == "ingestion:diagnostics":
            restricted.diagnostics(world.actor, world.definition.id, run.id)
        elif permission == "ingestion:cancel":
            restricted.cancel(world.actor, world.definition.id, run.id)
        else:
            restricted.submit(
                world.actor,
                world.definition.id,
                RunInput(idempotency_key="denied", mappings=[MappingRef(id="Factory", version=1)]),
            )
    assert error.value.code == "forbidden" and count(world, Object) == 0


@pytest.mark.parametrize("permission", ["edit:initialize_source", "property:update", "link:create"])
def test_background_mutation_permissions_fail_closed(ingestion, permission):
    world, service, worker = ingestion

    class Deny:
        def require(self, p, operation, resource):
            world.objects.authorizer.require(p, operation, resource)
            if operation == permission:
                raise ApplicationError("forbidden", "Denied", 403)

    run = submit(ingestion)
    IngestionWorker(world.sessions, Deny(), worker.catalog).run_one(
        world.actor, world.definition.id
    )
    result = service.get(world.actor, world.definition.id, run.id)
    assert result.status == "FAILED" and result.last_error == "forbidden"
    assert count(world, Object) == count(world, Link) == 0


def test_unrelated_source_identity_collision(ingestion):
    world, service, _ = ingestion
    assert finish(ingestion, submit(ingestion, mappings=["Factory"])).created == 6
    service.create_source(
        world.actor,
        world.definition.id,
        SourceInput(id="Other", name="Other source", binding="Factory", identity_namespace="other"),
    )
    service.create_mapping(
        world.actor,
        world.definition.id,
        MappingInput(
            id="Other",
            source_id="Other",
            source_version=1,
            schema_version=world.definition.version,
            object_type="Factory",
            identity_column="factoryId",
            properties=[
                PropertyMapping(property=p, column=p)
                for p in ["factoryId", "factoryName", "location"]
            ],
        ),
    )
    result = finish(ingestion, submit(ingestion, mappings=["Other"]))
    assert (
        result.status == "FAILED"
        and result.last_error == "source_identity_collision"
        and count(world, Object) == 6
    )


def test_relationship_refresh_respects_governed_edits(ingestion, tmp_path):
    from test_phase1 import located

    world, service, _ = ingestion
    assert finish(ingestion, submit(ingestion)).status == "COMPLETED"
    path = tmp_path / "machines.csv"
    path.write_text(
        path.read_text().replace(
            "MCH-001,CNC Mill 01,RUNNING,73.9,FAC-001", "MCH-001,CNC Mill 01,RUNNING,73.9,FAC-002"
        )
    )
    changed = finish(ingestion, submit(ingestion))
    assert changed.status == "COMPLETED" and changed.links_created == 1 and count(world, Link) == 70
    world.objects.delete_link(world.actor, world.definition.id, located("MCH-001", "FAC-002"))
    world.objects.create_link(world.actor, world.definition.id, located("MCH-001", "FAC-003"))
    protected = finish(ingestion, submit(ingestion))
    assert protected.status == "COMPLETED" and protected.links_created == 0
    neighbors = world.objects.neighbors(
        world.actor, world.definition.id, "Machine", "MCH-001", "locatedInFactory"
    )
    assert neighbors[0].object_id == "FAC-003"
    assert any(
        d.code == "relationship_edit_conflict"
        for d in service.diagnostics(world.actor, world.definition.id, protected.id)
    )


def test_removed_source_rows_do_not_delete_objects(ingestion, tmp_path):
    world, _, _ = ingestion
    finish(ingestion, submit(ingestion, mappings=["Factory"]))
    path = tmp_path / "factories.csv"
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n")
    result = finish(ingestion, submit(ingestion, mappings=["Factory"]))
    assert result.processed == 5 and result.updated == 0 and count(world, Object) == 6


@pytest.mark.parametrize("kind", ["json", "parquet"])
def test_json_parquet_end_to_end(ingestion, tmp_path, kind):
    import polars as pl

    world, service, worker = ingestion
    with (tmp_path / "factories.csv").open() as stream:
        records = list(csv.DictReader(stream))
    filename = "factories." + kind
    if kind == "json":
        (tmp_path / filename).write_text("\n".join(json.dumps(r) for r in records) + "\n")
    else:
        pl.DataFrame(records).write_parquet(tmp_path / filename)
    original = worker.catalog.get(world.actor.tenant_id, "Factory")
    worker.catalog.bindings[(world.actor.tenant_id, kind)] = original.model_copy(
        update={"key": kind, "kind": kind, "file_name": filename}
    )
    service.create_source(
        world.actor,
        world.definition.id,
        SourceInput(
            id="Factory", name="Factories", version=2, binding=kind, identity_namespace="Factory"
        ),
    )
    service.create_mapping(
        world.actor,
        world.definition.id,
        MappingInput(
            id="Factory",
            version=2,
            source_id="Factory",
            source_version=2,
            schema_version=world.definition.version,
            object_type="Factory",
            identity_column="factoryId",
            properties=[
                PropertyMapping(property=name, column=name)
                for name in ["factoryId", "factoryName", "location"]
            ],
        ),
    )
    run = service.submit(
        world.actor,
        world.definition.id,
        RunInput(idempotency_key=kind, mappings=[MappingRef(id="Factory", version=2)]),
    )
    result = finish(ingestion, run)
    assert result.status == "COMPLETED" and result.created == 6


@pytest.mark.parametrize(
    "mutation",
    ["object", "property", "column", "link", "identity", "conversion", "default", "duplicate"],
)
def test_invalid_mapping_publication(ingestion, mutation):
    from ontology_platform.db.models import IngestionMapping
    from pydantic import ValidationError

    world, service, _ = ingestion
    with world.sessions() as session:
        original = session.get(
            IngestionMapping, (world.actor.tenant_id, world.definition.id, "Machine", 1)
        )
        definition = json.loads(original.definition_json)
    definition["id"] = "Invalid"
    if mutation == "object":
        definition["object_type"] = "Absent"
    elif mutation == "property":
        definition["properties"][0]["property"] = "unknown"
    elif mutation == "column":
        definition["properties"][0]["column"] = "unknown"
    elif mutation == "link":
        definition["relationships"][0]["link"] = "unknown"
    elif mutation == "identity":
        definition["identity_column"] = "machineName"
    elif mutation == "conversion":
        definition["properties"][0]["conversion"] = "date"
    elif mutation == "default":
        definition["properties"][-1].update(nulls="default", default="invalid")
    else:
        definition["properties"].append(definition["properties"][0])
    with pytest.raises((ValidationError, ApplicationError)):
        service.create_mapping(
            world.actor, world.definition.id, MappingInput.model_validate(definition)
        )


def test_run_history_remains_bound_to_original_configuration(ingestion):
    from ontology_platform.db.models import IngestionMapping

    world, service, worker = ingestion
    first = finish(ingestion, submit(ingestion, key="original", mappings=["Factory"]))
    service.create_source(
        world.actor,
        world.definition.id,
        SourceInput(
            id="Factory",
            version=2,
            name="New label",
            binding="Factory",
            identity_namespace="Factory",
        ),
    )
    with world.sessions() as session:
        original = session.get(
            IngestionMapping, (world.actor.tenant_id, world.definition.id, "Factory", 1)
        )
        definition = MappingInput.model_validate_json(original.definition_json).model_copy(
            update={"version": 2, "source_version": 2}
        )
    service.create_mapping(world.actor, world.definition.id, definition)
    assert submit(ingestion, key="original", mappings=["Factory"]).id == first.id
    with world.sessions() as session:
        persisted = session.get(
            IngestionRun, (world.actor.tenant_id, world.definition.id, first.id)
        )
        assert persisted.plan == [{"id": "Factory", "version": 1}]
    assert (
        service.get_source(world.actor, world.definition.id, "Factory", 1).definition["name"]
        == "Factory"
    )


def test_background_override_permission_is_rechecked(ingestion):
    from test_phase1 import factory

    world, service, worker = ingestion
    world.objects.create(world.actor, world.definition.id, factory(factoryName="Governed name"))
    service.create_source(
        world.actor,
        world.definition.id,
        SourceInput(
            id="Factory",
            version=2,
            name="Factories",
            binding="Factory",
            identity_namespace="Factory",
            reconciliation="source_wins",
        ),
    )
    service.create_mapping(
        world.actor,
        world.definition.id,
        MappingInput(
            id="Factory",
            version=2,
            source_id="Factory",
            source_version=2,
            schema_version=world.definition.version,
            object_type="Factory",
            identity_column="factoryId",
            properties=[
                PropertyMapping(property=name, column=name)
                for name in ["factoryId", "factoryName", "location"]
            ],
        ),
    )
    run = service.submit(
        world.actor,
        world.definition.id,
        RunInput(idempotency_key="override", mappings=[MappingRef(id="Factory", version=2)]),
    )

    class Deny:
        def require(self, p, operation, resource):
            world.objects.authorizer.require(p, operation, resource)
            if operation == "edit:override":
                raise ApplicationError("forbidden", "Override denied", 403)

    IngestionWorker(world.sessions, Deny(), worker.catalog).run_one(
        world.actor, world.definition.id
    )
    result = service.get(world.actor, world.definition.id, run.id)
    row = world.objects.get(world.actor, world.definition.id, "Factory", "FAC-001")
    assert (
        result.last_error == "forbidden"
        and row.version == 1
        and row.properties["factoryName"] == "Governed name"
    )


@pytest.mark.parametrize(
    "constraint,code", [("unique", "unique_conflict"), ("cardinality", "cardinality_conflict")]
)
def test_ingestion_operational_constraint_rollback(ingestion, tmp_path, constraint, code):
    from ontology_platform.contracts import PlanInput
    from ontology_platform.db.models import IngestionMapping
    from test_phase1 import next_definition

    world, service, worker = ingestion

    def mutate(data):
        if constraint == "unique":
            for typed in data["object_types"]:
                if typed["id"] == "Factory":
                    next(p for p in typed["properties"] if p["id"] == "factoryName").update(
                        unique=True, indexed=True
                    )
        else:
            next(t for t in data["link_types"] if t["id"] == "locatedInFactory")["cardinality"] = (
                "one_to_one"
            )

    definition = next_definition(world, mutate)
    world.registry.draft(world.actor, definition.id, definition)
    plan = world.registry.create_plan(world.actor, definition.id, definition.version, PlanInput())
    world.registry.approve_plan(world.actor, definition.id, plan.id)
    world.registry.publish(world.actor, definition.id, definition.version, plan.id)
    world.registry.activate(world.actor, definition.id, definition.version, plan.id)
    names = ["Factory"] if constraint == "unique" else list(FILES)
    for name in names:
        with world.sessions() as session:
            original = session.get(
                IngestionMapping, (world.actor.tenant_id, definition.id, name, 1)
            )
            mapping = MappingInput.model_validate_json(original.definition_json).model_copy(
                update={"version": 2, "schema_version": definition.version}
            )
        service.create_mapping(world.actor, definition.id, mapping)
    if constraint == "unique":
        path = tmp_path / "factories.csv"
        path.write_text(path.read_text().replace("East Fabrication", "North Assembly"))
    run = service.submit(
        world.actor,
        definition.id,
        RunInput(
            idempotency_key=constraint, mappings=[MappingRef(id=name, version=2) for name in names]
        ),
    )
    result = finish(ingestion, run)
    assert result.status == "FAILED" and result.last_error == code
    assert count(world, Object) == count(world, Link) == count(world, EditOverlay) == 0


def test_literal_source_filter_advances_checkpoint_without_replay(ingestion):
    world, service, worker = ingestion
    binding = worker.catalog.get(world.actor.tenant_id, "Factory")
    worker.catalog.bindings[(world.actor.tenant_id, "Filtered")] = binding.model_copy(
        update={"key": "Filtered", "equals": {"factoryId": "FAC-004"}}
    )
    service.create_source(
        world.actor,
        world.definition.id,
        SourceInput(
            id="Filtered", name="Filtered", binding="Filtered", identity_namespace="filtered"
        ),
    )
    service.create_mapping(
        world.actor,
        world.definition.id,
        MappingInput(
            id="Filtered",
            source_id="Filtered",
            source_version=1,
            schema_version=world.definition.version,
            object_type="Factory",
            identity_column="factoryId",
            properties=[
                PropertyMapping(property=name, column=name)
                for name in ["factoryId", "factoryName", "location"]
            ],
        ),
    )
    result = finish(ingestion, submit(ingestion, mappings=["Filtered"], size=1))
    assert result.status == "COMPLETED" and result.created == result.staged == result.processed == 1
    assert result.checkpoint > 6 and count(world, Object) == 1
    assert world.objects.get(world.actor, world.definition.id, "Factory", "FAC-004").version == 1


def test_pipeline_ownership_is_explicit_and_stable(ingestion):
    world, service, worker = ingestion
    service.create_source(
        world.actor,
        world.definition.id,
        SourceInput(
            id="Factory",
            name="Pipeline",
            version=2,
            binding="Factory",
            identity_namespace="Factory",
            owner="pipeline",
        ),
    )
    service.create_mapping(
        world.actor,
        world.definition.id,
        MappingInput(
            id="Factory",
            version=2,
            source_id="Factory",
            source_version=2,
            schema_version=world.definition.version,
            object_type="Factory",
            identity_column="factoryId",
            properties=[
                PropertyMapping(property=name, column=name)
                for name in ["factoryId", "factoryName", "location"]
            ],
        ),
    )

    def run(key):
        return service.submit(
            world.actor,
            world.definition.id,
            RunInput(idempotency_key=key, mappings=[MappingRef(id="Factory", version=2)]),
        )

    assert finish(ingestion, run("pipeline-first")).created == 6
    assert finish(ingestion, run("pipeline-repeat")).updated == 0
    with world.sessions() as session:
        assert set(session.scalars(select(EditOverlay.owner))) == {"pipeline"}
        assert all(row.version == 1 for row in session.scalars(select(Object)))


@pytest.mark.parametrize("kind", ["source", "run"])
def test_listing_requires_each_record_permission(ingestion, kind):
    world, service, worker = ingestion
    run = submit(ingestion, mappings=["Factory"])

    class DenyRecord:
        def require(self, p, operation, resource):
            world.objects.authorizer.require(p, operation, resource)
            if (kind == "source" and resource.endswith("/sources/Factory")) or (
                kind == "run" and resource.endswith(str(run.id))
            ):
                raise ApplicationError("forbidden", "Record denied", 403)

    restricted = IngestionService(world.sessions, DenyRecord(), worker.catalog)
    with pytest.raises(ApplicationError):
        (restricted.sources if kind == "source" else restricted.runs)(
            world.actor, world.definition.id
        )
