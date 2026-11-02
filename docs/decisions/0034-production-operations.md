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
