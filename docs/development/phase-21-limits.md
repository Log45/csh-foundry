# Phase 21 operator limits

Production remains **BLOCKED / NOT PRODUCTION-CERTIFIED** under PLANS.md §23B.

| Boundary | Hard limit / behavior |
| --- | --- |
| Traversal depth | 8 (default 3; Studio requests 6) |
| Nodes | 200 (default/Studio 100) |
| Edges | 400 (default/Studio 200) |
| Internal examined edges | 2,000; at most 500 candidates per frontier identity |
| Concurrent graph queries | Four PostgreSQL advisory transaction slots, plus existing tenant governance serialization |
| Impact paths | 100 deterministic witness paths, one per reached identity |
| Column dependencies | 1,000; PARTIAL when the record limit is reached |
| Definition graph size | Existing Phase 20 100 transforms, 16 sources/outputs and AST/byte limits |
| Backfill batch | 1–100 canonical records; default 50 |
| Controller reconciliation | Four pending resources per tick; bounded merged source pages |
| Backlog coalescing | One durable pending row per resource, with generations; no per-heartbeat queue growth |
| Event/history page | 100 records; offset at most 10,000 |
| Operational event visibility/retention | 90 days; at most 500 expired events removed per controller tick |
| Dashboard range | 1–30 days, default 7 |
| Dashboard executions | 500 most recent authorized jobs; truncation reported |
| Health | Latest requested page; last success/failure/consecutive failures are page-scoped |

These are metadata limits, not performance guarantees. Queries use existing per-statement database
budgets and fail closed on capacity/timeouts. Index lag is reported instead of presenting missing
history as complete. Scope pruning precedes graph expansion and aggregates. Private node identities,
sibling counts and staging details are not exposed. Prepared objects are never published datasets.

No client may override execution budgets, index batch ceilings or graph limits. Existing Phase 20
1 GiB source/2 GiB memory/4 GiB temporary storage and atomic publication limits remain authoritative.
The index reads metadata only. Historical column lineage without immutable source pins is unsupported.
No per-cell lineage, invented per-node percentage or inferred application-result materialization.

Current operational limits requiring further work are recorded in the phase report, including any
unexecuted acceptance workflows; this document does not confer acceptance or production certification.
