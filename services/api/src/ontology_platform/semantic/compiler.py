"""Deterministic RDF projection; canonical JSON stays authoritative."""

import base64
import hashlib
import json
from urllib.parse import quote

from ontology_schema.models import OntologyDefinition, PropertyDefinition
from pydantic import JsonValue
from rdflib import OWL, RDF, RDFS, SH, XSD, Graph, Literal, URIRef
from rdflib.term import Node

from ontology_platform.errors import ApplicationError
from ontology_platform.semantic.contracts import MAX_BYTES, MAX_TRIPLES, Diagnostic

DATATYPES = {
    "string": XSD.string,
    "integer": XSD.integer,
    "float": XSD.double,
    "boolean": XSD.boolean,
    "date": XSD.date,
    "timestamp": XSD.dateTime,
    "uuid": XSD.string,
    "decimal": XSD.decimal,
}


def term(namespace: str, kind: str, *ids: str) -> URIRef:
    # Category-separated, reversible tuples prevent type/property/link identity collisions.
    payload = json.dumps(ids, ensure_ascii=False, separators=(",", ":")).encode()
    return URIRef(
        namespace
        + "schema/v1/"
        + kind
        + "/"
        + base64.urlsafe_b64encode(payload).decode().rstrip("=")
    )


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def serialize(graph: Graph) -> bytes:
    if len(graph) > MAX_TRIPLES:
        raise ApplicationError("semantic_resource_limit", "Graph exceeds 20000 triples", 422)
    # Generated graphs use named skolem nodes exclusively; imported graphs are retained as-is.
    data = ("\n".join(sorted(f"{s.n3()} {p.n3()} {o.n3()} ." for s, p, o in graph)) + "\n").encode()
    if len(data) > MAX_BYTES:
        raise ApplicationError("semantic_resource_limit", "Artifact exceeds 4 MiB", 422)
    return data


def parse(content: bytes, code: str = "invalid_rdf") -> Graph:
    if len(content) > MAX_BYTES:
        raise ApplicationError("semantic_resource_limit", "Artifact exceeds 4 MiB", 422)
    try:
        graph = Graph().parse(data=content, format="turtle")
    except Exception as exc:
        raise ApplicationError(code, "Invalid semantic input", 422) from exc
    if len(graph) > MAX_TRIPLES:
        raise ApplicationError("semantic_resource_limit", "Graph exceeds 20000 triples", 422)
    return graph


def literal(prop: PropertyDefinition, value: JsonValue) -> Literal:
    datatype = DATATYPES.get(prop.data_type)
    if datatype is None or prop.array:
        raise ApplicationError("unsupported_construct", "JSON/array projection is unsupported", 422)
    # Explicit RDF 1.1 normalization: all strings, including enums, use xsd:string.
    return Literal(value, datatype=datatype, normalize=True)


def compile_schema(schema: OntologyDefinition) -> tuple[bytes, bytes, list[Diagnostic]]:
    owl, shapes = Graph(), Graph()
    diagnostics: list[Diagnostic] = []
    ns = schema.namespace

    def diag(code: str, construct: str, message: str) -> None:
        diagnostics.append(Diagnostic(code=code, construct=construct, message=message))

    ontology = term(ns, "ontology", schema.id)
    owl.add((ontology, RDF.type, OWL.Ontology))
    owl.add(
        (
            ontology,
            OWL.versionIRI,
            URIRef(str(ontology) + "/version/" + quote(schema.version, safe="")),
        )
    )
    for typed in sorted(schema.object_types, key=lambda t: t.id):
        cls = term(ns, "class", typed.id)
        shape = term(ns, "shape", typed.id)
        owl.add((cls, RDF.type, OWL.Class))
        owl.add((cls, RDFS.label, Literal(typed.name, datatype=XSD.string)))
        if typed.description:
            owl.add((cls, RDFS.comment, Literal(typed.description, datatype=XSD.string)))
        shapes.add((shape, RDF.type, SH.NodeShape))
        shapes.add((shape, SH.targetClass, cls))
        for prop in sorted(typed.properties, key=lambda p: p.id):
            path = term(ns, "property", typed.id, prop.id)
            ps = term(ns, "property-shape", typed.id, prop.id)
            if prop.array or prop.data_type == "json":
                diag(
                    "unsupported_property",
                    f"{typed.id}/{prop.id}",
                    "JSON and ordered arrays have no scalar RDF mapping; export"
                    " rejects selected nonnull values",
                )
                continue
            owl.add((path, RDF.type, OWL.DatatypeProperty))
            owl.add((path, RDFS.domain, cls))
            owl.add((path, RDFS.range, DATATYPES[prop.data_type]))
            shapes.add((shape, SH.property, ps))
            shapes.add((ps, SH.path, path))
            shapes.add((ps, SH.datatype, DATATYPES[prop.data_type]))
            shapes.add((ps, SH.maxCount, Literal(1)))
            if prop.required and not prop.nullable:
                shapes.add((ps, SH.minCount, Literal(1)))
            if prop.nullable:
                diag(
                    "null_absence",
                    f"{typed.id}/{prop.id}",
                    "RDF omits null; required presence of a nullable field cannot be validated",
                )
            if prop.max_length is not None:
                shapes.add((ps, SH.maxLength, Literal(prop.max_length)))
            if prop.enum:
                nodes = [term(ns, "enum", typed.id, prop.id, str(i)) for i in range(len(prop.enum))]
                shapes.add((ps, SH["in"], nodes[0]))
                for i, value in enumerate(prop.enum):
                    shapes.add((nodes[i], RDF.first, literal(prop, value)))
                    shapes.add(
                        (nodes[i], RDF.rest, nodes[i + 1] if i + 1 < len(nodes) else RDF.nil)
                    )
            for enabled, code, message in (
                (
                    prop.unique,
                    "operational_uniqueness",
                    "SQL uniqueness is not OWL identity equality",
                ),
                (
                    prop.indexed,
                    "operational_index",
                    "Physical index requests remain operational metadata",
                ),
                (
                    prop.has_default or prop.default is not None,
                    "operational_default",
                    "Defaults are applied by operational services, not SHACL",
                ),
                (
                    prop.data_type == "decimal",
                    "decimal_precision",
                    "Precision/scale remain canonical operational validation",
                ),
                (
                    prop.data_type == "uuid",
                    "uuid_lexical",
                    "UUID is projected as xsd:string; canonical validation enforces UUID syntax",
                ),
            ):
                if enabled:
                    diag(code, f"{typed.id}/{prop.id}", message)
    for link in sorted(schema.link_types, key=lambda t: t.id):
        path = term(ns, "link", link.id)
        source, target = term(ns, "class", link.source_type), term(ns, "class", link.target_type)
        owl.add((path, RDF.type, OWL.ObjectProperty))
        owl.add((path, RDFS.domain, source))
        owl.add((path, RDFS.range, target))
        ps = term(ns, "link-shape", link.id)
        shapes.add((term(ns, "shape", link.source_type), SH.property, ps))
        shapes.add((ps, SH.path, path))
        shapes.add((ps, SH["class"], target))
        shapes.add((ps, SH.nodeKind, SH.IRI))
        if link.cardinality in {"one_to_one", "many_to_one"}:
            shapes.add((ps, SH.maxCount, Literal(1)))
        if link.cardinality in {"one_to_one", "one_to_many"}:
            inv = term(ns, "inverse-shape", link.id)
            invpath = term(ns, "inverse-path", link.id)
            shapes.add((term(ns, "shape", link.target_type), SH.property, inv))
            shapes.add((inv, SH.path, invpath))
            shapes.add((invpath, SH.inversePath, path))
            shapes.add((inv, SH.maxCount, Literal(1)))
        if link.inverse_name:
            owl.add((term(ns, "inverse-link", link.id), OWL.inverseOf, path))
        # Never add OWL functionality: its equality semantics do not enforce SQL cardinality.
    for action in sorted(schema.action_types, key=lambda a: a.id):
        diag("operational_action", action.id, "Governed actions have no RDF execution semantics")
    diag(
        "canonical_scope",
        schema.id,
        "Canonical v1 has no inheritance, minimum link counts, numeric"
        " bounds or OWL rule definitions; none are invented",
    )
    return serialize(owl), serialize(shapes), diagnostics


def triple_id(s: Node, p: Node, o: Node) -> str:
    return digest(f"{s.n3()} {p.n3()} {o.n3()} .".encode())
