# Phase 10 deployment and operator runbooks

This is a bounded single-host deployment profile, not an HA or multi-region guarantee.
Read the [readiness matrix](readiness.md) before promotion. A failed scan or unexecuted acceptance
gate is not production readiness. No production deployment was performed by this implementation.

## Topology and ownership

`infrastructure/production/compose.yaml` runs nginx → Studio → FastAPI, PostgreSQL, Keycloak,
and optional separate supervised ingestion/semantic workers. Open Ontologies remains a child
process in the semantic worker, with its own container memory/CPU/disk boundary. API and workers
use the existing application services and transaction/security locks. No RDF/OWL operational
store, custom issuer or second authorization system is introduced.

Initial target: one API, one PostgreSQL, one Keycloak and one or two Studio replicas. Two built
Studio processes and shared PostgreSQL sessions are tested. API/Keycloak replication, rolling
mixed-release operation, failover and multi-host network transport are not certified. A dedicated
host with 8 vCPU/16 GiB RAM and encrypted storage is a provisional recommendation, not a measured
capacity promise. Size disk, backup/WAL retention and memory from a representative deployment.

Assign named humans to the following operational roles before deployment:

| Role | Responsibility |
|---|---|
| Platform operator | Host, nginx/TLS, application releases, worker processes, quotas, alerts |
| Database operator | Separate owner/runtime roles, encrypted backups, WAL, restoration, storage |
| Identity administrator | Keycloak, upstream organizations, explicit verified identity links, signing keys |
| Tenant administrator | Platform membership, least-privilege roles, restrictive ABAC, deactivation |
| Security/release reviewer | Vulnerability findings, artifact integrity, release/deployment approval |

Networks isolate frontend, broker proxy, database and outbound access. Only nginx publishes ports
80/443 (HTTP redirects only on 80). API does not trust forwarded headers. Nginx replaces forwarded identity headers; Keycloak
trusts only nginx's fixed identity-network address. Origins/redirects are fixed operator values.
The API internal session/metrics routes are inaccessible through public ingress. Keep the Docker
socket and host administration private. External source/outbox access requires explicit egress
policy; the default ingestion/semantic containers have no direct Internet network.

## Configuration and secrets

Copy `infrastructure/production/environment.example` outside the checkout. It contains public
hostnames, approved image digests and paths only. Never use its placeholder image digests.
Assign non-overlapping Docker subnets if 172.30.10.0/24 or 172.30.11.0/24 is already in use;
change both nginx addresses and Keycloak trusted-proxy addresses together.

Create secret files outside Git, on encrypted host storage. Use at least 32 random bytes per secret.
File names: `postgres_password`, `migrator_password`, `runtime_password`, `keycloak_password`,
`keycloak_admin_password`, `FOUNDRY_DATABASE_URL`, `FOUNDRY_BROWSER_STATE_SECRET`,
`FOUNDRY_BROWSER_STATE_KEYS`, `FOUNDRY_QUERY_CURSOR_SECRET`, `FOUNDRY_WORKER_CLIENT_SECRET`.
`FOUNDRY_DATABASE_URL` is the runtime `postgresql+psycopg://foundry_runtime:...@postgres:5432/foundry`
URL with properly URL-encoded credentials. Do not use the superuser/migration URL at runtime.

Generate Fernet keys with `uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`
in a private terminal and store them directly; never paste real output into committed files.
`FOUNDRY_BROWSER_STATE_KEYS` is a comma-separated key ring, newest first. Store secret files as
root:10001 mode 0440 (or a runtime-readable 0400 equivalent); directories must permit traversal
only for the intended service identities. Compose file-backed secrets preserve host permissions;
the containers explicitly share supplemental group 10001. Test actual readability on the host.
The PostgreSQL superuser/bootstrap credentials must not be mounted into API/Studio/workers.

API production startup requires OIDC, explicit HTTPS public origin, exact allowed hosts, database
credentials and persistent cursor/session keys. Studio requires an explicit HTTPS origin and shared
session credential. There is no production fallback to local/test identity or memory sessions.
For private CAs add only the public root to API `FOUNDRY_OIDC_CA_BUNDLE` and Studio
`NODE_EXTRA_CA_CERTS` through read-only mounts; hostname/certificate verification stays enabled.

Preflight, after exporting the public environment values into the shell:

```bash
uv run python scripts/validate_production_config.py
docker compose --env-file /private/path/production.env -f infrastructure/production/compose.yaml config --quiet
```

The template is a NEW deployment. It must not replace the existing local Keycloak container or
reuse its nonpersistent filesystem. Preserve the existing local realm, user, private CA and objects.

## First installation and migrations

1. Obtain explicit target-environment approval. Verify the source revision, release checksums,
   attestation identity, scan results and SBOMs. The release workflow does not deploy automatically.
2. Start only the new PostgreSQL service and verify encrypted disk/WAL directory ownership.
3. As the database operator, review `scripts/provision_production_database.py --secrets PATH`
   (dry-run default). With the approved new cluster's private `FOUNDRY_ADMIN_DATABASE_URL`, run
   `--apply`. This creates separate non-superuser `foundry_migrator`, `foundry_runtime` and
   `keycloak` owners/runtime roles and revokes PUBLIC database access. It intentionally refuses
   duplicate CREATE operations; it is not an in-place credential-rotation tool.
4. Run `alembic upgrade head` as `foundry_migrator`, then `alembic check`. Use an isolated migration
   container attached to the data network; do not start migrations in application startup.
5. Run the provisioning script with `--apply --grant-runtime`, pointed at that same new cluster.
   Runtime gets DML and migration-version read access, no DDL/table ownership/role creation.
   Security audit UPDATE/DELETE/TRUNCATE are explicitly revoked. Reapply grants after migrations.
6. Render a new broker realm as described below. Mount upstream secrets only when configured.
7. Start nginx, Keycloak, API and Studio; startup/readiness must succeed before opening traffic.
   The ingress resolves upstream container names dynamically, permitting startup and replica changes.
8. Explicitly bootstrap verified platform issuer/subject bindings and tenant administrators through
   the Phase 7 bootstrap/admin services. Then configure worker identities and expiring delegation.
9. Execute the target deployment's manufacturing, security, recovery and SSO acceptance gates.

Releases use a maintenance window: stop admission, let bounded work finish or safely expire leases,
stop workers/Studio/API, take and verify backups, migrate, regrant runtime, start broker/API/Studio,
verify readiness/authorization/session behavior, start workers, then reopen traffic. A failed
migration leaves the transaction rolled back; keep old services stopped until compatibility is
understood. Do not claim mixed-version or zero-downtime migration compatibility.

0016 adds encrypted disposable browser state and request budgets. 0017 adds tenant artifact-byte
accounting and pending-job admission triggers, backfilling accounting without rewriting domain
rows. New writes may be denied when old retained content already exceeds quota. Downgrading 0016
forces reauthentication. Downgrading 0017 removes admission accounting, not artifacts. Earlier
Phase 9 downgrades destroy SDK/branch history and are **not lossless rollback**. Prefer approved
forward repair or full backup restore to a separate cluster. Read `docs/architecture/migrations.md`.

## Keycloak and external SSO

Render a new realm import (the output path must not already exist):

```bash
uv run python scripts/configure_keycloak.py \
  --issuer https://identity.example.org/realms/foundry \
  --studio-origin https://studio.example.org \
  --output /private/path/realm-import/foundry-realm.json
```

Use `--entra-tenant ORGANIZATION_UUID --entra-client CLIENT_ID` for one exact Entra organization.
Register `https://identity.example.org/realms/foundry/broker/entra/endpoint` as its redirect URI.
The generated provider uses the organization's v2 issuer and JWKS with signature validation and
upstream PKCE. Multi-organization `common` and personal Microsoft accounts are not supported by
this profile. Graph access tokens and Microsoft ID tokens are never accepted by FastAPI.

Use `--google-client CLIENT_ID` for Google accounts, or
`--workspace-client CLIENT_ID --workspace-domain example.org` for managed Workspace sign-in.
Register broker callbacks ending in `/broker/google/endpoint` and `/broker/workspace/endpoint`
respectively in the corresponding Google OAuth applications. Configure the consent screen,
test users, allowed organization and organization-admin approvals in those external consoles.
Workspace uses one exact hosted domain; it is not platform tenant provisioning or a consumer-account
organization-management guarantee. Supply `ENTRA_CLIENT_SECRET`, `GOOGLE_CLIENT_SECRET`,
`WORKSPACE_CLIENT_SECRET` through private files mounted at `/run/secrets/NAME` using a reviewed
Compose override; `keycloak-entry.sh` reads them. Never commit generated provider credentials.

First broker login denies unlinked upstream identities. The identity administrator must verify
the upstream immutable issuer/subject, independently authenticate both sides and explicitly create
the Keycloak federated link through its secured administrator interface. Disable/revoke affected
platform access during disputed linking; retain an approval/audit record. No email-based matching,
automatic merging or unauthorized self-service membership creation is implemented. A dedicated
realm/Studio per organization is the supported routing policy. Platform memberships and roles
are separately approved via existing Phase 7 administration. Deactivation removes memberships or
disables the principal; provider/domain claims never bypass those checks.

Keycloak realm imports apply only on first startup if the realm is absent. They do not safely
update an existing realm or restore credentials/sessions. Review subsequent administrative changes
against the generated contract, back up the broker database, and rerun token tests. Disable the
bootstrap admin credential after establishing named administrators. Public nginx blocks `/admin/`;
use a private administrative tunnel or `kcadm` from an approved operator context.

## Sessions, revocation and key rotation

Sessions/logins persist as encrypted PostgreSQL rows. Cookies contain random opaque handles,
are HttpOnly/SameSite=Lax, host-only and Secure over HTTPS. State/nonce/PKCE, exact Origin and
synchronizer CSRF checks remain. CAS rejects concurrent tenant updates; login consumption is atomic.
Logout deletes shared state first and offers a standard broker logout redirect. Broker failure
does not retain the platform session. Existing bearer JWTs are not instantly revoked at the
issuer by browser logout; remove platform authority for emergency immediate domain-access denial.

No browser refresh tokens are issued/retained. Reauthenticate after the broker's five-minute API
token expires. Session maximum is one hour and never exceeds the token. Account/session rotation
requires a new verified login, new handle/CSRF and invalidation of the preceding handle.

Rotate encryption keys by adding a new first key to every API replica while retaining old keys.
Updates reencrypt with the newest key. Keep old keys for at least the maximum session lifetime,
then remove them after confirming no unexpired old rows. Rotate internal transport credentials
in a maintenance window across API and Studio; no secret should be logged. Rotate cursor keys
with an explicit expectation that outstanding cursors become invalid. Rotate broker signing keys
with overlap longer than the verifier cache/token lifetime; unknown keys can be rejected for up
to 30 seconds by bounded refresh throttling. Cached known keys work until cache TTL; expired or
unavailable verification material fails closed. Restore clocks/NTP before diagnosing token expiry.

Run `scripts/maintain_operations.py` periodically under the appropriate application identity for
bounded expired-session and stale-budget cleanup. Back up encryption keys independently from the
database. Losing those keys invalidates sessions; do not recover by disabling encryption.

## Worker supervision, quotas and storage

The worker profile obtains a new RFC 9068 client-credentials token for each child cycle from the
configured trusted discovery/token endpoint. `FOUNDRY_WORKER_CLIENT_SECRET` is independent from
browser credentials. A service principal, tenant role and expiring ontology/kind/initiator delegation
must already exist; successful broker authentication alone grants nothing. Rotate client secrets
and mounted files through the identity operator; children reread configuration on each invocation.

Supervisor backoff is bounded to 60 seconds. Children have process-group deadlines; SIGTERM/SIGKILL
stops outstanding native work. A terminated worker's PostgreSQL lease expires and a later eligible
worker can reclaim, subject to existing fencing/checkpoint/retry limits. Semantic subprocess timeouts
remain 30 seconds and the semantic container has 768 MiB RAM/128 MiB tmpfs/one CPU. Ingestion has
its existing Polars/file/row/batch limits and separate container bounds. OS/container limits can kill
work; they do not promise successful reasoning for arbitrary input. There is no unbounded retry.
Outbox uses `python -m ontology_platform.jobs.supervisor --kind outbox --ontology ...` with an
operator-fixed `FOUNDRY_OUTBOX_DESTINATION` and explicit outbound network policy. External effects
are at-least-once; recipients deduplicate event IDs. Do not enable arbitrary destinations or scripts.

Defaults: 120 verified requests/minute/issuer-subject; 20 combined active jobs/tenant; 256 MiB
logical retained artifact/staging bytes/tenant. Set `FOUNDRY_REQUEST_LIMIT_PER_MINUTE`,
`FOUNDRY_TENANT_PENDING_JOB_LIMIT`, `FOUNDRY_TENANT_STORAGE_LIMIT_BYTES` explicitly when capacity
testing justifies it. The ordinary pool defaults to five connections plus five overflow. Each API
process reserves a separate audit pool capped at two connections with no overflow, using the same
restricted role and database. Budget **12 connections per API process** at the default settings,
plus workers, broker and operational connections. This prevents business lock waiters from starving
the independent audit transaction required before the lock holder commits. Both pools retain the
three-second pool wait,
two-second lock and three-second ordinary statement budgets. Some existing governed workflows have
explicit bounded statement extensions. Admission/quota failure rolls back the governed transaction.

Logical artifact quotas exclude physical TOAST/index/WAL usage, operational objects and independent
security audit. Monitor disk and immutable history growth; do not disable immutable triggers for
ad-hoc deletion. Preserve source inputs for replay, purge eligible terminal ingestion staging through
the existing cleanup service, archive approved evidence before any future governed retention change.

## Backups, PITR and disaster recovery

Proposed initial recovery objectives: RPO at most 60 seconds with healthy off-host WAL shipping;
RTO at most four hours after an operator initiates restore. These are **proposals**, not measured
business-approved objectives. A single host is a failure domain. Assign backup/recovery owners,
encryption recipients, off-host destination, retention/legal policy and alert delivery before release.

The profile enables WAL archival to a separately mounted encrypted filesystem. PostgreSQL must own
the archive directory and failed/full archival must alert. Ship completed WAL and timeline files
off-host, preserving checksums and encryption; local archival alone is not disaster recovery.
Take periodic `pg_basebackup -X stream` physical backups as an authorized replication/backup role
and retain all required WAL from that backup. Store TLS/session/identity configuration and encryption
keys in separate protected backup custody. Test restoration regularly and after major changes.

For a logical backup, install the established `age` CLI and use:

```bash
uv run python scripts/backup_database.py --container APPROVED_POSTGRES_CONTAINER \
  --database foundry --user foundry_migrator --recipient AGE_PUBLIC_RECIPIENT \
  --output /encrypted/backups/foundry.dump.age
```

Repeat for the isolated `keycloak` database with its owner. The script streams dump → age without
writing plaintext, refuses overwrites and discards incomplete artifacts. Logical dumps of separate
databases are not a common-point cluster snapshot. Keep physical backups/WAL for consistent PITR.
Verify ciphertext hashes, decrypt only in a protected restore environment, restore with `pg_restore`
into a NEW empty database, apply ownership/grants and run integrity/authorization/fixture checks.
Do not stream an unverified restore directly into the serving database.

PITR procedure: fence traffic/workers, preserve the failed cluster, create a new isolated cluster
from the approved physical base backup, configure `restore_command` and an explicitly reviewed
time/LSN/named recovery target, add `recovery.signal`, replay retained WAL, verify the target and
promote. Verify tenant/object/branch/SDK/security integrity, reset sessions if trust is uncertain,
run readiness and acceptance checks, then explicitly approve traffic cutover. Keep a rollback copy.
Do not run arbitrary `alembic downgrade` as incident recovery. The automated local drill verifies
pre-backup and post-backup committed data and excludes a post-target record; off-host recovery,
encrypted-volume loss and target-environment RPO/RTO still require an operator drill.

## Observability, alerts and incidents

API JSON request spans contain route templates, request/trace IDs, status and duration only.
Private `/internal/metrics` requires the separate service credential. Scrape each API replica
through the trusted network; use `infrastructure/monitoring/alerts.yaml` with the operator's
existing Prometheus/alert delivery infrastructure. No monitoring service or external receiver is
automatically deployed. Protect the metrics credential with a separate trusted scraper context.

Alert on API readiness, elevated 5xx, p95 latency, broker unavailability, worker failure cycles or
stale heartbeat, active jobs whose leases repeatedly expire, database connections/locks, logical
quota saturation, physical disk free space, WAL archive failures/age, backup age and TLS/key expiry.
API metrics alone cannot report host/PostgreSQL disk or WAL health; use host/database monitoring.
Request-level JSON trace correlation is available; a distributed OpenTelemetry collector is not
configured. Protect log storage and redact downstream collectors; ingress logs only status/duration,
with URI-bearing nginx error output disabled. Do not re-enable callback query logging. Security audit remains append-only in PostgreSQL, not database-owner-proof archival.

For a suspected identity incident: deny public traffic if necessary, disable affected platform
principals/memberships and worker delegation, revoke broker sessions/credentials, preserve audit,
rotate compromised credentials/keys and validate a clean login/authorization before reopening.
For job/engine exhaustion: stop admission/workers, preserve fenced state, inspect redacted codes and
resource/queue metrics, fix capacity/input policy, then restart bounded workers. Never bypass
permission, lease, schema activation or inferred-fact approval checks to clear an incident.

## SDK and release distribution

Generated packages retain canonical schema/API hashes, generator version, per-file digests and a
deterministic archive. `scripts/verify_sdk.py ARCHIVE --sha256 TRUSTED_HASH` independently verifies
archive, inventory, file digests and schema, with optional trusted schema/generator constraints.
Obtain the expected digest from the authenticated platform API or a signed release manifest;
a hash supplied alongside attacker-controlled bytes is not authenticity. Private download still
requires current platform schema permission.

Internal Python/npm registries, authenticated direct downloads and offline archives are supported
distribution patterns; assign package ownership and registry access separately. No public registry
publication is performed. Generated SDK archives are not individually signed by this implementation.
Release images have a SHA256 manifest, SBOMs and an opt-in GitHub provenance-attestation workflow;
verify it with `gh attestation verify` against the approved repository/workflow identity. GitHub-hosted
attestation and environment protection must be configured and independently exercised by operators.

Build → test → package → scan → stage → review/approve → explicit deployment → verify → restore
is the supported release process. Configure required reviewers on the `production-approval`
GitHub environment; an environment name alone does not enforce a reviewer. Failed scan/tests stop
packaging. There is no automatic production deploy step. Review all remaining scan findings and
target acceptance gates before approving an image, even if local regression tests pass.

## Acceptance closure — disposable production profile

The Phase 10 closure harness is `scripts/accept_phase10.py`. It creates a unique Compose project,
new databases/roles, a short-lived private CA, disposable broker identities/secrets and fixture
registrations. It uses the production template and real production images. It never reads `.env`
for deployment configuration and never attaches the developer database volume or existing broker.
Generated credentials, dumps and detailed failure logs remain in ignored `artifacts/foundry-accept-*/`.
Do not publish those directories. Redacted check results go to
`docs/architecture/evidence/phase-10-closure/`.

Build the four prerequisite images from the reviewed checkout:

```bash
docker build -t csh-foundry-ingress:phase10-closure -f infrastructure/docker/ingress.Dockerfile .
docker build -t csh-foundry-api:phase10-closure -f infrastructure/docker/api.Dockerfile .
docker build -t csh-foundry-studio:phase10-closure -f infrastructure/docker/studio.Dockerfile .
docker build --platform linux/amd64 -t csh-foundry-api:phase10-closure-amd64 -f infrastructure/docker/api.Dockerfile .
docker build --platform linux/amd64 --build-arg BASE_IMAGE=csh-foundry-api:phase10-closure-amd64 \
  -t csh-foundry-semantic:phase10-closure -f infrastructure/docker/semantic.Dockerfile .
uv run python scripts/accept_phase10.py
uv run python scripts/test_alert_delivery.py
```

Prerequisites: Docker Compose supporting `!override`, Node >=22 on PATH, frozen uv dependencies,
Studio's installed TypeScript compiler, free Docker subnets 172.29.100/101 and sufficient resources.
The pinned upstream Linux engine release is amd64; ARM Docker Desktop uses emulation for the
semantic image. This is not representative target hardware. The encrypted restore check uses the
retained local `artifacts/age-tool/age/{age,age-keygen}` tools; without them that check is NOT RUN.
Install reviewed age tools there or adapt that path in a reviewed change; never substitute a
plaintext backup and call encryption accepted.

The harness overrides public ports with random loopback bindings, adds only public CA mounts,
uses separate test subnets/trusted proxy address and adds a disposable PostgreSQL management
network/loopback port for offline provisioning. API/Studio/workers keep their production internal
networks and runtime limits. The production DNS/digest preflight intentionally rejects `.test`
hostnames and local image tags; passing Compose validation in this test is not target preflight.
The physical recovery helper `scripts/phase10_pitr.py` verifies the source Compose-project label
and exact WAL bind mount before changing archive ownership. It refuses developer projects and
existing restore volumes. It streams a base backup to a new volume, replays the profile's archived
WAL to a named target, and checks all Foundry/Keycloak public-table row counts and content hashes.
Its restore container has no network. The original source cluster is retained until the normal
disposable-project teardown. This is a same-host database drill; it does not start the restored
application/broker or certify target RPO/RTO.

Only the harness's own project and volumes are removed in `finally`. Private evidence is retained.
Interrupted runs may need the project-specific `docker compose ... down --volumes` command from
that generated directory; never use a broad Docker prune or remove existing developer resources.

Production changes validated by this work: quoted tmpfs options, API source-catalog registration,
Keycloak readiness before API warmup, frontend aliases for the ingress hosts, and HTTP-to-HTTPS
redirects for exact allowed hosts. Only nginx exposes ports 80/443; unknown HTTP hosts are dropped.
Port 80 serves redirects only. Internal metrics/session endpoints remain private. Semantic leases
use the shared database clock without initializing the ingestion/Polars runtime.

The harness records assertions individually; a partial run is not a full acceptance pass. Read
`deployment.json`, the last run log, runtime limits, deployed load results, backup checksums and the
readiness matrix together. A failed assertion writes private diagnostics and exits nonzero.
`test_alert_delivery.py` evaluates the unchanged two-minute API outage rule with actual Prometheus
and Alertmanager, then verifies local firing/resolution webhooks. It uses a synthetic scrape target,
not production monitoring; configure and test the actual receiver and deployed scrape topology
separately. Host/WAL/backup/queue/storage alert rules are not supplied by this small rule set.

## Evidence required before release promotion

Read [the vulnerability disposition](vulnerability-disposition.md). High findings block release;
upstream `wont-fix` classifications do not authorize platform exceptions. All four custom images,
including semantic execution and patched ingress, are scanned and archived. Pinned PostgreSQL
and Keycloak images are also scanned. Scanner/SBOM JSON is retained by
CI even when scanning fails. Image base/tool identities are pinned to reviewed digests.

`verify_release_evidence.py` rejects missing or non-PASS mandatory local gates, wrong revision/image
identities, evidence path escapes and changed evidence bytes. The release workflow expects
`artifacts/acceptance/release-manifest.json` for the exact candidate; it does not manufacture that
file from partial results. The evidence collection/owner review handoff must be configured before
hosted promotion can succeed. A manifest has `source_revision`, `images` (api/studio/semantic/ingress/postgres/keycloak image
IDs), `supply_chain`, and `checks`, with one entry for every name in the script's `REQUIRED` set. Each entry contains
`result: PASS`, a repository-relative `evidence` file and its `sha256`. Use distinct executed evidence
where appropriate; hashes establish integrity, not the truth or approval of a claim. Owner review,
required environment reviewers, off-host custody, live SSO and target certification remain separate.
The validator implements no implicit risk-exception path. Missing evidence deliberately blocks the
archive/provenance/approval jobs. The workflow still performs no deployment.

For operator capacity planning, alert before free data/backup/WAL space drops below an agreed
headroom threshold (provisional starting point: 20% free; page at 10%), and on WAL archive failures
or age beyond the intended RPO. Measure data/TOAST/index, immutable audit/branch/SDK growth and
backup retention separately. These are operator proposals, not enforced physical quotas or approved
business SLOs. Establish named owners, alert routes and measured target retention/capacity before
certification. Logical tenant quotas cannot certify physical disk bounds.

The ingress image now uses the supplier's maintained stable nginx 1.30.6 release (reviewed digest),
which upstream lists as fixed for the remaining nginx-core advisories, and applies maintained Alpine
OS updates. Unused ACME/GeoIP/image-filter/njs/XSLT modules and their unnecessary libraries are removed;
the profile uses built-in HTTP proxy/TLS only. An intermediate 1.28.3 package update was insufficient
and its evidence is retained. `INGRESS_IMAGE` is a new required immutable image input, checked by
preflight. Build, scan and validate it before promotion.
The Keycloak 26.8.1 digest was refreshed from the supplier; existing developer containers are not
recreated. Remaining supplier-library findings still block release and require owner review.
All nginx server blocks, including HTTP redirects and rejected hosts, explicitly select status-only
logging. The callback-sentinel regression caught inherited URI logging before this fix.

## Continuation 3: connection budget and acceptance commands

The production broker now explicitly uses `KC_DB_POOL_INITIAL_SIZE=2`, `KC_DB_POOL_MIN_SIZE=2`
and `KC_DB_POOL_MAX_SIZE=10`. The [supplier default maximum is 100](https://www.keycloak.org/server/db),
which cannot be budgeted together with other clients against this profile's 100 connections.
Do not change the existing developer broker to apply this template change.

An example conservative budget for the documented process counts is:

| Consumer | Maximum connections |
|---|---:|
| Two API processes: each ordinary 5+5 plus audit 2 | 24 |
| One ingestion child plus one semantic child | 20 |
| Optional single outbox child | 10 |
| Keycloak | 10 |
| Single migration process | 1 |
| Explicitly bounded database monitoring allowance | 2 |
| Administrative allowance | 4 |
| PostgreSQL superuser reserved connections | 3 |
| Total including optional outbox | 74 |
| Remaining operational headroom at max_connections=100 | 26 |

This is a process-budget example, not a measured capacity guarantee. Worker maxima count each
child's ordinary default pool conservatively; supervisors do not add another operational datastore.
Studio connects through API, not directly to PostgreSQL. Keep migration concurrency at one and
bound actual monitoring/admin clients to the allowance. More replicas/workers, plugins or changed
pool sizes require recalculation. A one-API/two-worker deployment without outbox uses a maximum
budget of 52 including these allowances/reservations. The separate audit pool is not removed or
unbounded; audit persistence still fails closed and survives ordinary business rollback.

Run the extended fixtures only against newly generated local acceptance projects:

```bash
PATH=/opt/homebrew/opt/node/bin:$PATH uv run python scripts/accept_phase10_closure3.py \
  --output docs/architecture/evidence/NEW_PHASE10_RUN
PATH=/opt/homebrew/opt/node/bin:$PATH uv run python scripts/accept_phase10_operations.py \
  --output docs/architecture/evidence/NEW_OPERATIONS_RUN
```

The first adds warm-up, three original 1/4/8-client repetitions, a 90-second eight-client sample,
a distinct one-CPU contention sample, mixed admission and restored-application startup. Do not
run scans, builds or regressions during its controlled latency window. The separate operations
runner is useful for bounded fault/quota/monitoring retries without repeating a database-only PITR
exercise. Read each assertion/result and private diagnostic path; no partial execution is a complete
acceptance PASS. Retained-load mode checks image identities and CPU/memory bounds only, and explicitly
records that no new measurement ran. It does not assert equivalence of all configuration values.

The browser harness supports `STUDIO_E2E_PORT`, `STUDIO_E2E_API_PORT`,
`STUDIO_E2E_REPLICA_PORT` and `STUDIO_E2E_DIRECTORY`. Check listeners before startup; never let
readiness connect to an unrelated already-running Studio. Continuation 3 uses 13000/18001/13001
and its own private test CA directory, retaining the signed local test provider's unprivileged 8443.

The optional recovery callback can start the restored database on **only** the exact project's
owned internal data network, with `recovered-postgres` as a distinct alias. Source applications
are temporarily fenced and reconnected only within that disposable project. After restored login,
metadata/object/history/SDK/authorization checks, reconnect its source applications and remove its
restore container/volume. Developer volumes, realms and certificates are never substituted.

Supply-chain manifests now require all six role names under `images` and `supply_chain`. Each
`supply_chain[ROLE]` contains the selected `image_id`, exported `config_digest`, and `scan`/`sbom`
records with repository-relative `evidence` and its `sha256`. Bind the platform config digest to
the raw scanner source image ID, and the CycloneDX component version to its platform manifest
digest. Do not equate an OCI index ID with the config digest. The verifier also reads actual
findings and database validity; a claimed PASS or self-declared exception cannot hide high/critical
matches. Old four-image manifests intentionally fail closed and must be regenerated from genuine
executed six-image evidence. Hashes remain integrity checks, not named-owner approval.

The scanner defaults to one locked `artifacts/.cache/grype` database cache across output folders.
Use `--cache-dir /approved/shared/cache` to override it. Do not copy the multi-GiB cache into each
scan/SBOM evidence directory or release archive; record the database identifier, build/source checksum
and raw report. Automatic database freshness validation and the high threshold remain enabled.

Logical quotas still exclude WAL, indexes, TOAST, audit history, object/branch history outside the
accounted artifact rows, backup retention and temporary physical storage. Cancellation releases
active-job slots but retains ingestion staging until the existing minimum-seven-day governed
cleanup. Measure and alert on physical growth separately; byte-limit PASS cannot certify disk bounds.

## Acceptance Closure 4 — correlated timing and bounded workloads (2026-11-03)

The [executed evidence](../architecture/evidence/phase-10-closure-4/README.md) retains final runtime
configuration, all read attempts, bounded writes/async timing, fault outcomes and security gates.
Build reviewed API/Studio images tagged `csh-foundry-api:phase10-closure4` and
`csh-foundry-studio:phase10-closure4` with their existing Dockerfiles. Keep the selected semantic,
ingress, PostgreSQL and Keycloak identities recorded in images.json; they did not change here.

```bash
PATH=/opt/homebrew/opt/node/bin:$PATH uv run python scripts/accept_phase10_closure4.py \
  --scope all --output docs/architecture/evidence/NEW_CLOSURE4_RUN
# Focused follow-ups preserve the read workload or bounded write workload separately:
PATH=/opt/homebrew/opt/node/bin:$PATH uv run python scripts/accept_phase10_closure4.py \
  --scope reads --output docs/architecture/evidence/NEW_READ_RUN
PATH=/opt/homebrew/opt/node/bin:$PATH uv run python scripts/accept_phase10_closure4.py \
  --scope writes --output docs/architecture/evidence/NEW_WRITE_RUN
```

Use one disposable acceptance project at a time because its fixed test subnets are shared by this
harness. Random loopback ports and new owned volumes remain mandatory. No developer `.env`, realm,
volume or trust store is used. Private credentials/WAL/logs stay under ignored artifacts.

`FOUNDRY_DIAGNOSTIC_TIMING=true` and `STUDIO_DIAGNOSTIC_TIMING=true` are optional diagnostic flags,
default false; the harness sets them only on disposable API/BFF containers. Trace propagation joins
the internal browser-state and governed API calls. Timings contain finite stage totals and IDs,
not statements/parameters/tenant values/tokens. Acquisition includes pre-ping/creation/callbacks.
The bounded sampler retains container ID/name, counters, database waits/connections/queue age and
macOS aggregate memory-free queries; live log collection survives recreation. Raw spans are
deduplicated on correlation. Linux hosts without `memory_pressure` cannot claim that macOS probe.

Current read protocol passes; historical failures and the captured shared one-second stall remain
retained, with causal root unresolved. No speculative query/cache/pool optimization was made.
Final writes separate HTTP admission from server queue/execution/completion; semantic completion
can exceed two seconds even when admission passes. These are fixture-scale engineering targets,
not approved SLOs or production capacity. Existing 52/64/74 connection-budget examples remain.

Security still blocks promotion: 274 high/two critical raw matches. Supported RHEL CA correction is
already present in the selected Keycloak image, verified against actual Java anchors and vendor
package advisory; no automatic scanner exception is introduced. Stable trixie libxml2 remains
UNFIXED. A named security/release owner must obtain supported fixes or authorize a separate reviewed
disposition process. Existing external SSO/off-host/receiver/owner/target/hosted prerequisites and
procedures remain mandatory. No actual target deployment or external modification was performed.

## Security candidate and deployment configuration — 2026-11-03

Build the reviewed database runtime using
`docker build -t csh-foundry-postgres:REVIEWED -f infrastructure/docker/postgres.Dockerfile .`.
It retains the pinned official PostgreSQL 17.11-trixie base/ABI/locale/extension/backup layout and
uses apt to remove supplier-build GnuPG tools. PostgreSQL libxml2 is retained and still vulnerable.
`POSTGRES_IMAGE` is now **required**, alongside API/Studio/semantic/ingress identities in the public
production environment file. Set it to the independently reviewed derived image's immutable
registry digest after an authorized publication. Do not substitute the unminimized supplier image
and assume the new scan applies. No image was published here; local candidate IDs in evidence are
not downloadable registry artifacts. Developer Compose is unchanged; no in-place cluster conversion.

The API Dockerfile now installs dependencies in a separate same-base stage; runtime has no uv
installer/cache. Operators use the installed Python commands at runtime. Semantic engine pin and
security/transaction/session/worker contracts remain unchanged. See
[security closure](../architecture/evidence/phase-10-security-closure/README.md) for removed packages,
all 32 advisory dossiers, supported/rejected upgrade paths and combined recovery evidence.

Run exact local candidate acceptance with the existing harness:

```bash
PATH=/opt/homebrew/opt/node/bin:$PATH uv run python scripts/accept_phase10_closure3.py   --candidate-images docs/architecture/evidence/phase-10-security-closure/images.json   --output docs/architecture/evidence/NEW_SECURITY_CANDIDATE_RUN
```

The file must contain all six roles and immutable local `sha256:` identities; replacements cannot
be pulled. This mode runs the bounded original workload, not a new general latency investigation.
Use only new owned disposable projects/volumes, never existing developer/production resources.

Release policy has no independently approved advisory-authorization provider. Build provenance does
not confer risk approval. The CLI rejects disposition submissions and all raw high/critical matches.
`scripts/security_dispositions.py` validates exact advisory/image/config/package/purl/evidence,
decision/authority/expiry and detached-signature authorization through an external verifier interface;
it installs no keys and provides no production CLI bypass. Actual integration requires an independently
administered approved provider and security/release policy review. Do not use developer keys to
approve an exception. The Keycloak vendor CA correction dossier is approval-ready technical
evidence, not authorization. Current raw gate remains FAIL: 251 high/two critical across 31 IDs.
Review by November 10 or any supplier/image/database/trust-store change. No risk is accepted.

The final candidate additionally removes the optional `mount` command package from API, Studio,
semantic and PostgreSQL using apt. Sixteen util-linux source-package matches disappear; required
util-linux/libmount components and their four advisories remain unresolved. No full advisory fix
is inferred from these command removals. The earlier 267-high candidate and its deployment evidence
are retained separately; final candidate counts are 251 high/two critical.

Final exact-candidate combined deployment **PASS: 58 assertions / 50 distinct checks**, including
physical PITR/restored applications, worker recovery, authorization/governance, durable sessions,
TLS, rotations and rollback. Final isolated browser E2E **five PASS**; an earlier final attempt
retains one stale activation-header failure despite successful activation. Its cause remains
unresolved and is recorded as an intermittent validation limitation, not erased by the passing
rerun. Final security/release/recovery focused suite: **55 PASS**. No assertions/timeouts changed.

## OKD4 portability continuation

Use [the OKD4 guide](okd4-deployment.md) for application-only Kubernetes deployment with external
PostgreSQL/Keycloak. The existing Compose topology is preserved, with a coordinated ingress image
and port update: the new unprivileged nginx listens on 8080/8443, mapped to host 80/443. Rebuild
and select it together with the updated Compose template; historical ingress images listening on
80/443 cannot be mixed with that template. API/Studio/workers use an explicit OIDC backchannel
socket port 8443 inside Compose; public issuer identity and TLS/signature checks remain unchanged.
TLS private keys must be readable by supplemental group10001 (e.g. root:10001 mode0440), with
traversable parent directories; there is no runtime root ownership fix. Test-only generated keys
may use different permissions inside their private disposable directories.

`scripts/test_nonroot_containers.py` tests two unknown UID/GID pairs with read-only roots and
no capabilities. `scripts/accept_okd4_local.py --candidate-images FILE --output NEW_DIRECTORY`
runs the isolated combined profile; `--scope replicas` checks two ingestion workers and two API
replicas. Put Node>=22 on PATH first. These runners preserve previous outputs and never certify
actual Kubernetes routing/admission. Complete exact candidate supply-chain/security gates and
independent target approval before any publication or deployment.
