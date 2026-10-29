# ADR 0024: Immutable bounded semantic artifacts and explicit compilation loss

Status: Accepted for Phase 5

Canonical published JSON and PostgreSQL operational state remain authoritative. RDFLib 7.1.4,
already pinned for validation, becomes a runtime dependency for serialization/parsing only. All
reasoning and SHACL evaluation use the existing replaceable Open Ontologies batch adapter.

Store complete immutable manifests and at most 4 MiB of content per artifact in PostgreSQL. Include
input/output hashes, published schema, compiler/engine pins, actor/time and export boundary. Use
content/configuration fingerprints within tenant/ontology/principal to deduplicate artifacts and
job requests. Retain artifacts, facts, approval events and job history indefinitely; no implicit purge
or retention promise beyond this local foundation. Failed transactions leave no partial outputs;
temporary engine files are removed after each invocation. Database owners can bypass triggers.

Compile deterministic sorted full-IRI Turtle (N-Triples-compatible statements), with no prefix
ordering ambiguity and no generated blank nodes. Category-separated base64url JSON tuple IRIs
separate classes, type-scoped properties, links, shapes and list nodes from identity mapping v1.
SHACL has explicit xsd:string enumeration literals. Null values project to absent triples. Ordered
arrays/JSON are diagnosed and selected nonnull values reject export; nullable required presence,
SQL uniqueness, indexes/defaults, decimal precision and UUID syntax remain explicit operational
limitations. Canonical v1 contains no inheritance, minimum link counts, numeric bounds or OWL rules;
none are invented. OWL domain/range/inverse axioms complement SHACL maxima; SQL cardinality is not
translated into OWL functionality/equality. Opaque native ontology/shapes artifacts require a distinct
publication permission and explicit published version. This does not translate OWL to operational
schemas or activate imported metadata; that remains Phase 6.
