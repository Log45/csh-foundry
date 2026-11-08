# Shared worker execution

Workers authenticate with their own Keycloak/OIDC service identity. The submitting user remains
the initiating principal. PostgreSQL creates a server-side grant after submission authorization,
in the same transaction as the job and immutable input pins. No user access/refresh tokens,
per-user Deployments, manual per-user delegation, or administrator impersonation are involved.

## Authorization and claims

The OIDC service must be provisioned as a Foundry `service` principal with enabled membership in
its configured tenant. Grant consumption requires `worker:delegate`, the queue capability
(`ingestion:claim`, `semantic:claim`, or `execution:claim`), and each operation's ordinary RBAC
permission. Provision a bounded worker role through the security role/assignment APIs. For Project
jobs, explicitly add the service as a Project editor in the Projects it serves. This does not grant
users any new access. A worker credential does not discover other tenants' queues.

Ingestion and semantic workers use `FOR UPDATE SKIP LOCKED LIMIT 1` to claim a pending job or an
expired lease. They resolve the initiator from the grant, validate current authority and then assign
a new random fencing token in that transaction. Denied candidates become FAILED with
`job_authorization_denied`, are audited, and do not obstruct later candidates. Legacy jobs without
grants fail closed with the same diagnostic; grant lookup identifies them as requiring resubmission.
The execution controller retains its admission quotas/advisory lock and attempt fencing.
Jobs outside an execution worker's Project scope remain queued for another eligible service;
the skipped decision is audited and does not block eligible candidates.

Each protected transaction intersects current user and worker tenant membership, roles, row/property
policies, Project membership/shares, grant operations/resource scope, expiry and revocation, job
state and fencing token. Grants capture the submitting principal's permitted operations at creation;
adding permissions later cannot broaden an existing grant. Identity and policy caches live only
within a security-revision-locked transaction. Grant and job locks prevent revocation/claim races;
no global mutable initiating identity is used.

Execution contexts carry tenant, job, initiating principal, authenticated actor, grant ID and attempt
token. Ingestion grants cover the submitted mapping/source/binding and object/link types. Semantic
grants cover pinned artifacts, their export selections and the source/run provenance referenced by
those artifacts; provenance checks still revalidate current user and worker authority. Execution grants cover immutable
input/output/definition resource bindings, including reserved DAG outputs. The resource services
also check current Project governance for the worker and initiator independently.

Protected inputs are checked before extraction/download; checkpoints and output publication are
checked again in fresh transactions. Execution-controller heartbeats revalidate authority and stop
the isolated child after revocation. Semantic engine work is bounded by its existing timeout and
revalidated before persistence. Ingestion validates between bounded batches. Already committed
batches remain visible; a later revocation cannot undo them. Pure computation or an input read
already authorized and started may finish, but cannot publish after revocation wins the commit
boundary. In-flight PostgreSQL mutations hold the security revision lock, so concurrent policy
changes serialize before or after that transaction's commit.

## Grant lifecycle

| Event | Behavior |
| --- | --- |
| Authorized admission | Job and grant commit atomically; rollback removes both |
| Queued | Grant is usable only for its bound job, within seven days of admission |
| Claim / active attempt | Live authority required; context bound to the current attempt token |
| Lease expiry / crash | No fresh authority; another eligible service can recover with a new token |
| Automatic retry | Same job/initiator/grant, new fencing token; original expiry still applies |
| Explicit transient-failure retry | Existing governed retry API authorizes initiator; same job/grant and original expiry |
| Success / cancellation / permanent failure | Terminal job state makes grant unusable; CANCELLING also prevents protected operations |
| Explicit revocation | `DELETE /api/v1/security/job-grants/{id}`; requires `security:delegation:manage` |
| Expiry / disabled user / revoked access | Subsequent protected operations fail; service may only record fenced failure metadata |

Grant bindings and scope are immutable in PostgreSQL. Revocation is irreversible. Retained terminal
grants are audit evidence, not reusable authority. Expired/revoked/legacy jobs must be resubmitted
with a new idempotency key after correcting authorization (semantic job submission now accepts an
optional `idempotency_key` for this purpose); do not backfill grants or reset terminal
states with SQL. Execution jobs rejected for authorization are permanently failed and cannot use
the infrastructure-only retry API. No grant can create another job grant.

## Alice and Bob

1. Provision one worker service in tenant T and give it the queue/operation capabilities and Project
   access needed for its workload. Configure one Deployment with T and service credentials.
2. Alice submits an ingestion run through her authenticated API session. Submission authorizes Alice
   and creates Alice's job grant. Bob submits another run; it receives Bob's grant.
3. Any replica in that pool may claim either run. It reconstructs Alice's or Bob's context per job;
   permissions and policies are independently checked for that initiator and the same service actor.
4. Audit rows retain the initiating principal, service actor, job, grant, attempt token and decision.
   Neither user's permissions transfer to the other job.

## Scheduled and other execution

Pipeline/DAG runs, dataset validation, mappings and functions use the existing execution controller
and now have the same grant and service-actor checks. Pipeline scheduling has no separate scheduler;
existing automations invoke functions. Automation activation explicitly binds the activating owner;
other editors cannot replace that principal by editing a definition or activation. Changing the
execution owner requires disabling and creating a new activation resource under the new owner.
Scheduled/event dispatch requires the verified scheduler service with `automation:dispatch`, tenant
membership, Project editor access and authorized target access. Each dispatch rechecks the bound
owner and creates a separate job grant. Disabling/re-enabling changes the activation ID, fencing
already queued jobs for the older activation. Removed/disabled owners disable further dispatch.

Outbox/webhook delivery uses its verified service directly with `outbox:deliver`; it is not user
impersonation and does not consume user job grants. At-least-once external delivery semantics are
unchanged. Lineage maintenance and DAG scratch cleanup are tenant-filtered control-plane work;
they cannot publish protected user results. No new queue, database, broker or service is introduced.

## OKD4 upgrade and rollout

No deployment or external resource changes are performed by this implementation.

1. Pause ingestion/semantic/execution workers and schedulers; let bounded attempts finish or expire.
   Back up the database. Keep API and worker versions coordinated during this security upgrade.
2. With the migration owner, run `uv run alembic -c alembic.ini upgrade head` from `services/api`.
   Revision `0028_job_execution_grants` is forward-only. It adds grants, audit correlation columns
   and shared-queue indexes; existing jobs/audit remain intact. There is no privileged backfill.
3. Grant the runtime role SELECT/INSERT/UPDATE/DELETE on `job_execution_grants` using the existing
   operator grant procedure; keep audit UPDATE/DELETE/TRUNCATE revoked and keep runtime non-owner.
   Refresh normal runtime grants after migration, not from API startup.
4. Provision/update tenant service roles with `worker:delegate`, required claim/operation permissions,
   and `automation:dispatch` if scheduling. Existing persisted roles are not silently broadened.
   Add explicit worker Project memberships for execution jobs. Provision before creating semantic
   exports because tenant security revisions invalidate earlier export policy hashes.
5. Remove `FOUNDRY_WORKER_SUBJECT_ID` / `WORKER_SUBJECT_ID` from ConfigMaps, Compose settings and
   operator environments. There is no replacement global user setting and no compatibility fallback.
   Keep `FOUNDRY_WORKER_TENANT_ID`, `FOUNDRY_WORKER_PROVIDER_ID`, `FOUNDRY_WORKER_CLIENT_ID`, and the
   mounted `FOUNDRY_WORKER_CLIENT_SECRET`. Existing verified short-lived service access tokens remain
   supported; client credentials are preferred for refresh between bounded invocations.
6. Deploy the matching API and workers, preserving restricted SCC/non-root contexts, secrets mounts,
   network policies and fixed tenant authorization. The execution controller refreshes credentials
   between jobs; token expiry during a job stops further authority and lease recovery remains safe.
7. Resubmit pre-migration queued jobs through the authorized API. Completed historical jobs remain
   readable. Do not assign legacy jobs to an administrator. Re-export semantic inputs if needed.
8. Submit Alice and Bob smoke-test jobs and inspect `/security/audit` for both initiating identities,
   the service actor, grant IDs, distinct attempt tokens and terminal outcomes.

Use `TEST_DATABASE_URL=<disposable PostgreSQL URL> uv run python scripts/validate_phase14.py --workers`
for the existing disposable MinIO-backed worker regression harness. Production OKD4 rollout,
Keycloak credential rotation and restricted-SCC acceptance still require the target installation.

Media parsing/preview extraction runs synchronously under the existing authenticated service
request and isolated parser budget; it is not a shared-worker queue and does not borrow a worker
identity. No additional fixed-subject background queues were found.

The existing execution-controller entry point is `uv run python scripts/run_execution_worker.py`.
It now uses the same service credentials and configured tenant as the ontology workers; scheduling
also requires `automation:dispatch`. The base OKD4 manifests currently instantiate ingestion and
semantic pools; provisioning an execution-controller Deployment remains an operator rollout action.
No controller Deployment or new external infrastructure is created automatically.
