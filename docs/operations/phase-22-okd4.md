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
3. Automatic worker enrollment defaults to enabled. The authenticated worker registers its own
   verified issuer and subject and enrolls missing tenant and Project access as persisted work
   appears. This includes already queued jobs in existing tenants and new personal workspaces.
   Set `FOUNDRY_WORKER_AUTO_PROVISION: 'false'` only for explicitly manual deployments.
   Existing disabled memberships and restrictive roles remain in force. To suspend a tenant,
   disable the worker membership. To restrict a Project, retain a viewer membership. Removing
   a Project membership in automatic mode allows missing access to be enrolled again.
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
5. `FOUNDRY_WORKER_SUBJECT` is an optional identity pin. Automatic pools derive their service
   subject from the verified token and require no per-user or per-tenant provisioning commands.
   The configured client ID must be the worker service client, never the Studio client.
   Outbox-enabled tenants use the configured fixed
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

## LDAP recipient picker in `csh-foundry`

1. Select project **csh-foundry** in the OKD web console. Open **Workloads → Config Maps →
   foundry-config → YAML**. Merge these keys into the existing `data` map and save.
   Keep existing ConfigMap entries. [OKD ConfigMap guide](https://docs.okd.io/4.19/nodes/pods/nodes-pods-configmaps.html)

   ```yaml
   data:
     FOUNDRY_DIRECTORY_SOURCES: '["ldap"]'
     FOUNDRY_DIRECTORY_LDAP_URL: 'ldap://ldap.csh.rit.edu'
     FOUNDRY_DIRECTORY_LDAP_BASE_DN: 'cn=users,cn=accounts,dc=csh,dc=rit,dc=edu'
   ```

   This uses anonymous verified StartTLS on TCP 389. The system trust store is the default. If
   the directory uses a private CA, mount the approved CA through the API Deployment's existing
   trust volume and set `FOUNDRY_DIRECTORY_LDAP_CA_BUNDLE` to its PEM path under `/run/trust`.
   Set `FOUNDRY_DIRECTORY_LDAP_PROVIDER_ID` when multiple trusted Keycloak realms are configured.
   The configured realm must use the same unique, case-sensitive username as the LDAP UID.
   If the directory operator supplies an approved member filter, set
   `FOUNDRY_DIRECTORY_LDAP_MEMBER_FILTER` to the complete parenthesized LDAP filter. The directory
   branch includes administrative accounts. Studio sign-in and claim authorization still apply.
2. Open **Networking → NetworkPolicies → api → YAML**. Keep the DNS, database and HTTPS
   rules. Add an egress rule under `spec.egress` for the approved address ranges of
   `ldap.csh.rit.edu`, TCP port 389, and save. Use only the directory addresses supplied by
   the network operator. Standard NetworkPolicy uses CIDRs, so update them if the endpoint
   addresses change or use the cluster's approved DNS-aware egress controls.
   [OKD NetworkPolicy guide](https://docs.okd.io/4.19/networking/network_security/network_policy/creating-network-policy.html)

   ```yaml
     - to:
       - ipBlock:
           cidr: <approved-LDAP-IPv4-address>/32
       ports:
       - protocol: TCP
         port: 389
   ```

3. Keep Keycloak's existing configuration. Confirm with the identity operator that the current
   Studio client supplies `preferred_username` in its signed API access token. If the existing
   client permits the optional `profile` scope, set `STUDIO_OIDC_REQUEST_PROFILE: 'true'` in
   Studio's environment or the shared ConfigMap. Studio adds `profile` for Keycloak when the
   discovery document advertises it. If the signed username is absent, a valid link remains
   pending and the recipient gets a sign-in/support message. Check the claim locally during
   a controlled sign-in without copying tokens into logs or browser URLs.
   [Keycloak client scopes](https://www.keycloak.org/docs/26.8.1/server_admin/#_client_scopes)
4. In the approved maintenance window run the version-matched migration Job to
   `0030_directory_shares` and update the image digests as described below. Under **Workloads →
   Deployments**, confirm `api` and `studio` use the new image and their current pod templates
   reference `foundry-config`. If only ConfigMap environment values changed, choose
   **Actions → Restart rollout** on the affected Deployment. Watch **Workloads → Pods** until
   the new pods are Ready. [OKD deployment guide](https://docs.okd.io/4.19/applications/deployments/managing-deployment-processes.html)
5. Open **Workloads → Pods → the new API pod → Terminal** and select container `api`.
   Run the following inside the API image. It requests at most three five-entry pages on one
   connection and prints counts only. It uses the API's trust bundle and membership filter
   when those are configured. Run using the image's Python environment.

   ```bash
   python - <<'PY'
   from ldap3 import DEREF_NEVER, LEVEL
   from ontology_platform.config import get_settings
   from ontology_platform.security.ldap_directory import (
       LdapDirectory, PAGE_CONTROL, search_filter,
   )

   api_settings = get_settings()
   assert api_settings.directory_ldap_url == "ldap://ldap.csh.rit.edu"
   base = "cn=users,cn=accounts,dc=csh,dc=rit,dc=edu"
   assert api_settings.directory_ldap_base_dn == base
   directory = LdapDirectory(api_settings)
   connection = directory.connect()
   seen = set()
   cookie = b""
   try:
       for page in range(1, 4):
           connection.search(
               base, search_filter("", api_settings.directory_ldap_member_filter),
               search_scope=LEVEL, dereference_aliases=DEREF_NEVER,
               attributes=["uid", "displayName", "cn"],
               time_limit=3, paged_size=5, paged_criticality=True, paged_cookie=cookie,
           )
           assert connection.result["result"] == 0
           entries = {row["dn"] for row in connection.response if row["type"] == "searchResEntry"}
           assert 0 < len(entries) <= 5 and seen.isdisjoint(entries)
           seen.update(entries)
           print(f"PASS verified LDAP page {page}, {len(entries)} entries")
           cookie = connection.result["controls"][PAGE_CONTROL]["value"]["cookie"]
           if not cookie:
               break
   finally:
       directory.disconnect(connection)
   PY
   ```

6. In Studio, as an owner, choose **Sharing → Shared by me**, select a resource, and focus
   **Recipient** with an empty input. Browse, select **Load more** and check a known name and
   UID prefix. Share a Viewer invitation privately with an eligible test user who has never
   signed in. Have them open the link, sign in, name a workspace, accept, and open the resource
   from **Shared with me**. Test a wrong account, revoked link, replay, and direct Principal ID
   sharing. Record sanitized outcomes. A second source can be verified with
   `["ldap","keycloak"]` if Keycloak directory credentials already exist.

`["keycloak"]` uses only the existing Keycloak search, which resolves registered Foundry
principals. An unset source list retains the legacy Keycloak behavior for configured clients.
`[]` disables directory lookup. Principal ID and tenant ID entry work in every mode.

Each API process holds the LDAP connection and RFC 2696 cursor for up to 45 idle seconds.
The first continuation consumes an opaque Foundry cursor and returns a new one for the
next page. API replicas can verify the selected recipient using the shared cursor signing key,
and PostgreSQL handles claims across replicas. A continuation must reach the same live API
process. If it arrives at another process, expires, or loses the LDAP connection, restart the
search from the first page. The baseline API runs one pod with one process. To paginate
through a multi-replica rollout, verify that the Studio-to-API routing preserves affinity
for the whole browse session. For example, with one API process per pod, test
`sessionAffinity: ClientIP` on the API Service from the same Studio pod, plus ingress
affinity if Studio has multiple replicas. A restart stays safe even without sticky routing.

Disable LDAP immediately through the source list and restart the API if lookup needs to be
withdrawn. Revoke outstanding links individually from **Shared by me** if they must be withdrawn.
Already issued invitations otherwise remain valid until expiry or revocation.

## Coordinated rollout

1. Use **Workloads → Deployments** to scale all worker replicas to zero and suspend any
   scheduling CronJobs. Drain bounded attempts or allow their leases to expire. Stop API/Studio
   writes for the schema window, retaining the maintenance procedure for users.
2. Using **Import YAML**, create the release migration Job from the reviewed migration
   manifest with the matching API digest and a unique Job name. Use the existing migration
   owner credentials. On **Workloads → Jobs → Pods → Logs**, verify it reached
   `0030_directory_shares`. Under owner runtime mode keep
   `FOUNDRY_ALLOW_OWNER_RUNTIME_ROLE=true`. For a Phase 22 baseline upgrade with distinct
   migration and runtime roles, confirm runtime DML access to `tenant_shares` before
   restarting. Inspect the Job result and schema revision from its authorized administrative pod terminal.
3. In the ConfigMap YAML remove `FOUNDRY_WORKER_TENANT_ID`. Remove any deployment-level
   equivalent and remove the fixed `--ontology` selector from each shared worker Deployment
   command. The optional CLI filter remains for deliberate diagnostics. Update all enabled
   worker and API deployments to the approved digest, including the separately managed
   execution controller where enabled. Set `FOUNDRY_PROCESS_ROLE=worker` on worker pods.
4. Bring up API and Studio together so sign-in can call the new endpoint. Confirm readiness
   using the console. Restore the worker replica counts and schedule settings. Watch
   workload events, readiness and logs. Check `worker_cycle` exits and actual queue progress.
5. Jobs with valid revision-0028 grants remain resumable using their persisted owner tenants
   and leases. Automatic enrollment handles missing worker permissions for new memberships. There is
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
