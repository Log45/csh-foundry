# ADR 0016: Materialized bounded-step traversal and one compiler

Status: Accepted for Phase 2

## Decision

Reuse forward links. Resolve each step's source/target/direction and authorize its link/type/grant.
Use materialized nonrecursive identity CTEs per step to prevent nested subquery join-order planning
explosion observed in PostgreSQL tests. Bound paths at four steps and return unique final identities.
Root, per-step and final filters share the same schema-aware compiler. SQL handles all graph work;
no in-memory collection filtering or recursive unbounded graph search. Internal immutable ObjectSet
builders emit this same AST and service path; no separate query/SDK implementation.

## Consequences

Preserve all Phase 0/1 contracts, tenant boundaries and semantic fixtures.
See docs/api/queries.md and the Phase 2 report for limits and executed evidence.
