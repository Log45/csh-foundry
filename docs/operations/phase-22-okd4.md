# Phase 22 OKD4 rollout and verification

Use the OKD web console and its workload pod terminals for these steps. Rollout requires
separate approval for the target. Retain the existing route, service account, NetworkPolicies,
TLS trust, secret mounts and restricted-v2 effective SCC. Use version-matched, approved image
digests for API, Studio and every enabled worker. Keep PostgreSQL and Keycloak operator-owned.
See the [OKD4 baseline](okd4-deployment.md) and [OKD 4.19 web console guide](https://docs.okd.io/4.19/web_console/web-console-overview.html).

## Before the maintenance window

1. In the console select the Foundry namespace and save the current workload, ConfigMap and
   migration Job YAML, image digests and replica counts. Identify every execution controller
   and scheduler, including separately managed Deployments or CronJobs. Record authoritative
   schema revision, job depths and active leases with read-only queries from an authorized pod
   terminal. Preserve the existing Keycloak client and worker subject. Confirm
   `FOUNDRY_WORKER_PROVIDER_ID` and `FOUNDRY_WORKER_CLIENT_ID` match the verified worker token.
2. Have the database operator take a timestamped, verified PostgreSQL backup/PITR checkpoint.
   Include separate artifact storage in the recovery point if enabled. Rehearse restoring into a
   disposable target before changing the shared database. Keep backup material on approved
   storage outside the application pod or workstation.
3. Inventory the shared worker's membership, roles and Project memberships in legacy tenants.
   Existing permissions stay in force. To enable another existing tenant, its authorized
   membership admin registers the exact verified worker issuer and subject with
   `POST /api/v1/security/identities` as `principal_type: service`. Use the role and assignment
   APIs to give it only the claim and execution operations its queues need. Add explicit Project
   editor access for execution jobs and automations it serves. The service identity is reused.
4. Configure eligibility on the trusted Keycloak provider in `FOUNDRY_OIDC_PROVIDERS` using
   `access_token_profile: keycloak` and `personal_tenant_client` set to the existing Studio client.
   Set `personal_tenant_all_users: true` to let every human who can sign in to that client name
   and create one personal workspace. Omit `personal_tenant_role` in this mode. This requires
   no additional Keycloak role or group. Use this mode only if everyone who can authenticate to
   the Studio client should be able to create a workspace. Confirm the existing Studio client
   uses authorization code with PKCE and has service accounts and Direct Access Grants disabled.
   For role-gated onboarding, omit `personal_tenant_all_users` and set `personal_tenant_role`
   to the approved human-only realm role. Confirm it is present in signed Studio access tokens
   for eligible humans and scoped out of service accounts. Match version and provider policy in Studio.
   Use the approved identity configuration process for any realm changes.
   [Keycloak server administration guide](https://www.keycloak.org/docs/26.8.1/server_admin/)
5. Set `FOUNDRY_WORKER_SUBJECT` on the API and workers to the same exact verified Keycloak
   service token subject to enable automatic ingestion, semantic and execution capabilities for
   new personal tenants. Optional Project memberships, tenant outbox and scheduling
   permissions are granted explicitly. Outbox-enabled tenants use the configured fixed
   server-side HTTPS receiver for new deliveries. Verify it is intended to receive those
   tenants' data. Existing pinned destinations remain with their delivery records.

## Optional Keycloak user search

Create a dedicated confidential OIDC client in the Foundry Keycloak realm. Enable service
accounts and disable Standard Flow and Direct Access Grants. Assign its service account the
`realm-management` client role `view-users` and include that role in the client's role scope.
The API uses this credential to read directory matches and resolves each Keycloak subject
against enabled Foundry users linked to the same issuer. [Keycloak server administration guide](https://www.keycloak.org/docs/26.8.1/server_admin/)

Set `FOUNDRY_DIRECTORY_PROVIDER_ID` to the existing trusted Keycloak provider ID and
`FOUNDRY_DIRECTORY_CLIENT_ID` to the dedicated client ID in the API's configuration. Add
`FOUNDRY_DIRECTORY_CLIENT_SECRET` to the mounted `foundry-api` Secret. The API must be
able to reach the issuer and its Admin REST user search endpoint over HTTPS. The manual
principal ID option works without this configuration.

## Coordinated rollout

1. Use **Workloads → Deployments** to scale all worker replicas to zero and suspend any
   scheduling CronJobs. Drain bounded attempts or allow their leases to expire. Stop API/Studio
   writes for the schema window, retaining the maintenance procedure for users.
2. Using **Import YAML**, create the release migration Job from the reviewed migration
   manifest with the matching API digest and a unique Job name. Use the existing migration
   owner credentials. On **Workloads → Jobs → Pods → Logs**, verify it reached
   `0029_personal_tenants`. Under owner runtime mode keep
   `FOUNDRY_ALLOW_OWNER_RUNTIME_ROLE=true`. For distinct migration and runtime roles,
   apply the approved runtime DML grants for the new tables before restarting. Inspect the
   Job result and schema revision from its authorized administrative pod terminal.
3. In the ConfigMap YAML remove `FOUNDRY_WORKER_TENANT_ID`. Remove any deployment-level
   equivalent and remove the fixed `--ontology` selector from each shared worker Deployment
   command. The optional CLI filter remains for deliberate diagnostics. Update all enabled
   worker and API deployments to the approved digest, including the separately managed
   execution controller where enabled. Set `FOUNDRY_PROCESS_ROLE=worker` on worker pods.
4. Bring up API and Studio together so sign-in can call the new endpoint. Confirm readiness
   using the console. Restore the worker replica counts and schedule settings. Watch
   workload events, readiness and logs. Check `worker_cycle` exits and actual queue progress.
5. Jobs with valid revision-0028 grants remain resumable using their persisted owner tenants
   and leases. Give the worker the required permissions before opening the queues. There is
   no grant backfill for pre-0028 jobs. Missing, invalid, expired or revoked grants fail
   closed. Review the cause and resubmit via the original authorized path with a fresh
   idempotency key after correcting the condition. Do not edit queued grants or pin jobs to a
   replacement user.

## Verify after rollout

- In an approved empty smoke environment, start the workers before any tenants exist and
  observe idle cycles. In Studio sign in as an eligible human. With all-users onboarding,
  enter a workspace name and verify the workspace appears with that name. Sign out and in
  again and verify the ID is unchanged and the naming prompt does not recur.
- Sign in as a shared-tenant member and select each workspace. Issue a Viewer and Collaborator
  invitation to a second person or an authorized recipient tenant. Verify discovery, acceptance,
  owner attribution, allowed edits, rejection of independent content and revocation.
- Submit semantic validation jobs from two tenants, one provisioned after worker startup.
  Confirm work is picked up by the same deployed replicas without a config change. Submit
  fixture ingestion only if both tenant source bindings are already authorized and available.
  In enabled execution, separately test a Project with the service assigned as editor.
- With the existing security audit API, inspect tenant ID, initiator, service actor, job grant,
  fencing token and status. Check that a rejected or stalled queue leaves the other tenant
  progressing and that eligible outbox events go to the approved receiver. Record pod UIDs,
  effective SCC, image digests, timestamps and sanitized outcomes.

## Recovery

Pause writers, schedulers and all workers if migration or rollout fails. The migration is
forward-only. First prefer correcting settings or images and continuing on the same expanded
schema. Rollback to older binaries requires a coordinated return to a consistent pre-upgrade
database and artifact checkpoint because readiness pins the schema revision and old workers
depend on a fixed tenant. Restore the recorded ConfigMap, images and replica counts only with
that recovery point. Preserve post-upgrade audit and queue evidence under the approved
database recovery process before restoring. Reconcile jobs, artifacts and external deliveries
that occurred after the checkpoint, including possible at-least-once webhook delivery.
Never reenable the old worker against the expanded schema as a partial rollback.

The local rehearsal restored a populated revision-0028 PostgreSQL backup into two disposable
databases. One restore upgraded to revision 0029 and retained tenant, identity, membership,
catalog share, queued job and job-grant records. The second restore verified recovery at
revision 0028. The target rehearsal still needs the target's backup mechanism, artifact recovery
point, image digests and namespace controls.
