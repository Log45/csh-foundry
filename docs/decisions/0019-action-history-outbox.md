# ADR 0019: Durable retries, redacted history and leased delivery

Status: Accepted for Phase 3

Use committed execution rows as the idempotency registry, rather than a redundant second table.
Scope hashed keys by tenant/principal/ontology and bind normalized parameters, action hash and
schema version. Retry against the original immutable definition, returning its original committed
result even after activation changes. Failed rollbacks leave no reservation; uncertain clients
retry the same key. Keep successful history indefinitely in this foundation.

Execution/audit rows reject UPDATE/DELETE through database triggers. Capture identities, actor,
revisions and changed property names, omitting property values/parameters. This is append-only
application history, not tamper-proof evidence. Failed requests are not durable execution rows.

Insert one redacted action.committed outbox event atomically with execution. A minimal tenant-scoped
runner claims with SKIP LOCKED, records an attempt and commits a 60-second lease before HTTP. Pin
public HTTPS destination addresses, validate TLS, reject redirects/private addresses, limit socket
timeouts and retry at most five claims. Persist UNKNOWN attempts for crash recovery; use tokens
to reject stale completions and stable event IDs for consumer deduplication. Delivery is at least
once. No broker, distributed workflow engine or external write inside the action transaction.

One configured destination and one category are sufficient for this phase. Signing, fan-out,
scheduler orchestration, pre-commit external hooks and an operator dead-letter UI are deferred;
none is implied by a committed outbox row. DNS resolution still follows OS resolver timing.
