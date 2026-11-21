# Operational architecture

CSH Foundry is a modular FastAPI/Pydantic/SQLAlchemy backend with a Next.js Studio and
Python/TypeScript developer tooling. Current source covers Phases 0–22 and subsequent
worker and directory-sharing fixes. PostgreSQL is authoritative for operational state,
metadata, authorization, jobs, audit, lineage and browser sessions. Optional S3-compatible
storage holds immutable binary artifacts; it does not replace PostgreSQL governance.

Canonical JSON/Pydantic metadata is independent of RDF/OWL. Open Ontologies is an external
semantic process; Protégé is optional file-based authoring tooling. Publication, activation,
object mutations and derived-fact approval remain distinct governed operations.

Public application contracts live in `ontology_platform/contracts.py`. HTTP routes depend
on application services; services use the shared public governed unit-of-work and database
models. Registry storage helpers expose canonical snapshots to object services. Object
validation and persistence checks expose an explicit interface to schema activation.
The API never writes ORM entities directly. Domain services access semantic functionality through the separate adapter boundary.

## Tenant and transaction boundaries

Authentication defaults to disabled domain access. Trusted local identity is an opt-in
loopback development profile with a server-configured tenant and principal. OIDC mode
verifies provider access tokens, resolves platform-controlled memberships and applies RBAC
and restrictive SQL ABAC. An authorized `X-Tenant-ID` selects acting context; a client header
never grants membership. Eligible configured Keycloak identities can provision one personal
tenant through the governed onboarding transaction.

Every persisted ontology/version/type/object/link/plan/activation is tenant-owned through
composite foreign keys. Object/link lookup, counts and navigation include tenant predicates.
Explicit Project/Ontology invitations can authorize bounded cross-tenant access. Shared
requests resolve the persisted owning tenant and enforce owner policy plus share scope;
share-only authority cannot submit jobs. See [personal tenants and sharing](personal-tenants-and-sharing.md).
Database RLS is not enabled: the application database role is trusted, and direct SQL is not
an authenticated API. All operational mutations pass through governed services and own a
PostgreSQL transaction.

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
without query grants fail closed. Current security grants apply RBAC and restrictive ABAC before SQL execution.

Measured fixed-width status equality and C-collation identity ordering indexes complement the existing identity/link indexes.
Other property index jobs remain deferred. Per-ontology shared/exclusive locks are unchanged.
See ADRs 0013–0017, the query API reference and the Phase 2 report for exact semantics/evidence.

## Phase 3 actions

Governed actions compose existing object/link services in one caller-owned PostgreSQL transaction.
History/idempotency, redacted immutable audits, outbox and action overlays commit together. Preview
rolls back a savepoint. A bounded leased runner delivers notifications outside action transactions.
Property ownership/reconciliation services protect edits during subsequent ingestion and materialization. See
[the action contract](../api/actions.md) and ADRs 0018–0020. PostgreSQL and ontology locks remain authoritative across API, UI, SDK and worker callers.

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


Phase 6 adds [governed ontology file interchange](../api/interchange.md).
Explicit mappings reuse canonical definitions and registry drafts. PostgreSQL remains authoritative;
Protégé/WebProtégé are optional. Original semantic axioms remain archived separately from operational
definitions. See ADR 0027 for bounds, preservation and publication/activation boundaries.


## Phase 7 security

[Production identity and authorization](../api/security.md) replaces trusted local assumptions in
OIDC mode. Explicit provider JWT verification resolves immutable issuer/subject identities and
platform-controlled memberships; tenant-owned roles and restrictive ABAC extend Authorizer and
QueryGrant. Policies stay SQL-enforced through query compilation. CRUD, actions, schema activation,
ingestion/reconciliation, semantic artifacts and OWL imports reuse governed checks. Tenant security
locks hold authorization state through commit; version/revocation changes invalidate cursor contexts.
Transaction-local snapshots only reuse lock-protected security state. Independent redacted decision
audit survives request rollback. Shared workers intersect current service/initiator authority through
immutable job-scoped grants, dynamically resolved per attempt. See ADR 0047 and the
[worker rollout guide](../operations/dynamic-workers.md). No RLS or production deployment is claimed.


## Projects, assets and execution

Project membership, resource governance and canonical ontology permissions are cumulative.
Generic artifacts have immutable verified versions; datasets add format/schema validation,
previews and immutable source versions. Pipelines pin inputs and published definitions.
The visual builder compiles closed graph documents into the existing Polars execution
contracts, including versioned DAGs and atomically published multiple outputs. Mapping
materialization reuses canonical object/link reconciliation; committed batches can remain
visible when a later batch fails. See [materialization](materialization.md) and the
[pipeline API](../api/pipelines.md).

Media Sets, trusted typed functions and automations use the same governed resources and
durable execution control plane. Published declarative applications invoke canonical query
and action services through the existing BFF/SDK. No arbitrary user code is executed.

Workers authenticate as services and resolve the owning tenant and initiating user from
immutable job grants at claim time. Leases, attempt fencing and current user/worker authority
guard publication. The execution controller also dispatches automations and reconciles
pending lineage while no execution is queued; see [ADR 0052](../decisions/0052-worker-memory-and-idle-maintenance.md).

## Studio, lineage and deployment boundaries

Studio's BFF keeps API tokens server-side and uses opaque HttpOnly browser cookies.
Production browser state is encrypted in PostgreSQL through a credential-protected internal
API; multiple Studio replicas share state. Process-local sessions remain a development option.
See [ADR 0033](../decisions/0033-durable-browser-state.md).

Lineage is a governed projection of canonical resources, immutable versions and executions.
Transactional invalidation and bounded reconciliation expose completeness explicitly.
Impact, column lineage, freshness and operational events independently enforce visibility;
see [lineage contracts](../development/lineage-observability.md).

The current readiness revision is `0030_directory_shares`. Compose and OKD4 deployment
profiles exist, but implementation and local checks do not establish production certification.
Release remains blocked by [the readiness gates](../operations/readiness.md) and PLANS.md §23B.
