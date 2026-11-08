# ADR 0047: job-scoped worker authority

Date: 2026-11-08. Status: implemented for the explicit shared-worker task.

The fixed worker subject conflated queue execution with initiating-user identity. Explicit
per-user worker delegations also required administrative intervention for each submitter.
The execution controller used durable principal snapshots but lacked authenticated service-actor
intersection. PostgreSQL remains the sole operational authority.

Authorized admission now creates a seven-day server-side job grant transactionally. Composite
foreign keys bind the tenant and specific ingestion/semantic/execution job; a membership foreign
key binds the initiating principal. Unique constraints prevent multiple grants per job. A trigger
makes bindings, operations, resource scope and expiry immutable and revocation irreversible.
No grants are backfilled from historical jobs. Legacy jobs require authorized resubmission.

Only tenant-authorized service principals with `worker:delegate`, the queue claim capability,
ordinary operation permissions, and applicable resource/Project access may consume grants.
The worker authenticates independently through the existing verified OIDC/client-credentials
path. Each immutable per-attempt principal includes both identities, job, grant and fencing token.
It is constructed from server-side records, never incoming payload ownership fields or retained
personal tokens. Grant contexts cannot mint further grants or author definitions.

Every governed transaction revalidates job/grant state and both principals' current authority.
The established security revision lock serializes membership/RBAC/ABAC revocation against commits;
job/grant row locks serialize grant revocation and attempts. Transaction-local caches avoid
repeating authority queries in materialization loops; no cache survives a protected boundary.
Project governance and object/property policies intersect both principals. Work outside transactions
has no right to publish its results without another fenced authorization check.

Terminal job state consumes authority without deleting audit evidence. Automatic recovery/retries
retain the original bounded grant and rotate fencing tokens. An explicitly authorized transient
failure retry can reactivate the same job within its original grant expiry; permanent authorization
failure, cancellation and success cannot. Explicit revocation/expiry always requires resubmission.
Control-plane failure retirement/cleanup uses independently checked service authority and fencing;
it can neither read protected user inputs nor publish results after user revocation.

Automation activation retains its explicit bound owner. A scheduler authenticates as a tenant
service, verifies its own dispatch/target access and the bound owner's current authority, then
admits each job/grant atomically. Definitions edited by another principal never change that owner.

Outbox delivery remains service-owned at-least-once work. Existing pipeline isolation, storage,
leases, fencing and quotas are retained. No new scheduler, broker, datastore, public impersonation
endpoint or external semantic-engine contract is introduced. See the operator guide for rollout
and the validation report for executed checks and remaining production-environment gates.
