# ADR 0017: Measured status/identity indexes and retained transaction locks

Status: Accepted for Phase 2

## Decision

Measure manufacturing and 10,000 synthetic-machine workloads using EXPLAIN ANALYZE BUFFERS in a
disposable migrated schema. Add the justified status equality and bytewise identity ordering indexes. Use fixed-width hashes of
ontology/type/status after native tenant UUID, with exact identity/value rechecks in SQL. This avoids
B-tree key-size failures on valid long identifiers or future property types; collisions cannot add rows.
No numeric casts are embedded in index DDL, so future schema changes cannot break unrelated writes.
The identity ordering index uses the existing composite identity columns with explicit C collation.
The primary key uses database collation; without this index a 50-row page sorts the whole type.
Measured execution fell from 7.833ms to 0.222ms on 10,000 synthetic machines. Status equality
fell from 2.355ms to 0.537ms with its index alone (0.495ms with both). These are local warm-cache
samples, not production guarantees. No other JSONB property indexes are added.
Administrative Alembic creation is outside handlers and bounded by 2s lock / 30s statement timeouts;
a timeout rolls back the migration. Concurrent/background dynamic index jobs remain deferred.
Keep existing ontology shared-read/exclusive-write locking. Controlled contention is measurable;
there is no representative production evidence justifying a correctness-risking lock redesign.

## Consequences

Preserve all Phase 0/1 contracts, tenant boundaries and semantic fixtures.
See docs/api/queries.md and the Phase 2 report for limits and executed evidence.
