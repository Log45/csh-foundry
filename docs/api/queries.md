# Phase 2 operational queries

All routes use the same server-configured trusted principal and tenant as Phase 1. No request
can select tenant identity. Queries resolve the active published schema inside a governed,
shared-ontology-lock transaction. Existing CRUD endpoints and contracts are retained.

| POST endpoint under /api/v1/ontologies/{ontology} | Request / response |
|---|---|
| /objects/{type}/query | QueryRequest / QueryPage; path type must equal root object_type |
| /object-sets/query | Same QueryRequest / QueryPage |
| /traverse | Same QueryRequest / QueryPage, with traversal steps |
| /aggregate | AggregateRequest / AggregateResult |

OpenAPI includes manufacturing examples. There is no SQL, SPARQL, expression-evaluation or
arbitrary JSON-key endpoint.

## Query contract

```json
{
  "object_type": "Machine",
  "filter": {"and": [
    {"property":"operationalStatus","operator":"eq","value":"RUNNING"},
    {"property":"temperatureCelsius","operator":"gt","value":"80"}
  ]},
  "order_by": [{"property":"temperatureCelsius","direction":"desc"}],
  "select": ["machineId","machineName","operationalStatus"],
  "limit": 50
}
```

The decimal threshold is a **string**, matching the Phase 0 canonical representation. Integer,
float and boolean operands retain their strict canonical JSON types. Date/timestamp/UUID/decimal
operands use canonical strings; timestamps require offsets. Arrays require typed JSON lists.
Object properties returned in projections keep their original canonical JSON representation.

Comparison leaves use `property`, `operator`, `value`. Operators are `eq`, `ne`, `gt`, `gte`,
`lt`, `lte`, `is_null`, `is_not_null`, `contains`, `starts_with`, `ends_with`. Boolean nodes
are `{"and":[...]}`, `{"or":[...]}`, `{"not":...}`. Empty Boolean lists and comparison null
operands are invalid; use a null operator, which accepts no operand or an explicit null.

- Equality/inequality: all supported canonical types. JSON and arrays use PostgreSQL JSONB
  structural equality; array order matters, and decimal/timestamp strings inside arrays compare
  by representation. Scalar decimal/timestamp values use numeric/instant semantics.
- Ordered comparisons: integer, float, decimal, date, timestamp scalars only.
- String operators: scalar strings only; literal case-sensitive substring/prefix/suffix matching.
  `%`, `_` and backslash are escaped, not treated as user SQL wildcards.
- Comparison operands must match canonical types/precision/length; string search needles use the
  general operand bound. Enum membership is a data constraint,
  not a restriction on comparison bounds (e.g. a partial string or an absent status can be queried).
- Missing keys and explicit JSON null both satisfy `is_null`; neither satisfies `is_not_null`.
  All other leaves, including `ne`, are false for either null state. Boolean NOT complements those
  two-valued predicates, so `not(eq(...))` can include nulls. A stored string `"null"` is not null.
- Projections preserve the distinction: absent keys are omitted; explicitly null values stay null.

Only active-schema properties may be used. Unknown properties/operators, invalid types and
unsupported operations are rejected. Sort/filter/projection/group/aggregate property visibility
is checked before SQL execution. `select` omitted returns all **visible schema-defined** properties;
`select:[]` returns identity/revision metadata only. Unknown stored JSON keys are never returned.
Object identity is always visible for authorized objects; hiding a primary-key property does not
hide the identity itself. Hiding identities requires a row restriction.

## Limits

| Dimension | Maximum |
|---|---|
| Boolean nesting | 8, checked before recursive union validation |
| Predicates across root/result/step filters | 64 |
| Boolean nodes | 128 |
| Normalized UTF-8 JSON operand | 8,192 bytes |
| Property/type/link name length | 200 characters |
| Result page | 200 objects; default 50 |
| Offset | 10,000 |
| Sort fields | 4 plus mandatory identity tie-breaker |
| Projection fields | 32 |
| Traversal steps | 4 |
| Aggregates | 8 metrics; one grouping property |
| Group results | 100; exceeding the requested max_groups is an error, never silent truncation |
| Explicit authorization identity set | 1,000 IDs per type; predicates/allow-all also supported |
| Cursor | 16,384 characters; one hour lifetime |

SQL runs with the existing application statement budget (3 seconds; isolated PostgreSQL test
fixtures use 5 seconds). Traversal intermediates/aggregation input are evaluated inside PostgreSQL,
not page-limited or Python-filtered. Large/dense workloads may time out rather than consume
unbounded handler time. Full production workload admission control remains later work.

## Ordering and pagination

`order_by` accepts ascending/descending sortable scalar properties: numeric, string, boolean,
date, timestamp and UUID. JSON/arrays are not sortable. Nulls are always last. Text/identity uses
PostgreSQL `C` collation. Object identity ascending is the final stable tie-breaker; the query
already fixes tenant, ontology and final object type.

Default `pagination:"cursor"` emits `next_cursor` when `has_more` is true. Continue with the
same normalized request plus `cursor`. Selection, filter, path, page size and ordering must match.
`pagination:"offset"` disables cursor emission, including at offset zero; nonzero offset requests
also do not emit a cursor. Cursor and nonzero offset cannot be combined. Offset is bounded.

Tokens are HMAC-SHA256 signed and bind tenant, principal, ontology, root type, active schema,
normalized query and complete per-type keyed policy fingerprints. They include the last returned identity,
object revision and a keyed digest of the observed typed sort tuple. They contain **no sort/property values**.
Continuation reselects the anchor through current SQL authorization/filters and reconstructs the
sort tuple; it rejects deleted, invisible, updated or changed anchors. Actual page selection uses
lexicographic keyset predicates, not an offset disguised as a cursor.

- Invalid/tampered/expired/incompatible query/policy/context cursor: 400 `invalid_cursor`.
- Active schema changed: 409 `cursor_schema_changed`; restart the query.
- Anchor changed/deleted/no longer in the set: 409 `cursor_stale`; restart.
- Identity too large for a bounded token: 422 `cursor_too_large`; use explicit offset pagination.

This is deterministic ordering under unchanged data, **not a multi-request snapshot**. Non-anchor
mutations can cause skips/repeats or changed values between pages. Each request uses current state.
Configure `FOUNDRY_QUERY_CURSOR_SECRET` with a random secret of at least 32 UTF-8 bytes to share a
key across restarts/processes. If omitted, the API process generates a private random key and
restart invalidates its tokens. Do not commit a real key. No cursor state table is added.

## Traversal

```json
{
 "object_type":"Factory",
 "filter":{"property":"factoryId","operator":"eq","value":"FAC-005"},
 "traverse":[
   {"link":"containsMachine","filter":{"property":"operationalStatus","operator":"eq","value":"CRITICAL"}},
   {"link":"hasMaintenanceTask"},
   {"link":"assignedEmployee"}
 ],
 "select":["employeeId","employeeName"],
 "limit":50
}
```

The root filter addresses the root type. Each step's optional filter addresses its target type.
Optional `result_filter`, selection, sorting and metrics address the final type. Forward IDs support
`direction:"inverse"`; declared inverse names imply inverse navigation, matching Phase 1. Wrong
source types, unknown/ambiguous names and unsupported directions are rejected.

Each step is a materialized nonrecursive CTE of authorized target identities joined to existing
forward edges. Tenant/ontology/schema/type restrictions and target row grants apply at every step.
Link access is authorized before use. Set semantics deduplicate identities, including multiple
paths and bounded cycles; a cyclic four-step path terminates after four steps. No inverse rows or
graph database are introduced. Response object_type identifies the final type.

## Aggregation

```json
{"object_type":"Machine","group_by":"operationalStatus",
 "metrics":[{"name":"machines","operator":"count"},
            {"name":"averageTemperature","operator":"avg","property":"temperatureCelsius"}]}
```

Aggregations accept the same root/path/result filters and current SQL grants. `count` without a
property counts authorized objects; with a property it counts nonmissing/nonnull values, including
JSON/arrays. `sum`/`avg` require numeric scalars. `min`/`max` support numeric, string, date and timestamp
scalars. Grouping supports one sortable scalar property. UUID/boolean min/max, arrays/JSON ordering,
multiple group keys, arbitrary analytical expressions and aggregate cursors are unsupported.

Missing and explicit null values form one null group and are excluded by property aggregates.
An empty ungrouped set returns count 0 and null sum/avg/min/max. Grouped empty sets return no groups.
Results carry `data_type` and `value`; decimals (including integer averages) return strings,
integer counts/sums return integers, float results remain floats, and temporal results are ISO
strings. PostgreSQL numeric arithmetic/average precision applies; no unlimited-precision promise.

## Internal Object Sets

```python
from ontology_platform.queries.object_set import ObjectSet

machines = (ObjectSet.objects(query_service, principal, "manufacturing", "Machine")
    .filter(operationalStatus="RUNNING")
    .filter(temperatureCelsius__gt="80")
    .order_by("temperatureCelsius", descending=True)
    .select("machineId", "machineName")
    .limit(50))
page = machines.execute()
```

Builders are immutable/lazy; execution uses the exact same QueryRequest and QueryService as HTTP.
`where(Predicate/All/AnyOf/Negation)` supports explicit AST composition. Filters after traversal
apply to the last target step, so subsequent traversal preserves intermediate filters. Traversal
resets ordering/projection to avoid applying the old element type's fields to the new type.
`after(token)` and `offset(n)` provide pagination; limits always bound the final returned page.
`aggregate(Metric(...), group_by=...)` applies to the complete filtered set, not its current page.
This is an internal application abstraction, not a generated or network SDK.

## SQL authorization interface

Phase 1 `Authorizer.require` remains in force. New query-capable providers implement
`QueryAuthorizer.query_grant(principal, ontology_id, object_type)` returning a server-owned
`QueryGrant`: optional complete row predicate, optional allowed identities, optional visible
properties, and policy revision. Legacy providers lacking this capability are denied query access.
The default LocalAuthorizer grants all properties/objects **inside the configured tenant only**.

A query grant is the authoritative set-level read restriction and must express every applicable
object/property restriction; arbitrary per-row Python callbacks cannot be inferred or post-filtered
safely around counts and pagination. Trusted policy filters may reference hidden fields; client
filters cannot. Grants are refreshed/copied each request and included in cursor binding. Providers
must keep require and query_grant consistent for legacy CRUD and new queries. This extends an
interface for query security; it does not add production RBAC/ABAC/OIDC or a policy administration UI.
