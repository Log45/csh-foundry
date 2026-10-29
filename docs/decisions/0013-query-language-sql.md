# ADR 0013: Bounded query AST and schema-aware SQL

Status: Accepted for Phase 2

## Decision

Use Pydantic query contracts with raw nesting/size checks before recursive validation. Resolve every
property/operator against the active canonical snapshot. All JSON keys/values and identity predicates
use SQLAlchemy bound expressions. Typed numeric/temporal/UUID casts use CASE scoped to tenant,
ontology/type/version so planner predicate reordering cannot cast unrelated types' JSON values.
Use two-valued null-aware leaves; missing and JSON null share query null semantics but projections
preserve presence. SQL selects only approved keys, not whole JSONB for later redaction.
Arrays/JSON use structural equality; scalar decimals/timestamps use value semantics. Keep explicit
query complexity/page/group bounds and database statement budgets. No arbitrary SQL/SPARQL API.

## Consequences

Preserve all Phase 0/1 contracts, tenant boundaries and semantic fixtures.
See docs/api/queries.md and the Phase 2 report for limits and executed evidence.
