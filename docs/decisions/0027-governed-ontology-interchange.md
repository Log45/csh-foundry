# ADR 0027: Optional file authoring through one canonical registry

Status: Accepted for Phase 6.

Use pinned RDFLib, existing canonical models, RegistryService and compatibility analysis for explicit
Turtle/RDF/XML imports. Operational primary keys and constraints require explicit canonical mapping
choices. Do not derive constraints from OWL open-world equality/cardinality/key semantics. Preserve
all source bytes and semantic-only statements, with structured diagnostics. No actions, access
policies, individuals, publication or activation are inferred from OWL. No second registry or
Protégé-specific ontology schema exists. Native future authoring uses the same canonical APIs.

Parse in a killable no-network child process before acquiring the existing ontology write lock.
Enforce source/statement/term/blank-node/namespace/time bounds. Reject XML DTD/entities and unsupported
formats; never follow imports. Five-second synchronous authoring is bounded and separate from
longer semantic jobs; durable large imports and aggregate resource admission are deferred.

Atomically compose RegistryService.draft in the caller-owned PostgreSQL transaction with immutable
private source/request/result/diagnostic provenance and accepted IRI bindings. Previews archive source
without canonical changes. Reauthorize every request and compare mutable base hashes; don't treat
preview as execution authority. Immutable tenant/ontology-scoped vocabulary bindings reject ambiguous
IRIs and canonical-target aliases. Explicit keep/replace resolves canonical-definition conflicts,
while existing publication/activation/migration approval remains unchanged.

Deterministic canonical exports reuse compilation and version/hash-bound accepted vocabulary IRIs with explicit reimport
mapping manifests. Original semantic files remain separately downloadable: never union stale source
restrictions into a changed operational schema. Preserve supported constraints via canonical mapping
metadata, diagnose unsupported features, and distinguish OWLAPI axiom equality from RDF serialization
syntax. OWL/XML is verified in the optional Java harness but unsupported by the platform parser.

Protégé/WebProtégé remain optional; no GUI, live sync, endpoint contract, deployment, extra database,
parser dependency, custom reasoner, production identity or Phase 7 behavior is introduced.

Imported vocabulary applies only to its exact created version and canonical content hash. Creating a
new draft cannot change older exports. Editing an imported draft before publication makes its source
mapping stale: export uses generated canonical vocabulary with an explicit diagnostic. Accepted IRI
conflict bindings still prevent silent reassignment; they are provenance, not schema authority.
