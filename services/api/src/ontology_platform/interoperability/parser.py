"""No-network bounded RDFLib parser, isolated behind a killable subprocess deadline."""

import json
import socket
import subprocess
import sys
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree

from rdflib import BNode, Graph, URIRef
from rdflib.compare import to_canonical_graph
from rdflib.plugins.stores.memory import Memory

from ontology_platform.errors import ApplicationError
from ontology_platform.interoperability.contracts import (
    MAX_BNODES,
    MAX_INPUT,
    MAX_NAMESPACES,
    MAX_STATEMENTS,
    PARSE_SECONDS,
)


class ImportLimit(Exception):
    pass


class BoundedMemory(Memory):
    def __init__(self) -> None:
        super().__init__()
        self.statements = 0
        self.bnodes: set[BNode] = set()
        self.names: set[tuple[str, str]] = set()

    def add(self, triple: Any, context: Any, quoted: bool = False) -> None:
        # Count parser events as well as unique triples to bound repeated statements.
        self.statements += 1
        self.bnodes.update(t for t in triple if isinstance(t, BNode))
        if self.statements > MAX_STATEMENTS or len(self.bnodes) > MAX_BNODES:
            raise ImportLimit()
        for term in triple:
            if len(str(term).encode()) > 8192:
                raise ImportLimit()
            if isinstance(term, URIRef) and (
                not urlsplit(str(term)).scheme or str(term).startswith("urn:foundry:unresolved:")
            ):
                raise ValueError("Explicit absolute IRIs or a document base are required")
        super().add(triple, context, quoted)

    def bind(self, prefix: str, namespace: URIRef, override: bool = True) -> None:
        self.names.add((prefix, str(namespace)))
        if len(self.names) > MAX_NAMESPACES:
            raise ImportLimit()
        super().bind(prefix, namespace, override)


def serialize_graph(graph: Graph) -> str:
    # RDFLib's N-Triples writer escapes multiline literals; Node.n3() can emit Turtle long strings.
    output = "\n".join(sorted(graph.serialize(format="nt").splitlines())) + "\n"
    if len(output.encode()) > 4 * 1024 * 1024:
        raise ImportLimit()
    return output


def parse_local(content: str, format: str) -> str:
    if format not in {"turtle", "rdfxml"}:
        raise ValueError("Unsupported format")
    if len(content.encode()) > MAX_INPUT:
        raise ImportLimit()
    # UTF-8 text input only: DTD/entity declarations cannot hide behind UTF-16 bytes.
    if "<!DOCTYPE" in content.upper() or "<!ENTITY" in content.upper():
        raise ValueError("DTD and entity declarations are forbidden")
    if (
        format == "rdfxml"
        and ElementTree.fromstring(content).tag
        != "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF"
    ):
        raise ValueError("RDF/XML requires rdf:RDF root; OWL/XML is unsupported")
    graph = Graph(store=BoundedMemory(), bind_namespaces="none")
    graph.parse(
        data=content,
        format="xml" if format == "rdfxml" else "turtle",
        publicID="urn:foundry:unresolved:",
    )
    # Canonicalization, including pathological blank-node graphs, shares the process deadline.
    return serialize_graph(to_canonical_graph(graph))


def parse_import(content: str, format: str, *, timeout: float = PARSE_SECONDS) -> Graph:
    if len(content.encode()) > MAX_INPUT:
        raise ApplicationError("import_resource_limit", "Import exceeds 256 KiB", 422)
    if format not in {"turtle", "rdfxml"}:
        raise ApplicationError("unsupported_format", "Use turtle or rdfxml", 422)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "ontology_platform.interoperability.parser"],
            input=json.dumps({"content": content, "format": format}),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ApplicationError(
            "import_timeout", "Ontology parsing exceeded its deadline", 422
        ) from exc
    except OSError as exc:
        raise ApplicationError("import_unavailable", "Ontology parser unavailable", 503) from exc
    if result.returncode:
        code = "import_resource_limit" if result.returncode == 3 else "invalid_ontology"
        raise ApplicationError(code, "Ontology input rejected by isolated parser", 422)
    if len(result.stdout.encode()) > 4 * 1024 * 1024:
        raise ApplicationError("import_resource_limit", "Parsed graph exceeds 4 MiB", 422)
    # Trusted, size-bounded N-Triples emitted by our child, with no remote resolution capability.
    return Graph().parse(data=result.stdout, format="nt")


def _no_network(*args: Any, **kwargs: Any) -> Any:
    raise ValueError("Network resolution is disabled")


if __name__ == "__main__":
    socket.socket = _no_network  # type: ignore[misc, assignment]
    socket.create_connection = _no_network
    try:
        request = json.loads(sys.stdin.read(MAX_INPUT * 8))
        sys.stdout.write(parse_local(request["content"], request["format"]))
    except ImportLimit:
        sys.exit(3)
    except Exception:
        # Never echo parser input, filesystem paths, or secrets through diagnostics.
        sys.exit(2)
