# Phase 2 completion report — Operational Object Queries and Traversal

Phase: **2 only**, implemented 2026-10-28. Base revision:
`e46c3e75943d3cb4cce5c0d73d2d7a26e584f551`; Phase 2 changes are in the working tree.
Environment: macOS ARM64, Python 3.12.0, Docker PostgreSQL 17.6, locked uv dependencies.
No Phase 3 implementation, production authentication, ingestion, semantic materialization,
frontend, generated SDK, Rust accelerator or additional database is included.

## Implementation summary

Implemented a bounded Pydantic query AST, active-schema resolution, parameterized SQLAlchemy
compiler, JSONB filtering, Boolean composition, deterministic ordering, offset/keyset pages,
property projection, authorized multi-step traversal, five basic aggregates and an immutable
internal ObjectSet builder. All execution uses governed PostgreSQL transactions and the existing
active ontology registry. Existing CRUD/publication/activation/revision/link contracts remain intact.

Versioned POST routes under `/api/v1/ontologies/{ontology_id}`:

- `/objects/{type_id}/query`: path and root type must agree.
- `/object-sets/query` and `/traverse`: the same composable query contract.
- `/aggregate`: filtered/traversed, optionally grouped metrics.

Typed requests/responses and manufacturing examples are included in OpenAPI.
See [query API reference](../api/queries.md) for complete contracts and examples.

## Files created or modified

| Area | Significant files |
|---|---|
| Query implementation | `services/api/src/ontology_platform/queries/{ast,compiler,cursor,service,object_set,routes}.py` |
| Query authorization | New `security/query.py`; updated `security/local.py` |
| App/configuration | Updated `main.py`, `config.py`, `.env.example`, `infrastructure/compose.yaml` |
| Persistence | Updated `db/models.py`, `db/governance.py`, migration environment; new revisions `0004_query_index.py`, `0005_query_order.py` |
| Tests | New `services/api/tests/test_query_ast.py`, `test_queries.py` |
| Diagnostics | New `scripts/benchmark_queries.py`, `scripts/smoke_queries.py` |
| Documentation | New `docs/api/queries.md`, ADRs 0013–0017, this report, `docs/development/phase-3.md`; updated README/API/architecture/migration documentation |
| CI/evidence | Updated validation workflow name; existing full-suite runner discovers all new tests. Executed evidence in `docs/architecture/evidence/phase-2/` |

No fixture, canonical schema package, semantic adapter, dependency pin or existing regression test
was changed. Existing `queries/__init__.py` remains empty to avoid import cycles.

## Query language

Comparison nodes contain `property`, `operator`, `value`. Supported comparisons are eq, ne, gt,
gte, lt, lte; null operators are is_null/is_not_null; string operators are contains/starts_with/
ends_with. Boolean nodes use `and`, `or`, `not`. Requests additionally support root/per-step/final
filters, traversal, order_by, select, limit, offset/pagination mode and cursor. Unknown fields,
operators/properties, invalid scalar types and malformed Boolean structures are rejected.

| Bound | Value |
|---|---|
| Boolean depth / nodes / predicates | 8 / 128 / 64, shared across all request filters |
| One normalized JSON operand | 8,192 UTF-8 bytes |
| Names | 200 characters |
| Page / offset | 200 objects (default 50) / 10,000 |
| Sort / projection fields | 4 plus identity / 32 |
| Traversal | 4 explicit steps |
| Aggregation | 8 metrics, one grouping key, at most 100 groups |
| Explicit policy identity list | 1,000 IDs per object type |
| Cursor | 16,384 characters, one hour lifetime |

Operands retain canonical representations without coercion: decimal/date/timestamp/UUID strings,
strict integers/booleans, typed arrays and JSON. Scalar decimal and temporal comparisons use
numeric/instant semantics. JSON and arrays use structural JSONB equality; canonical string values
inside arrays compare by representation. Ordered comparisons require numeric/date/timestamp scalars.
String matching is case sensitive and escapes SQL wildcard characters. Enum membership constrains
stored data, not comparison thresholds. Sorting/grouping require supported scalar types.

Missing properties and explicit JSON null share query null semantics. Other leaves, including ne,
are false for either; NOT complements these two-valued leaves. Projections retain absence versus
explicit null and return only selected visible schema keys. Stable identity and revision metadata
remain present. Default projection includes only visible schema properties; schemas exceeding 32
visible properties require an explicit selection.

## SQL compilation

SQLAlchemy expressions bind values, JSON keys, tenant/ontology/type/version and all comparison
operands. No client-supplied identifiers or SQL fragments are interpolated. Every object alias and
edge is scoped to the current tenant, ontology, type and active schema. Typed JSONB extraction casts
are protected by CASE scope checks because PostgreSQL can reorder WHERE clauses; unrelated types
with the same JSON key cannot cause invalid numeric/temporal casts.

Filtering, traversal, grouping and aggregation execute inside PostgreSQL. Projection selects
individual JSONB keys and presence tests, rather than fetching full documents and redacting in
Python. Service operations retain the existing shared ontology lock, preventing concurrent activation
within one request. SQL statement budgets remain 3s in application engines (5s in test fixtures).
Database time/lock limits return structured 503 query_timeout errors. Unsupported operations and
schema validation failures return structured 422 errors; authorization failures return 401/403.

## Authorization

Existing Authorizer.require calls remain mandatory. A minimal QueryAuthorizer interface supplies
server-owned QueryGrant records containing a complete SQL row predicate and/or allowed identity
set, visible properties and policy revision. Legacy providers without SQL query grants fail closed.
The trusted local provider still grants access only to its server-configured tenant.

Restrictions apply to the root, every traversal target, projections, filters, sorting, grouping,
counts and aggregate properties. Link access is checked separately. Trusted policy predicates may
use hidden properties; client predicates cannot. Grants are copied/refreshed each request and bound
to cursors. Restricted rows are removed by SQL, never Python post-filtering. Test policies verify
hidden-property denials, restricted counts, hidden intermediate/final objects, policy changes and
cross-tenant reads/joins/cursors. Custom providers must keep query grants and legacy CRUD require
checks coherent. This interface is not a production RBAC/ABAC policy implementation.

## Pagination

Ordering uses validated scalar fields, NULLS LAST, C-collation strings and a stable ascending object
identity tie-breaker. Final type/tenant/ontology scope supplies the remaining composite identity.

Opaque HMAC-SHA256 cursors bind principal, tenant, ontology, root type, active schema, normalized
query, complete policy grants and the last identity/revision/typed sort tuple. Private policies and
sort values use domain-separated keyed digests, so tokens expose neither raw policy nor unselected
property values. Continuation reselects the authorized anchor, verifies it is unchanged and applies
real lexicographic keyset predicates. Incompatible/tampered/expired cursors return 400; a changed
active schema returns 409 cursor_schema_changed; a changed/deleted/invisible anchor returns 409
cursor_stale. Page size/projection/filter/path/order must remain identical.

This is **not snapshot pagination**. Non-anchor mutations can move objects and cause skips/repeats
between requests. A stable configured secret (at least 32 UTF-8 bytes) shares validity across
processes/restarts; otherwise process-random keys invalidate tokens on restart. Explicit offset mode
is bounded and emits no cursor, including at offset zero. Very large identities can exceed token
bounds and must use offset mode.

## Traversal

Root filters address the root type; per-step filters address the target; result_filter, selection,
ordering and aggregates address the final type. Forward link IDs accept forward/inverse direction;
declared inverse names preserve Phase 1 navigation semantics. Source/target/type/direction are
validated against the active schema.

Each step uses an authorized, deduplicated materialized identity CTE over the existing forward-edge
records. Materialization avoids the planner join-order explosion observed with nested subqueries
at three steps. Explicit maximum depth four and set semantics bound cycles and duplicate paths.
Intermediate SQL sets are subject to the database time budget, rather than silently truncated.
No recursive arbitrary-depth search, redundant inverse rows or graph database is introduced.

## Aggregations

count, sum, avg, min, max operate over the complete authorized filtered/traversed set. count without
a property counts objects; count(property) excludes missing/null values, including JSON/arrays.
sum/avg accept numeric scalars; min/max accept numeric/string/date/timestamp scalars. Grouping
accepts one sortable scalar. Excess grouping cardinality returns an error rather than partial totals.

Null/missing values form one null group and are excluded from property aggregates. Empty ungrouped
sets yield count zero and null other metrics; empty grouped sets yield no groups. Results carry
explicit canonical data_type/value: decimals and integer averages are strings, integer sums/counts
are integers, float results are floats, and temporal values are ISO strings. PostgreSQL arithmetic
precision applies. UUID/boolean min/max, array ordering and arbitrary analytical expressions are
unsupported.

## Performance

| Workload | Fixture-only SQL ms | 10,063 objects before indexes | With both indexes | Final plan highlights |
|---|---:|---:|---:|---|
| CRITICAL status equality | 0.094 | 2.355 | 0.495 | Status index + primary-key nested loop + small sort |
| Numeric temperature range | 0.040 | 5.763 | 3.864 | C-order index scan + primary-key nested loop, early limit |
| Temperature descending, 50 rows | 0.060 | 10.016 | 10.231 | Scoped sequential scans/hash join + top sort |
| Identity order, 50 rows | 0.045 | 7.833 | 0.222 | C-order index scan + primary-key nested loop, early limit |
| Factory → Machines, 50 rows | 0.100 | 0.778 | 0.781 | Materialized CTE + ix_link_target + identity indexes |
| Machines grouped by status | 0.050 | 6.513 | 6.545 | Scoped sequential scans/hash join + grouped aggregate |

Cursor continuation application wall time: 18.513ms before, 11.640ms with both indexes. Status lookup alone: 0.537ms. These times include only the stated workloads.

The benchmark loads the canonical 63 objects/70 forward links through governed services, then
adds 10,000 synthetic machines and 300 machine→factory links in a disposable migrated schema.
Total measured dataset: 10,063 objects and 370 links. Each SQL measurement is the median of three
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) runs after ANALYZE, on warm local Docker caches.
Application times additionally include authorization, registry resolution, SQL round trips and
serialization; they are single observations, not a load-test percentile or production guarantee.

Evidence: [full plans and measurements](../architecture/evidence/phase-2/query-plans.json),
[benchmark output](../architecture/evidence/phase-2/benchmark-run.txt).
The script drops candidate indexes **only in its private temporary schema** for before/after
comparisons; it never changes operational tenant data or live indexes.

The measured status predicate uses a tenant-scoped fixed-width md5 lookup index plus exact
ontology/type/value rechecks. Hash collisions cannot broaden results. The C-collation identity
index eliminates full-type sorting for default pages; the database-collation primary key alone
cannot satisfy that ordering. Existing target traversal/identity indexes remain useful. Numeric
range/sort and aggregates still scan their authorized candidate set; these local measurements do
not justify indexing every property. Numeric cast indexes could also constrain future schemas.
Property indexed requests remain canonical metadata; automatic dynamic index jobs are deferred.
The safe Phase 2 path is version-controlled, administratively applied bounded Alembic DDL.

A controlled 100ms shared ontology lock blocked a writer, whose measured wall time was
116.822ms including database/application overhead.
Existing coarse ontology locks are retained: one synthetic hold demonstrates contention, not a
representative production workload warranting a change to activation/cardinality guarantees.

## Database migrations

- `0004_query_index`: adds ix_objects_status_lookup on tenant UUID and fixed-width ontology/type/
  operationalStatus digests. Exact rechecks remain mandatory. No numeric casts or new data tables.
- `0005_query_order`: adds ix_objects_query_order on existing composite identity columns, using
  explicit C collation for object_id. No additional property data/type constraint.

Both upgrades/downgrades use transaction-local 2s lock and 30s statement timeouts, roll back on
failure and preserve operational rows. Downgrade drops only indexes; previous schema revisions
remain applicable. Full upgrade→downgrade→upgrade tests run in disposable PostgreSQL schemas.
Alembic's specific COLLATE reflection workaround checks actual pg_get_indexdef before suppressing
a false difference; correct and deliberately incorrect collation definitions are regression-tested.
Local development database is at `0005_query_order` and `alembic check` reports no drift.
See [migration reference](../architecture/migrations.md).

## Architecture decisions

ADRs [0013](../decisions/0013-query-language-sql.md)–[0017](../decisions/0017-query-index-measurements.md)
record schema-resolved bound SQL/null behavior, SQL query grants, signed anchor cursors, materialized
bounded traversal/shared ObjectSet compilation and measured indexes/retained locks. PostgreSQL
remains authoritative; canonical schemas and deterministic RDF identities are unchanged.

No dependency was added or upgraded. Open Ontologies remains v2.1.0 at the pinned commit,
subprocess adapter unchanged; owl-rl-ext inference remains working. Protégé compatibility remains
the existing OWLAPI 4.5.29 harness, not a deployed GUI/WebProtégé integration. Exact existing pins,
licenses and limitations remain in [the compatibility matrix](../architecture/semantic-compatibility.md).

## Validation results

The **pre-implementation baseline** executed `uv run python scripts/validate_phase0.py`:
84 passed, one expected pySHACL failure; lint, formatting, strict mypy and Alembic check passed.
No preexisting unexpected test failure was observed. Raw pySHACL incompatibility, base owl-rl
inference limitation and the TestClient deprecation warning were already present.

The final full runner executed successfully: **154 passed, 1 xfailed, no skips**, 155 collected,
41.16s. Ruff checked/formatted 68 files; strict mypy checked 46 source files. No unexpected newly
introduced failure remains. Statuses below describe executed checks, not future/MVP claims.

| Check | Result | Evidence / limitation |
|---|---|---|
| Python imports, canonical valid/invalid models and identity mapping | PASS | Full suite; canonical package unchanged |
| PostgreSQL connectivity, schema publication/immutability/activation rollback | PASS | Existing real-PostgreSQL Phase 1 regressions |
| CRUD/revisions/multi-object rollback/endpoint integrity/cardinality | PASS | Existing Phase 1 suite retained |
| Query AST/operators/type/depth/size bounds | PASS | New unit and PostgreSQL tests |
| SQL binding/injection/scope/JSONB casts/null/string semantics | PASS | Compilation and real-PostgreSQL tests |
| Sorting/ties/keyset/offset/cursor binding/schema/policy/mutation checks | PASS | New PostgreSQL and cursor tests |
| Projection/property visibility/cross-tenant rejection | PASS | Restricted policies, overlapping tenant identities |
| Forward/inverse/multi-step/cyclic traversal | PASS | Manufacturing links; intermediate/final denials |
| Five aggregates/group counts/nulls/unauthorized exclusion | PASS | Manufacturing and canonical-datatype integration cases |
| ObjectSet lazy composition and API contracts | PASS | Same service/AST for HTTP and internal builders |
| Alembic upgrade/downgrade/head/drift including index collation | PASS | Temporary schemas, head 0005, check no drift |
| pytest | PASS | 154 passed, 1 expected failure; [log](../architecture/evidence/phase-2/validation.txt) |
| Ruff lint / formatting / strict mypy | PASS | Full runner, same log |
| Host Uvicorn startup/health/readiness/OpenAPI/trusted query/cursor/traverse/aggregate | PASS | [HTTP smoke](../architecture/evidence/phase-2/http-smoke.txt) |
| Docker API build and startup smoke | PASS | [Build](../architecture/evidence/phase-2/docker-build.txt), [smoke](../architecture/evidence/phase-2/docker-smoke.txt); readiness/OpenAPI 200, absent principal query 401 |
| Turtle parsing / CSV counts, identities and foreign references | PASS | Existing RDFLib/Polars fixture tests |
| Fixture bytes / canonical and semantic preservation | PASS | [Integrity checks](../architecture/evidence/phase-2/integrity.txt) |
| Raw unmodified pySHACL conformance | FAIL | Preserved expected failure: simple literals versus xsd:string sh:in terms; no fixture edits |
| In-memory RDF 1.1-normalized SHACL baseline/negative cases | PASS | Existing test harness; not a claim that raw pySHACL conforms |
| Open Ontologies fixture parse/SHACL/diagnostics | PASS | Existing semantic tests executed against pinned binary |
| CriticalMachine inference with owl-rl-ext | PASS | All three critical machines, ordinary machines excluded |
| Equivalent inference with base owl-rl | NOT SUPPORTED | Executed profile comparison documents missing fixture rules |
| Protégé-compatible OWL import/export | PASS | [OWLAPI harness](../architecture/evidence/phase-2/protege.txt), RDF/XML round trip; extra xsd:date declaration recorded |
| Protégé GUI / WebProtégé deployment | NOT RUN | No expansion required in Phase 2; existing file harness used |
| Representative EXPLAIN plans/index/lock measurements | PASS | Reproducible private-schema benchmark and plan JSON |
| GitHub Actions remote run / act | NOT RUN | gh/act unavailable; workflow requires push/PR, no remote run requested; equivalent local runner executed |
| Actions/reconciliation, Polars operational ingestion, materialization | NOT RUN | Later approved phases, not Phase 2 |
| Production authentication/authorization deployment | NOT RUN | Trusted local development model only |

A first Docker HTTP probe raced process startup and disconnected; retrying after actual liveness
succeeded. This was a smoke-harness timing issue, not a suppressed application failure. Temporary
integration/benchmark schemas and host smoke processes were cleaned up; API container was stopped.
PostgreSQL remains running. No existing tenant data was overwritten or removed.

## Known limitations

1. Cursor pages are deterministic for unchanged data, not multi-request snapshots; anchor changes
   explicitly require restart. Stable shared signing configuration is required across workers.
2. The local principal is an explicit tenant administrator. Production policy administration and
   authentication remain deferred; custom query providers must express complete restrictions in SQL.
3. Traversal/aggregate input sets are bounded by schema/step/complexity/time limits, not a guaranteed
   intermediate row cap. Dense graphs or large groupings may return timeouts/errors. No distributed
   execution, arbitrary recursion or analytical SQL engine is claimed.
4. Numeric sorts and aggregates scan scoped JSONB candidate sets. Two measured indexes are added;
   dynamic property-index worker orchestration and concurrent large-database builds remain deferred.
5. Existing Phase 1 activation limits (1,000 objects/5,000 links) and ontology-wide write serialization
   remain. The synthetic benchmark activates before loading 10,000 objects; it does not claim that
   large-schema activation has become supported.
6. Canonical array/JSON equality is structural; decimal/timestamp strings inside arrays are compared
   by representation. Scalar numeric/temporal comparisons retain canonical value semantics.
7. Raw pySHACL mismatch and base owl-rl limitations remain visible. Full authoring translation,
   materialization, production security and end-to-end ingestion/action MVP validation are not claimed.
8. Existing Starlette/httpx TestClient deprecation and Java harness warnings remain; dependencies
   were not changed speculatively in this query phase.

## Phase 3 readiness

Ready for separately approved Phase 3 work within the documented development/activation bounds.
No unresolved implementation defect blocks that phase. Before production use, production security,
workload admission, durable work/index handling and larger activation/migration execution remain
necessary later work. Phase 3 action execution has **not** begun.

## Recommended Phase 3 tasks

Follow the ordered [Phase 3 implementation checklist](phase-3.md): inert action contracts; tenant-safe
execution/idempotency/audit/outbox migrations; governed transactional operations; execution-time
authorization; pure previews; edit overlays/reconciliation; durable delivery/retry boundaries; action
routes; manufacturing atomicity/idempotency/security tests; measured locks; complete regressions
and a Phase 3 report. Separate approval is required before implementing any of these tasks.
