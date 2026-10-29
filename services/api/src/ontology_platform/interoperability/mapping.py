"""Conservative explicit OWL-to-canonical projection. No reasoning or policy inference."""

import json
from collections.abc import Callable
from urllib.parse import urlsplit

from ontology_schema.models import OntologyDefinition
from pydantic import ValidationError
from rdflib import OWL, RDF, RDFS, Graph, URIRef
from rdflib.term import Node

from ontology_platform.interoperability.contracts import ImportInput
from ontology_platform.semantic.compiler import DATATYPES
from ontology_platform.semantic.contracts import Diagnostic


def target(*parts: str) -> str:
    return json.dumps(parts, ensure_ascii=False, separators=(",", ":"))


def expand(value: str, namespaces: dict[str, str]) -> str:
    prefix, sep, local = value.partition(":")
    result = namespaces[prefix] + local if sep and prefix in namespaces else value
    if len(result) > 2048 or not urlsplit(result).scheme or any(c.isspace() for c in result):
        raise ValueError("Mapping requires an absolute IRI")
    return result


def project(
    graph: Graph,
    base: OntologyDefinition,
    request: ImportInput,
    binding_conflict: Callable[[str, str], bool],
) -> tuple[OntologyDefinition | None, list[Diagnostic], dict[str, str], int, list[str]]:
    diagnostics: list[Diagnostic] = []
    bindings: dict[str, str] = {}
    reverse: dict[str, str] = {}
    consumed: set[tuple[Node, Node, Node]] = set()
    objects = {o.id: o for o in base.object_types}
    links = {o.id: o for o in base.link_types}
    classes: dict[str, URIRef] = {}
    changes: list[str] = []

    def diag(code: str, path: str, message: str) -> None:
        diagnostics.append(Diagnostic(code=code, construct=path, message=message))

    def bind(iri: str, path: str) -> URIRef:
        resolved = expand(iri, request.namespace_mappings)
        if (
            (resolved in bindings and bindings[resolved] != path)
            or (path in reverse and reverse[path] != resolved)
            or binding_conflict(resolved, path)
        ):
            diag(
                "iri_conflict", path, "Imported IRI or canonical target already has another mapping"
            )
        bindings[resolved], reverse[path] = path, resolved
        return URIRef(resolved)

    def require(s: URIRef, p: URIRef, o: URIRef, path: str) -> None:
        # Multiple domains/ranges have intersection semantics, never silently choose one.
        if set(graph.objects(s, p)) != {o}:
            diag(
                "mapping_conflict",
                path,
                "Missing, ambiguous or incompatible declaration/domain/range",
            )
        else:
            consumed.add((s, p, o))

    def choose(path: str, old: object, new: object) -> bool:
        if old is None or old == new:
            if old is None:
                changes.append("add " + path)
            return True
        choice = request.conflict_choices.get(path)
        if choice == "replace":
            changes.append("replace " + path)
            return True
        if choice == "keep":
            changes.append("keep " + path)
            return False
        diag(
            "definition_conflict",
            path,
            "Existing canonical definition differs; choose keep or replace",
        )
        return False

    try:
        ids = [m.definition.id for m in request.mappings.classes]
        lids = [m.definition.id for m in request.mappings.links]
        if len(ids) != len(set(ids)) or len(lids) != len(set(lids)):
            raise ValueError("Duplicate mapping targets")
        for mapping in request.mappings.classes:
            typed = mapping.definition
            path = target("class", typed.id)
            classes[typed.id] = URIRef(expand(mapping.iri, request.namespace_mappings))
            if not choose(path, objects.get(typed.id), typed):
                continue
            cls = bind(mapping.iri, path)
            # Punning is retained semantically, but cannot be operationally mapped.
            if (cls, RDF.type, OWL.Class) not in graph:
                diag("mapping_conflict", path, "Mapped class requires an owl:Class declaration")
            else:
                consumed.add((cls, RDF.type, OWL.Class))
            if any(
                (cls, RDF.type, kind) in graph
                for kind in (OWL.ObjectProperty, OWL.DatatypeProperty)
            ):
                diag(
                    "mapping_conflict",
                    path,
                    "Class/property punning cannot map to an operational type",
                )
            for prop in typed.properties:
                ppath = target("property", typed.id, prop.id)
                iri = bind(mapping.property_iris[prop.id], ppath)
                if prop.array or prop.data_type == "json":
                    diag(
                        "mapping_conflict",
                        ppath,
                        "Scalar OWL properties cannot map to JSON or ordered arrays",
                    )
                    continue
                if (iri, RDF.type, OWL.DatatypeProperty) not in graph or (
                    iri,
                    RDF.type,
                    OWL.ObjectProperty,
                ) in graph:
                    diag(
                        "mapping_conflict",
                        ppath,
                        "Mapped property requires an unambiguous datatype-property declaration",
                    )
                else:
                    consumed.add((iri, RDF.type, OWL.DatatypeProperty))
                require(iri, RDFS.domain, cls, ppath)
                require(iri, RDFS.range, DATATYPES[prop.data_type], ppath)
            objects[typed.id] = typed
        for link_mapping in request.mappings.links:
            link = link_mapping.definition
            path = target("link", link.id)
            if not choose(path, links.get(link.id), link):
                continue
            iri = bind(link_mapping.iri, path)
            if (iri, RDF.type, OWL.ObjectProperty) not in graph or (
                iri,
                RDF.type,
                OWL.DatatypeProperty,
            ) in graph:
                diag(
                    "mapping_conflict",
                    path,
                    "Mapped relationship requires an object-property declaration",
                )
            else:
                consumed.add((iri, RDF.type, OWL.ObjectProperty))
            if link.source_type not in classes or link.target_type not in classes:
                diag(
                    "mapping_conflict",
                    path,
                    "Relationship endpoints require explicit class mappings",
                )
                continue
            require(iri, RDFS.domain, classes[link.source_type], path)
            require(iri, RDFS.range, classes[link.target_type], path)
            links[link.id] = link
        candidate = OntologyDefinition.model_validate(
            base.model_dump()
            | {
                "version": request.version,
                "object_types": tuple(objects.values()),
                "link_types": tuple(links.values()),
            }
        )
        if not request.mappings.classes:
            diag(
                "mapping_conflict",
                "classes",
                "Select explicit operational class mappings before creating a draft",
            )
    except (ValueError, ValidationError):
        candidate = None
        diag(
            "mapping_conflict", "mappings", "Invalid canonical mapping, reference, or absolute IRI"
        )
    # Every remaining RDF statement is preserved. Group diagnostics by predicate, not input labels.
    unsupported: dict[str, int] = {}
    for s, p, o in graph:
        if (s, p, o) not in consumed:
            unsupported[str(p)] = unsupported.get(str(p), 0) + 1
    for predicate, count in sorted(unsupported.items()):
        diag(
            "semantic_only",
            predicate,
            f"{count} statements retained in original; no operational semantics inferred",
        )
    return candidate, diagnostics, bindings, len(consumed), changes
