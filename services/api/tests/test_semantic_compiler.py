"""Deterministic compiler and actual pinned engine interoperability."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from ontology_platform.errors import ApplicationError
from ontology_platform.semantic.compiler import compile_schema, literal, parse, serialize, term
from ontology_platform.semantic.engine import OpenOntologiesAdapter
from ontology_schema.models import OntologyDefinition, PropertyDefinition
from rdflib import OWL, RDF, SH, XSD, Graph, Literal, URIRef
from rdflib.compare import isomorphic

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def schema():
    return OntologyDefinition.model_validate_json(
        (ROOT / "ontologies/examples/manufacturing.json").read_text()
    )


def test_deterministic_schema_and_ordering(schema):
    first = compile_schema(schema)
    second = compile_schema(schema)
    assert first == second
    reordered = schema.model_copy(
        update={
            "object_types": tuple(reversed(schema.object_types)),
            "link_types": tuple(reversed(schema.link_types)),
        }
    )
    assert compile_schema(reordered) == first
    assert isomorphic(parse(first[0]), parse(second[0]))
    assert not any(str(node).startswith("_:") for triple in parse(first[1]) for node in triple)
    assert {d.code for d in first[2]} >= {"decimal_precision", "canonical_scope"}
    for typed in schema.object_types:
        assert (term(schema.namespace, "class", typed.id), RDF.type, OWL.Class) in parse(first[0])
    assert term(schema.namespace, "class", "Machine") != term(
        schema.namespace, "property", "Machine"
    )
    assert term(schema.namespace, "property", "a/b", "c") != term(
        schema.namespace, "property", "a", "b/c"
    )


@pytest.mark.parametrize(
    "kind,value,datatype",
    [
        ("string", "hello", XSD.string),
        ("integer", 10, XSD.integer),
        ("float", 1.5, XSD.double),
        ("boolean", True, XSD.boolean),
        ("date", "2026-01-01", XSD.date),
        ("timestamp", "2026-01-01T12:00:00+00:00", XSD.dateTime),
        ("uuid", str(uuid4()), XSD.string),
        ("decimal", "12.30", XSD.decimal),
    ],
)
def test_scalar_literals(kind, value, datatype):
    prop = PropertyDefinition(
        id="p",
        name="P",
        data_type=kind,
        **({"precision": 10, "scale": 2} if kind == "decimal" else {}),
    )
    assert literal(prop, value).datatype == datatype


def test_unsupported_and_nullable_diagnostics(schema):
    typed = schema.object_types[0]
    props = (
        PropertyDefinition(id="json", name="JSON", data_type="json"),
        PropertyDefinition(id="array", name="Array", data_type="string", array=True),
        PropertyDefinition(
            id="null", name="Nullable", data_type="string", nullable=True, required=True
        ),
    )
    schema = schema.model_copy(
        update={
            "object_types": (typed.model_copy(update={"properties": typed.properties + props}),)
        }
    )
    owl, shapes, diagnostics = compile_schema(schema)
    assert sum(d.code == "unsupported_property" for d in diagnostics) == 2
    assert any(d.code == "null_absence" for d in diagnostics)
    assert (
        term(schema.namespace, "property-shape", typed.id, "null"),
        SH.minCount,
        Literal(1),
    ) not in parse(shapes)
    with pytest.raises(ApplicationError, match="unsupported"):
        literal(props[0], {"a": 1})


def test_graph_and_artifact_limits():
    with pytest.raises(ApplicationError) as error:
        parse(b"a" * (4194304 + 1))
    assert error.value.code == "semantic_resource_limit"
    with pytest.raises(ApplicationError) as error:
        parse(b"not turtle")
    assert error.value.code == "invalid_rdf"
    graph = Graph()
    for i in range(20001):
        graph.add((URIRef(f"urn:{i}"), RDF.type, URIRef("urn:Class")))
    with pytest.raises(ApplicationError):
        serialize(graph)


@pytest.mark.semantic
def test_engine_full_derivations_and_change(fixtures):
    binary = os.environ.get("OPEN_ONTOLOGIES_BIN")
    if not binary:
        pytest.skip("NOT RUN: pinned engine required")
    engine = OpenOntologiesAdapter(Path(binary))
    for profile in ("owl-rl", "owl-rl-ext"):
        result = engine.derive(
            (fixtures / "manufacturing.ttl").read_bytes(),
            (fixtures / "manufacturing-data.ttl").read_bytes(),
            profile,
        )
        proof = result.files["certificate/derivations.tsv"]
        triples = [" ".join(line.split("\t")[1:4]) + " ." for line in proof.splitlines()]
        derived = Graph().parse(data="\n".join(triples), format="nt")
        critical = {
            str(s).rsplit("#", 1)[-1]
            for s in derived.subjects(
                RDF.type, URIRef("https://example.org/ontologies/manufacturing#CriticalMachine")
            )
        }
        assert critical == ({"MCH-005", "MCH-011", "MCH-017"} if profile == "owl-rl-ext" else set())
        assert len(derived) == result.records[2]["result"]["inferred_count"]
    changed = engine.analyze_change(b"<urn:s> a <urn:A> .", b"<urn:s> a <urn:B> .")
    assert changed.records[-1]["result"]["added"] == 1
    assert changed.records[-1]["result"]["removed"] == 1
    with pytest.raises(ApplicationError):
        engine.derive(b"", b"", "bogus")
