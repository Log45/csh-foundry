"""Action, reconciliation and outbox guarantees on real PostgreSQL."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from ontology_platform.actions.contracts import ActionRequest, ExecuteRequest
from ontology_platform.actions.service import ActionExecutionService
from ontology_platform.contracts import CreateObject, ObjectPatch
from ontology_platform.db.models import (
    ActionExecution,
    AuditEvent,
    EditOverlay,
    Object,
    OutboxEvent,
    ReconciliationConflict,
    WebhookAttempt,
)
from ontology_platform.edits.service import ReconciliationService, SourceUpdate
from ontology_platform.errors import ApplicationError
from ontology_platform.jobs.webhooks import WebhookRunner, deliver, destination
from ontology_platform.main import create_app
from ontology_platform.security.interfaces import Principal
from ontology_schema.models import OntologyDefinition
from sqlalchemy import event, func, select, text, update
from sqlalchemy.exc import IntegrityError
from test_phase1 import active, machine, make_world, migrate, next_definition
from test_phase1 import database as pg_database

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.integration


def examples():
    return json.loads((ROOT / "ontologies/examples/manufacturing-actions.json").read_text())


@pytest.fixture
def database():
    yield from pg_database.__wrapped__()


@pytest.fixture
def world(database):
    world = make_world(database)
    data = world.definition.model_dump(mode="json")
    data["action_types"] = examples()
    world.definition = OntologyDefinition.model_validate(data)
    active(world)
    world.objects.create(world.actor, world.definition.id, machine())
    for key in ("EMP-001", "EMP-002"):
        world.objects.create(
            world.actor,
            world.definition.id,
            CreateObject(
                object_type_id="Employee",
                object_id=key,
                properties={"employeeId": key, "employeeName": key, "department": "Maintenance"},
            ),
        )
    return world


def service(world, authorizer=None):
    return ActionExecutionService(world.sessions, authorizer or world.objects.authorizer)


def execute(world, action="UpdateMachineStatus", key="key", **params):
    return service(world).execute(
        world.actor,
        world.definition.id,
        action,
        ExecuteRequest(
            idempotency_key=key,
            parameters=params
            or {"machineId": "MCH-001", "newStatus": "STOPPED", "expectedRevision": 1},
        ),
    )


def count(world, model):
    with world.sessions() as session:
        return session.scalar(select(func.count()).select_from(model))


def object_row(world, kind="Machine", key="MCH-001"):
    return world.objects.get(world.actor, world.definition.id, kind, key)


def task(world, key="TASK-001", status="OPEN"):
    return world.objects.create(
        world.actor,
        world.definition.id,
        CreateObject(
            object_type_id="MaintenanceTask",
            object_id=key,
            properties={"taskId": key, "scheduledDate": "2026-11-01", "taskStatus": status},
        ),
    )


def schedule(world, key="schedule", **params):
    return execute(
        world,
        "ScheduleMaintenance",
        key,
        **(
            {
                "machineId": "MCH-001",
                "employeeId": "EMP-001",
                "taskId": "TASK-NEW",
                "scheduledDate": "2026-11-01",
            }
            | params
        ),
    )


def test_preview_execution_and_durable_retry(world):
    before_overlays = count(world, EditOverlay)
    request = ExecuteRequest(
        idempotency_key="key",
        parameters={"machineId": "MCH-001", "newStatus": "STOPPED", "expectedRevision": 1},
    )
    preview = service(world).preview(
        world.actor,
        world.definition.id,
        "UpdateMachineStatus",
        ActionRequest(parameters=request.parameters),
    )
    assert preview.advisory and preview.execution_id is None
    assert preview.changes[0].new_revision == 2
    assert object_row(world).version == 1
    assert count(world, EditOverlay) == before_overlays
    for model in (ActionExecution, AuditEvent, OutboxEvent):
        assert count(world, model) == 0
    result = execute(world)
    assert result.changes == preview.changes
    assert object_row(world).properties["operationalStatus"] == "STOPPED"
    assert object_row(world).version == 2
    assert (
        service(world).execute(world.actor, world.definition.id, "UpdateMachineStatus", request)
        == result
    )
    assert (
        service(world).get_execution(world.actor, world.definition.id, result.execution_id).result
        == result
    )
    assert len(service(world).audit(world.actor, world.definition.id, result.execution_id)) == 1
    for model in (ActionExecution, AuditEvent, OutboxEvent):
        assert count(world, model) == 1
    with world.sessions() as session:
        overlay = session.get(
            EditOverlay,
            (world.actor.tenant_id, world.definition.id, "Machine", "MCH-001", "operationalStatus"),
        )
        assert overlay.owner == "action" and overlay.execution_id == result.execution_id
        event = session.scalar(select(OutboxEvent))
        assert "STOPPED" not in json.dumps(event.payload)
        audit = session.scalar(select(AuditEvent))
        assert "STOPPED" not in json.dumps(audit.details)


@pytest.mark.parametrize(
    "params,code",
    [
        ({"newStatus": "BROKEN"}, "invalid_action"),
        ({"expectedRevision": True}, "invalid_action"),
        ({"expectedRevision": "1"}, "invalid_action"),
        ({"unknown": "x"}, "invalid_action"),
        ({"expectedRevision": 2}, "revision_conflict"),
        ({"machineId": "absent"}, "not_found"),
    ],
)
def test_invalid_execution_rolls_back(world, params, code):
    with pytest.raises(ApplicationError) as error:
        execute(
            world,
            **({"machineId": "MCH-001", "newStatus": "STOPPED", "expectedRevision": 1} | params),
        )
    assert error.value.code == code
    assert object_row(world).version == 1
    assert (
        count(world, ActionExecution) == count(world, OutboxEvent) == count(world, AuditEvent) == 0
    )


def test_idempotency_conflict_and_schema_change(world):
    result = execute(world)
    with pytest.raises(ApplicationError, match="Key belongs"):
        execute(world, machineId="MCH-001", newStatus="RUNNING", expectedRevision=1)
    definition = next_definition(world, lambda data: None)
    world.registry.draft(world.actor, definition.id, definition)
    world.registry.publish(world.actor, definition.id, definition.version)
    world.registry.activate(world.actor, definition.id, definition.version)
    assert execute(world) == result
    assert object_row(world).version == 3
    assert count(world, ActionExecution) == 1


@pytest.mark.parametrize("same_key,same_payload", [(True, True), (True, False), (False, False)])
def test_concurrent_retries_and_revisions(world, same_key, same_payload):
    def run(index):
        try:
            return execute(
                world,
                key="shared" if same_key else str(index),
                machineId="MCH-001",
                newStatus="STOPPED" if same_payload or index == 0 else "CRITICAL",
                expectedRevision=1,
            )
        except ApplicationError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, [0, 1]))
    successes = [r for r in results if not isinstance(r, str)]
    if same_key and same_payload:
        assert len(successes) == 2 and successes[0] == successes[1]
    else:
        assert len(successes) == 1
        assert ("idempotency_conflict" if same_key else "revision_conflict") in results
    assert count(world, ActionExecution) == 1 and object_row(world).version == 2


def test_schedule_atomic_preview_links_and_retry(world):
    params = dict(
        machineId="MCH-001", employeeId="EMP-001", taskId="TASK-NEW", scheduledDate="2026-11-01"
    )
    preview = service(world).preview(
        world.actor, world.definition.id, "ScheduleMaintenance", ActionRequest(parameters=params)
    )
    assert len(preview.changes) == 3
    with pytest.raises(ApplicationError):
        object_row(world, "MaintenanceTask", "TASK-NEW")
    result = schedule(world)
    assert schedule(world) == result
    assert object_row(world, "MaintenanceTask", "TASK-NEW").properties["taskStatus"] == "OPEN"
    neighbors = world.objects.neighbors(
        world.actor, world.definition.id, "MaintenanceTask", "TASK-NEW", "assignedEmployee"
    )
    assert neighbors[0].object_id == "EMP-001"
    assert count(world, AuditEvent) == 3 and count(world, OutboxEvent) == 1


def test_late_failure_rolls_back_and_key_can_retry(world):
    # Deny the last relationship after the task and first edge have been inserted.
    class Deny:
        def require(self, principal, operation, resource):
            world.objects.authorizer.require(principal, operation, resource)
            if operation == "link:create" and resource.endswith("assignedEmployee"):
                raise ApplicationError("forbidden", "Denied", 403)

    params = dict(
        machineId="MCH-001", employeeId="EMP-001", taskId="TASK-NEW", scheduledDate="2026-11-01"
    )
    request = ExecuteRequest(idempotency_key="retry", parameters=params)
    for preview in (True, False):
        with pytest.raises(ApplicationError):
            (service(world, Deny()).preview if preview else service(world, Deny()).execute)(
                world.actor, world.definition.id, "ScheduleMaintenance", request
            )
        with pytest.raises(ApplicationError):
            object_row(world, "MaintenanceTask", "TASK-NEW")
        assert count(world, ActionExecution) == count(world, OutboxEvent) == 0
    assert (
        service(world)
        .execute(world.actor, world.definition.id, "ScheduleMaintenance", request)
        .execution_id
    )


def test_complete_preconditions_and_execution_revalidation(world):
    task(world, status="IN_PROGRESS")
    params = dict(taskId="TASK-001", expectedRevision=1)
    service(world).preview(
        world.actor, world.definition.id, "CompleteMaintenance", ActionRequest(parameters=params)
    )
    world.objects.patch(
        world.actor,
        world.definition.id,
        "MaintenanceTask",
        "TASK-001",
        ObjectPatch(expected_version=1, properties={"taskStatus": "CANCELLED"}),
    )
    with pytest.raises(ApplicationError) as error:
        execute(world, "CompleteMaintenance", **params)
    assert error.value.code == "precondition_failed"
    task(world, key="TASK-002", status="IN_PROGRESS")
    execute(world, "CompleteMaintenance", taskId="TASK-002", expectedRevision=1)
    assert object_row(world, "MaintenanceTask", "TASK-002").properties["taskStatus"] == "COMPLETED"


def test_concurrent_assignment_cardinality(world):
    task(world)

    def run(employee):
        try:
            return execute(
                world,
                "AssignTask",
                employee,
                taskId="TASK-001",
                employeeId=employee,
                expectedRevision=1,
            )
        except ApplicationError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, ["EMP-001", "EMP-002"]))
    assert sum(not isinstance(r, str) for r in results) == 1
    assert "cardinality_conflict" in results
    assert count(world, ActionExecution) == 1


@pytest.mark.parametrize(
    "denied", ["action:invoke", "object:read", "object:update", "property:update"]
)
def test_authorization_rechecked_after_preview(world, denied):
    params = dict(machineId="MCH-001", newStatus="STOPPED", expectedRevision=1)
    service(world).preview(
        world.actor, world.definition.id, "UpdateMachineStatus", ActionRequest(parameters=params)
    )

    class Deny:
        def require(self, principal, operation, resource):
            world.objects.authorizer.require(principal, operation, resource)
            if operation == denied:
                raise ApplicationError("forbidden", "Denied", 403)

    with pytest.raises(ApplicationError) as error:
        service(world, Deny()).execute(
            world.actor,
            world.definition.id,
            "UpdateMachineStatus",
            ExecuteRequest(idempotency_key="denied", parameters=params),
        )
    assert error.value.code == "forbidden" and object_row(world).version == 1


def test_tenant_principal_history_audit_and_immutability(world):
    result = execute(world)
    for principal in (
        None,
        Principal(tenant_id=uuid4(), principal_id=world.actor.principal_id),
        Principal(tenant_id=world.actor.tenant_id, principal_id="spoofed"),
    ):
        with pytest.raises(ApplicationError):
            service(world).get_execution(principal, world.definition.id, result.execution_id)

    class Deny:
        def require(self, principal, operation, resource):
            if operation in {"action:history", "action:audit"}:
                raise ApplicationError("forbidden", "Denied", 403)
            world.objects.authorizer.require(principal, operation, resource)

    for operation in ("get_execution", "audit"):
        with pytest.raises(ApplicationError):
            getattr(service(world, Deny()), operation)(
                world.actor, world.definition.id, result.execution_id
            )
    for model in (ActionExecution, AuditEvent):
        with pytest.raises(IntegrityError), world.sessions.begin() as session:
            session.execute(update(model).values(ontology_id="modified"))
    assert (
        service(world).history(world.actor, world.definition.id, limit=1).items[0].id
        == result.execution_id
    )


def test_history_paging_and_http(world):
    first = execute(world)
    execute(world, key="second", machineId="MCH-001", newStatus="CRITICAL", expectedRevision=2)
    page = service(world).history(world.actor, world.definition.id, limit=1)
    assert len(page.items) == 1 and page.has_more
    assert (
        service(world).history(world.actor, world.definition.id, limit=1, offset=1).items[0].id
        == first.execution_id
    )
    app = create_app(world.settings)
    app.state.sessions = world.sessions
    with TestClient(app) as client:
        base = f"/api/v1/ontologies/{world.definition.id}/actions"
        assert client.get(base + "/executions").status_code == 200
        assert client.get(base + f"/executions/{first.execution_id}").status_code == 200
        assert client.get(base + f"/executions/{first.execution_id}/audit").status_code == 200
        body = {
            "parameters": {"machineId": "MCH-001", "newStatus": "STOPPED", "expectedRevision": 3}
        }
        assert client.post(base + "/UpdateMachineStatus/preview", json=body).json()["advisory"]
        assert client.post(base + "/UpdateMachineStatus/execute", json=body).status_code == 422
        body["idempotency_key"] = "http"
        assert client.post(base + "/UpdateMachineStatus/execute", json=body).status_code == 200
        assert client.post(base + "/UpdateMachineStatus/execute", json=body).status_code == 200
        assert (
            client.post(
                base + "/missing/execute", json=body | {"idempotency_key": "missing"}
            ).status_code
            == 404
        )


def test_webhook_failure_retry_delivery_outside_transaction(world):
    execute(world)
    now = datetime.now(UTC) + timedelta(seconds=1)
    runner = WebhookRunner(world.sessions, world.objects.authorizer)
    ids = []

    def transport(url, event_id, payload):
        assert object_row(world).version == 2  # Another connection sees the action commit.
        ids.append(event_id)
        return 503 if len(ids) == 1 else 204

    event_id = runner.run_one(
        world.actor, world.definition.id, "https://example.org/events", transport=transport, now=now
    )
    assert event_id and object_row(world).version == 2
    assert (
        runner.run_one(
            world.actor,
            world.definition.id,
            "https://example.org/events",
            transport=transport,
            now=now,
        )
        is None
    )
    # New service instance represents worker restart; same stable event ID is retried.
    WebhookRunner(world.sessions, world.objects.authorizer).run_one(
        world.actor,
        world.definition.id,
        "https://example.org/events",
        transport=transport,
        now=now + timedelta(seconds=2),
    )
    assert ids == [str(event_id)] * 2
    with world.sessions() as session:
        event = session.get(OutboxEvent, (world.actor.tenant_id, world.definition.id, event_id))
        assert event.status == "DELIVERED" and event.attempts == 2
    assert count(world, WebhookAttempt) == 2


@pytest.mark.parametrize("mode", ["timeout", "permanent", "limit", "crash"])
def test_webhook_failures_and_abandoned_claims(world, mode):
    execute(world)
    now = datetime.now(UTC) + timedelta(seconds=1)
    runner = WebhookRunner(world.sessions, world.objects.authorizer)

    def transport(*args):
        if mode == "timeout":
            raise TimeoutError()
        if mode == "crash":
            raise RuntimeError("process lost")
        return 400 if mode == "permanent" else 503

    if mode == "crash":
        with pytest.raises(RuntimeError):
            runner.run_one(
                world.actor,
                world.definition.id,
                "https://example.org",
                transport=transport,
                now=now,
            )
        assert runner.run_one(
            world.actor,
            world.definition.id,
            "https://example.org",
            transport=lambda *a: 204,
            now=now + timedelta(seconds=61),
        )
    else:
        for index in range(5 if mode == "limit" else 1):
            runner.run_one(
                world.actor,
                world.definition.id,
                "https://example.org",
                transport=transport,
                now=now + timedelta(seconds=index * 120),
            )
    with world.sessions() as session:
        event = session.scalar(select(OutboxEvent))
        assert event.status == (
            "DELIVERED" if mode == "crash" else "PENDING" if mode == "timeout" else "DEAD"
        )
        assert event.last_error in {None, "transport_failure", "http_400", "http_503"}


def test_concurrent_webhook_claims(world):
    execute(world)
    entered, release = Event(), Event()
    runner = WebhookRunner(world.sessions, world.objects.authorizer)

    def transport(*args):
        entered.set()
        assert release.wait(3)
        return 200

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            runner.run_one,
            world.actor,
            world.definition.id,
            "https://example.org",
            transport=transport,
        )
        assert entered.wait(3)
        try:
            assert (
                runner.run_one(
                    world.actor, world.definition.id, "https://example.org", transport=transport
                )
                is None
            )
        finally:
            release.set()
        assert first.result()
    assert count(world, WebhookAttempt) == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org",
        "https://u:p@example.org",
        "https://example.org:8443",
        "https://example.org?q=secret",
        "https://example.org/#frag",
    ],
)
def test_destination_configuration_restrictions(url):
    with pytest.raises(ApplicationError):
        destination(url)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"])
def test_destination_rejects_private_dns(monkeypatch, address):
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **k: [(0, 0, 0, "", (address, 443))])
    with pytest.raises(ApplicationError):
        deliver("https://example.org", str(uuid4()), {})


@pytest.mark.parametrize(
    "policy,decision",
    [("edit_wins", "preserved"), ("reject", "conflict"), ("manual", "resolution_required")],
)
def test_reconciliation_preserves_action_edits(world, policy, decision):
    execute(world)
    reconcile = ReconciliationService(world.sessions, world.objects.authorizer)
    update = SourceUpdate(
        source="erp", expected_version=2, properties={"operationalStatus": "RUNNING"}, policy=policy
    )
    result = reconcile.refresh(world.actor, world.definition.id, "Machine", "MCH-001", update)
    assert result.decision == decision and result.object.version == 2
    assert result.object.properties["operationalStatus"] == "STOPPED"
    if result.conflicts:
        retry = reconcile.refresh(world.actor, world.definition.id, "Machine", "MCH-001", update)
        assert retry.conflicts == result.conflicts and count(world, ReconciliationConflict) == 1
        resolved = reconcile.resolve(
            world.actor,
            world.definition.id,
            result.conflicts[0],
            expected_version=2,
            accept_source=True,
        )
        assert (
            resolved.object.version == 3
            and resolved.object.properties["operationalStatus"] == "RUNNING"
        )
    assert count(world, ActionExecution) == count(world, OutboxEvent) == 1


def test_source_ownership_user_edits_and_explicit_resolution(world):
    reconcile = ReconciliationService(world.sessions, world.objects.authorizer)

    def refresh(version, value, policy="edit_wins", source="erp"):
        return reconcile.refresh(
            world.actor,
            world.definition.id,
            "Machine",
            "MCH-001",
            SourceUpdate(
                source=source,
                expected_version=version,
                properties={"operationalStatus": value},
                policy=policy,
            ),
        )

    assert refresh(1, "STOPPED", "source_wins").object.version == 2
    assert refresh(2, "CRITICAL").object.version == 3
    with pytest.raises(ApplicationError):
        refresh(3, "STOPPED", source="other")
    world.objects.patch(
        world.actor,
        world.definition.id,
        "Machine",
        "MCH-001",
        ObjectPatch(expected_version=3, properties={"operationalStatus": "MAINTENANCE"}),
    )
    assert refresh(4, "RUNNING").object.properties["operationalStatus"] == "MAINTENANCE"
    conflict = refresh(4, "RUNNING", "manual").conflicts[0]
    preserved = reconcile.resolve(
        world.actor, world.definition.id, conflict, expected_version=4, accept_source=False
    )
    assert preserved.object.version == 4
    with pytest.raises(ApplicationError):
        refresh(3, "RUNNING")


def test_phase2_upgrade_preserves_operational_data(database):
    engine, sessions, url = database
    migrate(engine, "0005_query_order", downgrade=True)
    # Phase 2 services are verified by baseline; seed its frozen relational schema here.
    with engine.begin() as connection:
        tenant = uuid4()
        connection.execute(
            text("INSERT INTO tenants(id,name) VALUES (:id,'phase2')"), {"id": tenant}
        )
    migrate(engine)
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT name FROM tenants WHERE id=:id"), {"id": tenant})
            == "phase2"
        )
    config = Config(str(ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.check(config)


def add_action(world, action):
    data = world.definition.model_dump(mode="json")
    data["version"] = "1.1.0"
    data["action_types"].append(action)
    definition = OntologyDefinition.model_validate(data)
    world.registry.draft(world.actor, definition.id, definition)
    world.registry.publish(world.actor, definition.id, definition.version)
    world.registry.activate(world.actor, definition.id, definition.version)
    world.definition = definition


def test_delete_relationships_and_objects(world):
    schedule(world)

    def literal(value):
        return {"kind": "literal", "value": value}

    add_action(
        world,
        dict(
            id="RemoveTask",
            name="RemoveTask",
            bindings=[
                dict(id="task", object_type="MaintenanceTask", object_id=literal("TASK-NEW")),
                dict(id="machine", object_type="Machine", object_id=literal("MCH-001")),
                dict(id="employee", object_type="Employee", object_id=literal("EMP-001")),
            ],
            preconditions=[
                dict(type="LINK_EXISTS", link="taskForMachine", source="task", target="machine")
            ],
            operations=[
                dict(
                    type="DELETE_LINK",
                    target="taskForMachine",
                    source="task",
                    destination="machine",
                ),
                dict(
                    type="DELETE_LINK",
                    target="assignedEmployee",
                    source="task",
                    destination="employee",
                ),
                dict(
                    type="DELETE_OBJECT",
                    target="MaintenanceTask",
                    binding="task",
                    expected_version=literal(2),
                ),
            ],
        ),
    )
    before = count(world, EditOverlay)
    result = service(world).execute(
        world.actor, world.definition.id, "RemoveTask", ExecuteRequest(idempotency_key="delete")
    )
    assert len(result.changes) == 3
    with pytest.raises(ApplicationError):
        object_row(world, "MaintenanceTask", "TASK-NEW")
    assert count(world, EditOverlay) == before - 3


def test_references_and_multiple_object_updates(world):
    world.objects.create(world.actor, world.definition.id, machine("MCH-002"))

    def literal(value):
        return {"kind": "literal", "value": value}

    add_action(
        world,
        dict(
            id="CopyStatus",
            name="CopyStatus",
            bindings=[
                dict(id="first", object_type="Machine", object_id=literal("MCH-001")),
                dict(id="second", object_type="Machine", object_id=literal("MCH-002")),
            ],
            operations=[
                dict(
                    type="UPDATE_OBJECT",
                    target="Machine",
                    binding="first",
                    expected_version=literal(2),
                    properties={"operationalStatus": literal("STOPPED")},
                ),
                dict(
                    type="UPDATE_OBJECT",
                    target="Machine",
                    binding="second",
                    expected_version=literal(2),
                    properties={
                        "operationalStatus": {
                            "kind": "object",
                            "binding": "first",
                            "property": "operationalStatus",
                        }
                    },
                ),
            ],
        ),
    )
    result = service(world).execute(
        world.actor, world.definition.id, "CopyStatus", ExecuteRequest(idempotency_key="copy")
    )
    assert len(result.changes) == 2
    assert object_row(world).version == object_row(world, "Machine", "MCH-002").version == 3
    assert object_row(world, "Machine", "MCH-002").properties["operationalStatus"] == "STOPPED"


def test_multi_property_conflict_does_not_release_ownership(world):
    reconcile = ReconciliationService(world.sessions, world.objects.authorizer)
    request = SourceUpdate(
        source="erp",
        expected_version=1,
        policy="manual",
        properties={"machineName": "Machine MCH-001", "operationalStatus": "STOPPED"},
    )
    result = reconcile.refresh(world.actor, world.definition.id, "Machine", "MCH-001", request)
    assert result.conflicts
    # Equal observation of the name was planned before the conflict; it cannot release ownership.
    result = reconcile.refresh(
        world.actor,
        world.definition.id,
        "Machine",
        "MCH-001",
        SourceUpdate(
            source="erp", expected_version=1, properties={"machineName": "Source overwrite"}
        ),
    )
    assert result.object.properties["machineName"] == "Machine MCH-001"
    assert result.object.version == 1


def test_raw_action_http_payload_limit(world):
    app = create_app(world.settings)
    app.state.sessions = world.sessions
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/ontologies/manufacturing/actions/UpdateMachineStatus/execute",
            content=json.dumps({"parameters": {"x": "x" * 65536}}),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 413
    assert count(world, ActionExecution) == 0


def test_parameter_defaults_idempotency_binding(world):
    action = json.loads(json.dumps(examples()[0]))
    action["id"] = action["name"] = "DefaultStatus"
    action["parameters"][1].update(default="STOPPED", has_default=True, required=False)
    add_action(world, action)
    first = service(world).execute(
        world.actor,
        world.definition.id,
        "DefaultStatus",
        ExecuteRequest(
            idempotency_key="default", parameters={"machineId": "MCH-001", "expectedRevision": 2}
        ),
    )
    retry = service(world).execute(
        world.actor,
        world.definition.id,
        "DefaultStatus",
        ExecuteRequest(
            idempotency_key="default",
            parameters={"machineId": "MCH-001", "expectedRevision": 2, "newStatus": "STOPPED"},
        ),
    )
    assert first == retry and object_row(world).version == 3


def test_timeout_after_mutation_rolls_back(world, monkeypatch):
    from types import SimpleNamespace

    elapsed = 0
    observed_update = False

    def after_statement(conn, cursor, statement, parameters, context, executemany):
        nonlocal elapsed, observed_update
        if statement.startswith("UPDATE objects "):
            observed_update = True
            elapsed = 4

    clock = SimpleNamespace(monotonic=lambda: elapsed)
    monkeypatch.setattr("ontology_platform.actions.service.time", clock)
    monkeypatch.setattr("ontology_platform.actions.deadline.time", clock)
    event.listen(world.engine, "after_cursor_execute", after_statement)
    try:
        with pytest.raises(ApplicationError) as error:
            execute(world)
    finally:
        event.remove(world.engine, "after_cursor_execute", after_statement)
    assert observed_update and error.value.code == "action_timeout"
    assert object_row(world).version == 1
    assert (
        count(world, ActionExecution) == count(world, OutboxEvent) == count(world, AuditEvent) == 0
    )


def test_reconciliation_schema_change_requires_fresh_conflict(world):
    reconcile = ReconciliationService(world.sessions, world.objects.authorizer)
    result = reconcile.refresh(
        world.actor,
        world.definition.id,
        "Machine",
        "MCH-001",
        SourceUpdate(
            source="erp",
            expected_version=1,
            properties={"operationalStatus": "STOPPED"},
            policy="manual",
        ),
    )
    definition = next_definition(world, lambda data: None)
    world.registry.draft(world.actor, definition.id, definition)
    world.registry.publish(world.actor, definition.id, definition.version)
    world.registry.activate(world.actor, definition.id, definition.version)
    with pytest.raises(ApplicationError) as error:
        reconcile.resolve(
            world.actor, definition.id, result.conflicts[0], expected_version=2, accept_source=True
        )
    assert error.value.code == "reconciliation_conflict"
    # Compatible overlays remain protected across activation, with the new revision.
    preserved = reconcile.refresh(
        world.actor,
        definition.id,
        "Machine",
        "MCH-001",
        SourceUpdate(source="erp", expected_version=2, properties={"operationalStatus": "STOPPED"}),
    )
    assert (
        preserved.object.version == 2
        and preserved.object.properties["operationalStatus"] == "RUNNING"
    )


def test_upgrade_preserves_phase2_objects(database):
    world = make_world(database)
    active(world)
    world.objects.create(world.actor, world.definition.id, machine())
    migrate(world.engine, "0005_query_order", downgrade=True)
    with world.sessions() as session:
        row = session.get(
            Object, (world.actor.tenant_id, world.definition.id, "Machine", "MCH-001")
        )
        assert row.version == 1 and row.properties["operationalStatus"] == "RUNNING"
    migrate(world.engine)
    assert object_row(world).version == 1
    # Objects created before provenance existed are conservatively protected.
    reconciler = ReconciliationService(world.sessions, world.objects.authorizer)
    result = reconciler.refresh(
        world.actor,
        world.definition.id,
        "Machine",
        "MCH-001",
        SourceUpdate(source="erp", expected_version=1, properties={"operationalStatus": "STOPPED"}),
    )
    assert result.object.version == 1 and result.object.properties["operationalStatus"] == "RUNNING"


def test_action_unique_validation_rolls_back_first_operation(database):
    world = make_world(database)
    data = world.definition.model_dump(mode="json")
    for typed in data["object_types"]:
        if typed["id"] == "Factory":
            for prop in typed["properties"]:
                if prop["id"] == "factoryName":
                    prop.update(unique=True, indexed=True)

    def literal(x):
        return {"kind": "literal", "value": x}

    data["action_types"] = [
        dict(
            id="UniqueTest",
            name="UniqueTest",
            bindings=[dict(id="machine", object_type="Machine", object_id=literal("MCH-001"))],
            operations=[
                dict(
                    type="UPDATE_OBJECT",
                    target="Machine",
                    binding="machine",
                    expected_version=literal(1),
                    properties={"operationalStatus": literal("STOPPED")},
                ),
                dict(
                    type="CREATE_OBJECT",
                    target="Factory",
                    binding="new",
                    object_id=literal("FAC-002"),
                    properties={
                        "factoryId": literal("FAC-002"),
                        "factoryName": literal("same"),
                        "location": literal("Test"),
                    },
                ),
            ],
        )
    ]
    world.definition = OntologyDefinition.model_validate(data)
    active(world)
    world.objects.create(world.actor, world.definition.id, machine())
    world.objects.create(
        world.actor,
        world.definition.id,
        CreateObject(
            object_type_id="Factory",
            object_id="FAC-001",
            properties={"factoryId": "FAC-001", "factoryName": "same", "location": "Test"},
        ),
    )
    with pytest.raises(ApplicationError) as error:
        service(world).execute(
            world.actor, world.definition.id, "UniqueTest", ExecuteRequest(idempotency_key="unique")
        )
    assert error.value.code == "unique_conflict" and object_row(world).version == 1
    assert (
        count(world, ActionExecution) == count(world, AuditEvent) == count(world, OutboxEvent) == 0
    )


def test_absence_and_required_parameter_preconditions(world):
    def literal(x):
        return {"kind": "literal", "value": x}

    add_action(
        world,
        dict(
            id="CreateFactory",
            name="CreateFactory",
            parameters=[
                dict(id="confirmation", name="confirmation", data_type="boolean", required=False)
            ],
            bindings=[dict(id="candidate", object_type="Factory", object_id=literal("FAC-NEW"))],
            preconditions=[
                dict(type="NOT_EXISTS", binding="candidate"),
                dict(type="PARAMETER_PRESENT", parameter="confirmation"),
            ],
            operations=[
                dict(
                    type="CREATE_OBJECT",
                    target="Factory",
                    binding="created",
                    object_id=literal("FAC-NEW"),
                    properties={
                        "factoryId": literal("FAC-NEW"),
                        "factoryName": literal("New"),
                        "location": literal("Test"),
                    },
                )
            ],
        ),
    )
    with pytest.raises(ApplicationError) as error:
        service(world).execute(
            world.actor,
            world.definition.id,
            "CreateFactory",
            ExecuteRequest(idempotency_key="create"),
        )
    assert error.value.code == "precondition_failed"
    result = service(world).execute(
        world.actor,
        world.definition.id,
        "CreateFactory",
        ExecuteRequest(idempotency_key="create", parameters={"confirmation": True}),
    )
    assert result.changes[0].new_revision == 1
    with pytest.raises(ApplicationError):
        service(world).execute(
            world.actor,
            world.definition.id,
            "CreateFactory",
            ExecuteRequest(idempotency_key="new-key", parameters={"confirmation": True}),
        )


def test_preview_cannot_replay_a_committed_idempotency_key(world):
    execute(world)
    with pytest.raises(ApplicationError) as error:
        service(world).preview(
            world.actor,
            world.definition.id,
            "UpdateMachineStatus",
            ExecuteRequest(
                idempotency_key="key",
                parameters={"machineId": "MCH-001", "newStatus": "STOPPED", "expectedRevision": 1},
            ),
        )
    assert error.value.code == "revision_conflict"
    assert object_row(world).version == 2 and count(world, ActionExecution) == 1


def test_source_override_requires_explicit_permission(world):
    class Deny:
        def require(self, principal, operation, resource):
            world.objects.authorizer.require(principal, operation, resource)
            if operation == "edit:override":
                raise ApplicationError("forbidden", "Override denied", 403)

    reconciler = ReconciliationService(world.sessions, Deny())
    with pytest.raises(ApplicationError) as error:
        reconciler.refresh(
            world.actor,
            world.definition.id,
            "Machine",
            "MCH-001",
            SourceUpdate(
                source="erp",
                policy="source_wins",
                expected_version=1,
                properties={"operationalStatus": "STOPPED"},
            ),
        )
    assert error.value.code == "forbidden" and object_row(world).version == 1


@pytest.mark.parametrize("url", ["https://example.org:invalid", "https://[invalid"])
def test_malformed_destination_errors_are_structured(url):
    with pytest.raises(ApplicationError) as error:
        destination(url)
    assert error.value.code == "invalid_destination"


def test_preview_database_constraint_failure_rolls_back_savepoint(world):
    schedule(world)

    def literal(x):
        return {"kind": "literal", "value": x}

    add_action(
        world,
        dict(
            id="FailDelete",
            name="FailDelete",
            bindings=[
                dict(id="task", object_type="MaintenanceTask", object_id=literal("TASK-NEW")),
                dict(id="machine", object_type="Machine", object_id=literal("MCH-001")),
            ],
            operations=[
                dict(
                    type="UPDATE_OBJECT",
                    target="Machine",
                    binding="machine",
                    expected_version=literal(2),
                    properties={"operationalStatus": literal("CRITICAL")},
                ),
                dict(
                    type="DELETE_OBJECT",
                    target="MaintenanceTask",
                    binding="task",
                    expected_version=literal(2),
                ),
            ],
        ),
    )
    for method in ("preview", "execute"):
        with pytest.raises(ApplicationError) as error:
            getattr(service(world), method)(
                world.actor,
                world.definition.id,
                "FailDelete",
                ExecuteRequest(idempotency_key="failed-delete"),
            )
        assert error.value.code == "constraint_conflict"
        assert (
            object_row(world).version == 2
            and object_row(world).properties["operationalStatus"] == "RUNNING"
        )
        assert object_row(world, "MaintenanceTask", "TASK-NEW").version == 2
        assert count(world, ActionExecution) == count(world, OutboxEvent) == 1
