# Operational architecture — Phases 0–4

PostgreSQL remains the authoritative operational store. The backend is a modular Python
monolith. Canonical JSON/Pydantic metadata is independent of RDF/OWL. Open Ontologies is
an external semantic process; Protégé is optional file-based authoring tooling. Semantic
adapter code and fixtures are unchanged through Phase 4. Studio and SDKs remain later roadmap
work. Governed actions, outbox delivery and a bounded PostgreSQL ingestion runner are implemented.
Phase 2 operational queries share the existing governed transactions and active registry.

Public application contracts live in `ontology_platform/contracts.py`. HTTP routes depend
on application services; services use the shared public governed unit-of-work and database
models. Registry storage helpers expose canonical snapshots to object services. Object
validation and persistence checks expose an explicit interface to schema activation.
The API never writes ORM entities directly. No service imports the semantic engine.

## Tenant and transaction boundaries

The server-configured trusted local principal is opt-in and fails closed. Each service
operation invokes an authorization interface, resolves an existing tenant, and owns a
transaction. Provisioning is the sole exception to preexisting tenant resolution and can
create only the principal's own configured tenant. Clients cannot select tenant identity
through headers. Canonical schema bodies include tenant identity and are rejected if it
differs from the principal. OIDC/RBAC/ABAC and public deployment remain out of scope.

Every persisted ontology/version/type/object/link/plan/activation is tenant-owned through
composite foreign keys. Object/link lookup, counts and navigation include tenant predicates.
No cross-tenant sharing is supported. Database RLS is not enabled: the application database
role is trusted, and direct unrestricted SQL is not an authenticated API. All operational
mutations must pass through governed services.

Writers lock the owning ontology row `FOR UPDATE`. Readers needing a consistent active
schema/data interval use `FOR SHARE`. This intentionally coarse foundation serializes
cardinality, uniqueness and activation decisions. Object patches also use an expected-version
predicate with `UPDATE ... RETURNING`; deletes require the current revision. This has modest
per-ontology write throughput and should be revisited with evidence before adding finer locks.

## Registry and publication

`ontology_versions.definition_json` is the canonical snapshot and SHA256 content hash.
Version-owned object/link definition rows provide relational FK targets; properties/actions
remain inside canonical definitions. Draft replacement updates both representations atomically.
A PostgreSQL trigger rejects all update/delete operations on published versions and rejects
mutation/insertion of published type snapshots. Publication records actor/time and freezes
metadata; it never activates a version.

`ontologies.active_version` is one pointer, with a composite FK including the constant
`PUBLISHED` status. A draft-only ontology has no active version and cannot hold objects
through the services. Once activated, the pointer cannot be cleared; historical published
versions remain addressable. Ontology ID and namespace cannot change.

Activation compares proposed metadata to the actual active version, checks any required
approved migration plan, applies declared property replacements, validates all existing
objects and forward links under the target, updates validation versions/revisions, records
actor/time/history and switches the pointer in one PostgreSQL transaction. All failures
roll back migrated data and leave the old pointer in place. No implicit object deletion,
primary-key rewrite or imported-IRI merge is performed.

## Objects and links

Objects use `(tenant_id, ontology_id, object_type_id, object_id)` as the primary key with
JSONB properties, schema version, revision and aware timestamps. Primary-key properties
must match the supplied immutable object ID. Canonical datatype/null/default/enum rules
apply without coercion. Unknown properties are rejected. Defaults apply on creation;
activation does not silently fill missing required data. Declared uniqueness is checked
transactionally under the ontology write lock (multiple missing/null values are allowed).
Decimal and timestamp uniqueness compares values; other types use JSONB equality.

Forward link rows have composite endpoint FKs and a FK to the exact versioned source/target
link definition. Forward navigation joins to targets; inverse navigation joins to sources.
Cardinality enforces maximum fan-in/fan-out; canonical contracts do not define mandatory
minimum edge counts. Existing links prevent endpoint deletion until explicitly removed.
Primary/link traversal B-tree indexes exist. Property `indexed` declarations are persisted;
custom expression/GIN index materialization is deferred until query workloads and background
index operations are implemented. No unbounded object listing/query API is exposed.

## Bounds and deferred work

Activation supports at most 1,000 objects and 5,000 links in Phase 1. Migration plans contain
at most 1,000 full property replacements with expected object revisions. Larger work fails
explicitly and requires a later durable worker path. No arbitrary SQL or Python can execute
from ontology/plan metadata. Per-ontology locking plus these bounds keep this initial path
transactional; a production migration/job orchestrator is not claimed.


## Phase 2 query boundary

`queries/ast.py` defines bounded public contracts; `compiler.py` resolves schema/policies and
produces parameterized SQL; `service.py` handles bounded results, projections, aggregates and
signed keyset pagination; `object_set.py` composes the same requests lazily. Each traversal step
uses an authorized materialized identity CTE over existing forward links. JSONB property casts
are type/scope guarded. QueryGrant expresses SQL-visible rows and properties; legacy providers
without query grants fail closed. No production policy engine is introduced.

Measured fixed-width status equality and C-collation identity ordering indexes complement the existing identity/link indexes.
Other property index jobs remain deferred. Per-ontology shared/exclusive locks are unchanged.
See ADRs 0013–0017, the query API reference and the Phase 2 report for exact semantics/evidence.

## Phase 3 actions

Governed actions compose existing object/link services in one caller-owned PostgreSQL transaction.
History/idempotency, redacted immutable audits, outbox and action overlays commit together. Preview
rolls back a savepoint. A bounded leased runner delivers notifications outside action transactions.
Property ownership/reconciliation services protect edits without introducing ingestion. See
[the action contract](../api/actions.md) and ADRs 0018–0020. PostgreSQL and ontology locks remain
authoritative; no semantic, UI, SDK or production identity expansion is included.

## Phase 4 ingestion

Tenant-owned immutable source/mapping versions refer to server-registered connectors. Durable
PostgreSQL jobs stage bounded canonical proposals, validate identities and compose existing object,
link and reconciliation services under retained ontology locks. Operational batches and fenced
checkpoints commit together; schema changes fail stale runs. Explicit reject/quarantine policies
distinguish whole-run and batch atomicity. No request-selected path/SQL/credentials or parallel
mutation/reconciliation implementation exists. See ADRs 0021–0023 and the ingestion API/report.


Phase 5 adds principal-private semantic artifacts, compiled RDF/OWL/SHACL, governed exports,
fenced jobs and separately approved derived facts. See [semantic API](../api/semantic.md) and ADRs 0024–0026.
Migrations `0010_semantic` and `0011_semantic_history` add four semantic tables and bounded
claim/error history; downgrade removes semantic history while preserving operational objects.
