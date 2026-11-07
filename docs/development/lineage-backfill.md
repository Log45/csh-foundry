# Historical lineage backfill and reconciliation

Migration 0027 installs transactional invalidation triggers on canonical resource/version/definition/
execution tables and creates one pending generation/checkpoint per existing resource. API/worker
publication does not depend on an HTTP background task. The existing execution controller advances
at most four pending resources per tick; failure leaves dirty generations visible to readers.

`GET /api/v1/resources/{id}/lineage/index` reports completeness. `POST .../reconcile?batch=50`
requires Project write authority and advances at most 100 authoritative records. Its keyset cursor is
private. The index merges bounded pages from artifact, dataset, pipeline, mapping, application,
automation/function and execution tables. Stable edge hashes plus insert-on-conflict make resumption
and repeated reconstruction idempotent. Edges are append-only. A new canonical change resets that
resource's checkpoint and increments its generation in the same publication transaction. Do not edit
immutable source versions or mark a dirty generation complete manually.

Completeness is conservative across visible registry resources, because downstream edges may belong
to another resource's publication. Hidden resources are not counted or identified. A partial graph
must not be interpreted as absence of a dependency. Reconciliation never reads dataset/artifact bytes
and cannot create successful outputs for failed, cancelled or PREPARED manifests.

Reconstructible history: committed physical/logical versions; immutable v2 source pins, transformations
and existing output targets; historical execution inputs and successful legacy/DAG output manifests;
published mapping target types and actual persisted partial materialization type records; immutable
published application manifests/query types/actions; immutable automation targets/event sources.
Unrecoverable history is explicit: old linear definitions without source pins have no design-time
version provenance; missing worker measurements/attempt transitions are unavailable; pre-0027 operational
state transitions are not fabricated; query result objects are never treated as materialized provenance.
No per-cell, arbitrary connector or undocumented semantic-engine provenance is inferred.

Recover by replaying canonical records with the same versioned projection. A new projection algorithm
requires an explicitly versioned reconciliation/migration plan; do not silently rewrite historical
edges. The existing append-only index has no general user-supplied edge insertion endpoint.

The final projection uses a private `v1|` checkpoint prefix. The controller selects either dirty
resource generations or older/unversioned checkpoints, including rows whose counters were already
equal. Reconciliation writes the current prefix only after reading canonical records. This permits
recovery of history indexed before the final projection without rewriting source definitions. An
explicit governed reconcile request restarts a completed resource scan; repeated edge insertion is
idempotent and the request is audited.
