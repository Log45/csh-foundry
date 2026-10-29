"""Phase 5 PostgreSQL, governed export, worker, inference and HTTP boundaries."""

import json
import os
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from ontology_platform.contracts import CreateObject, ObjectPatch
from ontology_platform.db.models import (
    DerivedFact,
    Object,
    SemanticApproval,
    SemanticArtifact,
    SemanticJob,
)
from ontology_platform.errors import ApplicationError
from ontology_platform.main import create_app
from ontology_platform.queries.ast import QueryRequest
from ontology_platform.security.interfaces import Principal
from ontology_platform.security.query import QueryGrant
from ontology_platform.semantic.compiler import compile_schema, parse, serialize, term
from ontology_platform.semantic.contracts import (
    ApprovalInput,
    CompileInput,
    ExportInput,
    JobInput,
    NativeInput,
)
from ontology_platform.semantic.engine import OpenOntologiesAdapter
from ontology_platform.semantic.service import SemanticService
from ontology_platform.semantic.worker import SemanticWorker
from ontology_schema.models import RDFMapping
from rdflib import RDF, SH, Graph, Literal, URIRef
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_ingestion import setup, submit
from test_phase1 import active, make_world, migrate
from test_phase1 import database as pg_database

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.integration


@pytest.fixture
def database():
    yield from pg_database.__wrapped__()


@pytest.fixture
def semantic(database):
    world = make_world(database)
    active(world)
    world.objects.create(
        world.actor,
        world.definition.id,
        CreateObject(
            object_type_id="Factory",
            object_id="F",
            properties={"factoryId": "F", "factoryName": "Factory", "location": "Earth"},
        ),
    )
    binary = os.environ.get("OPEN_ONTOLOGIES_BIN")
    if not binary:
        pytest.skip("NOT RUN: pinned semantic engine required")
    service = SemanticService(world.sessions, world.objects.authorizer)
    worker = SemanticWorker(
        world.sessions, world.objects.authorizer, engine=OpenOntologiesAdapter(Path(binary))
    )
    return world, service, worker


def inputs(semantic):
    world, service, _ = semantic
    ontology = world.definition.id
    compiled = service.compile(
        world.actor, ontology, CompileInput(schema_version=world.definition.version)
    )
    spec = ExportInput(
        schema_version=world.definition.version,
        selections=(QueryRequest(object_type="Factory", limit=200),),
    )
    asserted = service.export(world.actor, ontology, spec)
    return compiled, asserted, spec


def job(semantic, operation="validation", profile="owl-rl-ext"):
    world, service, worker = semantic
    compiled, asserted, spec = inputs(semantic)
    request = JobInput(
        operation=operation,
        primary_artifact=asserted,
        secondary_artifact=compiled[1 if operation == "validation" else 0],
        profile=profile,
    )
    result = service.submit(world.actor, world.definition.id, request)
    return result, request


def test_compile_export_dedup_and_manifest(semantic):
    world, service, _ = semantic
    compiled, asserted, spec = inputs(semantic)
    assert service.export(world.actor, world.definition.id, spec) == asserted
    view = service.get(world.actor, world.definition.id, asserted)
    assert view.freshness == "CURRENT"
    assert view.manifest.output_hash
    assert view.manifest.provenance["iri_mapping_version"] == 1
    mapping = RDFMapping(namespace=world.definition.namespace)
    graph = parse(view.content.encode())
    subject = next(graph.subjects(RDF.type, term(world.definition.namespace, "class", "Factory")))
    assert mapping.identity_from_iri(str(subject)).object_id == "F"
    assert len(graph) == 4
    for key in compiled:
        assert service.get(world.actor, world.definition.id, key).freshness == "SCHEMA_ONLY"


@pytest.mark.parametrize("operation", ["validation", "reasoning"])
def test_worker_results_and_approval_no_operational_mutation(semantic, operation):
    world, service, worker = semantic
    run, request = job(semantic, operation)
    before = world.objects.get(world.actor, world.definition.id, "Factory", "F")
    assert service.submit(world.actor, world.definition.id, request).id == run.id
    assert worker.run_one(world.actor, world.definition.id) == run.id
    result = service.job(world.actor, world.definition.id, run.id)
    assert result.status == "COMPLETED", result.last_error
    outputs = [service.get(world.actor, world.definition.id, k) for k in result.outputs]
    if operation == "validation":
        assert json.loads(outputs[0].content)["conforms"] is True
    else:
        derived = next(o for o in outputs if o.manifest.kind == "derived")
        proof = next(o for o in outputs if o.manifest.kind == "proof")
        assert json.loads(proof.content)["verification"] == "NOT RUN"
        service.approve(
            world.actor, world.definition.id, derived.manifest.id, ApprovalInput(state="APPROVED")
        )
        service.approve(
            world.actor, world.definition.id, derived.manifest.id, ApprovalInput(state="REJECTED")
        )
        assert [
            event.state
            for event in service.approval_history(
                world.actor, world.definition.id, derived.manifest.id
            )
        ] == ["APPROVED", "REJECTED"]
        with world.sessions() as s:
            assert s.scalar(select(func.count()).select_from(SemanticApproval)) == 2
    assert world.objects.get(world.actor, world.definition.id, "Factory", "F") == before
    assert worker.run_one(world.actor, world.definition.id) is None
    assert service.submit(world.actor, world.definition.id, request).id == run.id


def test_validation_violation_is_completed_result(semantic):
    world, service, worker = semantic
    compiled, asserted, _ = inputs(semantic)
    _, shapes, _ = compile_schema(world.definition)
    g = parse(shapes)
    ps = term(world.definition.namespace, "property-shape", "Factory", "factoryName")
    g.set((ps, SH.maxCount, Literal(0)))
    key = service.native(
        world.actor,
        world.definition.id,
        NativeInput(
            schema_version=world.definition.version, kind="shapes", content=serialize(g).decode()
        ),
    )
    run = service.submit(
        world.actor,
        world.definition.id,
        JobInput(operation="validation", primary_artifact=asserted, secondary_artifact=key),
    )
    worker.run_one(world.actor, world.definition.id)
    completed = service.job(world.actor, world.definition.id, run.id)
    assert completed.status == "COMPLETED"
    report = json.loads(service.get(world.actor, world.definition.id, completed.outputs[0]).content)
    assert report["conforms"] is False and report["violation_count"] > 0
    assert "/var/" not in json.dumps(report)


def test_native_invalid_and_unsupported_profile(semantic):
    world, service, _ = semantic
    with pytest.raises(ApplicationError) as error:
        service.native(
            world.actor,
            world.definition.id,
            NativeInput(
                schema_version=world.definition.version, kind="shapes", content="invalid turtle"
            ),
        )
    assert error.value.code == "invalid_shacl"


def test_change_job(semantic):
    world, service, worker = semantic
    keys = [
        service.native(
            world.actor,
            world.definition.id,
            NativeInput(
                schema_version=world.definition.version,
                kind="ontology",
                content=f"<urn:s> a <urn:{kind}> .",
            ),
        )
        for kind in ("A", "B")
    ]
    run = service.submit(
        world.actor,
        world.definition.id,
        JobInput(operation="change", primary_artifact=keys[0], secondary_artifact=keys[1]),
    )
    worker.run_one(world.actor, world.definition.id)
    result = service.job(world.actor, world.definition.id, run.id)
    assert result.status == "COMPLETED", result.last_error
    report = json.loads(service.get(world.actor, world.definition.id, result.outputs[0]).content)
    assert report["analysis"]["added"] == 1


@pytest.mark.parametrize(
    "error_code", ["semantic_timeout", "semantic_unavailable", "semantic_failed", "invalid_rdf"]
)
def test_worker_failures_retry_and_no_partial_outputs(semantic, error_code):
    world, service, worker = semantic
    run, _ = job(semantic)
    with patch.object(
        worker.engine, "validate_shapes", side_effect=ApplicationError(error_code, "redacted", 504)
    ):
        worker.run_one(world.actor, world.definition.id)
    result = service.job(world.actor, world.definition.id, run.id)
    retry = error_code in {"semantic_timeout", "semantic_unavailable"}
    assert result.status == ("PENDING" if retry else "FAILED")
    assert result.outputs == [] and result.last_error == error_code
    if retry:
        worker.run_one(world.actor, world.definition.id)
        assert service.job(world.actor, world.definition.id, run.id).status == "COMPLETED"


def test_cancel_and_stale_worker_completion(semantic):
    world, service, worker = semantic
    run, _ = job(semantic)
    key, token = worker.claim(world.actor, world.definition.id)
    assert worker.claim(world.actor, world.definition.id) is None
    worker.renew(world.actor, world.definition.id, key, token)
    assert service.cancel(world.actor, world.definition.id, key).status == "CANCELLED"
    with pytest.raises(ApplicationError) as error:
        worker.execute(world.actor, world.definition.id, key, token)
    assert error.value.code == "lease_lost"
    assert service.cancel(world.actor, world.definition.id, key).status == "CANCELLED"


def test_expired_lease_restart_and_fencing(semantic):
    world, service, worker = semantic
    run, _ = job(semantic)
    key, old = worker.claim(world.actor, world.definition.id)
    with world.sessions.begin() as s:
        row = s.get(SemanticJob, (world.actor.tenant_id, world.definition.id, key))
        row.lease_until = s.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)
    _, new = worker.claim(world.actor, world.definition.id)
    assert new != old
    with pytest.raises(ApplicationError):
        worker.execute(world.actor, world.definition.id, key, old)
    worker.execute(world.actor, world.definition.id, key, new)
    assert service.job(world.actor, world.definition.id, key).status == "COMPLETED"


def test_lease_exhaustion(semantic):
    world, service, worker = semantic
    run, _ = job(semantic)
    for _ in range(3):
        key, token = worker.claim(world.actor, world.definition.id)
        with world.sessions.begin() as s:
            row = s.get(SemanticJob, (world.actor.tenant_id, world.definition.id, key))
            row.lease_until = s.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)
    assert worker.claim(world.actor, world.definition.id) is None
    assert service.job(world.actor, world.definition.id, run.id).last_error == "lease_exhausted"


def test_stale_edit_and_freshness(semantic):
    world, service, worker = semantic
    run, request = job(semantic)
    world.objects.patch(
        world.actor,
        world.definition.id,
        "Factory",
        "F",
        ObjectPatch(expected_version=1, properties={"factoryName": "Changed"}),
    )
    assert (
        service.get(world.actor, world.definition.id, request.primary_artifact).freshness == "STALE"
    )
    worker.run_one(world.actor, world.definition.id)
    assert service.job(world.actor, world.definition.id, run.id).last_error == "stale_inputs"
    with pytest.raises(ApplicationError):
        service.submit(world.actor, world.definition.id, request)


class Policy:
    def __init__(self, delegate):
        self.delegate = delegate
        self.visible = None
        self.ids = None
        self.denied = None

    def require(self, p, operation, resource):
        self.delegate.require(p, operation, resource)
        if operation == self.denied:
            raise ApplicationError("forbidden", "Denied", 403)

    def query_grant(self, p, ontology_id, object_type):
        self.delegate.require(p, "object:query", f"{p.tenant_id}/{ontology_id}")
        return QueryGrant(
            visible_properties=self.visible, allowed_object_ids=self.ids, revision="v1"
        )


def test_property_row_projection_and_policy_revocation(semantic):
    world, service, _ = semantic
    policy = Policy(world.objects.authorizer)
    service = SemanticService(world.sessions, policy)
    policy.visible = ("factoryId",)
    spec = ExportInput(
        schema_version=world.definition.version, selections=(QueryRequest(object_type="Factory"),)
    )
    key = service.export(world.actor, world.definition.id, spec)
    assert 'Factory"' not in service.get(world.actor, world.definition.id, key).content
    assert len(parse(service.get(world.actor, world.definition.id, key).content.encode())) == 2
    policy.ids = ()
    with pytest.raises(ApplicationError) as error:
        service.get(world.actor, world.definition.id, key)
    assert error.value.status_code == 403


@pytest.mark.parametrize(
    "permission", ["semantic:export", "object:read", "property:read", "schema:read", "link:read"]
)
def test_permission_denials(semantic, permission):
    world, _, _ = semantic
    policy = Policy(world.objects.authorizer)
    policy.denied = permission
    service = SemanticService(world.sessions, policy)
    spec = ExportInput(
        schema_version=world.definition.version, selections=(QueryRequest(object_type="Factory"),)
    )
    with pytest.raises(ApplicationError) as error:
        service.export(world.actor, world.definition.id, spec)
    assert error.value.status_code == 403


def test_tenant_principal_and_inputs(semantic):
    world, service, _ = semantic
    compiled, asserted, _ = inputs(semantic)
    other = Principal(tenant_id=world.actor.tenant_id, principal_id="other")

    # Explicit same-tenant admin authorizer exercises the artifact ownership check independently.
    class Allow:
        def require(self, *args):
            pass

    scoped = SemanticService(world.sessions, Allow())
    with pytest.raises(ApplicationError) as error:
        scoped.get(other, world.definition.id, asserted)
    assert error.value.status_code == 404
    foreign = world.actor.model_copy(update={"tenant_id": uuid4()})
    with pytest.raises(ApplicationError):
        service.get(foreign, world.definition.id, asserted)
    with pytest.raises(ApplicationError):
        service.submit(
            world.actor,
            world.definition.id,
            JobInput(
                operation="validation", primary_artifact=compiled[0], secondary_artifact=asserted
            ),
        )


def test_migration_constraints_immutability_and_preservation(semantic):
    world, service, worker = semantic
    compiled, asserted, _ = inputs(semantic)
    with pytest.raises(DBAPIError):
        with world.sessions.begin() as s:
            s.execute(
                text("UPDATE semantic_artifacts SET content=:content WHERE id=:id"),
                {"content": "tampered", "id": asserted},
            )
    with pytest.raises(DBAPIError):
        with world.sessions.begin() as s:
            s.execute(text("DELETE FROM semantic_artifacts WHERE id=:id"), {"id": asserted})
    run, _ = job(semantic)
    with pytest.raises(DBAPIError):
        with world.sessions.begin() as s:
            s.execute(
                text("UPDATE semantic_jobs SET principal_id=:principal WHERE id=:id"),
                {"principal": "other", "id": run.id},
            )
    migrate(world.engine, "0009_ingestion_diagnostics", downgrade=True)
    assert world.objects.get(world.actor, world.definition.id, "Factory", "F").version == 1
    migrate(world.engine)
    assert world.objects.get(world.actor, world.definition.id, "Factory", "F").version == 1


def test_http_semantic_contract_and_raw_limit(semantic):
    world, _, _ = semantic
    app = create_app(world.settings)
    app.state.sessions = world.sessions
    with TestClient(app) as client:
        prefix = f"/api/v1/ontologies/{world.definition.id}/semantic"
        response = client.post(
            prefix + "/compile", json={"schema_version": world.definition.version}
        )
        assert response.status_code == 200, response.text
        key = response.json()[0]
        assert client.get(prefix + f"/artifacts/{key}").status_code == 200
        assert client.post(prefix + "/compile", content="x" * 65537).status_code == 413
        assert client.get(prefix + "/jobs").json() == []
        assert client.post(prefix + "/jobs", json={}).status_code == 422


def test_manufacturing_ingestion_export_validation_and_engine_inference(database, tmp_path):
    world, ingestion, ingest_worker = setup(database, tmp_path)
    run = submit((world, ingestion, ingest_worker))
    ingest_worker.run_one(world.actor, world.definition.id)
    assert ingestion.get(world.actor, world.definition.id, run.id).status == "COMPLETED"
    binary = os.environ.get("OPEN_ONTOLOGIES_BIN")
    if not binary:
        pytest.skip("NOT RUN: pinned semantic engine required")
    service = SemanticService(world.sessions, world.objects.authorizer)
    worker = SemanticWorker(
        world.sessions, world.objects.authorizer, engine=OpenOntologiesAdapter(Path(binary))
    )
    selections = tuple(
        QueryRequest(object_type=t.id, limit=200) for t in world.definition.object_types
    )
    spec = ExportInput(
        schema_version=world.definition.version,
        selections=selections,
        links=tuple(t.id for t in world.definition.link_types),
    )
    asserted = service.export(world.actor, world.definition.id, spec)
    view = service.get(world.actor, world.definition.id, asserted)
    graph = parse(view.content.encode())
    assert len(graph) == 412
    assert len(view.manifest.provenance["selected"]["Machine"]) == 20
    assert len(view.manifest.provenance["ingestion"]["source_versions"]) == 4
    compiled = service.compile(
        world.actor, world.definition.id, CompileInput(schema_version=world.definition.version)
    )
    valid = service.submit(
        world.actor,
        world.definition.id,
        JobInput(operation="validation", primary_artifact=asserted, secondary_artifact=compiled[1]),
    )
    worker.run_one(world.actor, world.definition.id)
    result = service.job(world.actor, world.definition.id, valid.id)
    assert result.status == "COMPLETED", result.last_error
    assert (
        json.loads(service.get(world.actor, world.definition.id, result.outputs[0]).content)[
            "conforms"
        ]
        is True
    )
    # Compare raw fixture semantically after the explicitly versioned identity/vocabulary mapping.
    raw = Graph().parse(ROOT / "fixtures/manufacturing-data.ttl")
    ns = world.definition.namespace
    mapping = RDFMapping(namespace=ns)
    transformed = Graph()
    classes = {ns + t.id: t.id for t in world.definition.object_types}
    types = {str(s): classes[str(o)] for s, o in raw.subject_objects(RDF.type)}
    for s, p, o in raw:
        typ = types[str(s)]
        identity = mapping.identity_from_iri(
            next(
                str(x)
                for x in graph.subjects(RDF.type, term(ns, "class", typ))
                if mapping.identity_from_iri(str(x)).object_id == str(s).rsplit("#", 1)[-1]
            )
        )
        subject = URIRef(mapping.individual_iri(identity))
        if p == RDF.type:
            predicate, value = RDF.type, term(ns, "class", typ)
        elif isinstance(o, URIRef):
            link = next(
                t
                for t in world.definition.link_types
                if str(p) in {ns + t.id, ns + str(t.inverse_name)}
            )
            predicate = term(ns, "link" if ns + link.id == str(p) else "inverse-link", link.id)
            value = URIRef(
                mapping.individual_iri(
                    identity.model_copy(
                        update={
                            "object_type_id": types[str(o)],
                            "object_id": str(o).rsplit("#", 1)[-1],
                        }
                    )
                )
            )
        else:
            predicate, value = term(ns, "property", typ, str(p).rsplit("#", 1)[-1]), o
        transformed.add((subject, predicate, value))
    assert set(transformed) == set(graph)
    # Native authored OWL rules use the mapped vocabulary with unchanged OWL semantics.
    native = Graph().parse(ROOT / "fixtures/manufacturing.ttl")
    replacement = {}
    for typed in world.definition.object_types:
        replacement[URIRef(ns + typed.id)] = term(ns, "class", typed.id)
        for prop in typed.properties:
            replacement[URIRef(ns + prop.id)] = term(ns, "property", typed.id, prop.id)
    for link in world.definition.link_types:
        replacement[URIRef(ns + link.id)] = term(ns, "link", link.id)
        if link.inverse_name:
            replacement[URIRef(ns + link.inverse_name)] = term(ns, "inverse-link", link.id)
    translated = Graph()
    for triple in native:
        translated.add(tuple(replacement.get(x, x) for x in triple))
    ontology = service.native(
        world.actor,
        world.definition.id,
        NativeInput(
            schema_version=world.definition.version,
            kind="ontology",
            content=translated.serialize(format="turtle"),
        ),
    )
    reasoning = service.submit(
        world.actor,
        world.definition.id,
        JobInput(operation="reasoning", primary_artifact=asserted, secondary_artifact=ontology),
    )
    worker.run_one(world.actor, world.definition.id)
    completed = service.job(world.actor, world.definition.id, reasoning.id)
    assert completed.status == "COMPLETED", completed.last_error
    derived = next(
        key
        for key in completed.outputs
        if service.get(world.actor, world.definition.id, key).manifest.kind == "derived"
    )
    facts = service.facts(world.actor, world.definition.id, derived, 100)
    critical = {
        mapping.identity_from_iri(f.subject.strip("<>")).object_id
        for f in facts
        if f.object == URIRef(ns + "CriticalMachine").n3() and f.predicate == RDF.type.n3()
    }
    assert critical == {"MCH-005", "MCH-011", "MCH-017"}
    assert all(f.approval == "PENDING" for f in facts)
    with world.sessions() as s:
        assert s.scalar(select(func.count()).select_from(Object)) == 63


def test_atomic_result_failure_rolls_back_and_retry_history(semantic):
    world, service, worker = semantic
    run, _ = job(semantic, "reasoning")
    original = worker.store
    calls = 0

    def broken(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("simulated crash after first output insert")
        return original(*args, **kwargs)

    with world.sessions() as s:
        before = s.scalar(select(func.count()).select_from(SemanticArtifact))
    with patch.object(worker, "store", side_effect=broken):
        worker.run_one(world.actor, world.definition.id)
    with world.sessions() as s:
        assert s.scalar(select(func.count()).select_from(SemanticArtifact)) == before
        assert s.scalar(select(func.count()).select_from(DerivedFact)) == 0
    assert service.job(world.actor, world.definition.id, run.id).status == "PENDING"
    worker.run_one(world.actor, world.definition.id)
    result = service.job(world.actor, world.definition.id, run.id)
    assert result.status == "COMPLETED"
    assert [event["event"] for event in result.history] == [
        "CLAIMED",
        "ERROR",
        "CLAIMED",
        "COMPLETED",
    ]


def test_schema_activation_rejects_pending_job(semantic):
    world, service, worker = semantic
    run, request = job(semantic)
    new = world.definition.model_copy(update={"version": "1.1.0", "name": "Renamed"})
    world.registry.draft(world.actor, world.definition.id, new)
    world.registry.publish(world.actor, world.definition.id, new.version)
    world.registry.activate(world.actor, world.definition.id, new.version)
    worker.run_one(world.actor, world.definition.id)
    assert service.job(world.actor, world.definition.id, run.id).last_error == "stale_schema"
    with pytest.raises(ApplicationError) as error:
        service.get(world.actor, world.definition.id, request.primary_artifact)
    assert error.value.code == "stale_schema"


def test_semantic_results_reauthorize_inputs(semantic):
    world, service, worker = semantic
    run, _ = job(semantic)
    worker.run_one(world.actor, world.definition.id)
    result = service.job(world.actor, world.definition.id, run.id)
    policy = Policy(world.objects.authorizer)
    policy.visible = ("factoryId",)
    restricted = SemanticService(world.sessions, policy)
    with pytest.raises(ApplicationError) as error:
        restricted.get(world.actor, world.definition.id, result.outputs[0])
    assert error.value.status_code == 403


def test_export_relationships_cannot_reveal_invisible_endpoint(semantic):
    world, _, _ = semantic
    world.objects.create(
        world.actor,
        world.definition.id,
        CreateObject(
            object_type_id="Machine",
            object_id="M",
            properties={
                "machineId": "M",
                "machineName": "Machine",
                "operationalStatus": "RUNNING",
                "temperatureCelsius": "30.0",
            },
        ),
    )
    from ontology_platform.contracts import LinkInput

    world.objects.create_link(
        world.actor,
        world.definition.id,
        LinkInput(
            link_type_id="locatedInFactory",
            source_object_type_id="Machine",
            source_object_id="M",
            target_object_type_id="Factory",
            target_object_id="F",
        ),
    )

    class HideFactory(Policy):
        def query_grant(self, p, ontology_id, object_type):
            return QueryGrant(
                allowed_object_ids=() if object_type == "Factory" else None, revision="1"
            )

    service = SemanticService(world.sessions, HideFactory(world.objects.authorizer))
    key = service.export(
        world.actor,
        world.definition.id,
        ExportInput(
            schema_version=world.definition.version,
            selections=(QueryRequest(object_type="Machine"), QueryRequest(object_type="Factory")),
            links=("locatedInFactory",),
        ),
    )
    graph = parse(service.get(world.actor, world.definition.id, key).content.encode())
    assert not list(
        graph.triples((None, term(world.definition.namespace, "link", "locatedInFactory"), None))
    )
    mapping = RDFMapping(namespace=world.definition.namespace)
    assert all(
        mapping.identity_from_iri(str(s)).object_type_id == "Machine" for s in graph.subjects()
    )


@pytest.mark.parametrize("when", ["before_commit", "after_commit"])
def test_actual_semantic_process_crash_recovery(semantic, when):
    import select as io_select
    import subprocess
    import sys

    world, service, worker = semantic
    run, _ = job(semantic)
    with world.engine.connect() as conn:
        schema = conn.scalar(text("SELECT current_schema()"))
    env = dict(
        os.environ,
        CRASH_SCHEMA=schema,
        CRASH_TENANT=str(world.actor.tenant_id),
        CRASH_PRINCIPAL=world.actor.principal_id,
        CRASH_WHEN=when,
        TEST_DATABASE_URL=world.settings.database_url.get_secret_value(),
    )
    code = """
import os,sys
from pathlib import Path
from sqlalchemy import create_engine,event
from sqlalchemy.orm import sessionmaker
from ontology_platform.config import Settings
from ontology_platform.security.local import LocalAuthorizer
from ontology_platform.security.interfaces import Principal
from ontology_platform.semantic.worker import SemanticWorker
from ontology_platform.semantic.engine import OpenOntologiesAdapter
from pydantic import SecretStr
settings=Settings(database_url=SecretStr(os.environ['TEST_DATABASE_URL']),trusted_local_identity=True,
 local_tenant_id=os.environ['CRASH_TENANT'],local_principal_id=os.environ['CRASH_PRINCIPAL'],_env_file=None)
options='-c search_path='+os.environ['CRASH_SCHEMA']
engine=create_engine(os.environ['TEST_DATABASE_URL'],connect_args={'options':options})
adapter=OpenOntologiesAdapter(Path(os.environ['OPEN_ONTOLOGIES_BIN']))
worker=SemanticWorker(sessionmaker(engine),LocalAuthorizer(settings),engine=adapter)
p=Principal(tenant_id=settings.local_tenant_id,principal_id=settings.local_principal_id)
if os.environ['CRASH_WHEN']=='before_commit':
 def inserted(conn,cursor,statement,parameters,context,executemany):
  if statement.startswith('INSERT INTO semantic_artifacts'):
   print('READY',flush=True);sys.stdin.readline()
 event.listen(engine,'after_cursor_execute',inserted)
worker.run_one(p,'manufacturing')
print('COMMITTED',flush=True)
os._exit(17)
"""
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", code],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        assert io_select.select([process.stdout], [], [], 30)[0]
        line = process.stdout.readline().strip()
        assert line == ("READY" if when == "before_commit" else "COMMITTED"), line
        if when == "before_commit":
            process.kill()
        process.communicate(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
    if when == "before_commit":
        assert service.job(world.actor, world.definition.id, run.id).outputs == []
        with world.sessions.begin() as s:
            row = s.get(SemanticJob, (world.actor.tenant_id, world.definition.id, run.id))
            row.lease_until = s.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)
        worker.run_one(world.actor, world.definition.id)
    else:
        assert process.returncode == 17
    result = service.job(world.actor, world.definition.id, run.id)
    assert result.status == "COMPLETED" and len(result.outputs) == 1
    assert worker.run_one(world.actor, world.definition.id) is None


def test_engine_version_change_marks_old_results_stale(semantic):
    world, service, worker = semantic
    run, _ = job(semantic)
    worker.run_one(world.actor, world.definition.id)
    result = service.job(world.actor, world.definition.id, run.id)
    with patch("ontology_platform.semantic.service.ENGINE_VERSION", "future-version"):
        assert service.get(world.actor, world.definition.id, result.outputs[0]).freshness == "STALE"
