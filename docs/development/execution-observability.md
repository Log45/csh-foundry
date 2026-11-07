# Execution observability

The existing execution_jobs and DAG node/manifest tables own state. Read
`GET /api/v1/observability/executions/{job_id}`, resource `/health`, `/events`, and the bounded dashboard
through the authenticated API/SDK/BFF. Execution identity correlates safe operational state events.

The response distinguishes parent state from atomic publication state and returns only independently
authorized committed outputs. Node timelines expose actual state/attempt/start/completion and derived
durations; numeric metrics are allowlisted from measured records. No percentages, fencing tokens,
staging object identities, raw requests, principals, secrets, stack traces or filesystem paths are
returned. Restricted callers cannot see node metadata or staging counts for hidden bindings.

Health and execution pages are bounded; null duration/queue delay means missing timestamps. Last
success/failure and consecutive failures are scoped to the selected history page, explicitly marked
when older history exists. Partial materialization retains its actual batch metrics and existing
visible-transactional-batch semantics; failed/cancelled work is not rolled back by a dashboard.

State/attempt events begin at migration 0027, in the same canonical transaction as job changes. There
is no fabricated pre-migration retry timeline. Errors map to fixed safe classes, with unknown failures
falling back to EXECUTION_FAILED. Operational events do not replace the authorization audit log or
current job state. Ninety-day visibility and bounded deletion are separate from immutable job/audit
retention. No production observability/SLA certification follows from local measurements.
