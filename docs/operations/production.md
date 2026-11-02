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

Networks isolate frontend, broker proxy, database and outbound access. Only nginx publishes a port
(443). API does not trust forwarded headers. Nginx replaces forwarded identity headers; Keycloak
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
testing justifies it. Pool defaults are five connections plus five overflow, three-second pool wait,
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
