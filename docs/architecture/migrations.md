# Database migrations

Apply with `uv run alembic upgrade head`; inspect with `uv run alembic current` and
`uv run alembic check`. Readiness expects `0005_query_order`.

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
