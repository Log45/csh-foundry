"""Phase 1 persistence tests run against real PostgreSQL in isolated migrated schemas."""

import csv
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from ontology_platform.config import Settings
from ontology_platform.contracts import (
    CreateObject,
    LinkInput,
    MigrationUpdate,
    ObjectPatch,
    PlanInput,
)
from ontology_platform.db.models import (
    Activation,
    Link,
    LinkType,
    MigrationPlan,
    Object,
    ObjectType,
    Ontology,
    Version,
)
from ontology_platform.errors import ApplicationError
from ontology_platform.main import create_app
from ontology_platform.metadata.service import RegistryService
from ontology_platform.objects.service import ObjectService
from ontology_platform.security.interfaces import Principal
from ontology_platform.security.local import LocalAuthorizer
from ontology_platform.security.tenants import TenantService
from ontology_schema.models import OntologyDefinition, RDFMapping
from pydantic import SecretStr
from sqlalchemy import create_engine, delete, func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]


def migrate(engine, target="head", downgrade=False):
    config = Config(str(ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        (command.downgrade if downgrade else command.upgrade)(config, target)


@pytest.fixture
def database():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("NOT RUN: set TEST_DATABASE_URL to a real disposable PostgreSQL database")
    schema = "test_phase1_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))  # Generated identifier only.
    engine = create_engine(
        url, connect_args={"options": f"-c search_path={schema} -c statement_timeout=5000"}
    )
    try:
        migrate(engine)
        yield engine, sessionmaker(engine, expire_on_commit=False), url
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@dataclass
class World:
    engine: object
    sessions: object
    settings: Settings
    actor: Principal
    registry: RegistryService
    objects: ObjectService
    definition: OntologyDefinition


def make_world(database, *, provision=True):
    engine, sessions, url = database
    settings = Settings(
        database_url=SecretStr(url),
        trusted_local_identity=True,
        local_tenant_id=uuid4(),
        local_principal_id="local-developer",
        _env_file=None,
    )
    actor = Principal(tenant_id=settings.local_tenant_id, principal_id=settings.local_principal_id)
    authorizer = LocalAuthorizer(settings)
    if provision:
        TenantService(sessions, authorizer).provision(actor, "Manufacturing test tenant")
    data = json.loads((ROOT / "ontologies/examples/manufacturing.json").read_text())
    data["tenant_id"] = str(actor.tenant_id)
    definition = OntologyDefinition.model_validate(data)
    return World(
        engine,
        sessions,
        settings,
        actor,
        RegistryService(sessions, authorizer),
        ObjectService(sessions, authorizer),
        definition,
    )


@pytest.fixture
def world(database):
    return make_world(database)


def active(world):
    r, p, d = world.registry, world.actor, world.definition
    r.create(p, d)
    r.publish(p, d.id, d.version)
    r.activate(p, d.id, d.version)


def factory(key="FAC-001", **properties):
    return CreateObject(
        object_type_id="Factory",
        object_id=key,
        properties={"factoryId": key, "factoryName": "Factory " + key, "location": "Test"}
        | properties,
    )


def machine(key="MCH-001", **properties):
    return CreateObject(
        object_type_id="Machine",
        object_id=key,
        properties={
            "machineId": key,
            "machineName": "Machine " + key,
            "operationalStatus": "RUNNING",
            "temperatureCelsius": "25.0",
        }
        | properties,
    )


def located(machine_id="MCH-001", factory_id="FAC-001"):
    return LinkInput(
        link_type_id="locatedInFactory",
        source_object_type_id="Machine",
        source_object_id=machine_id,
        target_object_type_id="Factory",
        target_object_id=factory_id,
    )


@contextmanager
def error(code):
    with pytest.raises(ApplicationError) as caught:
        yield
    assert caught.value.code == code


def next_definition(world, mutate, version="2.0.0"):
    data = world.definition.model_dump(mode="json")
    data["version"] = version
    mutate(data)
    return OntologyDefinition.model_validate(data)


def test_tenant_provision_and_registry_metadata(world):
    r, p, d = world.registry, world.actor, world.definition
    with error("tenant_exists"):
        TenantService(world.sessions, r.authorizer).provision(p, "duplicate")
    assert r.create(p, d).status == "DRAFT"
    assert r.get(p, d.id).active_version is None
    assert r.version(p, d.id, d.version).definition == d
    with world.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ObjectType)
                .where(ObjectType.tenant_id == p.tenant_id)
            )
            == 4
        )
        assert (
            session.scalar(
                select(func.count()).select_from(LinkType).where(LinkType.tenant_id == p.tenant_id)
            )
            == 3
        )
    with error("schema_inactive"):
        world.objects.create(p, d.id, factory())
    assert r.validate(p, d.id, d.version).classification == "additive"
    r.publish(p, d.id, d.version)
    assert r.get(p, d.id).active_version is None  # Publication is not activation.
    r.activate(p, d.id, d.version)
    assert len(r.object_types(p, d.id)) == 4
    assert [o.id for o in r.list_ontologies(p)] == [d.id]


def test_immutable_published_snapshots_and_active_fk(world):
    active(world)
    r, p, d = world.registry, world.actor, world.definition
    with error("version_immutable"):
        r.draft(p, d.id, d, replace=True)
    with error("version_immutable"):
        r.publish(p, d.id, d.version)
    new = next_definition(world, lambda data: None)
    r.draft(p, d.id, new)
    statements = [
        update(Version).where(Version.tenant_id == p.tenant_id).values(definition_json="{}"),
        delete(Version).where(Version.tenant_id == p.tenant_id, Version.version == d.version),
        update(ObjectType).where(ObjectType.tenant_id == p.tenant_id).values(definition={}),
        delete(LinkType).where(
            LinkType.tenant_id == p.tenant_id, LinkType.schema_version == d.version
        ),
        update(Ontology)
        .where(Ontology.tenant_id == p.tenant_id)
        .values(active_version=new.version),
        update(Ontology).where(Ontology.tenant_id == p.tenant_id).values(active_version=None),
    ]
    for statement in statements:
        with pytest.raises(IntegrityError), world.sessions.begin() as session:
            session.execute(statement)
    assert r.version(p, d.id, d.version).definition == d
    assert r.get(p, d.id).active_version == d.version


def test_additive_activation_preserves_identity_and_increments_revision(world):
    active(world)
    o, r, p, d = world.objects, world.registry, world.actor, world.definition
    before = o.create(p, d.id, factory())

    def optional(data):
        data["object_types"][0]["properties"].append(
            {"id": "note", "name": "Note", "data_type": "string"}
        )

    new = next_definition(world, optional, "1.1.0")
    r.draft(p, d.id, new)
    assert r.validate(p, d.id, new.version).classification == "additive"
    with error("schema_unpublished"):
        r.activate(p, d.id, new.version)
    r.publish(p, d.id, new.version)
    assert o.get(p, d.id, "Factory", "FAC-001").schema_version == d.version
    r.activate(p, d.id, new.version)
    after = o.get(p, d.id, "Factory", "FAC-001")
    assert after.schema_version == new.version and after.version == before.version + 1
    assert after.object_id == before.object_id and after.properties == before.properties
    assert RDFMapping(namespace=d.namespace).individual_iri(before) == RDFMapping(
        namespace=d.namespace
    ).individual_iri(after)
    assert len(r.versions(p, d.id)) == 2
    with world.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Activation)
                .where(Activation.tenant_id == p.tenant_id)
            )
            == 2
        )


def test_breaking_plan_approval_failure_rollback_and_success(world):
    active(world)
    o, r, p, d = world.objects, world.registry, world.actor, world.definition
    o.create_many(p, d.id, [factory("FAC-001"), factory("FAC-002")])

    def required(data):
        data["object_types"][0]["properties"].append(
            {"id": "code", "name": "Code", "data_type": "string", "required": True}
        )

    new = next_definition(world, required)
    r.draft(p, d.id, new)
    assert r.validate(p, d.id, new.version).classification == "breaking"
    with error("migration_required"):
        r.publish(p, d.id, new.version)
    patch = MigrationUpdate(**factory("FAC-001", code="A").model_dump(), expected_version=1)
    plan = r.create_plan(p, d.id, new.version, PlanInput(updates=[patch]))
    with error("invalid_plan"):
        r.publish(p, d.id, new.version, plan.id)
    r.approve_plan(p, d.id, plan.id)
    with pytest.raises(IntegrityError), world.sessions.begin() as session:
        session.execute(update(MigrationPlan).where(MigrationPlan.id == plan.id).values(updates=[]))
    r.publish(p, d.id, new.version, plan.id)
    # First object is changed/flushed, then full validation finds the un-migrated second object.
    with error("invalid_properties"):
        r.activate(p, d.id, new.version, plan.id)
    assert r.get(p, d.id).active_version == d.version
    assert "code" not in o.get(p, d.id, "Factory", "FAC-001").properties
    assert o.get(p, d.id, "Factory", "FAC-001").version == 1
    full = PlanInput(
        updates=[
            MigrationUpdate(**factory(key, code=key).model_dump(), expected_version=1)
            for key in ("FAC-001", "FAC-002")
        ]
    )
    approved = r.create_plan(p, d.id, new.version, full)
    r.approve_plan(p, d.id, approved.id)
    r.activate(p, d.id, new.version, approved.id)
    assert o.get(p, d.id, "Factory", "FAC-002").properties["code"] == "FAC-002"
    assert r.get(p, d.id).active_version == new.version


def test_stale_plan_and_object_revision_guards(world):
    active(world)
    r, o, p, d = world.registry, world.objects, world.actor, world.definition
    o.create(p, d.id, factory())
    new = next_definition(
        world,
        lambda data: data["object_types"][0]["properties"].append(
            {"id": "code", "name": "Code", "data_type": "string", "required": True}
        ),
    )
    r.draft(p, d.id, new)
    plan = r.create_plan(
        p,
        d.id,
        new.version,
        PlanInput(updates=[MigrationUpdate(**factory(code="A").model_dump(), expected_version=1)]),
    )
    r.approve_plan(p, d.id, plan.id)
    edited = new.model_dump(mode="json")
    edited["name"] = "Renamed draft"
    r.draft(p, d.id, OntologyDefinition.model_validate(edited), replace=True)
    with error("invalid_plan"):
        r.publish(p, d.id, new.version, plan.id)
    new_plan = r.create_plan(
        p,
        d.id,
        new.version,
        PlanInput(updates=[MigrationUpdate(**factory(code="A").model_dump(), expected_version=1)]),
    )
    r.approve_plan(p, d.id, new_plan.id)
    r.publish(p, d.id, new.version, new_plan.id)
    o.patch(
        p,
        d.id,
        "Factory",
        "FAC-001",
        ObjectPatch(expected_version=1, properties={"location": "new"}),
    )
    with error("revision_conflict"):
        r.activate(p, d.id, new.version, new_plan.id)
    assert r.get(p, d.id).active_version == d.version
    assert o.get(p, d.id, "Factory", "FAC-001").properties["location"] == "new"


def test_object_crud_validation_and_atomic_batches(world):
    active(world)
    o, p, d = world.objects, world.actor, world.definition
    created = o.create(p, d.id, factory())
    assert created.version == 1
    assert o.get(p, d.id, "Factory", created.object_id).properties == created.properties
    with error("object_exists"):
        o.create(p, d.id, factory())
    with error("identity_mismatch"):
        o.patch(
            p,
            d.id,
            "Factory",
            "FAC-001",
            ObjectPatch(expected_version=1, properties={"factoryId": "RENAMED"}),
        )
    with error("invalid_properties"):
        o.create(p, d.id, machine(temperatureCelsius=25))
    with error("invalid_properties"):
        o.create(p, d.id, machine(operationalStatus="BROKEN"))
    with error("invalid_properties"):
        o.create(p, d.id, factory("FAC-X", unexpected="field"))
    with error("invalid_properties"):
        o.create_many(p, d.id, [factory("FAC-NEW"), machine(temperatureCelsius="bad")])
    assert o.count(p, d.id, "Factory") == 1
    with error("not_found"):
        o.get(p, d.id, "Factory", "FAC-NEW")
    changed = o.patch(
        p,
        d.id,
        "Factory",
        "FAC-001",
        ObjectPatch(expected_version=1, properties={"location": "updated"}),
    )
    assert changed.version == 2
    with error("revision_conflict"):
        o.patch(
            p,
            d.id,
            "Factory",
            "FAC-001",
            ObjectPatch(expected_version=1, properties={"location": "stale"}),
        )
    with error("revision_conflict"):
        o.delete(p, d.id, "Factory", "FAC-001", 1)
    o.delete(p, d.id, "Factory", "FAC-001", 2)
    assert o.count(p, d.id, "Factory") == 0


def test_real_concurrent_updates_have_one_winner(world):
    active(world)
    o, p, d = world.objects, world.actor, world.definition
    o.create(p, d.id, factory())

    def writer(value):
        try:
            return o.patch(
                p,
                d.id,
                "Factory",
                "FAC-001",
                ObjectPatch(expected_version=1, properties={"location": value}),
            ).version
        except ApplicationError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(writer, ["one", "two"]))
    assert sorted(map(str, results)) == ["2", "revision_conflict"]


@pytest.mark.parametrize(
    "cardinality", ["one_to_one", "many_to_one", "one_to_many", "many_to_many"]
)
def test_relationship_cardinality_and_integrity(world, cardinality):
    data = world.definition.model_dump(mode="json")
    data["link_types"][0]["cardinality"] = cardinality
    world.definition = OntologyDefinition.model_validate(data)
    active(world)
    o, p, d = world.objects, world.actor, world.definition
    o.create_many(
        p, d.id, [factory("FAC-001"), factory("FAC-002"), machine("MCH-001"), machine("MCH-002")]
    )
    with error("not_found"):
        o.create_link(p, d.id, located(factory_id="absent"))
    o.create_link(p, d.id, located())
    if cardinality in {"one_to_one", "many_to_one"}:
        with error("cardinality_conflict"):
            o.create_link(p, d.id, located(factory_id="FAC-002"))
    else:
        o.create_link(p, d.id, located(factory_id="FAC-002"))
    if cardinality in {"one_to_one", "one_to_many"}:
        with error("cardinality_conflict"):
            o.create_link(p, d.id, located(machine_id="MCH-002"))
    else:
        o.create_link(p, d.id, located(machine_id="MCH-002"))
    assert o.neighbors(p, d.id, "Machine", "MCH-001", "locatedInFactory")[0].object_id == "FAC-001"
    assert o.neighbors(p, d.id, "Factory", "FAC-001", "containsMachine")[0].object_id == "MCH-001"
    with error("constraint_conflict"):
        o.delete(p, d.id, "Machine", "MCH-001", 1)
    o.delete_link(p, d.id, located())


def test_concurrent_cardinality_enforcement(world):
    active(world)
    o, p, d = world.objects, world.actor, world.definition
    o.create_many(p, d.id, [factory("FAC-001"), factory("FAC-002"), machine()])

    def writer(target):
        try:
            o.create_link(p, d.id, located(factory_id=target))
            return "created"
        except ApplicationError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(writer, ["FAC-001", "FAC-002"]))
    assert sorted(results) == ["cardinality_conflict", "created"]


def test_cross_tenant_service_and_database_constraints(world, database):
    active(world)
    other = make_world(database)
    active(other)
    p, q, d = world.actor, other.actor, world.definition
    world.objects.create_many(p, d.id, [factory(), machine()])
    other.objects.create(q, d.id, factory("FAC-OTHER"))
    assert world.objects.count(p, d.id, "Factory") == 1
    with error("not_found"):
        other.objects.get(q, d.id, "Machine", "MCH-001")
    with error("not_found"):
        other.objects.patch(
            q, d.id, "Machine", "MCH-001", ObjectPatch(expected_version=1, properties={})
        )
    with error("not_found"):
        world.objects.create_link(p, d.id, located(factory_id="FAC-OTHER"))
    with error("forbidden"):
        world.objects.get(q, d.id, "Factory", "FAC-001")
    with error("forbidden"):
        world.registry.draft(p, d.id, other.definition)
    with pytest.raises(IntegrityError), world.sessions.begin() as session:
        session.add(
            Link(
                tenant_id=p.tenant_id,
                ontology_id=d.id,
                schema_version=d.version,
                **located(factory_id="FAC-OTHER").model_dump(),
            )
        )
    world.objects.create_link(p, d.id, located())
    assert other.objects.neighbors(q, d.id, "Factory", "FAC-OTHER", "containsMachine") == []
    assert other.objects.count(q, d.id, "Factory") == 1


def test_manufacturing_63_objects_70_forward_links_and_inverse_navigation(world, fixtures):
    active(world)
    o, p, d = world.objects, world.actor, world.definition
    records, tables = [], {}
    for filename, cls, key in [
        ("factories.csv", "Factory", "factoryId"),
        ("machines.csv", "Machine", "machineId"),
        ("employees.csv", "Employee", "employeeId"),
        ("maintenance_tasks.csv", "MaintenanceTask", "taskId"),
    ]:
        with (fixtures / filename).open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        tables[cls] = rows
        fields = {prop.id for t in d.object_types if t.id == cls for prop in t.properties}
        records.extend(
            CreateObject(
                object_type_id=cls,
                object_id=row[key],
                properties={field: row[field] for field in fields},
            )
            for row in rows
        )
    created = o.create_many(p, d.id, records)
    assert len(created) == 63
    for cls, count in [("Factory", 6), ("Machine", 20), ("Employee", 12), ("MaintenanceTask", 25)]:
        assert o.count(p, d.id, cls) == count
    for row in tables["Machine"]:
        o.create_link(p, d.id, located(row["machineId"], row["factoryId"]))
    for row in tables["MaintenanceTask"]:
        for link_id, target_type, column in [
            ("taskForMachine", "Machine", "machineId"),
            ("assignedEmployee", "Employee", "assignedEmployeeId"),
        ]:
            o.create_link(
                p,
                d.id,
                LinkInput(
                    link_type_id=link_id,
                    source_object_type_id="MaintenanceTask",
                    source_object_id=row["taskId"],
                    target_object_type_id=target_type,
                    target_object_id=row[column],
                ),
            )
    with world.sessions() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(Link).where(Link.tenant_id == p.tenant_id)
            )
            == 70
        )
    assert (
        o.neighbors(p, d.id, "MaintenanceTask", "TASK-001", "taskForMachine")[0].object_id
        == "MCH-007"
    )
    assert (
        o.neighbors(p, d.id, "MaintenanceTask", "TASK-001", "assignedEmployee")[0].object_id
        == "EMP-005"
    )
    assert {
        row.object_id for row in o.neighbors(p, d.id, "Factory", "FAC-001", "containsMachine")
    } == {"MCH-001", "MCH-007", "MCH-013", "MCH-019"}


def test_migration_upgrade_downgrade(database):
    engine, _, _ = database
    migrate(engine, "0001_tenants", downgrade=True)
    assert set(inspect(engine).get_table_names()) == {"tenants", "alembic_version"}
    migrate(engine)
    assert "object_links" in inspect(engine).get_table_names()
    migrate(engine, "base", downgrade=True)
    assert inspect(engine).get_table_names() == ["alembic_version"]
    migrate(engine)
    assert "ontology_versions" in inspect(engine).get_table_names()


def client_for(world):
    app = create_app(world.settings)
    app.state.sessions = world.sessions
    return TestClient(app)


def test_governed_http_endpoints(world):
    p, d = world.actor, world.definition
    with client_for(world) as client:
        assert client.get("/health/live").status_code == 200
        # World already provisioned. Registry publication/activation are separate API operations.
        response = client.post("/api/v1/ontologies", json=d.model_dump(mode="json"))
        assert response.status_code == 201, response.text
        base = f"/api/v1/ontologies/{d.id}"
        assert client.post(base + f"/versions/{d.version}/publish", json={}).status_code == 200
        assert client.post(base + f"/versions/{d.version}/activate", json={}).status_code == 200
        assert client.get(base + "/object-types").status_code == 200
        path = base + "/objects/Factory"
        payload = factory().model_dump(exclude={"object_type_id"})
        assert client.post(path, json=payload).status_code == 201
        assert client.get(path + "/FAC-001").json()["tenant_id"] == str(p.tenant_id)
        assert (
            client.patch(
                path + "/FAC-001", json={"expected_version": 1, "properties": {"location": "new"}}
            ).json()["version"]
            == 2
        )
        stale = client.patch(path + "/FAC-001", json={"expected_version": 1, "properties": {}})
        assert stale.status_code == 409 and stale.json()["error"]["code"] == "revision_conflict"
        assert client.delete(path + "/FAC-001?expected_version=2").status_code == 204
        assert client.get(path + "/FAC-001").status_code == 404
        assert client.get("/api/v1/ontologies?limit=101").status_code == 422


def test_http_denies_absent_invalid_and_spoofed_tenant(world, database):
    _, sessions, url = database
    app = create_app(Settings(database_url=SecretStr(url), _env_file=None))
    app.state.sessions = sessions
    with TestClient(app) as client:
        assert client.get("/api/v1/ontologies").status_code == 401
        assert client.post("/api/v1/tenant", json={"name": "untrusted"}).status_code == 401
    active(world)
    other = make_world(database)
    active(other)
    other.objects.create(other.actor, other.definition.id, factory("PRIVATE"))
    with client_for(world) as client:
        response = client.get(
            f"/api/v1/ontologies/{world.definition.id}/objects/Factory/PRIVATE",
            headers={"X-Tenant-ID": str(other.actor.tenant_id)},
        )
        assert response.status_code == 404
    unprovisioned = make_world(database, provision=False)
    with client_for(unprovisioned) as client:
        assert client.get("/api/v1/ontologies").status_code == 403
        assert client.post("/api/v1/tenant", json={"name": "Local bootstrap"}).status_code == 201
        assert client.get("/api/v1/tenant").status_code == 200


def test_authorization_interface_cannot_be_bypassed(world):
    active(world)

    class Deny:
        def require(self, principal, operation, resource):
            raise ApplicationError("forbidden", "Denied by policy", 403)

    for call in [
        lambda: ObjectService(world.sessions, Deny()).get(
            world.actor, world.definition.id, "Factory", "x"
        ),
        lambda: ObjectService(world.sessions, Deny()).create(
            world.actor, world.definition.id, factory()
        ),
        lambda: RegistryService(world.sessions, Deny()).get(world.actor, world.definition.id),
        lambda: world.registry.get(None, world.definition.id),
    ]:
        with pytest.raises(ApplicationError) as caught:
            call()
        assert caught.value.status_code in {401, 403}


def test_unique_properties_and_defaults(world):
    data = world.definition.model_dump(mode="json")
    data["object_types"][0]["properties"][1].update(unique=True, indexed=True)
    data["object_types"][0]["properties"].append(
        {"id": "label", "name": "Label", "data_type": "string", "default": "automatic"}
    )
    data["object_types"][1]["properties"][-1].update(unique=True, indexed=True)
    world.definition = OntologyDefinition.model_validate(data)
    active(world)
    o, p, d = world.objects, world.actor, world.definition
    value = o.create(p, d.id, factory("FAC-001", factoryName="Unique name"))
    assert value.properties["label"] == "automatic"
    with error("unique_conflict"):
        o.create(p, d.id, factory("FAC-002", factoryName="Unique name"))
    o.create(p, d.id, machine("MCH-001", temperatureCelsius="12.30"))
    with error("unique_conflict"):
        o.create(p, d.id, machine("MCH-002", temperatureCelsius="12.3"))


def test_activation_cardinality_failure_retains_previous_schema(world):
    data = world.definition.model_dump(mode="json")
    data["link_types"][0]["cardinality"] = "many_to_many"
    world.definition = OntologyDefinition.model_validate(data)
    active(world)
    o, r, p, d = world.objects, world.registry, world.actor, world.definition
    o.create_many(p, d.id, [factory("FAC-001"), factory("FAC-002"), machine()])
    o.create_link(p, d.id, located(factory_id="FAC-001"))
    o.create_link(p, d.id, located(factory_id="FAC-002"))
    proposed = next_definition(
        world, lambda data: data["link_types"][0].update(cardinality="many_to_one")
    )
    r.draft(p, d.id, proposed)
    plan = r.create_plan(p, d.id, proposed.version, PlanInput())
    r.approve_plan(p, d.id, plan.id)
    r.publish(p, d.id, proposed.version, plan.id)
    with error("cardinality_conflict"):
        r.activate(p, d.id, proposed.version, plan.id)
    assert r.get(p, d.id).active_version == d.version
    assert o.get(p, d.id, "Machine", "MCH-001").version == 1
    assert len(o.neighbors(p, d.id, "Machine", "MCH-001", "locatedInFactory")) == 2


def test_draft_replacement_namespace_and_inactive_schema_guards(world):
    r, p, d = world.registry, world.actor, world.definition
    r.create(p, d)
    changed = d.model_dump(mode="json")
    changed["name"] = "Draft replacement"
    r.draft(p, d.id, OntologyDefinition.model_validate(changed), replace=True)
    assert r.version(p, d.id, d.version).definition.name == "Draft replacement"
    changed["namespace"] = "https://example.org/changed#"
    with error("identity_immutable"):
        r.draft(p, d.id, OntologyDefinition.model_validate(changed), replace=True)
    with error("schema_unpublished"):
        r.activate(p, d.id, d.version)


def test_http_plan_approval_activation_and_relationships(world):
    active(world)
    d = world.definition
    with client_for(world) as client:
        base = f"/api/v1/ontologies/{d.id}"
        for record in [factory(), machine()]:
            response = client.post(
                base + "/objects/" + record.object_type_id,
                json=record.model_dump(exclude={"object_type_id"}),
            )
            assert response.status_code == 201, response.text
        assert client.post(base + "/links", json=located().model_dump()).status_code == 201
        neighbors = client.get(base + "/objects/Factory/FAC-001/links/containsMachine")
        assert neighbors.status_code == 200 and neighbors.json()[0]["object_id"] == "MCH-001"
        invalid = located().model_dump() | {"tenant_id": str(uuid4())}
        assert client.post(base + "/links", json=invalid).status_code == 422
        proposed = next_definition(
            world,
            lambda data: data["object_types"][0]["properties"].append(
                {"id": "code", "name": "Code", "data_type": "string", "required": True}
            ),
        )
        assert (
            client.post(base + "/versions", json=proposed.model_dump(mode="json")).status_code
            == 201
        )
        lifecycle = base + f"/versions/{proposed.version}"
        assert client.post(lifecycle + "/validate").json()["classification"] == "breaking"
        assert client.post(lifecycle + "/publish", json={}).status_code == 409
        plan = client.post(
            lifecycle + "/migration-plans",
            json={
                "updates": [
                    MigrationUpdate(
                        **factory(code="A").model_dump(), expected_version=1
                    ).model_dump()
                ]
            },
        ).json()
        assert client.post(base + f"/migration-plans/{plan['id']}/approve").status_code == 200
        assert client.post(lifecycle + "/publish", json={"plan_id": plan["id"]}).status_code == 200
        assert client.post(lifecycle + "/activate", json={"plan_id": plan["id"]}).status_code == 200
        assert client.get(base + "/objects/Factory/FAC-001").json()["properties"]["code"] == "A"
        assert (
            client.request("DELETE", base + "/links", json=located().model_dump()).status_code
            == 204
        )


def test_api_cross_tenant_updates_deletes_and_metadata_rejected(world, database):
    active(world)
    world.objects.create(world.actor, world.definition.id, factory("ONLY-A"))
    other = make_world(database)
    active(other)
    with client_for(other) as client:
        path = f"/api/v1/ontologies/{world.definition.id}/objects/Factory/ONLY-A"
        assert client.patch(path, json={"expected_version": 1, "properties": {}}).status_code == 404
        assert client.delete(path + "?expected_version=1").status_code == 404
        data = world.definition.model_dump(mode="json")
        data["version"] = "2.0.0"
        assert (
            client.post(f"/api/v1/ontologies/{world.definition.id}/versions", json=data).status_code
            == 403
        )
    assert world.objects.get(world.actor, world.definition.id, "Factory", "ONLY-A").version == 1


def test_schema_owner_foreign_keys_reject_cross_tenant_type_reference(world, database):
    active(world)
    other = make_world(database)
    data = other.definition.model_dump(mode="json")
    data["id"] = "other-only"
    other.definition = OntologyDefinition.model_validate(data)
    active(other)
    with pytest.raises(IntegrityError), world.sessions.begin() as session:
        session.add(
            Object(
                tenant_id=world.actor.tenant_id,
                ontology_id="other-only",
                schema_version="1.0.0",
                object_type_id="Factory",
                object_id="X",
                properties={"factoryId": "X", "factoryName": "X", "location": "Test"},
            )
        )


def test_authorization_rechecked_for_migration_data_updates(world):
    active(world)
    world.objects.create(world.actor, world.definition.id, factory())
    proposed = next_definition(
        world,
        lambda data: data["object_types"][0]["properties"].append(
            {"id": "optional", "name": "Optional", "data_type": "string"}
        ),
        "1.1.0",
    )
    r, p, d = world.registry, world.actor, world.definition
    r.draft(p, d.id, proposed)
    r.publish(p, d.id, proposed.version)

    class NoObjectWrites:
        def require(self, principal, operation, resource):
            r.authorizer.require(principal, operation, resource)
            if operation == "object:update":
                raise ApplicationError("forbidden", "No object writes allowed", 403)

    with error("forbidden"):
        RegistryService(world.sessions, NoObjectWrites()).activate(p, d.id, proposed.version)
    assert r.get(p, d.id).active_version == d.version
    assert world.objects.get(p, d.id, "Factory", "FAC-001").version == 1


def test_opaque_ids_and_sql_values_through_http(world):
    active(world)
    with client_for(world) as client:
        base = f"/api/v1/ontologies/{world.definition.id}/objects/Factory"
        key = "FAC/机器#%' OR 1=1 --"
        payload = factory(key).model_dump(exclude={"object_type_id"})
        assert client.post(base, json=payload).status_code == 201
        retrieved = client.get(base, params={"object_id": key})
        assert retrieved.status_code == 200 and retrieved.json()["object_id"] == key
        assert (
            client.patch(
                base,
                params={"object_id": key},
                json={"expected_version": 1, "properties": {"location": "updated"}},
            ).status_code
            == 200
        )
        assert world.objects.count(world.actor, world.definition.id, "Factory") == 1
        assert (
            client.delete(base, params={"object_id": key, "expected_version": 2}).status_code == 204
        )


def test_activation_limit_leaves_previous_version_in_place(world):
    active(world)
    p, d, r = world.actor, world.definition, world.registry
    # Exercise the bound with valid persisted records, without an ingestion pipeline.
    world.objects.create_many(p, d.id, [factory(f"FAC-{i}") for i in range(1000)])
    world.objects.create(p, d.id, factory("FAC-over-limit"))
    proposed = next_definition(world, lambda data: None, "1.1.0")
    r.draft(p, d.id, proposed)
    r.publish(p, d.id, proposed.version)
    with error("activation_too_large"):
        r.activate(p, d.id, proposed.version)
    assert r.get(p, d.id).active_version == d.version
    assert world.objects.get(p, d.id, "Factory", "FAC-0").version == 1


def test_database_type_edit_serializes_with_concurrent_publication(world):
    r, p, d = world.registry, world.actor, world.definition
    r.create(p, d)
    with world.engine.begin() as editing:
        # A harmless direct SQL UPDATE exercises the DB trigger independent of service locks.
        editing.execute(
            update(ObjectType)
            .where(ObjectType.tenant_id == p.tenant_id)
            .values(definition=ObjectType.definition)
        )
        with pytest.raises(OperationalError) as blocked, world.engine.begin() as publishing:
            publishing.execute(text("SET LOCAL lock_timeout = '100ms'"))
            publishing.execute(
                update(Version)
                .where(Version.tenant_id == p.tenant_id)
                .values(status="PUBLISHED", published_at=func.now(), published_by="constraint-test")
            )
        assert blocked.value.orig.sqlstate == "55P03"
    assert r.publish(p, d.id, d.version).status == "PUBLISHED"


def test_approved_plan_invalidated_by_active_version_change(world):
    active(world)
    r, p, d = world.registry, world.actor, world.definition
    target = next_definition(
        world,
        lambda data: data["object_types"][0]["properties"].append(
            {"id": "code", "name": "Code", "data_type": "string", "required": True}
        ),
    )
    r.draft(p, d.id, target)
    old_plan = r.create_plan(p, d.id, target.version, PlanInput())
    r.approve_plan(p, d.id, old_plan.id)
    r.publish(p, d.id, target.version, old_plan.id)
    intermediate = next_definition(world, lambda data: None, "1.1.0")
    r.draft(p, d.id, intermediate)
    r.publish(p, d.id, intermediate.version)
    r.activate(p, d.id, intermediate.version)
    with error("invalid_plan"):
        r.activate(p, d.id, target.version, old_plan.id)
    assert r.get(p, d.id).active_version == intermediate.version
    fresh = r.create_plan(p, d.id, target.version, PlanInput())
    r.approve_plan(p, d.id, fresh.id)
    assert r.activate(p, d.id, target.version, fresh.id).active_version == target.version
