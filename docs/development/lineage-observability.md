# Governed lineage and observability contract

ADR [0046](../decisions/0046-lineage-observability.md) records the architectural boundary. PostgreSQL
canonical records remain authoritative. A version-1 derived edge index contains tenant-qualified source,
target and supporting origin resource identities, exact version/local node identities, relation,
DESIGN/EXECUTION mode, certainty, authoritative provenance and a database creation timestamp. It contains
no rows, artifact keys, draft documents, secrets or alternate authorization grants.

## Resource and edge catalog

RESOURCE nodes use the existing registry kind. PROJECT containment comes directly from persistent
registry Project ownership. ARTIFACT_VERSION and DATASET_VERSION retain physical/logical UUIDs.
PIPELINE_DEFINITION and TRANSFORM_NODE represent immutable v2 definitions and named closed operations.
EXECUTION nodes reference existing parent jobs; committed manifests establish successful outputs.
MAPPING_DEFINITION and schema-qualified ONTOLOGY_OBJECT_TYPE/ONTOLOGY_LINK_TYPE nodes cover published
mapping targets and actual materialization records, including partial batches. APPLICATION_VERSION
nodes use immutable published manifests, declared query object types and action bindings. AUTOMATION
and FUNCTION_DEFINITION pins represent immutable declared targets/event sources. Drafts are excluded.

HAS_VERSION and CONTAINS describe membership, never value derivation. DEPENDS_ON/BINDS_TO/INVOKES/
TRIGGERS describe published design dependencies. CONSUMES/EXECUTES/PRODUCES and MATERIALIZES_INTO
identify observed execution records. Failed/cancelled/prepared outputs never create successful output
provenance. Multi-output invalidation commits with the same PostgreSQL publication transaction; all
outputs index from that authoritative committed set. The index is asynchronous, so every graph includes
an explicit completeness marker. Completeness requires reconciled generations across visible resources.

Traversal is deterministic, deduplicates repeated identities and stops at enforced depth/node/edge/work
budgets. An inaccessible endpoint or supporting origin is pruned **before expansion**; there is no
placeholder, hidden identifier, hidden count or exported hidden path. Source, sibling outputs, schemas,
application dependencies and definition pins are independently checked through existing services.
Guessed/missing/private roots return the same governed 404. No graph read grants dataset byte access.

## APIs and integration

`POST /api/v1/lineage/traverse` accepts a typed root and explicit bounded traversal settings.
`POST /api/v1/lineage/impact` returns downstream dependencies and structured reasons/paths.
Resource index/reconcile, health/events, dataset freshness, pipeline-definition columns, execution
observations and dashboard endpoints are exported from actual FastAPI OpenAPI. The generated
`observability` SDK family and React hooks use existing session/principal/tenant cache isolation,
CSRF-protected BFF and classified read retries. Reconciliation/policy writes never auto-retry.
Existing Phase 14/20 dataset lineage and SDK APIs remain available.

## Column semantics

The implementation runs the actual Polars metadata planner over empty schema frames and propagates
source `(input name,column)` sets. Select/drop retain surviving values; rename changes output names;
cast/fill-null preserve source dependence; derive unions expression columns; aggregate includes keys
and aggregate inputs; union merges corresponding origins; join includes coalesced key values and both
key sets as ROW dependencies. Filter/deduplicate affect ROW dependencies; sort affects ORDER. Value
origins are separate from row/order dependencies. Constants have empty source sets. No dataset bytes
are loaded. Unsupported schema metadata returns UNSUPPORTED, limits return PARTIAL. Historical linear
definitions lack immutable source pins, so this definition-level endpoint reports UNSUPPORTED rather
than inventing pins; their run-level consumed versions remain available through execution lineage.

## Freshness and execution state

An optional governed policy has expected interval and/or maximum age, bounded 60 seconds–365 days.
No enabled policy is DISABLED; missing version/threshold is UNKNOWN. Database time and the last
COMMITTED version determine FRESH/STALE; a failed run cannot erase a successful version timestamp.
All DAG outputs use their atomic publication's committed version records. Policy mutation is audited.

Execution observations reuse real job states, attempts, timestamps, publication outcome and independently
filtered outputs. Durations/queue delays are derived only where timestamps exist. Node timelines and
allowlisted numeric metrics come from existing durable node records. Missing measurements are null/
UNAVAILABLE. Private binding visibility suppresses node identities and staging counts. Errors use fixed
safe categories; no raw exceptions, stack traces, paths, storage keys or environment values are returned.

Operational events record persisted state/attempt transitions transactionally. They are separate from
security audit, with resource/execution correlation, severity and database timestamps. They do not
replace current job state. Historical pre-migration transitions cannot be reconstructed and are not
fabricated. Event reads have a 90-day window; the trusted existing worker removes at most 500 expired
operational events per tick. Original audit and execution history are preserved.

Health/history and dashboards summarize persisted, authorized records within explicit pages/samples.
Counts are scoped to visible resources. Dashboard samples at most 500 jobs in a maximum 30-day range;
it reports truncation and does not promise exact tenant-wide totals. No second monitoring datastore,
scheduler, ontology engine, mutation engine, Prometheus, Kafka or Elasticsearch is introduced.

Canonical ontology type/action keys hash the ontology ID, exact schema version and entity ID, so
separate registered references to the same canonical type connect correctly. Each edge still retains
its own registry authorization scope; authorization cache keys include both canonical identity and
that scope. A public alias cannot authorize a private binding. Observed automation receipts establish
TRIGGERS edges and successful DAG manifests establish exact output-to-transform/source derivation.
