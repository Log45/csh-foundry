import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from ontology_platform.errors import ApplicationError
from ontology_platform.semantic.engine import OpenOntologiesAdapter
from rdflib import XSD, Graph, Literal, Namespace

NS = Namespace("https://example.org/ontologies/manufacturing#")


@pytest.fixture
def engine():
    binary = os.environ.get("OPEN_ONTOLOGIES_BIN")
    if not binary:
        pytest.skip("NOT RUN: set OPEN_ONTOLOGIES_BIN to checksum-verified v2.1.0 executable")
    return OpenOntologiesAdapter(Path(binary))


@pytest.mark.semantic
def test_engine_parse_and_shacl(engine, fixtures):
    parsed = engine.validate_ontology((fixtures / "manufacturing.ttl").read_bytes())
    assert parsed.records[0]["result"]["triples_loaded"] > 0
    shapes = (fixtures / "manufacturing-shapes.ttl").read_bytes()
    validated = engine.validate_shapes(shapes, (fixtures / "manufacturing-data.ttl").read_bytes())
    assert validated.records[-1]["result"]["conforms"] is True
    graph = Graph().parse(fixtures / "manufacturing-data.ttl")
    graph.set((NS["MCH-001"], NS.operationalStatus, Literal("BROKEN", datatype=XSD.string)))
    invalid = engine.validate_shapes(shapes, graph.serialize(format="turtle").encode())
    assert invalid.records[-1]["result"]["conforms"] is False
    assert invalid.records[-1]["result"]["violations"]
    with pytest.raises(ApplicationError, match="operation failed"):
        engine.validate_ontology(b"this is not Turtle")


@pytest.mark.semantic
@pytest.mark.parametrize("profile", ["owl-rl", "owl-rl-ext"])
def test_critical_inference_profiles(engine, fixtures, profile):
    result = engine.reason(
        (fixtures / "manufacturing.ttl").read_bytes(),
        (fixtures / "manufacturing-data.ttl").read_bytes(),
        profile=profile,
    )
    rows = result.records[-1]["result"]["results"]
    critical = {
        row["s"].removeprefix("<").removesuffix(">")
        for row in rows
        if row["type"].endswith("#CriticalMachine>") or row["type"] == str(NS.CriticalMachine)
    }
    # The base profile lacks hasValue/intersection rules in this pinned build.
    if profile == "owl-rl":
        assert critical == set()
    else:
        assert critical == {str(NS[key]) for key in ["MCH-005", "MCH-011", "MCH-017"]}
        assert str(NS["MCH-001"]) not in critical


def test_engine_unavailable_and_timeout():
    engine = OpenOntologiesAdapter(Path("/nonexistent/open-ontologies"))
    with pytest.raises(ApplicationError) as error:
        engine.validate_ontology(b"")
    assert error.value.code == "semantic_unavailable"
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("engine", 1)):
        with pytest.raises(ApplicationError) as error:
            engine.validate_ontology(b"")
        assert error.value.code == "semantic_timeout"
