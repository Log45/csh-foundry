# ruff: noqa: F811
"""Application schema, publication, canonical runtime and preservation integration."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from ontology_platform.actions.contracts import ExecuteRequest
from ontology_platform.applications.contracts import Document, Publish, RuntimeQuery, Save, validate
from ontology_platform.applications.service import ApplicationService
from ontology_platform.artifacts.contracts import CreateArtifact
from ontology_platform.db.models import ApplicationVersion
from ontology_platform.errors import ApplicationError
from ontology_platform.projects.contracts import CreateProject, CreateResource, UpdateResource
from pydantic import ValidationError
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from test_phase1 import active, database, factory, historical_database, machine, world  # noqa: F401, F811


def document():
    return {
        "title": "Manufacturing Operations Dashboard",
        "home": "machines",
        "pages": [
            {
                "id": "machines",
                "title": "Machines",
                "widgets": [{"id": "intro", "kind": "heading", "text": "Operations"}],
            }
        ],
    }


def test_roundtrip_digest():
    doc = Document.model_validate(document())
    assert Document.model_validate_json(doc.canonical()) == doc
    assert (
        doc.digest() == Document.model_validate(dict(reversed(list(document().items())))).digest()
    )
    assert validate(doc).valid


@pytest.mark.parametrize(
    "change",
    [
        {"format_version": 2},
        {"code": "alert(1)"},
        {"__proto__": {}},
        {"pages": [{"id": "a", "title": "a", "widgets": [{"id": "b", "kind": "javascript"}]}]},
        {"description": "x" * 60001},
    ],
)
def test_reject_unsupported(change):
    with pytest.raises(ValidationError):
        Document.model_validate(document() | change)


def test_reference_layout_and_interaction_diagnostics():
    raw = document()
    raw["pages"][0]["widgets"] += [
        {"id": "intro", "kind": "section", "parent": "intro"},
        {"id": "table", "kind": "table", "source": "absent"},
        {"id": "nav", "kind": "navigation", "page": "absent"},
    ]
    raw["interactions"] = [
        {"id": "event", "widget": "missing", "event": "click", "kind": "set", "target": "missing"}
    ]
    codes = {d.code for d in validate(Document.model_validate(raw)).diagnostics}
    assert {
        "duplicate_id",
        "layout_cycle_or_depth",
        "widget_reference_invalid",
        "interaction_widget_invalid",
        "interaction_target_invalid",
    } <= codes


def setup(world):
    active(world)
    svc = ApplicationService(world.sessions, world.registry.authorizer)
    project = svc.create_project(world.actor, CreateProject(name="Apps"))
    app = svc.create(world.actor, project.id, CreateArtifact(name="Operations"))
    dep = svc.create_resource(
        world.actor,
        project.id,
        CreateResource(
            resource_type="ONTOLOGY_VERSION",
            ontology_id=world.definition.id,
            schema_version=world.definition.version,
            entity_id=world.definition.version,
            name="Schema",
        ),
    )
    raw = document()
    raw["dependencies"] = [
        {
            "id": "schema",
            "resource_id": str(dep.id),
            "ontology_id": world.definition.id,
            "schema_version": world.definition.version,
        }
    ]
    raw["sources"] = [
        {
            "id": "machines_query",
            "dependency": "schema",
            "query": {
                "object_type": "Machine",
                "select": ["machineId", "machineName", "operationalStatus"],
                "limit": 1,
            },
        }
    ]
    return svc, project, app, Document.model_validate(raw)


def test_real_publication_runtime_immutability_and_moves(world):
    svc, project, app, doc = setup(world)
    p = world.actor
    draft = svc.save(p, app.id, Save(expected_revision=0, document=doc))
    pub = svc.publish(p, app.id, Publish(expected_revision=draft.revision))
    assert svc.publish(p, app.id, Publish(expected_revision=1)).id == pub.id
    world.objects.create(p, world.definition.id, factory())
    world.objects.create(p, world.definition.id, machine())
    result = svc.query(p, app.id, pub.id, RuntimeQuery(source_id="machines_query"))
    assert result.items[0].properties["machineId"] == "MCH-001"
    from ontology_platform.projects.contracts import CreateFolder

    folder = svc.create_folder(p, project.id, CreateFolder(name="Applications folder"))
    moved = svc.update_resource(
        p,
        app.id,
        UpdateResource(expected_revision=1, name="Renamed", description="", folder_id=folder.id),
        1,
    )
    assert moved.id == app.id and moved.folder_id == folder.id
    changed = doc.model_copy(deep=True)
    changed.title = "New title"
    svc.save(p, app.id, Save(expected_revision=1, document=changed))
    newer = svc.publish(p, app.id, Publish(expected_revision=2))
    assert newer.id != pub.id
    assert svc.version(p, app.id, pub.id).document.title == doc.title
    with world.engine.begin() as connection, pytest.raises(DBAPIError):
        connection.execute(update(ApplicationVersion).values(digest="bad"))
    assert len(svc.versions(p, app.id)) == 2
    with pytest.raises(ApplicationError):
        svc.version(p.model_copy(update={"tenant_id": uuid4()}), app.id, pub.id)


def test_concurrent_private_draft_cas_and_invalid_publication(world):
    svc, _, app, doc = setup(world)
    with ThreadPoolExecutor(max_workers=2) as pool:

        def save():
            try:
                return svc.save(
                    world.actor, app.id, Save(expected_revision=0, document=doc)
                ).revision
            except ApplicationError as exc:
                return exc.code

        outcomes = list(pool.map(lambda _: save(), range(2)))
    assert sorted(map(str, outcomes)) == ["1", "draft_conflict"]
    invalid = doc.model_copy(deep=True)
    invalid.home = "missing"
    svc.save(world.actor, app.id, Save(expected_revision=1, document=invalid))
    with pytest.raises(ApplicationError, match="Resolve validation"):
        svc.publish(world.actor, app.id, Publish(expected_revision=2))
    with world.sessions() as s:
        assert list(s.scalars(select(ApplicationVersion))) == []


def test_revoked_dependency_blocks_manifest(world):
    svc, _, app, doc = setup(world)
    svc.save(world.actor, app.id, Save(expected_revision=0, document=doc))
    pub = svc.publish(world.actor, app.id, Publish(expected_revision=1))
    svc.update_resource(world.actor, doc.dependencies[0].resource_id, None, 1)
    with pytest.raises(ApplicationError, match="dependencies"):
        svc.version(world.actor, app.id, pub.id)
    result = svc.validate(world.actor, app.id, doc)
    assert not result.valid and len(result.diagnostics) == 1
    assert "Schema" not in result.model_dump_json()


def test_fresh_migration_and_drift(database):
    from alembic import command
    from alembic.config import Config
    from test_phase1 import ROOT

    engine, _, _ = database
    with engine.begin() as c:
        assert (
            c.scalar(text("select version_num from alembic_version"))
            == "0027_lineage_observability"
        )
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["connection"] = c
        command.check(config)


def test_actual_action_preview_execution_audit_idempotency_and_conflict(world):
    import json

    from ontology_platform.actions.service import ActionExecutionService
    from ontology_platform.db.models import AuditEvent
    from ontology_schema.models import OntologyDefinition
    from test_actions import examples

    data = world.definition.model_dump(mode="json")
    data["action_types"] = examples()
    world.definition = OntologyDefinition.model_validate(data)
    svc, _, app, doc = setup(world)
    world.objects.create(world.actor, world.definition.id, machine())
    raw = json.loads(doc.canonical())
    raw["actions"] = [
        {
            "id": "update",
            "dependency": "schema",
            "action_id": "UpdateMachineStatus",
            "parameters": {
                "machineId": {"kind": "literal", "value": "MCH-001"},
                "newStatus": {"kind": "literal", "value": "STOPPED"},
                "expectedRevision": {"kind": "literal", "value": 1},
            },
            "parameter_types": {
                "machineId": "string",
                "newStatus": "string",
                "expectedRevision": "integer",
            },
        }
    ]
    doc = Document.model_validate(raw)
    assert svc.validate(world.actor, app.id, doc).valid
    svc.save(world.actor, app.id, Save(expected_revision=0, document=doc))
    pub = svc.publish(world.actor, app.id, Publish(expected_revision=1))
    body = ExecuteRequest(
        idempotency_key="app-action",
        parameters={"machineId": "MCH-001", "newStatus": "STOPPED", "expectedRevision": 1},
    )
    preview = svc.action(world.actor, app.id, pub.id, "update", body, True)
    assert preview.execution_id is None and preview.advisory
    result = svc.action(world.actor, app.id, pub.id, "update", body, False)
    assert svc.action(world.actor, app.id, pub.id, "update", body, False) == result
    assert (
        world.objects.get(world.actor, world.definition.id, "Machine", "MCH-001").properties[
            "operationalStatus"
        ]
        == "STOPPED"
    )
    actions = ActionExecutionService(world.sessions, world.registry.authorizer)
    assert len(actions.audit(world.actor, world.definition.id, result.execution_id)) == 1
    with world.sessions() as s:
        assert s.scalar(select(AuditEvent.actor)) == world.actor.principal_id
    with pytest.raises(ApplicationError):
        svc.action(
            world.actor,
            app.id,
            pub.id,
            "update",
            body.model_copy(update={"idempotency_key": "stale"}),
            False,
        )


def test_runtime_property_policy_and_pagination(world):
    from test_queries import RestrictedPolicy

    svc, _, app, doc = setup(world)
    world.objects.create(world.actor, world.definition.id, machine())
    world.objects.create(world.actor, world.definition.id, machine("MCH-005"))
    # No explicit projection: canonical policy filters fields and counts.
    doc.sources[0].query = doc.sources[0].query.model_copy(update={"select": None})
    svc.save(world.actor, app.id, Save(expected_revision=0, document=doc))
    pub = svc.publish(world.actor, app.id, Publish(expected_revision=1))
    restricted = ApplicationService(world.sessions, RestrictedPolicy(world))
    first = restricted.query(world.actor, app.id, pub.id, RuntimeQuery(source_id="machines_query"))
    assert len(first.items) == 1 and first.has_more
    assert "temperatureCelsius" not in first.items[0].properties
    second = restricted.query(
        world.actor,
        app.id,
        pub.id,
        RuntimeQuery(source_id="machines_query", cursor=first.next_cursor),
    )
    assert second.items[0].object_id != first.items[0].object_id


from test_security_platform import security  # noqa: E402, F401


def test_real_project_shares_do_not_grant_dependency_or_object_authority(security):
    from ontology_platform.projects.contracts import MemberChange, ShareChange
    from test_projects import grant_projects

    w, auth, admin_service, admin, reader, _ = security
    grant_projects(admin_service, admin, reader)
    svc = ApplicationService(w.sessions, auth)
    owner = svc.create_project(admin, CreateProject(name="Owner"))
    viewer = svc.create_project(admin, CreateProject(name="Viewer"))
    svc.member(
        admin,
        viewer.id,
        MemberChange(principal_id=reader.principal_id, role="viewer", expected_revision=1),
    )
    app = svc.create(admin, owner.id, CreateArtifact(name="Private app"))
    dep = svc.create_resource(
        admin,
        owner.id,
        CreateResource(
            resource_type="ONTOLOGY_VERSION",
            name="Private schema",
            ontology_id="manufacturing",
            schema_version="1.0.0",
            entity_id="1.0.0",
        ),
    )
    raw = document()
    raw["dependencies"] = [
        {
            "id": "schema",
            "resource_id": str(dep.id),
            "ontology_id": "manufacturing",
            "schema_version": "1.0.0",
        }
    ]
    doc = Document.model_validate(raw)
    svc.save(admin, app.id, Save(expected_revision=0, document=doc))
    published = svc.publish(admin, app.id, Publish(expected_revision=1))
    with pytest.raises(ApplicationError):
        svc.version(reader, app.id, published.id)
    app = svc.share(
        admin, app.id, ShareChange(project_id=viewer.id, enabled=True, expected_revision=1)
    )
    with pytest.raises(ApplicationError, match="dependencies"):
        svc.version(reader, app.id, published.id)
    svc.share(admin, dep.id, ShareChange(project_id=viewer.id, enabled=True, expected_revision=1))
    assert svc.version(reader, app.id, published.id).id == published.id
    with pytest.raises(ApplicationError):
        svc.save(reader, app.id, Save(expected_revision=0, document=doc))
    svc.share(
        admin,
        app.id,
        ShareChange(project_id=viewer.id, enabled=False, expected_revision=app.revision),
    )
    with pytest.raises(ApplicationError):
        svc.version(reader, app.id, published.id)


def test_upgrade_from_previous_head_preserves_existing_records(historical_database):
    from test_phase1 import make_world, migrate

    engine, sessions, _ = historical_database
    w = make_world(historical_database)
    svc = ApplicationService(sessions, w.registry.authorizer)
    project = svc.create_project(w.actor, CreateProject(name="Preserved project"))
    migrate(engine, "0024_pipeline_graphs")
    migrate(engine, "0025_applications")
    assert svc.get_project(w.actor, project.id).name == "Preserved project"


@pytest.mark.parametrize("method", ["POST", "PUT"])
def test_raw_application_payload_bound_before_authentication(method):
    from fastapi.testclient import TestClient
    from ontology_platform.main import create_app

    client = TestClient(create_app())
    response = client.request(
        method,
        f"/api/v1/applications/{uuid4()}/draft",
        content=b"x" * 65537,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "application_payload_too_large"


@pytest.mark.parametrize(
    "field, values",
    [
        ("pages", [{"id": f"page{i}", "title": "Page"} for i in range(17)]),
        ("states", [{"id": f"state{i}"} for i in range(65)]),
        (
            "interactions",
            [
                {
                    "id": f"event{i}",
                    "widget": "intro",
                    "event": "click",
                    "kind": "refresh",
                    "target": "source",
                }
                for i in range(129)
            ],
        ),
    ],
)
def test_explicit_structural_limits(field, values):
    with pytest.raises(ValidationError):
        Document.model_validate(document() | {field: values})


def test_default_expansion_is_also_bounded():
    pages = [
        {
            "id": f"page{i}",
            "title": "Page",
            "widgets": [{"id": f"widget{i}_{j}", "kind": "text"} for j in range(64)],
        }
        for i in range(4)
    ]
    with pytest.raises(ValidationError, match="Expanded application document"):
        Document.model_validate(document() | {"pages": pages})


def test_concurrent_publication_is_atomic_and_identical_content_is_deduplicated(world):
    svc, _, app, doc = setup(world)
    svc.save(world.actor, app.id, Save(expected_revision=0, document=doc))
    with ThreadPoolExecutor(max_workers=2) as pool:
        versions = list(
            pool.map(
                lambda _: svc.publish(world.actor, app.id, Publish(expected_revision=1)), range(2)
            )
        )
    assert versions[0].id == versions[1].id
    assert [v.sequence for v in svc.versions(world.actor, app.id)] == [1]


def test_failure_after_version_insert_rolls_back_publication_and_audit(world, monkeypatch):
    svc, _, app, doc = setup(world)
    svc.save(world.actor, app.id, Save(expected_revision=0, document=doc))
    original = svc.audit

    def fail(*args):
        raise ApplicationError("audit_unavailable", "Audit failed", 503)

    monkeypatch.setattr(svc, "audit", fail)
    with pytest.raises(ApplicationError, match="Audit failed"):
        svc.publish(world.actor, app.id, Publish(expected_revision=1))
    assert svc.versions(world.actor, app.id) == []
    monkeypatch.setattr(svc, "audit", original)
    assert svc.publish(world.actor, app.id, Publish(expected_revision=1)).sequence == 1


def test_existing_public_openapi_component_identities_are_preserved():
    from ontology_platform.main import create_app

    schemas = create_app().openapi()["components"]["schemas"]
    assert {
        "QueryRequest",
        "AggregateRequest",
        "All",
        "AnyOf",
        "Negation",
        "TraversalStep",
        "Value",
    } <= schemas.keys()
    assert "ApplicationDocument-Input" in schemas
    pending = list(schemas.values())
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            reference = value.get("$ref", "")
            if reference.startswith("#/components/schemas/"):
                assert reference.rsplit("/", 1)[-1] in schemas
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)


def test_expired_publication_budget_fails_closed_and_rolls_back(world, monkeypatch):
    import time

    from ontology_platform.actions.deadline import action_deadline
    from ontology_platform.applications import service as implementation

    svc, _, app, doc = setup(world)
    svc.save(world.actor, app.id, Save(expected_revision=0, document=doc))

    def expired(session, expires, **options):
        assert 0 < expires - time.monotonic() <= 5
        return action_deadline(session, time.monotonic() - 1, **options)

    monkeypatch.setattr(implementation, "action_deadline", expired)
    with pytest.raises(ApplicationError) as failure:
        svc.publish(world.actor, app.id, Publish(expected_revision=1))
    assert failure.value.code == "application_publication_timeout"
    assert svc.versions(world.actor, app.id) == []


def test_legacy_inert_action_references_cannot_publish(world):
    from ontology_schema.models import OntologyDefinition

    data = world.definition.model_dump(mode="json")
    data["action_types"] = [
        {
            "id": "Legacy",
            "name": "Legacy",
            "operations": [{"type": "UPDATE_OBJECT", "target": "Machine"}],
        }
    ]
    world.definition = OntologyDefinition.model_validate(data)
    svc, _, app, doc = setup(world)
    raw = doc.model_dump(mode="json", by_alias=True)
    raw["actions"] = [{"id": "legacy_binding", "dependency": "schema", "action_id": "Legacy"}]
    definition = Document.model_validate(raw)
    svc.save(world.actor, app.id, Save(expected_revision=0, document=definition))
    assert not svc.validate(world.actor, app.id, definition).valid
    with pytest.raises(ApplicationError, match="Resolve validation"):
        svc.publish(world.actor, app.id, Publish(expected_revision=1))
    assert svc.versions(world.actor, app.id) == []
