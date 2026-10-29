# ADR 0022: Fenced ingestion jobs and explicit atomicity

Status: Accepted for Phase 4

Use one PostgreSQL ingestion_runs row as run history and durable job, with immutable plan/principal/
schema/key, status, lease token, attempt limit and transactional checkpoints/counters. Claim through
FOR UPDATE SKIP LOCKED; reuse only the initiating server-configured principal with current
application authorization. Expired/stale workers cannot commit; successful steps renew leases.
No queue broker, workflow service or unrestricted background account is introduced.

Stage all proposals, validate duplicates, materialize objects, then materialize forward relationships.
Retain ontology-wide write locking and canonical object/link services. Check active schema before
every step; activation changes fail the run rather than reinterpret it. Commit operational effects,
identity/ownership state, stage transitions and checkpoints in the same batch transaction.

Provide bounded reject_run atomicity for up to 100 records. Reject_batch/quarantine commit bounded
batches and may preserve earlier objects when a later relationship batch fails. Mark that case
LINK_REJECTED rather than implying prior objects rolled back. Per-record savepoints isolate permitted
quarantine failures; authorization/transient errors roll back the batch. Cancellation fences the token
between steps and preserves committed batches. Actual subprocess kill/abrupt-exit tests complement
exception/lease tests. Three total claims and 40,000 steps per invocation bound recovery/work.
