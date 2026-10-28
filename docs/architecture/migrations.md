# Database migrations

Apply with `uv run alembic upgrade head`; inspect with `uv run alembic current` and
`uv run alembic check`. Readiness expects `0003_snapshot_locks`.

| Revision | Objects |
|---|---|
| 0001_tenants (Phase 0, unchanged) | Tenant ownership anchor |
| 0002_registry (Phase 1) | ontologies, ontology_versions, object_type_definitions, link_type_definitions, objects, object_links, schema_migration_plans, schema_activations |
| 0003_snapshot_locks (Phase 1) | Lock draft parent versions during type edits so publication cannot race immutability checks |

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
