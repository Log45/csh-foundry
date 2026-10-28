# Phase 1 task breakdown — requires separate approval

1. Add tenant provisioning/bootstrap application service and trusted-local development context.
2. Add tenant-owned ontologies, immutable version snapshots and canonical metadata definitions
   through Alembic; use tenant-safe composite unique keys and foreign keys throughout.
3. Implement schema registry validation and services for draft creation and explicit publication.
4. Add additive/breaking schema comparison, approved migration plans, data validation and atomic
   activation with one active published version; failed migrations retain the old active version.
5. Add JSONB object storage with composite `(tenant, ontology, type, object)` identity, revision
   and aware timestamps; enforce canonical property validation and stable primary keys.
6. Add link persistence with tenant-safe endpoint foreign keys and transactional cardinality checks.
   Store forward edges once; expose inverse navigation without redundant copies.
7. Add governed tenant-scoped CRUD services and initial versioned REST endpoints; require
   principal/authorization interface decisions before all reads and writes.
8. Add expected-version optimistic concurrency, structured conflicts and atomic multi-object rollback.
9. Run manufacturing persistence integration tests on real PostgreSQL: 63 stable identities,
   duplicate rejection, invalid property rejection, endpoint integrity and failed transaction rollback.
10. Test cross-tenant reads/writes/joins/counts/links and explicit job/export context boundaries;
    test immutable publication and failed activation/migration behavior.
11. Update API docs, ADRs and phase report; run every applicable fixtures/VALIDATION.md check.

No Phase 1 APIs, objects/links tables, ingestion, action execution or compiler are implemented in Phase 0.
