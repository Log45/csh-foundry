# Phase 6 governed ontology file interchange

Phase 7 now supplies verified OIDC/platform membership context and current RBAC/ABAC through
these same governed services. See [security](security.md) for configuration, permissions, tenant
selection, SQL restrictions and worker delegation. Earlier local-only descriptions below describe
the preserved isolated-development workflow, not an OIDC authentication bypass.


Protégé, WebProtégé and a future native Ontology Manager are optional authoring interfaces to the
same canonical registry. No authoring application is required at runtime. Existing canonical draft,
validation, publication, migration-plan and activation APIs remain authoritative.

All paths below start with `/api/v1/ontologies/{ontology_id}/interchange`. The ontology must already
exist: create it through the canonical registry API, with an empty initial draft if appropriate.
Trusted server context supplies tenant and principal. Request bodies cannot override identity.

| Method/path | Result |
|---|---|
| POST `/imports` | ImportInput → ImportView; explicit PREVIEW_ONLY (default) or CREATE_DRAFT |
| GET `/imports/{id}` | Original immutable preview/result, private to initiating principal |
| GET `/imports/{id}/original` | Exact original UTF-8 text; text/plain, nosniff |
| GET `/imports/{id}/vocabulary` | Declared named subjects and their rdf:type kinds; paginated |
| GET `/imports/{id}/diagnostics` | Full diagnostic pages; paginated |
| GET `/exports/{version}` | Published canonical OWL Turtle, exact hash, canonical hash and explicit reimport mapping manifest |

Read pages use limit 1–100 (default 50), offset 0–10000. Results contain at most 100 inline
diagnostics, full counts, a truncation flag and a diagnostic URL. No unbounded collection API exists.

## Explicit mapping contract

An example for one source class (all operational choices are explicit):

```json
{
  "format": "turtle",
  "mode": "PREVIEW_ONLY",
  "content": "@prefix m: <https://example.org/m#> . @prefix owl: <http://www.w3.org/2002/07/owl#> . @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> . m:Factory a owl:Class . m:factoryId a owl:DatatypeProperty; rdfs:domain m:Factory; rdfs:range <http://www.w3.org/2001/XMLSchema#string> .",
  "version": "2.0.0",
  "base_version": "1.0.0",
  "namespace_mappings": {"m": "https://example.org/m#"},
  "mappings": {
    "classes": [{
      "iri": "m:Factory",
      "definition": {
        "id": "Factory", "name": "Factory", "primary_key": "factoryId",
        "properties": [{"id":"factoryId", "name":"Factory ID", "data_type":"string", "required":true}]
      },
      "property_iris": {"factoryId": "m:factoryId"}
    }],
    "links": []
  }
}
```

`definition` is the existing canonical ObjectTypeDefinition or LinkTypeDefinition, not a Protégé
schema model. Every property requires an explicit source IRI. Names, primary keys, nullability,
required presence, enum/index/uniqueness/default/decimal policies and relationship cardinalities are
reviewed canonical choices supplied by the author. No OWL functional/key/restriction axiom silently
becomes a SQL constraint. Link mappings require both explicit endpoint class mappings. Inverses
remain canonical navigation aliases; redundant operational edges are never created.

Mapped classes must be declared owl:Class; mapped scalar properties must be declared
owl:DatatypeProperty with exactly one matching domain/range. Relationships require owl:ObjectProperty
with exactly one matching domain/range. Class/property punning, multiple domains/ranges, duplicate
mapping targets, datatype mismatches and missing references block draft creation with structured
conflicts. Supported scalar ranges are the existing compiler mappings: xsd:string, integer, double,
boolean, date, dateTime and decimal. UUID uses xsd:string with explicit canonical UUID validation.
Decimal precision/scale remain explicit. No implicit xsd:decimal → float conversion is performed.

The import overlays selected definitions on the chosen base; unselected canonical types, links and
actions remain. It does not infer actions or access policies. To resolve an existing definition
conflict, set `conflict_choices` with the compact JSON tuple key returned as diagnostic `construct`,
e.g. `{"[\"class\",\"Factory\"]":"replace"}` or `keep`. Keep leaves that source definition semantic-only
and registers no discarded mapping. Replace passes the ordinary compatibility/migration guards.
Imported IRI or canonical-target reassignment is always a conflict; no alias merging or owl:sameAs
identity merging occurs. Accepted bindings are immutable and ontology/tenant scoped, with import
provenance. Choose an existing binding, omit the incompatible mapping, or use a separately governed
ontology; remapping active identities is outside this phase.

`base_version` defaults to the active version. If there is no active version, select an existing
base explicitly. `expected_base_hash` rejects a changed base; CREATE_DRAFT requires it for mutable
draft bases. The result exposes the actual base version/hash. Publication/activation are separate
explicit registry calls. Imports never replace an existing target draft, publish or activate.
A preview is advisory: CREATE_DRAFT reparses, reauthorizes, relocks and rechecks the current base,
IRI bindings, canonical validation and version availability. Concurrent identical draft creations
commit once; the other receives `version_immutable`. There is no idempotent replay-key API.

## Preservation and diagnostics

All successfully parsed imports, including previews and mapping conflicts, archive the exact input,
SHA256, explicit request/source metadata, canonical RDF graph, complete diagnostics and bounded
result. Preview writes only this private provenance, never canonical drafts or accepted bindings.
Invalid/unsafe/over-limit parsing and failed transactions return sanitized errors and leave no record.

Inheritance, equivalent classes/restrictions/intersections, keys, functionality, RDF lists/blank nodes,
annotations, unmapped classes/properties, individuals, sameAs and imports declarations remain in the
original artifact. `semantic_only` diagnostics group retained statements by predicate. No individual
is materialized as an operational object. No inference, SHACL validation or proof verification is
claimed by a successful import; existing semantic jobs provide separate checks.

Counts are RDF-statement units, not OWLAPI logical-axiom counts: supported counts consumed declaration/
domain/range statements; preserved and unsupported counts describe the remaining statements. Every
statement, including supported statements, remains in the original artifact. All parsed statement
events count against a conservative axiom budget, bounding logical axiom count as well as duplicate
input statements. Multiple ontology/version IRIs conflict rather than choosing one silently.

Canonical export uses the deterministic existing compiler and accepted source vocabulary IRIs when
available for that exact imported version and canonical content hash. The companion mapping manifest preserves explicit supported canonical constraints during
reimport; OWL alone cannot encode every operational constraint. Exports include compiler diagnostics
for unsupported/lossy canonical features. JSON/array-bearing classes are omitted from reimport mappings
rather than represented as scalar properties. Existing actions remain in the canonical registry.
Canonical exports do not union stale unsupported source axioms with a changed schema. Download the
original artifact separately to retain or reauthor those axioms. This is supported-subset round trip,
not arbitrary OWL reconstruction from canonical metadata or live bidirectional synchronization.

## Parsing, formats and bounds

Only explicit `turtle` and `rdfxml` formats are accepted; there is no extension/MIME sniffing, path,
URL or archive import. UTF-8 text transports the original file. RDF/XML requires an rdf:RDF document
root; abbreviated typed roots are conservatively excluded to distinguish OWL/XML. OWL/XML,
JSON-LD, N3, ZIP and other formats are unsupported. Convert with Protégé/OWLAPI first.

| Resource | Bound |
|---|---|
| Entire POST body, before JSON parsing | 64 KiB |
| Internal source text | 256 KiB UTF-8 |
| Parsed statement events / conservative OWL axiom budget | 4,000 |
| Blank nodes / namespace bindings | 512 / 64 |
| One RDF term | 8,192 UTF-8 bytes |
| Parser plus canonicalization subprocess | 5 seconds; killed and reaped on timeout |
| Canonical source graph / full diagnostics | 4 MiB each |
| Proposed result / stored request including original | 256 / 512 KiB |
| Explicit classes / links / properties per class | 32 / 64 / 64 |

The RDFLib 7.1.4 parser receives in-memory data only, with sockets disabled in its isolated process.
DTD/entity declarations are rejected before XML parsing. owl:imports IRIs are preserved and never
resolved, including file URLs; no catalogs, remote contexts, dependencies or XInclude are loaded.
Relative IRIs without an explicit document base are rejected. Parsing and blank-node canonicalization
occur outside PostgreSQL transactions/locks; sync FastAPI routes run in its thread pool. There is
no durable import worker/job: this small bounded authoring operation completes synchronously while
parsing runs in a child process. Aggregate admission, hard OS memory quotas and durable large imports
remain later operational work; this is not a general-purpose untrusted-code sandbox.

Permission operations are `ontology:import`, `ontology:import:read`, `schema:read`, `schema:write` for
creation, and `schema:export`. Permissions are rechecked per operation; original/result/vocabulary/
diagnostics are initiating-principal private. Existing trusted local identity limitations remain.
Import retention is indefinite; no delete/expiry/sharing endpoint or aggregate storage quota exists.
Database triggers reject import/binding UPDATE/DELETE. Database owners can bypass triggers.

Imported vocabulary applies only to its exact created version and canonical content hash. Creating a
new draft cannot change older exports. Editing an imported draft before publication makes its source
mapping stale: export uses generated canonical vocabulary with an explicit diagnostic. Accepted IRI
conflict bindings still prevent silent reassignment; they are provenance, not schema authority.
