"""Phase 6 secure parsing, mapping and real PostgreSQL authoring lifecycle."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from ontology_platform.db.models import OntologyImport, Version, VocabularyBinding
from ontology_platform.errors import ApplicationError
from ontology_platform.interoperability.contracts import (
    ClassMapping,
    ImportInput,
    LinkMapping,
    MappingInput,
)
from ontology_platform.interoperability.mapping import target
from ontology_platform.interoperability.parser import parse_import, parse_local
from ontology_platform.interoperability.service import InteroperabilityService
from ontology_platform.main import create_app
from ontology_platform.security.interfaces import Principal
from ontology_platform.semantic.compiler import digest
from pydantic import ValidationError
from rdflib import OWL, RDF, Graph, URIRef
from rdflib.compare import isomorphic
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_phase1 import active, error, factory, make_world, migrate
from test_phase1 import database as pg_database

ROOT = Path(__file__).resolve().parents[3]
NS = "https://example.org/ontologies/manufacturing#"
SOURCE = (ROOT / "fixtures/manufacturing.ttl").read_text()


@pytest.fixture
def database():
    yield from pg_database.__wrapped__()


@pytest.fixture
def authoring(database):
    world = make_world(database)
    active(world)
    svc = InteroperabilityService(world.sessions, world.registry.authorizer)
    return world, svc


def request(world, **changes):
    schema = world.definition
    mappings = MappingInput(
        classes=tuple(
            ClassMapping(
                iri=NS + typed.id,
                definition=typed,
                property_iris={p.id: NS + p.id for p in typed.properties},
            )
            for typed in schema.object_types
        ),
        links=tuple(LinkMapping(iri=NS + link.id, definition=link) for link in schema.link_types),
    )
    data = dict(format="turtle", content=SOURCE, version="2.0.0", mappings=mappings)
    return ImportInput(**(data | changes))


def test_parser_formats_and_original_blank_nodes():
    turtle = parse_import(SOURCE, "turtle")
    xml = (ROOT / "integrations/protege/fixtures/manufacturing-rdfxml.owl").read_text()
    parsed = parse_import(xml, "rdfxml")
    # OWLAPI adds the documented xsd:date declaration only.
    from rdflib import XSD

    parsed.remove((XSD.date, RDF.type, RDFS_DATATYPE))
    # OWLAPI also reverses a symmetric inverse axiom and emits RDF 1.1 simple strings.
    # Record raw inequality and normalize those two serialization differences in memory only.
    assert not isomorphic(turtle, parsed)

    def normalized(graph):
        output = Graph()
        from rdflib import Literal

        for s, p, o in graph:
            if isinstance(o, Literal) and o.datatype is None and not o.language:
                o = Literal(str(o), datatype=XSD.string)
            if p == OWL.inverseOf and str(s) > str(o):
                s, o = o, s
            output.add((s, p, o))
        return output

    assert isomorphic(normalized(turtle), normalized(parsed))
    assert parse_local(SOURCE, "turtle") == parse_local(SOURCE, "turtle")
    assert len(turtle) == 115


RDFS_DATATYPE = URIRef("http://www.w3.org/2000/01/rdf-schema#Datatype")


@pytest.mark.parametrize(
    "content,format",
    [
        ("not turtle", "turtle"),
        ('<!DOCTYPE rdf:RDF [<!ENTITY x SYSTEM "file:///etc/passwd">]><rdf:RDF/>', "rdfxml"),
        ('<!DOCTYPE rdf:RDF SYSTEM "http://127.0.0.1:9/evil"><rdf:RDF/>', "rdfxml"),
        ('<Ontology xmlns="http://www.w3.org/2002/07/owl#"/>', "rdfxml"),
        ("<relative> <urn:p> <urn:o> .", "turtle"),
    ],
)
def test_invalid_and_unsafe_inputs(content, format):
    with error("invalid_ontology"):
        parse_import(content, format)


@pytest.mark.parametrize(
    "content",
    [
        "#" + "a" * 262144,
        "<urn:s> <urn:p> <urn:o> .\n" * 4001,
        "\n".join(f"_:b{i} <urn:p> <urn:o> ." for i in range(513)),
        "\n".join(f"@prefix n{i}: <urn:n{i}:> ." for i in range(65)),
        '<urn:s> <urn:p> "' + "x" * 8193 + '" .',
    ],
)
def test_parser_resource_limits(content):
    with error("import_resource_limit"):
        parse_import(content, "turtle")


def test_actual_parser_deadline_and_format_selection():
    with error("import_timeout"):
        parse_import(SOURCE, "turtle", timeout=0.000001)
    with error("unsupported_format"):
        parse_import(SOURCE, "owlxml")
    with pytest.raises(ValidationError):
        ImportInput(format="turtle", content=SOURCE, version="2.0.0", tenant_id=str(uuid4()))
    with pytest.raises(ValidationError):
        ImportInput(format="turtle", content=SOURCE, version="2.0.0", mode="ACTIVATE")


def test_import_declarations_never_resolve_network_or_files():
    source = (
        SOURCE
        + "\n<urn:test> <http://www.w3.org/2002/07/owl#imports> <file:///nonexistent-secret> ."
    )
    g = parse_import(source, "turtle")
    assert (URIRef("urn:test"), OWL.imports, URIRef("file:///nonexistent-secret")) in g


@pytest.mark.integration
def test_preview_preserves_original_diagnostics_inventory_and_no_draft(authoring):
    w, svc = authoring
    result = svc.import_ontology(w.actor, w.definition.id, request(w))
    assert result.status == "PREVIEWED", result.diagnostics
    assert result.conflict_count == 0
    assert result.supported_construct_count > 0
    assert result.unsupported_construct_count > 0
    assert result.ontology_iri == "https://example.org/ontologies/manufacturing"
    assert result.version_iri.endswith("/1.0.0")
    assert result.proposed_definition.action_types == ()
    assert svc.original(w.actor, w.definition.id, result.id) == SOURCE
    assert svc.get(w.actor, w.definition.id, result.id) == result
    diagnostics = svc.diagnostics(w.actor, w.definition.id, result.id)
    assert any(d.construct_path == str(OWL.equivalentClass) for d in diagnostics)
    assert any(d.construct_path == str(OWL.hasKey) for d in diagnostics)
    vocab = svc.vocabulary(w.actor, w.definition.id, result.id)
    assert any(t.iri == NS + "CriticalMachine" for t in vocab)
    with w.sessions() as s:
        assert s.scalar(select(func.count()).select_from(Version)) == 1
        assert s.scalar(select(func.count()).select_from(VocabularyBinding)) == 0


@pytest.mark.integration
@pytest.mark.parametrize("format", ["turtle", "rdfxml"])
def test_draft_creation_preserves_active_and_explicit_lifecycle(authoring, format):
    w, svc = authoring
    w.objects.create(w.actor, w.definition.id, factory())
    original = (
        SOURCE
        if format == "turtle"
        else (ROOT / "integrations/protege/fixtures/manufacturing-rdfxml.owl").read_text()
    )
    result = svc.import_ontology(
        w.actor, w.definition.id, request(w, mode="CREATE_DRAFT", format=format, content=original)
    )
    assert result.status == "DRAFT_CREATED", result.diagnostics
    draft = w.registry.version(w.actor, w.definition.id, "2.0.0")
    assert draft.status == "DRAFT"
    assert w.registry.get(w.actor, w.definition.id).active_version == "1.0.0"
    assert w.objects.get(w.actor, w.definition.id, "Factory", "FAC-001").version == 1
    assert svc.original(w.actor, w.definition.id, result.id) == original
    with error("schema_unpublished"):
        w.registry.activate(w.actor, w.definition.id, "2.0.0")
    w.registry.publish(w.actor, w.definition.id, "2.0.0")
    assert w.registry.get(w.actor, w.definition.id).active_version == "1.0.0"
    w.registry.activate(w.actor, w.definition.id, "2.0.0")
    assert w.objects.get(w.actor, w.definition.id, "Factory", "FAC-001").version == 2
    with w.sessions() as s:
        assert s.scalar(select(func.count()).select_from(VocabularyBinding)) == 20


@pytest.mark.integration
def test_export_determinism_and_supported_roundtrip_after_import(authoring):
    w, svc = authoring
    imported = svc.import_ontology(w.actor, w.definition.id, request(w, mode="CREATE_DRAFT"))
    w.registry.publish(w.actor, w.definition.id, imported.draft_version)
    exported = svc.export(w.actor, w.definition.id, "2.0.0")
    assert exported == svc.export(w.actor, w.definition.id, "2.0.0")
    assert NS + "Factory" in exported.content
    assert exported.output_hash == digest(exported.content.encode())
    roundtrip = svc.import_ontology(
        w.actor,
        w.definition.id,
        request(
            w,
            version="3.0.0",
            mode="CREATE_DRAFT",
            content=exported.content,
            mappings=exported.mappings,
        ),
    )
    assert roundtrip.status == "DRAFT_CREATED", roundtrip.diagnostics
    assert roundtrip.proposed_definition.object_types == imported.proposed_definition.object_types
    assert roundtrip.proposed_definition.link_types == imported.proposed_definition.link_types
    # Unsupported restrictions remain exactly available from the original source archive.
    assert "owl:equivalentClass" in svc.original(w.actor, w.definition.id, imported.id)


@pytest.mark.integration
@pytest.mark.parametrize(
    "kind", ["range", "domain", "duplicate_target", "same_iri", "punning", "multiple_ontology"]
)
def test_mapping_conflicts_block_drafts(authoring, kind):
    w, svc = authoring
    body = request(w, mode="CREATE_DRAFT")
    data = body.model_dump(mode="json")
    if kind == "range":
        data["content"] = SOURCE.replace("rdfs:range xsd:decimal", "rdfs:range xsd:string")
    elif kind == "domain":
        data["content"] += "\n:factoryId rdfs:domain :Machine ."
    elif kind == "duplicate_target":
        data["mappings"]["classes"].append(data["mappings"]["classes"][0])
    elif kind == "same_iri":
        data["mappings"]["classes"][1]["iri"] = data["mappings"]["classes"][0]["iri"]
    elif kind == "punning":
        data["content"] += "\n:Factory a owl:DatatypeProperty ."
    else:
        data["content"] += "\n<urn:second> a owl:Ontology ."
    result = svc.import_ontology(w.actor, w.definition.id, ImportInput.model_validate(data))
    assert result.status == "CONFLICT"
    assert result.conflict_count > 0
    assert result.draft_version is None
    with w.sessions() as s:
        assert s.scalar(select(func.count()).select_from(Version)) == 1
        assert s.scalar(select(func.count()).select_from(VocabularyBinding)) == 0


@pytest.mark.integration
def test_explicit_definition_conflict_choices_and_migration_guard(authoring):
    w, svc = authoring
    data = request(w, mode="CREATE_DRAFT").model_dump(mode="json")
    data["mappings"]["classes"][0]["definition"]["properties"] = data["mappings"]["classes"][0][
        "definition"
    ]["properties"][:1]
    data["mappings"]["classes"][0]["property_iris"] = {"factoryId": NS + "factoryId"}
    conflicted = svc.import_ontology(w.actor, w.definition.id, ImportInput.model_validate(data))
    assert conflicted.status == "CONFLICT"
    path = target("class", "Factory")
    data["conflict_choices"] = {path: "replace"}
    result = svc.import_ontology(w.actor, w.definition.id, ImportInput.model_validate(data))
    assert result.status == "DRAFT_CREATED"
    assert result.compatibility.classification == "breaking"
    assert result.changes == ["replace " + path]
    with error("migration_required"):
        w.registry.publish(w.actor, w.definition.id, "2.0.0")


@pytest.mark.integration
def test_namespace_expansion_and_no_unrequested_inference(authoring):
    w, svc = authoring
    data = request(w).model_dump(mode="json")
    data["namespace_mappings"] = {"m": NS}
    for cls in data["mappings"]["classes"]:
        cls["iri"] = cls["iri"].replace(NS, "m:")
        cls["property_iris"] = {k: v.replace(NS, "m:") for k, v in cls["property_iris"].items()}
    result = svc.import_ontology(w.actor, w.definition.id, ImportInput.model_validate(data))
    assert result.status == "PREVIEWED"
    assert {o.id for o in result.proposed_definition.object_types} == {
        "Factory",
        "Machine",
        "Employee",
        "MaintenanceTask",
    }
    assert result.proposed_definition.action_types == ()
    assert result.proposed_definition == w.definition.model_copy(update={"version": "2.0.0"})


@pytest.mark.integration
def test_persisted_iri_alias_conflicts(authoring):
    w, svc = authoring
    svc.import_ontology(w.actor, w.definition.id, request(w, mode="CREATE_DRAFT"))
    data = request(w, version="3.0.0", mode="CREATE_DRAFT").model_dump(mode="json")
    data["content"] = SOURCE.replace(":Factory", ":OtherFactory")
    data["mappings"]["classes"][0]["iri"] = NS + "OtherFactory"
    result = svc.import_ontology(w.actor, w.definition.id, ImportInput.model_validate(data))
    assert result.status == "CONFLICT"
    assert any(d.code == "iri_conflict" for d in result.diagnostics)


@pytest.mark.integration
def test_stale_base_and_mutable_base_hash(authoring):
    w, svc = authoring
    with error("stale_import_base"):
        svc.import_ontology(w.actor, w.definition.id, request(w, expected_base_hash="0" * 64))
    draft = w.registry.draft(
        w.actor, w.definition.id, w.definition.model_copy(update={"version": "1.1.0"})
    )
    with error("base_hash_required"):
        svc.import_ontology(
            w.actor, w.definition.id, request(w, base_version="1.1.0", mode="CREATE_DRAFT")
        )
    result = svc.import_ontology(
        w.actor,
        w.definition.id,
        request(w, base_version="1.1.0", expected_base_hash=draft.content_hash),
    )
    assert result.base_hash == draft.content_hash


@pytest.mark.integration
def test_atomic_import_rollback_after_draft_and_immutable_provenance(authoring):
    w, svc = authoring
    # Serialization runs after RegistryService.draft has flushed its new version/type rows.
    with patch(
        "ontology_platform.interoperability.service.serialize_graph",
        side_effect=RuntimeError("injected"),
    ):
        with pytest.raises(RuntimeError):
            svc.import_ontology(w.actor, w.definition.id, request(w, mode="CREATE_DRAFT"))
    with w.sessions() as s:
        assert s.scalar(select(func.count()).select_from(Version)) == 1
        assert s.scalar(select(func.count()).select_from(OntologyImport)) == 0
    result = svc.import_ontology(w.actor, w.definition.id, request(w, mode="CREATE_DRAFT"))
    for table in ("ontology_imports", "ontology_vocabulary_bindings"):
        with pytest.raises(DBAPIError), w.engine.begin() as connection:
            connection.execute(text(f"DELETE FROM {table}"))
    assert svc.get(w.actor, w.definition.id, result.id).status == "DRAFT_CREATED"


@pytest.mark.integration
def test_import_concurrency_same_draft_commits_once(authoring):
    w, svc = authoring

    def run():
        try:
            return svc.import_ontology(
                w.actor, w.definition.id, request(w, mode="CREATE_DRAFT")
            ).status
        except ApplicationError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert sorted(results) == ["DRAFT_CREATED", "version_immutable"]
    with w.sessions() as s:
        assert s.scalar(select(func.count()).select_from(OntologyImport)) == 1


@pytest.mark.integration
def test_principal_tenant_and_revoked_permissions(authoring):
    w, svc = authoring
    result = svc.import_ontology(w.actor, w.definition.id, request(w))
    other = Principal(tenant_id=w.actor.tenant_id, principal_id="another")

    class OwnTenant:
        def require(self, *args):
            pass

    private = InteroperabilityService(w.sessions, OwnTenant())
    with error("not_found"):
        private.original(other, w.definition.id, result.id)
    foreign = Principal(tenant_id=uuid4(), principal_id=w.actor.principal_id)
    with error("tenant_unavailable"):
        private.get(foreign, w.definition.id, result.id)

    class Deny:
        def require(self, p, operation, resource):
            raise ApplicationError("forbidden", "revoked", 403)

    denied = InteroperabilityService(w.sessions, Deny())
    with error("forbidden"):
        denied.original(w.actor, w.definition.id, result.id)
    with patch("ontology_platform.interoperability.service.parse_import") as parser:
        with error("forbidden"):
            denied.import_ontology(w.actor, w.definition.id, request(w))
        parser.assert_not_called()


@pytest.mark.integration
def test_http_import_export_contract_and_body_limit(authoring):
    w, svc = authoring
    app = create_app(w.settings)
    app.state.sessions = w.sessions
    with TestClient(app) as client:
        base = f"/api/v1/ontologies/{w.definition.id}/interchange"
        response = client.post(
            base + "/imports", json=request(w, mode="CREATE_DRAFT").model_dump(mode="json")
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == "DRAFT_CREATED"
        path = base + "/imports/" + result["id"]
        assert client.get(path).json() == result
        assert client.get(path + "/original").text == SOURCE
        assert client.get(path + "/diagnostics?limit=1").status_code == 200
        assert len(client.get(path + "/vocabulary?limit=2").json()) == 2
        assert client.get(path + "/vocabulary?limit=101").status_code == 422
        assert client.get(base + "/exports/1.0.0").status_code == 200
        assert client.get(base + "/exports/2.0.0").status_code == 409
        assert client.post(base + "/imports", content=b" " * 65537).status_code == 413
    app.state.engine.dispose()


@pytest.mark.integration
def test_migration_downgrade_preserves_operational_registry(authoring):
    w, svc = authoring
    w.objects.create(w.actor, w.definition.id, factory())
    svc.import_ontology(w.actor, w.definition.id, request(w, mode="CREATE_DRAFT"))
    migrate(w.engine, "0011_semantic_history", downgrade=True)
    assert w.objects.get(w.actor, w.definition.id, "Factory", "FAC-001").version == 1
    assert w.registry.version(w.actor, w.definition.id, "2.0.0").status == "DRAFT"
    migrate(w.engine)
    with w.sessions() as s:
        assert s.scalar(select(func.count()).select_from(OntologyImport)) == 0


@pytest.mark.integration
def test_keep_choice_does_not_register_rejected_vocabulary(authoring):
    w, svc = authoring
    data = request(w, mode="CREATE_DRAFT").model_dump(mode="json")
    data["mappings"]["classes"][0]["definition"]["name"] = "Changed label"
    data["conflict_choices"] = {target("class", "Factory"): "keep"}
    result = svc.import_ontology(w.actor, w.definition.id, ImportInput.model_validate(data))
    assert result.status == "DRAFT_CREATED"
    assert result.proposed_definition.object_types[0] == w.definition.object_types[0]
    with w.sessions() as s:
        assert (
            s.get(
                VocabularyBinding,
                (w.actor.tenant_id, w.definition.id, digest((NS + "Factory").encode())),
            )
            is None
        )


@pytest.mark.integration
def test_diagnostic_truncation_and_unmapped_inspection(authoring):
    w, svc = authoring
    source = SOURCE + "\n" + "\n".join(f'<urn:s> <urn:p{i}> "value" .' for i in range(120))
    result = svc.import_ontology(
        w.actor, w.definition.id, request(w, content=source, mappings=MappingInput())
    )
    assert result.status == "CONFLICT"
    assert result.diagnostics_truncated and len(result.diagnostics) == 100
    assert result.diagnostic_count > 120
    second = svc.diagnostics(w.actor, w.definition.id, result.id, 100, 100)
    assert len(second) == result.diagnostic_count - 100
    assert svc.original(w.actor, w.definition.id, result.id) == source


@pytest.mark.integration
def test_import_from_unactivated_draft_preserves_registry_as_authority(database):
    w = make_world(database)
    blank = w.definition.model_copy(update={"object_types": (), "link_types": ()})
    created = w.registry.create(w.actor, blank)
    svc = InteroperabilityService(w.sessions, w.registry.authorizer)
    result = svc.import_ontology(
        w.actor,
        w.definition.id,
        request(
            w,
            mode="CREATE_DRAFT",
            base_version="1.0.0",
            expected_base_hash=created.content_hash,
        ),
    )
    assert result.status == "DRAFT_CREATED"
    assert result.proposed_definition.object_types == w.definition.object_types
    assert w.registry.get(w.actor, w.definition.id).active_version is None
    w.registry.publish(w.actor, w.definition.id, "2.0.0")
    w.registry.activate(w.actor, w.definition.id, "2.0.0")
    assert w.objects.create(w.actor, w.definition.id, factory()).version == 1


@pytest.mark.integration
def test_import_draft_cannot_retroactively_change_published_export(authoring):
    w, svc = authoring
    before = svc.export(w.actor, w.definition.id, "1.0.0")
    svc.import_ontology(w.actor, w.definition.id, request(w, mode="CREATE_DRAFT"))
    assert svc.export(w.actor, w.definition.id, "1.0.0") == before
    draft = w.registry.version(w.actor, w.definition.id, "2.0.0").definition
    changed = draft.model_copy(update={"name": "Reviewed changes"})
    w.registry.draft(w.actor, w.definition.id, changed, replace=True)
    w.registry.publish(w.actor, w.definition.id, "2.0.0")
    exported = svc.export(w.actor, w.definition.id, "2.0.0")
    assert any(d.code == "import_mapping_stale" for d in exported.diagnostics)
    assert exported.mappings.classes[0].iri != NS + "Factory"


def test_multiline_annotation_and_explicit_document_base():
    source = '@base <https://example.org/base/> . <Class> <urn:annotation> """one\ntwo""" .'
    g = parse_import(source, "turtle")
    assert str(next(g.objects())) == "one\ntwo"
    assert str(next(g.subjects())) == "https://example.org/base/Class"


@pytest.mark.integration
def test_multiline_source_archive_inventory_and_export(authoring):
    w, svc = authoring
    source = SOURCE + '\n:Factory <urn:annotation> """one\ntwo""" .'
    result = svc.import_ontology(w.actor, w.definition.id, request(w, content=source))
    assert result.status == "PREVIEWED"
    assert svc.original(w.actor, w.definition.id, result.id) == source
    assert svc.vocabulary(w.actor, w.definition.id, result.id)
    changed = w.definition.model_dump()
    changed["version"] = "1.1.0"
    changed["object_types"][0]["name"] = "First line\nSecond line"
    from ontology_schema.models import OntologyDefinition

    w.registry.draft(w.actor, w.definition.id, OntologyDefinition.model_validate(changed))
    w.registry.publish(w.actor, w.definition.id, "1.1.0")
    exported = svc.export(w.actor, w.definition.id, "1.1.0")
    assert parse_import(exported.content, "turtle")
    from ontology_platform.semantic.compiler import term

    g = Graph().parse(data=exported.content, format="turtle")
    for link in w.definition.link_types:
        assert (
            term(w.definition.namespace, "inverse-link", link.id),
            RDF.type,
            OWL.ObjectProperty,
        ) in g
