# Phase 10 OKD4 deployment guide

This application-only profile targets standard restricted-v2 SCC behavior. The exact organizational
OKD version, namespace UID/fsGroup ranges and CNI behavior are unknown. Local checks are not SCC
admission or production certification. Security/release gates remain BLOCKED; no image has been
published and no organizational cluster has been modified. Phase 11 is not approved.

## Architecture and prerequisites

Studio remains a Next.js standalone BFF server, with PKCE callbacks, opaque browser sessions and
API proxying. An HTTPS OKD Route goes directly to Studio. FastAPI is namespace-private: **do not
publish its service wholesale**, because it includes credential-protected internal browser-state
and metrics routes. SDK clients require an approved private path/port-forward, or a separately
reviewed public ingress that excludes `/internal/` and management paths. No nginx is needed on OKD.

API, ingestion/outbox workers and migrations share the Python application image. The semantic
worker adds pinned Open Ontologies 2.1.0. SDK generation is synchronous/bounded in the API; there
is no unused SDK worker. PostgreSQL holds operational state, artifacts, job leases, sessions and
audit. Organization-managed PostgreSQL and Keycloak are prerequisites, not deployed workloads.
See [the storage audit](../architecture/storage-audit.md) and [administrator request](okd4-infrastructure-request.md).

Have administrators confirm cluster version, node architecture, namespace quota, registry policy,
SCC/group ranges, DNS/router selectors, DB/identity ownership, ingress transport and backup policy.
Initial semantic support is linux/amd64, including the selected native binary. API/Studio/ingress
build on this ARM64 workstation; an AMD64 API/semantic candidate is also built. Linux ARM64
semantic execution is NOT SUPPORTED by the current pinned release installer; it requires a
separately verified pinned-source build. Do not schedule the semantic image on ARM64 nodes.

The base deliberately uses nondeployable `example.invalid` image digests, example hostnames and
RFC 5737 egress addresses. A site overlay must replace them. No placeholder is a released image.
The source image defaults are numeric non-root users so runAsNonRoot admission can identify them;
**the manifests never select a fixed runtime UID**. OKD assigns its namespace UID and fsGroup.
Containers drop ALL capabilities, disable privilege escalation, use RuntimeDefault seccomp,
read-only roots and scoped `/tmp` emptyDir. No application startup chown/chmod or package install.
Build-stage root commands do not run in pods. No privileged/anyuid SCC, hostPath or host namespaces.

Portable self-hosted Kubernetes uses the same base and an fsGroup=20000 Deployment patch. Set an
appropriate allowed fsGroup on its separately rendered migration Job as well. OKD must inject its
own allowed group; do not copy portable group 20000 into an OKD namespace without approval.
Actual projected Secret/emptyDir ownership and SCC admission still require target validation.

## Images and registry

Build locally without pushing (choose a unique candidate tag):

```bash
docker build --platform linux/amd64 -f infrastructure/docker/api.Dockerfile -t foundry-api:CANDIDATE .
docker build --platform linux/amd64 --build-arg BASE_IMAGE=foundry-api:CANDIDATE \
  -f infrastructure/docker/semantic.Dockerfile -t foundry-semantic:CANDIDATE .
docker build --platform linux/amd64 -f infrastructure/docker/studio.Dockerfile -t foundry-studio:CANDIDATE .
uv run python scripts/scan_images.py foundry-api:CANDIDATE foundry-semantic:CANDIDATE \
  foundry-studio:CANDIDATE --output artifacts/NEW-CANDIDATE-SCAN
```

Obtain independent security/release approval before registry publication. Only then tag and push
to the approved registry, record the returned **registry manifest digest**, architecture and
SBOM/scanner/config identities, and set Kustomize images to `REGISTRY/IMAGE@sha256:DIGEST`.
A local Docker config/image ID is not automatically a portable registry digest. Configure a
namespace imagePullSecret or approved service-account pull policy through the site overlay.
Do not reuse previous SBOMs/scans for changed images. No publication is performed by these steps.

## Site configuration and Secrets

Create a site Kustomization referencing `infrastructure/kubernetes/overlays/okd` (or self-hosted),
then patch `foundry-config`, Route host, images, node selectors and NetworkPolicy destination CIDRs.
Include the same reviewed image and configuration in the separately rendered migration Job.
Set `nodeSelector: {kubernetes.io/arch: amd64}` for semantic workers on mixed-architecture clusters.

`foundry-config` contains public settings: HTTPS Studio origin, exact OIDC issuer/audience/client
allowlist/algorithms, explicit API allowed hosts, worker tenant/subject/provider and pool bounds.
Set both Studio and API identity configuration consistently. The API probe Host header is `api`
so TrustedHostMiddleware does not reject kubelet requests to pod IPs. Worker ontology arguments
must match the explicitly provisioned ontology; tenant membership and worker service permissions require explicit provisioning.

Before release, provision these namespace Secrets through the organization’s approved secret
manager. They are intentionally absent from tracked YAML. Use private files outside the checkout:

| Secret | Required keys |
|---|---|
| `foundry-api` | `FOUNDRY_DATABASE_URL`, `FOUNDRY_BROWSER_STATE_SECRET`, `FOUNDRY_BROWSER_STATE_KEYS`, `FOUNDRY_QUERY_CURSOR_SECRET` |
| `foundry-studio` | `FOUNDRY_BROWSER_STATE_SECRET` (same transport secret as API) |
| `foundry-worker` | `FOUNDRY_DATABASE_URL` (existing application owner in owner mode), `FOUNDRY_WORKER_CLIENT_SECRET` |
| `foundry-migration` | `FOUNDRY_DATABASE_URL` (same existing owner in owner mode) |
| `foundry-catalog` | `catalog.json` containing server-owned tenant registrations; `[]` if none |
| `foundry-trust` | Public `postgres-ca.pem` and `oidc-ca.pem` roots, not private CA keys |

Example approved-target command (not executed here):

```bash
kubectl --context APPROVED --namespace NAMESPACE create secret generic foundry-api \
  --from-file=FOUNDRY_DATABASE_URL=/private/application-database-url \
  --from-file=FOUNDRY_BROWSER_STATE_SECRET=/private/session-transport \
  --from-file=FOUNDRY_BROWSER_STATE_KEYS=/private/session-key-ring \
  --from-file=FOUNDRY_QUERY_CURSOR_SECRET=/private/cursor-key
```

Use at least 43 characters of random session transport material, valid comma-separated Fernet
keys (newest first), and >=32-byte cursor key. Persistent keys are required across replicas and
restarts; rotate using the existing production runbook. Never expose secrets in browser responses,
command output or tracked evidence. Catalog values can contain credentials: they remain a Secret.
Mount credentials 0440 with an SCC-provided readable supplemental group; do not assume group 0.

## External PostgreSQL

Use a URL like the following **only in a private Secret file**:

```text
postgresql+psycopg://APPLICATION_ROLE:URL_ENCODED_PASSWORD@DB_HOST:5432/DB_NAME?sslmode=verify-full&sslrootcert=/run/trust/postgres-ca.pem&connect_timeout=3
```

`FOUNDRY_DATABASE_TLS_REQUIRED=true` rejects missing verify-full/CA settings. Libpq verifies chain
and hostname; retain verify-full and the approved CA. Choose the existing dedicated database/schema.
For this OKD4 installation, use the **same existing PostgreSQL owner account** in the API, ingestion,
semantic/outbox workers, execution controller and migration Job's `FOUNDRY_DATABASE_URL`.
Separate Kubernetes Secret objects may contain that same database URL; they do not require
separate PostgreSQL roles. The profile does not provision an organizational database or roles.

Set `FOUNDRY_ALLOW_OWNER_RUNTIME_ROLE: 'true'` in `foundry-config` (as shown in the base example).
The API and every service-worker startup/credential-refresh path honor the same ownership exception.
Rebuild the matching API/semantic images and restart the API and worker Deployments with the
updated ConfigMap. Existing non-owner deployments can set the flag to `'false'`, its application
code default, and retain the existing ownership rejection.

The flag permits database/schema/table ownership only. It does not skip catalog checks for
`SUPERUSER`, `CREATEDB`, `CREATEROLE` or `REPLICATION`, and does not change Foundry OIDC verification,
service-principal validation, tenant membership, RBAC/ABAC, Project governance, job grants,
revocation, leases, fencing, constraints or immutable audit/grant triggers. No database trigger is
disabled. PostgreSQL owners can alter their own schema, so the owner connection remains a trusted
backend credential, never a user-facing credential.

Run migrations through the separate maintenance Job using the same existing owner URL. Alembic
already permits owner DDL; migration `0028_job_execution_grants` needs no role-specific changes.
**Owner mode requires no separate runtime-role table grants or refresh after migration.** Do not
run the separate-role `--grant-runtime` procedure for this mode. If using the provisioning helper,
`FOUNDRY_ALLOW_OWNER_RUNTIME_ROLE=true uv run python scripts/provision_production_database.py --apply`
validates the configured account without creating roles/databases or changing grants; it needs no
`FOUNDRY_ADMIN_DATABASE_URL` or `--secrets` argument. Owner mode uses the configured existing account
throughout. The PostgreSQL ingestion connector's independent read-only external-source check
remains in force; this application runtime setting does not change connector credential policy.

Pools default to three connections per process and zero overflow, plus the existing API audit
pool of two. Budget at least API_REPLICAS × (3+2), worker process pools and migration/admin
headroom; Keycloak has a separately owned connection budget. SQL/lock/pool/connect waits remain
bounded, with pre-ping and existing application retry/lease handling. Do not hide unavailable
services behind unlimited startup retries. Test credentials/CA failures before opening traffic.

## External Keycloak

Direct integration is supported when the realm supplies the existing contract. Studio uses a
**public** Code/S256 client (`openid` scope); it has no browser client secret. Require exact
`https://STUDIO_HOST/auth/callback`, exact origin, approved post-logout redirect, RS256 (or explicitly
approved ES256 in the backend), and disable password/implicit grants. Browser tokens never reach
localStorage. No refresh token is requested; short sessions require reauthentication. Configure
issuer logout through `STUDIO_BROKER_LOGOUT=true` when the approved discovery document supports it.

The default RFC 9068 profile requires API access tokens with `typ=at+jwt` (or application/at+jwt), exact issuer/audience, approved
`client_id`, consistent azp, sub/jti/iat/exp, valid lifetime and asymmetric signature. Discovery
issuer and same-origin JWKS must match. See `security/broker.py:realm_configuration` for the
already tested Keycloak RFC 9068/audience/client mapper settings; it is a review reference, not
permission to import or overwrite an existing realm. Public CA mounts extend trust without
turning off chain/hostname verification. Workers use a confidential service client and current
automatic PostgreSQL job-scoped grants. Platform bindings use `(issuer, sub)` and tenant membership;
email and realm roles do not grant platform access.

For an explicitly configured Keycloak-compatible access-token contract using `azp`, see
[token profiles and exact web-console YAML changes](../development/oidc-token-profiles.md).
Studio and API must load the same trusted provider policy. Strict RFC validation remains the default.

If administrators cannot issue this token profile, record the exact limitation and request a
separately approved controlled broker/upstream federation configuration. No second Keycloak is
included by default. Local Keycloak 26.8.1 compatibility does not certify another version, live
realm, upstream organization, certificate, key rotation or identity-link lifecycle.

## Rendering, admission and migration ordering

```bash
uv run python scripts/validate_kubernetes.py infrastructure/kubernetes/overlays/okd \
  --output /private/review/okd-example.yaml
kubectl kustomize infrastructure/kubernetes/migration > /private/review/migration-example.yaml
# After replacing site configuration/images, validate the rendered site overlay with --production.
uv run python scripts/validate_kubernetes.py /private/site-overlay \
  --production --output /private/review/application.yaml
```

Standard resources were checked with kubeconform; Route fields have local contract checks.
Actual server dry-run/SCC/network admission is separate, authorized-target work:

```bash
kubectl --context APPROVED --namespace NAMESPACE apply --dry-run=server -f /private/review/application.yaml
kubectl --context APPROVED --namespace NAMESPACE apply --dry-run=server -f /private/review/migration.yaml
```

Kustomize resource order does **not** guarantee migrations finish before Deployments start.
Use a maintenance window: stop external admission, verify backup/recovery, designate one release
operator (serialize release pipelines), render both candidates, verify release gates and Secret
identities. Then run the explicit tool, first without `--apply`:

```bash
uv run python scripts/rollout_kubernetes.py --context APPROVED --namespace NAMESPACE \
  --configuration /private/review/application.yaml --migration /private/review/migration.yaml
# Only after target and release approval, rerun the exact command with --apply.
```

The tool installs configuration/service-account/policy prerequisites, stops existing application
Deployments and waits for pods to exit, runs one migration Job and waits for success, then applies
Deployments/Services/Route and waits for rollout. The Job has no retry, a ten-minute deadline and
the same existing owner credentials in owner mode; the migration command uses a PostgreSQL advisory lock and Alembic drift
check on the same connection. Concurrent migrations fail closed. **Do not run concurrent rollout
commands**; the advisory lock does not coordinate two operators deleting/replacing Kubernetes Jobs.
Migration failure keeps applications stopped for reviewed repair. Observe `logs job/foundry-migrate`
and Job status. First installation needs the site Secrets. Owner mode needs no runtime-role grant refresh;
non-owner mode retains its existing grants procedure. This change adds no migration; the current
head remains `0028_job_execution_grants`.

Rollback is not automatic schema downgrade. Keep traffic closed; restore the previously reviewed
compatible images/configuration or forward-repair the schema, using verified DB restore if needed.
Earlier migration downgrades can destroy retained history. See the migration/recovery runbooks.

## Networking, TLS and storage

The OKD overlay uses edge TLS and redirects HTTP; the router owns certificates. Router-to-Studio
and Studio-to-API are explicitly namespace-internal HTTP in this initial profile. Require the
organization to approve that transport, or implement/review reencrypt/service TLS before deployment
if policy requires encryption on those hops. External PostgreSQL and OIDC always verify TLS.

Default-deny NetworkPolicies allow Studio→API, configured PostgreSQL/identity IPs and namespace
DNS. Replace TEST-NET /32s with approved destinations and actual ports; NetworkPolicy has no FQDN
semantics. Check CNI NAT/LB behavior and allow each current endpoint. Restrict DNS peer labels to
actual cluster resolvers if the broad system-namespace DNS rule is unsuitable. The OKD router rule
uses `network.openshift.io/policy-group=ingress`; verify actual labels and host-network router
behavior. Self-hosted ingress needs a site-specific controller policy; port-forward can provide
operator access before ingress approval. Outbox defaults to zero replicas and has no receiver
egress rule: configure an approved fixed receiver/delegation and narrow egress before enabling it.
External ingestion-source egress is also an explicit site policy. No Internet-wide allow rule.

For registered files, add `components/file-sources` to the site Kustomization and provision the
existing shared read-only `foundry-sources` PVC. API/ingestion replicas must see identical source
bytes. Remote PostgreSQL connectors need no source PVC. No S3 is required. Never place durable
source input, backups, artifacts or keys in emptyDir.

## Health, sizing, operation and upgrades

API liveness is `/health/live`; readiness verifies DB reachability and exact schema head.
Startup warms OIDC once and fails closed on initial configuration/discovery failure. Liveness
does not poll Keycloak/PostgreSQL. Studio `/health/live` is process-local; `/health/ready` checks
configuration/API readiness with a bounded request. Worker probes check supervisor progress using
its local heartbeat, **not** job success or valid credentials. Monitor failed worker cycles,
queue age and authorization denials separately. No artificial worker HTTP server is introduced.
SIGTERM stops new worker cycles and terminates the bounded child; durable leases/checkpoints and
fencing handle unfinished work. Termination grace is 45s, API graceful timeout 30s, child kill
fallback 5s. A restart is not permission to duplicate external effects; outbox receivers deduplicate.

Initial requests are 100m CPU /256Mi memory; API/Studio/ordinary worker limits 1 CPU/768Mi and
semantic 1 CPU/1Gi. These are provisional starting values, **not measured production capacity**.
Use workload profiles and namespace budgets; semantic engine/native memory can need more.
One child per supervisor bounds concurrency. Scale only after connection, source availability,
lease recovery and target-memory checks. Recreate strategy and explicit maintenance ordering do
not claim mixed-version/zero-downtime compatibility. Multiple replicas need shared keys/catalog.

Collect stdout/stderr using organization logging. Keep callback codes, tokens, object data and
private browser traces out of shared logs. API metrics require the internal credential and a
separately approved collector policy. Preserve existing monitoring alerts and assign named owners.
The managed DB operator owns backups/WAL/PITR, restores and off-host recovery tests; application
operators must validate restored authorization, artifacts, sessions and queues after recovery.

Troubleshooting: permission denied → inspect assigned UID/groups and projected volume ownership,
never request anyuid; probe 400 → verify API Host header; OIDC startup failure → verify exact
issuer/discovery/client/CA and egress; TLS failure → verify hostname and full CA chain, not a bypass;
worker no progress → inspect heartbeat and redacted cycle status/job-grant decisions; missing source → check
shared claim and catalog; admission failure → inspect target SCC/schema/version. Migration failure
blocks rollout. Do not reset the developer database, Keycloak, keys or volumes to fix target issues.

Compose remains available. Its optional nginx now uses the pinned maintained unprivileged image,
8080/8443 internally, and host mappings 80/443. Its explicit OIDC backchannel socket port 8443
preserves public issuer identity/TLS hostname and discovery/signature checks; no such override is
needed in OKD. TLS keys must be readable by the configured non-root supplemental group (10001
in Compose), not root-only. Rebuild/select the new ingress image together with the updated profile.
Old ingress images listening on 80/443 cannot be mixed with the new Compose port mappings.

Before promotion bind exact registry digests, rendered manifest hashes, Secret/ConfigMap object
UID/resourceVersion (no values), fresh SBOMs/scans, external service identities/compatibility/security
assurances and all existing release gates. `verify_release_evidence.py --profile okd` requires
exactly API/Studio/semantic supply-chain evidence plus explicit `--service postgres=IDENTITY`,
`--service keycloak=ISSUER` and `--deployment-sha256 HASH`; Compose still requires all six images.
This is evidence validation, not independent approval or infrastructure security certification.

Shared worker identity and the migration to job-scoped authority are documented in
[dynamic worker execution](dynamic-workers.md). This supersedes historical per-user delegation
setup for ingestion and semantic workers.
