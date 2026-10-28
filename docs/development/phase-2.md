# Phase 2 implementation checklist — separate approval required

1. Re-read AGENTS.md, PLANS.md, fixtures/VALIDATION.md, Phase 1 report and ADRs; run the current
   Phase 0/1 validation suite before changing persistence or API contracts.
2. Define a typed query AST for equality/inequality, numeric comparisons, Boolean combinations,
   null checks and string matching. Set explicit operator/type compatibility and complexity bounds.
3. Resolve every property against the active published schema. Reject unknown properties/operators
   and invalid operand types. Keep tenant/principal context mandatory and server-derived.
4. Compile ASTs with SQLAlchemy expressions and bound SQL parameters, including JSONB access.
   Never interpolate untrusted identifiers or values. Preserve canonical decimal/timestamp semantics.
5. Add deterministic sorting with composite identity tie-breakers, bounded pagination and a cursor
   contract tied to active schema/sort fields. Define behavior when a schema activates mid-pagination.
6. Add typed property projection and enforce authorization before selecting/returning fields.
   Keep inaccessible objects/properties out of traversal and aggregate outputs.
7. Extend existing direct/inverse navigation to validated bounded multi-step traversal only as required
   by the plan; retain one forward edge and existing endpoint/cardinality/tenant guarantees.
8. Add scoped basic aggregates with explicit null/type rules and authorization behavior. Prevent counts
   from revealing inaccessible tenants/objects. Do not add a separate analytical database.
9. Add versioned structured query endpoints and OpenAPI examples using manufacturing vocabulary.
   Preserve existing single-object CRUD and opaque-ID query-parameter lookups.
10. Measure PostgreSQL EXPLAIN plans/latency for representative manufacturing and synthetic fixtures;
    choose targeted indexes for measured predicates. Persist index requests and define a safe bounded
    or later-worker index-creation path; avoid blanket GIN indexes and unnecessary infrastructure.
11. Evaluate ontology-wide write-lock contention using evidence before changing locking. Retain
    transactional activation/cardinality/uniqueness and expected-revision behavior during any refinement.
12. Add real PostgreSQL tests for status/temperature filters, sort/page determinism, projections,
    forward/inverse traversal, invalid ASTs, parameter binding, cross-tenant queries/joins/counts,
    policy denials and active-schema changes. Run the full existing suite and semantic regressions.
13. Document API contracts, SQL compilation decisions, query performance limits and validation evidence;
    produce the Phase 2 report and stop for approval before Phase 3.

Do not implement actions, ingestion, full semantic materialization, Studio, SDKs, Rust or production
OIDC as part of Phase 2. They retain their existing roadmap phases.
