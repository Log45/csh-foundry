"""Phase 15 deterministic identity and real governed PostgreSQL/MinIO execution."""

from decimal import Decimal
from uuid import uuid4

import pytest
from ontology_platform.artifacts.contracts import CreateArtifact
from ontology_platform.contracts import ObjectPatch
from ontology_platform.db.models import MappingDefinition, MaterializationRecord
from ontology_platform.errors import ApplicationError
from ontology_platform.execution.worker import ExecutionWorker
from ontology_platform.mappings.contracts import Identity, MappingRun, MappingSpec
from ontology_platform.mappings.conversion import convert, identity
from ontology_platform.mappings.service import MappingService
from ontology_platform.pipelines.service import PipelineService
from ontology_platform.projects.contracts import CreateResource
from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from test_artifacts import store  # noqa: F401
from test_datasets import commit, dataset, make_service
from test_phase1 import active, database, historical_database, world  # noqa: F401
from test_security_platform import security  # noqa: F401


def key(kind="string", columns=("id",)):
    return Identity.model_validate(
        {"components": [{"column": c, "conversion": kind} for c in columns]}
    )


@pytest.mark.parametrize(
    "kind,left,right",
    [
        ("decimal", "1.00", Decimal("1")),
        ("integer", "01", 1),
        ("string", "e\u0301", "é"),
        ("timestamp", "2020-01-01T01:00:00+01:00", "2020-01-01T00:00:00Z"),
    ],
)
def test_identity_canonicalization(kind, left, right):
    assert identity(key(kind), {"id": left}) == identity(key(kind), {"id": right})


def test_composite_identity_is_unambiguous_and_null_rejected():
    spec = key(columns=("a", "b"))
    assert identity(spec, {"a": "ab", "b": "c"}) != identity(spec, {"a": "a", "b": "bc"})
    with pytest.raises(ValueError):
        identity(spec, {"a": None, "b": "b"})


@pytest.mark.parametrize(
    "kind,value",
    [
        ("integer", 1.5),
        ("integer", True),
        ("integer", 2**63),
        ("decimal", 1.2),
        ("boolean", 1),
        ("string", {}),
        ("float", "nan"),
        ("timestamp", "2020-01-01T00:00:00.1234567Z"),
        ("date", "2020-01-01T00:00:00Z"),
    ],
)
def test_strict_conversions(kind, value):
    with pytest.raises(ValueError):
        convert(value, kind)


def setup_mapping(
    w,
    backend,
    data=b"id,name\nF1,Factory One\nF2,Factory Two\n",
    *,
    prepared=False,
    actor=None,
    auth=None,
):
    if not prepared:
        active(w)
    actor = actor or w.actor
    auth = auth or w.registry.authorizer
    datasets = make_service(w, backend, auth)
    source = dataset(datasets, actor)
    version = commit(datasets, actor, source.id, data)
    svc = MappingService(w.sessions, auth, backend.settings, backend)
    target = svc.create_resource(
        actor,
        source.project_id,
        CreateResource(
            name="Ontology",
            resource_type="ONTOLOGY_VERSION",
            ontology_id=w.definition.id,
            schema_version=w.definition.version,
            entity_id=w.definition.version,
        ),
    )
    resource = svc.create(actor, source.project_id, CreateArtifact(name="Mapping"))
    spec = MappingSpec.model_validate(
        {
            "target_resource_id": str(target.id),
            "ontology_id": w.definition.id,
            "schema_version": w.definition.version,
            "columns": {"id": "String", "name": "String"},
            "objects": [
                {
                    "object_type": "Factory",
                    "identity": key().model_dump(),
                    "properties": {
                        "factoryName": {"column": "name", "conversion": "string"},
                        "location": {"constant": "Test", "conversion": "string"},
                    },
                }
            ],
        }
    )
    definition = svc.publish(actor, resource.id, spec)
    body = MappingRun(definition_id=definition.id, dataset_id=source.id, version_id=version.id)
    return svc, resource, spec, body


def test_real_materialization_replay_edit_ownership_and_provenance(world, store):  # noqa: F811
    svc, resource, spec, body = setup_mapping(world, store)
    assert svc.preview(world.actor, resource.id, body)["validation"] == "sample-only"
    from ontology_platform.mappings.contracts import MappingPreview

    draft = MappingPreview(
        dataset_id=body.dataset_id, version_id=body.version_id, specification=spec
    )
    assert svc.preview(world.actor, resource.id, draft)["full_source_validated"] is False
    assert world.objects.count(world.actor, spec.ontology_id, "Factory") == 0
    job = svc.start(world.actor, resource.id, body)
    worker = ExecutionWorker(
        PipelineService(world.sessions, svc.authorizer, svc.settings, svc.store)
    )
    assert worker.run_one() == job.id
    status = svc.status(world.actor, job.id)
    assert status.state == "SUCCEEDED", status
    assert status.metrics["created"] == 2
    assert "preview" not in status.metrics
    rows = svc.provenance(world.actor, job.id)
    assert len(rows) == 2 and all(r["version_id"] == str(body.version_id) for r in rows)
    assert all("properties" not in r["target"] for r in rows)
    obj = world.objects.get(world.actor, spec.ontology_id, "Factory", "F1")
    world.objects.patch(
        world.actor,
        spec.ontology_id,
        "Factory",
        "F1",
        ObjectPatch(expected_version=obj.version, properties={"factoryName": "Edited"}),
    )
    replay = svc.start(world.actor, resource.id, body)
    worker.run_one()
    assert svc.status(world.actor, replay.id).state == "SUCCEEDED"
    assert world.objects.count(world.actor, spec.ontology_id, "Factory") == 2
    assert (
        world.objects.get(world.actor, spec.ontology_id, "Factory", "F1").properties["factoryName"]
        == "Edited"
    )
    with world.sessions.begin() as s, pytest.raises(IntegrityError):
        s.execute(
            update(MappingDefinition)
            .where(MappingDefinition.id == body.definition_id)
            .values(sequence=9)
        )
    with world.sessions.begin() as s, pytest.raises(IntegrityError):
        s.execute(
            update(MaterializationRecord)
            .where(MaterializationRecord.run_id == job.id)
            .values(operation="observed")
        )


def test_full_validation_and_duplicate_failure_no_mutations(world, store):  # noqa: F811
    svc, resource, spec, body = setup_mapping(world, store, b"id,name\nF1,A\nF1,B\n")
    run = svc.start(world.actor, resource.id, body)
    worker = ExecutionWorker(svc)
    worker.run_one()
    state = svc.status(world.actor, run.id)
    assert state.state == "FAILED", state
    assert state.metrics["invalid_records"] == 1
    assert world.objects.count(world.actor, spec.ontology_id, "Factory") == 0


def test_full_validation_is_read_only_and_contracts_fail_closed(world, store):  # noqa: F811
    svc, resource, spec, body = setup_mapping(world, store)
    run = svc.start(world.actor, resource.id, body.model_copy(update={"mode": "full_validation"}))
    ExecutionWorker(svc).run_one()
    assert svc.status(world.actor, run.id).state == "SUCCEEDED"
    assert svc.provenance(world.actor, run.id) == []
    assert world.objects.count(world.actor, spec.ontology_id, "Factory") == 0
    with pytest.raises(ApplicationError):
        svc.publish(world.actor, resource.id, spec.model_copy(update={"schema_version": "9.0.0"}))
    with pytest.raises(ValidationError):
        MappingSpec.model_validate(spec.model_dump() | {"code": "exec('bad')"})
    with pytest.raises(ApplicationError):
        svc.preview(world.actor, uuid4(), body)


def test_partial_failure_replays_checkpoint_and_cancel_preserves_audit(world, store, monkeypatch):  # noqa: F811
    import ontology_platform.mappings.worker as mapping_worker

    data = ("id,name\n" + "".join(f"F{i},Factory {i}\n" for i in range(240))).encode()
    svc, resource, spec, body = setup_mapping(world, store, data)
    job = svc.start(world.actor, resource.id, body)
    operation = mapping_worker.object_operation
    calls = 0

    def interrupted(*args, **kwargs):
        nonlocal calls
        if args[-1]:
            calls += 1
            if calls == 101:
                raise OSError("simulated controller loss")
        return operation(*args, **kwargs)

    monkeypatch.setattr(mapping_worker, "object_operation", interrupted)
    ExecutionWorker(svc).run_one()
    status = svc.status(world.actor, job.id)
    assert status.state == "QUEUED", status
    assert world.objects.count(world.actor, spec.ontology_id, "Factory") == 100
    assert len(svc.provenance(world.actor, job.id, 100)) == 100
    monkeypatch.setattr(mapping_worker, "object_operation", operation)
    ExecutionWorker(svc).run_one()
    status = svc.status(world.actor, job.id)
    assert status.state == "SUCCEEDED" and status.metrics["created"] == 240, status
    assert world.objects.count(world.actor, spec.ontology_id, "Factory") == 240
    cancelled = svc.start(world.actor, resource.id, body)
    svc.change(world.actor, cancelled.id)
    assert svc.status(world.actor, cancelled.id).state == "CANCELLED"
    assert ExecutionWorker(svc).run_one() is None


def test_expired_lease_stale_worker_and_concurrent_runs(world, store):  # noqa: F811
    from concurrent.futures import ThreadPoolExecutor
    from datetime import timedelta

    from ontology_platform.db.models import ExecutionJob
    from ontology_platform.db.session import clock

    svc, resource, spec, body = setup_mapping(world, store)
    job = svc.start(world.actor, resource.id, body)
    worker = ExecutionWorker(svc)
    tenant, run, stale = worker.claim()
    with world.sessions.begin() as s:
        row = s.get(ExecutionJob, (tenant, run))
        row.lease_until = clock(s) - timedelta(seconds=1)
    tenant, run, token = worker.claim()
    assert stale != token
    with world.sessions.begin() as s, pytest.raises(ApplicationError, match="lease"):
        worker.fenced(s, tenant, run, stale)
    worker.execute(tenant, run, token)
    assert svc.status(world.actor, job.id).state == "SUCCEEDED"
    with ThreadPoolExecutor(2) as pool:
        jobs = list(pool.map(lambda _: svc.start(world.actor, resource.id, body), range(2)))
        list(pool.map(lambda _: ExecutionWorker(svc).run_one(), range(2)))
    while worker.run_one():
        pass
    assert all(svc.status(world.actor, j.id).state == "SUCCEEDED" for j in jobs)
    assert world.objects.count(world.actor, spec.ontology_id, "Factory") == 2


def test_mapping_cannot_adopt_or_steal_objects(world, store):  # noqa: F811
    from ontology_platform.contracts import CreateObject

    svc, resource, spec, body = setup_mapping(world, store)
    world.objects.create(
        world.actor,
        spec.ontology_id,
        CreateObject(
            object_type_id="Factory",
            object_id="F1",
            properties={"factoryId": "F1", "factoryName": "Existing", "location": "Test"},
        ),
    )
    run = svc.start(world.actor, resource.id, body)
    ExecutionWorker(svc).run_one()
    assert svc.status(world.actor, run.id).state == "FAILED"
    assert world.objects.count(world.actor, spec.ontology_id, "Factory") == 1


def machine_spec(spec):
    from ontology_platform.mappings.contracts import ObjectMapping, RelationshipMapping

    machine = ObjectMapping.model_validate(
        {
            "object_type": "Machine",
            "identity": key().model_dump(),
            "properties": {
                "machineName": {"column": "name", "conversion": "string"},
                "operationalStatus": {"constant": "RUNNING", "conversion": "string"},
                "temperatureCelsius": {"constant": "20.25", "conversion": "decimal"},
            },
        }
    )
    link = RelationshipMapping.model_validate(
        {
            "link_type": "locatedInFactory",
            "source": {"object_type": "Machine", "identity": key().model_dump()},
            "target": {"object_type": "Factory", "identity": key().model_dump()},
        }
    )
    return spec.model_copy(update={"objects": spec.objects + [machine], "relationships": [link]})


def test_relationships_same_run_idempotence_and_action_owned_values(world, store):  # noqa: F811
    from ontology_platform.actions.contracts import ExecuteRequest
    from ontology_platform.actions.service import ActionExecutionService
    from ontology_schema.models import OntologyDefinition
    from test_actions import examples

    world.definition = OntologyDefinition.model_validate(
        world.definition.model_dump() | {"action_types": examples()}
    )
    svc, resource, spec, body = setup_mapping(world, store)
    definition = svc.publish(world.actor, resource.id, machine_spec(spec))
    body = body.model_copy(update={"definition_id": definition.id})
    run = svc.start(world.actor, resource.id, body)
    ExecutionWorker(svc).run_one()
    assert svc.status(world.actor, run.id).state == "SUCCEEDED", svc.status(world.actor, run.id)
    obj = world.objects.get(world.actor, spec.ontology_id, "Machine", "F1")
    ActionExecutionService(world.sessions, svc.authorizer).execute(
        world.actor,
        spec.ontology_id,
        "UpdateMachineStatus",
        ExecuteRequest(
            idempotency_key="mapping-action",
            parameters={"machineId": "F1", "newStatus": "STOPPED", "expectedRevision": obj.version},
        ),
    )
    replay = svc.start(world.actor, resource.id, body)
    ExecutionWorker(svc).run_one()
    assert svc.status(world.actor, replay.id).state == "SUCCEEDED"
    assert (
        world.objects.get(world.actor, spec.ontology_id, "Machine", "F1").properties[
            "operationalStatus"
        ]
        == "STOPPED"
    )
    records = svc.provenance(world.actor, replay.id)
    assert len(records) == 6 and sum(r["target"]["kind"] == "link" for r in records) == 2


def test_resource_move_archive_immutable_versions_and_source_schema(world, store):  # noqa: F811
    from ontology_platform.projects.contracts import CreateFolder, UpdateResource

    svc, resource, spec, body = setup_mapping(world, store)
    folder = svc.create_folder(world.actor, resource.project_id, CreateFolder(name="Mappings"))
    moved = svc.update_resource(
        world.actor,
        resource.id,
        UpdateResource(name="Renamed", folder_id=folder.id, expected_revision=1),
        1,
    )
    assert moved.id == resource.id and moved.folder_id == folder.id
    definition = svc.publish(world.actor, resource.id, spec)
    assert definition.id != body.definition_id and definition.sequence == 2
    datasets = svc.datasets()
    incompatible = commit(datasets, world.actor, body.dataset_id, b"id,wrong\nF1,test\n")
    with pytest.raises(ApplicationError):
        svc.start(world.actor, resource.id, body.model_copy(update={"version_id": incompatible.id}))
    svc.update_resource(world.actor, resource.id, None, moved.revision)
    with pytest.raises(ApplicationError):
        svc.start(world.actor, resource.id, body)


def test_private_source_filtering_readonly_shares_and_revocation(security, store):  # noqa: F811
    from ontology_platform.projects.contracts import CreateProject, MemberChange, ShareChange
    from test_projects import grant_projects

    w, auth, admin, owner, other, _ = security
    grant_projects(admin, owner, other)
    svc, resource, spec, body = setup_mapping(
        w, store, b"id,name\nF3,Third\nF4,Fourth\n", prepared=True, actor=owner, auth=auth
    )
    run = svc.start(owner, resource.id, body)
    ExecutionWorker(svc).run_one()
    assert svc.status(owner, run.id).state == "SUCCEEDED"
    consumer = svc.create_project(owner, CreateProject(name="Consumer"))
    svc.member(
        owner,
        consumer.id,
        MemberChange(principal_id=other.principal_id, role="viewer", expected_revision=1),
    )
    svc.share(
        owner, resource.id, ShareChange(project_id=consumer.id, enabled=True, expected_revision=1)
    )
    assert svc.history(other, resource.id, 50, 0)[0].id == run.id
    with pytest.raises(ApplicationError):
        svc.provenance(other, run.id)
    with pytest.raises(ApplicationError):
        svc.start(other, resource.id, body)
    assert (
        svc.target_runs(
            other, spec.ontology_id, {"kind": "object", "type": "Factory", "id": "F1"}, 50, 0
        )
        == []
    )
    # Revocation at queued admission is checked by the worker before any target mutation.
    queued = svc.start(owner, resource.id, body)
    current = svc.get_project(owner, resource.project_id)
    current = svc.member(
        owner,
        resource.project_id,
        MemberChange(
            principal_id=other.principal_id, role="owner", expected_revision=current.revision
        ),
    )
    svc.member(
        owner,
        resource.project_id,
        MemberChange(
            principal_id=owner.principal_id, role="viewer", expected_revision=current.revision
        ),
    )
    ExecutionWorker(svc).run_one()
    assert svc.status(owner, queued.id).state == "FAILED"


@pytest.mark.parametrize(
    "change",
    [
        {"ontology_id": "unknown"},
        {"schema_version": "2.0.0"},
        {"target_resource_id": str(uuid4())},
        {"columns": {"id": "Binary"}},
    ],
)
def test_invalid_target_or_unsupported_source_contract(world, store, change):  # noqa: F811
    svc, resource, spec, _ = setup_mapping(world, store)
    with pytest.raises(ApplicationError):
        svc.publish(world.actor, resource.id, spec.model_copy(update=change))


def test_missing_relationship_endpoint_preflight_rolls_back_objects(world, store):  # noqa: F811
    svc, resource, spec, body = setup_mapping(world, store)
    linked = machine_spec(spec)
    linked = linked.model_copy(update={"objects": linked.objects[1:]})
    definition = svc.publish(world.actor, resource.id, linked)
    run = svc.start(
        world.actor, resource.id, body.model_copy(update={"definition_id": definition.id})
    )
    ExecutionWorker(svc).run_one()
    assert svc.status(world.actor, run.id).state == "FAILED"
    assert world.objects.count(world.actor, spec.ontology_id, "Machine") == 0


def test_mapping_ownership_conflict_between_resources(world, store):  # noqa: F811
    svc, resource, spec, body = setup_mapping(world, store)
    first = svc.start(world.actor, resource.id, body)
    ExecutionWorker(svc).run_one()
    assert svc.status(world.actor, first.id).state == "SUCCEEDED"
    other = svc.create(world.actor, resource.project_id, CreateArtifact(name="Other mapping"))
    definition = svc.publish(world.actor, other.id, spec)
    second = svc.start(
        world.actor, other.id, body.model_copy(update={"definition_id": definition.id})
    )
    ExecutionWorker(svc).run_one()
    assert svc.status(world.actor, second.id).state == "FAILED"
    assert world.objects.count(world.actor, spec.ontology_id, "Factory") == 2


def test_upgrade_from_phase14_preserves_definitions(historical_database, store):  # noqa: F811
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from test_execution import spec as pipeline_spec
    from test_phase1 import ROOT, make_world, migrate

    engine, sessions, _ = historical_database
    migrate(engine, "0021_execution")
    w = make_world(historical_database)
    datasets = make_service(w, store)
    source = dataset(datasets, w.actor)
    version = commit(datasets, w.actor, source.id)
    pipelines = PipelineService(sessions, w.registry.authorizer, store.settings, store)
    pipe = pipelines.create(w.actor, source.project_id, CreateArtifact(name="Preserved pipeline"))
    definition = pipelines.publish(w.actor, pipe.id, pipeline_spec())
    migrate(engine)
    config = Config(str(ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.check(config)
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == "0026_pipeline_dag"
        )
    assert pipelines.definitions(w.actor, pipe.id)[0].id == definition.id
    assert datasets.dataset_metadata(w.actor, source.id, version.id).checksum == version.checksum


def test_csv_string_identity_preserves_leading_zeros_across_batch_reordering(tmp_path):
    from ontology_platform.datasets.streaming import batches
    from ontology_platform.execution.config import ExecutionSettings

    path = tmp_path / "identity.csv"
    spec = key()
    observed = []
    for values in (["001"] * 8192 + ["X"], ["X"] + ["001"] * 8192):
        path.write_text("id\n" + "\n".join(values) + "\n")
        keys = set()
        for frame in batches(path, "csv", ExecutionSettings(), string_columns=("id",)):
            keys.update(identity(spec, row) for row in frame.iter_rows(named=True))
        observed.append(keys)
    assert observed == [{"001", "X"}, {"001", "X"}]


def test_new_source_versions_update_owned_values_and_preserve_absent_objects(world, store):  # noqa: F811
    svc, resource, spec, body = setup_mapping(world, store)
    first = svc.start(world.actor, resource.id, body)
    ExecutionWorker(svc).run_one()
    assert svc.status(world.actor, first.id).state == "SUCCEEDED"
    second_source = commit(
        svc.datasets(), world.actor, body.dataset_id, b"id,name\nF1,Updated factory\n"
    )
    second = svc.start(
        world.actor, resource.id, body.model_copy(update={"version_id": second_source.id})
    )
    ExecutionWorker(svc).run_one()
    assert svc.status(world.actor, second.id).state == "SUCCEEDED"
    assert world.objects.count(world.actor, spec.ontology_id, "Factory") == 2
    assert (
        world.objects.get(world.actor, spec.ontology_id, "Factory", "F1").properties["factoryName"]
        == "Updated factory"
    )
    assert svc.provenance(world.actor, second.id)[0]["version_id"] == str(second_source.id)


def test_composite_identity_stable_across_immutable_dataset_versions(world, store):  # noqa: F811
    svc, resource, spec, body = setup_mapping(world, store)
    item = spec.objects[0].model_copy(update={"identity": key(columns=("id", "name"))})
    definition = svc.publish(world.actor, resource.id, spec.model_copy(update={"objects": [item]}))
    body = body.model_copy(update={"definition_id": definition.id})
    first = svc.start(world.actor, resource.id, body)
    ExecutionWorker(svc).run_one()
    assert svc.status(world.actor, first.id).state == "SUCCEEDED"
    second_source = commit(
        svc.datasets(), world.actor, body.dataset_id, b"id,name\nF2,Factory Two\nF1,Factory One\n"
    )
    replay = svc.start(
        world.actor, resource.id, body.model_copy(update={"version_id": second_source.id})
    )
    ExecutionWorker(svc).run_one()
    status = svc.status(world.actor, replay.id)
    assert status.state == "SUCCEEDED" and status.metrics.get("created", 0) == 0, status
    assert world.objects.count(world.actor, spec.ontology_id, "Factory") == 2


def test_mapping_preview_limits_expanded_values_and_sanitizes_decimal_errors(world, store):  # noqa: F811
    import json

    from ontology_platform.mappings.contracts import MappingPreview, Value

    svc, resource, spec, body = setup_mapping(
        world, store, b"id,name\nF1,private-invalid-decimal\n"
    )
    from ontology_platform.mappings.conversion import evaluate

    with pytest.raises(ValueError):
        evaluate(Value(column="name", conversion="decimal"), {"name": "private-invalid-decimal"})
    with pytest.raises(ValueError):
        convert("1e100000000", "decimal")
    item = spec.objects[0].model_copy(
        update={
            "properties": spec.objects[0].properties
            | {"factoryName": Value(constant="x" * 100000, conversion="string")}
        }
    )
    draft = MappingPreview(
        dataset_id=body.dataset_id,
        version_id=body.version_id,
        specification=spec.model_copy(update={"objects": [item]}),
    )
    preview = svc.preview(world.actor, resource.id, draft)
    assert len(json.dumps(preview).encode()) < 65536
    assert world.objects.count(world.actor, spec.ontology_id, "Factory") == 0


def test_governed_link_removal_is_not_silently_recreated(world, store):  # noqa: F811
    from ontology_platform.contracts import LinkInput

    svc, resource, spec, body = setup_mapping(world, store)
    definition = svc.publish(world.actor, resource.id, machine_spec(spec))
    body = body.model_copy(update={"definition_id": definition.id})
    first = svc.start(world.actor, resource.id, body)
    ExecutionWorker(svc).run_one()
    assert svc.status(world.actor, first.id).state == "SUCCEEDED"
    edge = LinkInput(
        link_type_id="locatedInFactory",
        source_object_type_id="Machine",
        source_object_id="F1",
        target_object_type_id="Factory",
        target_object_id="F1",
    )
    world.objects.delete_link(world.actor, spec.ontology_id, edge)
    replay = svc.start(world.actor, resource.id, body)
    ExecutionWorker(svc).run_one()
    assert svc.status(world.actor, replay.id).state == "FAILED"
    with world.sessions() as session:
        from ontology_platform.db.models import Link

        assert (
            session.get(
                Link,
                (
                    world.actor.tenant_id,
                    spec.ontology_id,
                    "locatedInFactory",
                    "Machine",
                    "F1",
                    "Factory",
                    "F1",
                ),
            )
            is None
        )
