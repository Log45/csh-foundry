# ADR 0034 — A bounded single-host Docker deployment profile

Accepted for Phase 10. Extend Docker Compose; add no Kubernetes, Redis, Kafka, second authorization
engine or operational datastore. PostgreSQL keeps platform and identity-broker data in separate
logical databases and ownership domains. Nginx is the sole public TLS entry. Application, identity,
data and egress networks separate trust boundaries. Fixed issuer/origin configuration and exact
proxy addresses prevent OAuth origin selection from arbitrary headers.

One API, one Keycloak, one PostgreSQL and one or two Studio replicas are the initial target.
Single-host failure remains a recovery event. Backups and WAL must be encrypted and copied off
host by the deployment operator. `scripts/test_recovery.py` exercises real PostgreSQL physical
base backup plus WAL target recovery in isolated Docker volumes. A realm JSON export is not a
backup of Keycloak sessions, events or revoked tokens.

Run existing bounded ingestion/semantic/outbox children under a small supervisor. Each child gets
fresh configured credentials, existing platform delegation and a process-group deadline. Containers
bound memory, CPU, processes and temporary disk. PostgreSQL leases/fencing and three-claim limits
remain the recovery mechanism; the supervisor does not create a second job registry. External
outbox effects remain at-least-once and consumers must deduplicate event IDs.

Migration 0017 accounts logical JSON bytes of SDK/semantic/import/branch artifacts and ingestion
staging transactionally per tenant. It bounds combined pending/running ingestion and semantic jobs.
These quotas are admission controls, not complete physical disk accounting. Operational objects,
security audit and immutable earlier history still need capacity monitoring and an operator retention
policy. Shared database-clock request budgets restrict verified identities across API processes;
ingress separately limits client addresses. No external role claims affect these controls.

JSON request spans use W3C trace identifiers, finite route-template labels, status and duration;
no request bodies, query strings, tokens or raw exception text are logged. Private Prometheus
metrics expose counts and latency histograms. This is request-level tracing, not a distributed
OpenTelemetry collector. Long-term log/audit export and alert delivery are operator integrations.

Maintenance-window migrations/deployments are supported. No zero-downtime, automatic destructive
downgrade, rolling mixed-version, multi-host or HA guarantee is made. Release scans and approval
gates must fail closed; outstanding vulnerability findings block production promotion.

## Phase 10 acceptance-closure addendum (2026-11-02)

Actual combined deployment exposed invalid YAML tmpfs splitting and an API/broker startup race.
Quote mount options and require the broker's actual management readiness endpoint before API
OIDC warmup. The broker probe uses the [documented Bash TCP method](https://www.keycloak.org/observability/health); no curl package is added.
API receives the same server-owned ingestion catalog as its worker. Exact-host HTTP redirects
use nginx; no forwarded client origin selects a callback or provider.

A semantic-worker import of the ingestion clock initialized Polars and crashed under amd64
emulation without AVX. Lease time now comes from the shared database module. This removes an
unnecessary tabular runtime initialization while preserving database-clock lease/fencing behavior,
the pinned native semantic engine, and ingestion's Polars transformations.

Reviewed multi-platform base/tool digests are pinned in application Dockerfiles. Release packages
include and scan the semantic image as well as API/Studio, retain failed-scan evidence, and require
exact-candidate acceptance evidence before promotion. Integrity hashes are not owner approval.
No residual vulnerability exception, external infrastructure change, schema migration, new
reasoning/identity authority or Phase 11 capability is introduced.

Infrastructure scanning also exposed fixable findings in the retained nginx base. Use a reviewed
patched ingress image (`INGRESS_IMAGE`), supplier stable nginx 1.30.6, updated
Alpine OS libraries and no unused vendor modules. Preserve the official HTTP include/template layout. Pin PostgreSQL and the refreshed same-version Keycloak supplier image by digest.
Do not mix unstable Debian packages into PostgreSQL or independently replace Keycloak's bundled
Guava jar and call it supplier-certified. Retained critical supplier findings require review; no
exception is approved. Explicit status-only access logs cover redirect and rejected-host servers.

Concurrent full-profile admission testing exposed pool starvation: business transactions waiting
for an ontology lock consumed the ordinary pool while the lock holder needed an independent audit
transaction before commit. The API now gives authorization audit inserts a separate bounded pool
of two connections with no overflow, using the same database, schema and restricted role. Business
pool limits and lock/statement deadlines are unchanged. Independent decision evidence still survives
business rollback, and failed audit persistence still aborts the mutation. Default API connection
capacity becomes 12 per process; operators must include both pools in PostgreSQL sizing. Single-job
worker children keep their existing pool and sequential audit behavior. No database migration is
needed. Regression checks exercise concurrent mutations with a one-connection business pool.

## Continuation 3 — bounded broker connections and recoverable acceptance

Keycloak's documented default maximum is 100 database connections, which alone equals this
profile's PostgreSQL maximum. Explicitly configure initial/minimum two and maximum ten broker
connections. This changes only the production template; existing developer identities, keys and
persistent stores are not recreated. Count broker, API ordinary/audit pools, worker children and
operator tooling together. The cap is a connection budget, not a throughput certification.

The optional restored-application drill starts the restored cluster on the exact owned internal
Compose data network, with a distinct recovery alias. A `none` network cannot subsequently join
an application network. Keep network-none isolation for the database-only path. Validate network
name, ownership and internal status before use; never substitute a developer or public network.
The application drill preserves both restricted-role and TLS/issuer validation and tests a restored
broker/API/Studio instead of inferring availability from table checksums.

Supply-chain identity has two layers: the selected Docker image/index identity and the exported
platform config/manifest identities. Record and verify both rather than equating a multi-platform
index digest with a scanner config digest. Keep one shared, locked, refreshable vulnerability database
cache outside per-run evidence. Raw scans/SBOMs and their database identifiers remain the evidence;
copying a multi-GiB advisory cache into every output directory adds no acceptance assurance.
