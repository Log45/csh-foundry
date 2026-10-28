from pathlib import Path

import polars as pl
import pytest
from pyshacl import validate
from rdflib import RDF, SH, XSD, Graph, Literal, Namespace

NS = Namespace("https://example.org/ontologies/manufacturing#")
TABLES = [
    ("factories.csv", "Factory", "factoryId", 6),
    ("machines.csv", "Machine", "machineId", 20),
    ("employees.csv", "Employee", "employeeId", 12),
    ("maintenance_tasks.csv", "MaintenanceTask", "taskId", 25),
]


def test_turtle_parse(fixtures: Path):
    for filename in ("manufacturing.ttl", "manufacturing-shapes.ttl", "manufacturing-data.ttl"):
        graph = Graph().parse(fixtures / filename, format="turtle")
        assert len(graph) > 0
        print(filename, len(graph), "triples")


def test_csv_rdf_consistency(fixtures: Path):
    data = Graph().parse(fixtures / "manufacturing-data.ttl")
    frames = {}
    for filename, cls, key, count in TABLES:
        frame = pl.read_csv(fixtures / filename, infer_schema=False)
        frames[cls] = frame
        assert frame.height == count
        assert frame[key].null_count() == 0
        assert frame[key].n_unique() == count
        assert all(frame[key].to_list())
        subjects = set(data.subjects(RDF.type, NS[cls]))
        assert len(subjects) == count
        assert {str(data.value(subject, NS[key])) for subject in subjects} == set(frame[key])
    for row in frames["Machine"].iter_rows(named=True):
        assert row["factoryId"] in frames["Factory"]["factoryId"]
        assert list(data.objects(NS[row["machineId"]], NS.locatedInFactory)) == [
            NS[row["factoryId"]]
        ]
    for row in frames["MaintenanceTask"].iter_rows(named=True):
        for column, target, predicate in [
            ("machineId", "Machine", "taskForMachine"),
            ("assignedEmployeeId", "Employee", "assignedEmployee"),
        ]:
            target_key = "machineId" if target == "Machine" else "employeeId"
            assert row[column] in frames[target][target_key]
            assert list(data.objects(NS[row["taskId"]], NS[predicate])) == [NS[row[column]]]


def rdf11_shapes(fixtures: Path) -> Graph:
    # RDF 1.1 simple literals denote xsd:string. RDFLib retains different term
    # identities; normalize only this representation in a disposable shapes graph.
    graph = Graph().parse(fixtures / "manufacturing-shapes.ttl")
    for subject, predicate, value in list(graph):
        if isinstance(value, Literal) and value.datatype is None and value.language is None:
            graph.remove((subject, predicate, value))
            graph.add((subject, predicate, Literal(str(value), datatype=XSD.string)))
    return graph


class RawStringTermMismatch(Exception):
    pass


@pytest.mark.xfail(
    strict=True,
    raises=RawStringTermMismatch,
    reason=("Raw pySHACL/RDFLib simple/xsd:string mismatch; see semantic-compatibility.md"),
)
def test_raw_pyshacl_compatibility(fixtures: Path):
    conforms, report, _ = validate(
        str(fixtures / "manufacturing-data.ttl"),
        shacl_graph=str(fixtures / "manufacturing-shapes.ttl"),
    )
    components = list(report.objects(None, SH.sourceConstraintComponent))
    if not conforms and len(components) == 45 and set(components) == {SH.InConstraintComponent}:
        raise RawStringTermMismatch("45 simple-literal/xsd:string sh:in violations")
    assert conforms


def test_shacl_baseline_rdf11_normalized_shapes(fixtures: Path):
    conforms, _, report = validate(
        str(fixtures / "manufacturing-data.ttl"),
        shacl_graph=rdf11_shapes(fixtures),
        inference="none",
    )
    assert conforms, report


# Each mutation is isolated in memory; the canonical fixtures are never rewritten.
@pytest.mark.parametrize(
    "mutation,component",
    [
        ("missing_id", "MinCountConstraintComponent"),
        ("second_id", "MaxCountConstraintComponent"),
        ("status", "InConstraintComponent"),
        ("temperature_string", "DatatypeConstraintComponent"),
        ("temperature_low", "MinInclusiveConstraintComponent"),
        ("missing_factory", "MinCountConstraintComponent"),
        ("wrong_factory", "ClassConstraintComponent"),
        ("date", "DatatypeConstraintComponent"),
        ("second_employee", "MaxCountConstraintComponent"),
    ],
)
def test_negative_shacl(fixtures: Path, mutation: str, component: str):
    graph = Graph().parse(fixtures / "manufacturing-data.ttl")
    if mutation == "missing_id":
        graph.remove((NS["MCH-001"], NS.machineId, None))
    elif mutation == "second_id":
        graph.add((NS["MCH-001"], NS.machineId, Literal("other", datatype=XSD.string)))
    elif mutation == "status":
        graph.set((NS["MCH-001"], NS.operationalStatus, Literal("BROKEN", datatype=XSD.string)))
    elif mutation.startswith("temperature"):
        value = (
            Literal("bad") if mutation.endswith("string") else Literal("-274", datatype=XSD.decimal)
        )
        graph.set((NS["MCH-001"], NS.temperatureCelsius, value))
    elif mutation == "missing_factory":
        graph.remove((NS["MCH-001"], NS.locatedInFactory, None))
    elif mutation == "wrong_factory":
        graph.set((NS["MCH-001"], NS.locatedInFactory, NS["EMP-001"]))
    elif mutation == "date":
        graph.set((NS["TASK-001"], NS.scheduledDate, Literal("2026-11-04")))
    elif mutation == "second_employee":
        graph.add((NS["TASK-001"], NS.assignedEmployee, NS["EMP-001"]))
    conforms, report, text = validate(graph, shacl_graph=rdf11_shapes(fixtures), inference="none")
    assert not conforms, text
    assert SH[component] in set(report.objects(None, SH.sourceConstraintComponent))
