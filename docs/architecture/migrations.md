# Database migrations

Apply with `uv run alembic upgrade head`; inspect with `uv run alembic current` and
`uv run alembic check`. Readiness expects `0013_security`.

| Revision | Objects |
|---|---|
| 0001_tenants (Phase 0, unchanged) | Tenant ownership anchor |
| 0002_registry (Phase 1) | ontologies, ontology_versions, object_type_definitions, link_type_definitions, objects, object_links, schema_migration_plans, schema_activations |
| 0003_snapshot_locks (Phase 1) | Lock draft parent versions during type edits so publication cannot race immutability checks |
| 0004_query_index (Phase 2) | Fixed-width, tenant-scoped expression index for measured operationalStatus equality queries |
| 0005_query_order (Phase 2) | Tenant/ontology/type identity index with explicit C collation for deterministic query paging |

Phase 1 adds composite tenant-safe primary/foreign keys, a status-qualified active-version FK,
JSONB object checks, positive revision check, link endpoint/type FKs, target traversal index,
approved-plan binding, and activation history. Publication and approved-plan immutability plus
ontology identity/namespace stability are protected with PostgreSQL triggers/functions.
Existing Phase 0 tenants are preserved; no reference fixtures are inserted by Alembic.

Properties and action definitions are retained inside canonical snapshots rather than adding
premature per-property/action tables. No ingestion/action/job/security-provider tables are created.
The semantic engine is unchanged. PostgreSQL remains the only platform operational database.

Downgrade to `0001_tenants` removes Phase 1 data/tables/triggers/functions and retains tenants;
downgrade to `base` also removes the Phase 0 tenant table. These are destructive administrative
schema reversals, not a substitute for transactional schema activation rollback. Test round trips
run only in unique temporary PostgreSQL schemas. The application does not expose Alembic/DDL
execution through ontology metadata or migration-plan APIs.

Alembic env supports an injected SQLAlchemy connection for tests; production/default execution
uses configured PostgreSQL settings. Explicit create/drop of the circular active-version FK
ensures clean upgrades and downgrades. `alembic check` reports no ORM schema drift.


Phase 2 revision `0004_query_index` adds no table or business data mutation. It creates
`ix_objects_status_lookup` on tenant UUID and md5(ontology_id), md5(object_type_id),
md5(properties ->> 'operationalStatus'). The compiler always rechecks exact identities and
values; these hashes are lookup accelerators, not security decisions. Fixed-width digests
avoid creating new key-size constraints on future valid data. No numeric cast index is added.
Creation/drop runs through administrative Alembic with transaction-local lock timeout 2s and
statement timeout 30s. Failure rolls back; downgrade drops only this index and preserves rows.
Large deployments requiring concurrent builds need a later explicitly approved worker/admin path.

Revision `0005_query_order` creates `ix_objects_query_order` on tenant/ontology/type/object identity
with explicit `object_id COLLATE "C"`. The existing primary key uses database collation and cannot
serve bytewise page ordering. Measurements justify this additional ordering index. It uses the same
identity columns as the primary key and adds no property type/size constraint. Creation/drop uses
the same 2s/30s timeouts; downgrade removes only the index and preserves all data.

SQLAlchemy/PostgreSQL reflection reports a column-only COLLATE index as ordinary columns.
Alembic's index filter handles this specific false difference only after checking the real
`pg_get_indexdef` against the expected complete nonunique B-tree definition. Missing, reordered,
unique or wrong-collation indexes still report drift; a PostgreSQL regression test checks both
the correct index and a deliberately incorrect collation definition.

## Phase 3

`0006_actions` adds committed action execution/idempotency, audit, outbox, delivery attempt, overlay
and reconciliation-conflict tables with tenant-safe schema/execution FKs and lookup indexes.
Execution/audit UPDATE/DELETE protection uses PostgreSQL triggers. `0007_edit_provenance` adds
edit updater/time and conflict resolver/time; existing Phase 3 rows receive an explicit
legacy-unknown updater until changed. Neither migration rewrites Phase 0–2 objects or schemas.
Both use 2-second lock/30-second statement DDL limits. Downgrade removes Phase 3 structures/provenance
and is destructive to Phase 3 history; test it only in disposable schemas. It preserves earlier
operational objects. Local development is upgraded to 0007_edit_provenance; drift checks and
upgrade/downgrade/data-preservation tests are included.

## Phase 4

`0008_ingestion` creates seven tenant-owned structures: immutable source and mapping versions,
ingestion run/jobs, stage records, redacted diagnostics, source-object identities and managed link
state. Composite FKs, uniqueness, check constraints, lookup indexes and configuration/plan triggers
protect ownership and reproducibility. `0009_ingestion_diagnostics` adds mapping locations, staging
purge time, a diagnostic mapping FK, lease/counter/policy checks and explicit LINK_REJECTED state.
Both use bounded DDL lock/statement budgets. Downgrades remove Phase 4 history/configuration/staging
and source provenance; earlier operational objects remain. Reverting 0009 folds LINK_REJECTED into
REJECTED before restoring the older state check. Tests perform destructive reversals only in private
schemas and verify objects survive Phase 3 → head and head → Phase 3 → head. Development is at
0009_ingestion_diagnostics; no sample data is loaded by migrations.


Phase 5 adds principal-private semantic artifacts, compiled RDF/OWL/SHACL, governed exports,
fenced jobs and separately approved derived facts. See [semantic API](../api/semantic.md) and ADRs 0024–0026.
Migrations `0010_semantic` and `0011_semantic_history` add four semantic tables and bounded
claim/error history; downgrade removes semantic history while preserving operational objects.

## Phase 6

`0012_ontology_imports` adds immutable principal-private ontology_imports and tenant/ontology-scoped
ontology_vocabulary_bindings with fixed-width IRI/target hashes, composite FKs, target uniqueness,
format/byte checks and UPDATE/DELETE guards. Original/request/result/diagnostics and accepted bindings
commit in the same transaction as RegistryService draft creation. Preview/conflict records create
no canonical versions/bindings. No published metadata or operational rows are rewritten.
DDL retains 2-second lock/30-second statement budgets. Downgrade removes Phase 6 provenance/bindings
only; canonical drafts and operational objects remain. Tests reverse only disposable schemas.


Phase 7 adds [production identity and authorization](../api/security.md), tenant memberships,
RBAC, restrictive ABAC, policy versioning/revocation, administration and delegated service workers.
See ADR 0028 and the Phase 7 report. Earlier phase identity descriptions document the original
local-development workflow; OIDC mode now supplies verified platform principal context.

## Phase 7 migration

`0013_security` adds principals, immutable external_identities, security_state, tenant_memberships,
immutable security_roles, role_assignments, immutable security_policy_versions,
security_policy_bindings, worker_delegations and immutable authorization_audit. It initializes only
empty security-state rows for existing tenants; no external identity or privileged assignment is
automatically created. Composite membership/role/policy/delegation FKs enforce tenant ownership.
Mutation triggers coordinate the tenant security lock and bump cursor/policy revisions, including
on direct SQL changes. Global principal disable coordinates through principal-row locks.

DDL retains two-second lock and 30-second statement limits. Downgrade removes only Phase 7 security
state/history; operational objects, ontology imports and earlier history remain. This is destructive
to security identities and must be planned with configuration/backup; an OIDC API cannot serve
protected operations against the downgraded database. Tests reverse disposable schemas only.
