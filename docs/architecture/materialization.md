# Dataset materialization boundaries

See [ADR 0040](../decisions/0040-governed-materialization.md) and
[API contracts](../api/mappings.md). PostgreSQL stores resource/version/run/provenance state; source
bytes stay in ArtifactStore. Operational objects, links, edit overlays, action audit and outbox retain
their existing canonical services. Open Ontologies remains an independent semantic engine.

The shared execution controller dispatches MATERIALIZATION jobs to the mapping adapter. Its spawned
child reads bounded Polars batches and creates a disposable disk index for converted identities and
edges. This index is attempt-local processing scratch, not a second authoritative database, object
store or execution queue. It never contains credentials. After full-source validation, the controller
preflights ownership/endpoints and processes objects then links in 100-target transactions.

Each transaction acquires current security/tenant/ontology locks, rechecks resource/dependency access,
and checks the job's token, lease and deadline before and after changes. Only ReconciliationService and
ObjectService mutate canonical state. Provenance and ownership insertion additionally require a live
transaction-local fencing token in PostgreSQL. A crashed attempt loses its lease; another worker
rebuilds staging from immutable input and skips committed run/target checkpoint identities.

Batches are immediately visible. A failed/cancelled run retains its prior mutations, metrics and
immutable provenance; it is never represented as an atomic successful generation. Query APIs retain
their existing visibility and authorization model. No schema or object identity is silently rebased
when an ontology version changes. A mapping must be explicitly republished for the newly active version.

The 1 GiB source limit remains, with independent decoded, record, batch, CPU, wall, RSS and temporary
limits inherited from Phase 14. Default mapping budgets are 100,000 objects and links, with an absolute
one-million cap on each. Source cardinality and target cardinality are separate. One provenance record
per run/target avoids per-cell amplification. Published history has no automatic retention purge.
Soft watchdogs on macOS are development safeguards; hard Linux container/cgroup and production target
certification remain separate Section 23B obligations.
