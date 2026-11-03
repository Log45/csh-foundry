# Phase 10 storage audit

**Does the current implementation require S3 for correct operation on OKD4? No.**
S3 is not required for the current OKD4 deployment. No S3 library, credentials, bucket,
MinIO workload, or new storage service is introduced. This conclusion covers the current bounded
application, not the future dataset/media/artifact roadmap in PLANS.md version 1.5.

The audit searched runtime Python packages, Studio handlers/server code and SDK packages for
filesystem opens, writes, temporary directories, uploads and S3 libraries. Operational database
models and service calls were then inspected. PostgreSQL remains authoritative; RDF is derived.

| Component | Data / classification | Current backend / source | Durability and sharing | Deployment action |
|---|---|---|---|---|
| Ingestion | CSV/Parquet source files, external source | `ingestion/catalog.py:Binding.path`, `ingestion/connectors.py:extract` open registered read-only paths, reject traversal/symlinks, cap at 16 MiB; PostgreSQL connector reads registered external tables | Files must remain available and byte-stable through extraction/retry. API source validation and every eligible ingestion worker need the same registration and source bytes | Use a pre-existing shared read-only source PVC, or registered PostgreSQL sources. Never put durable input only in emptyDir |
| Ingestion | Runs, staging rows, checkpoints, fingerprints, durable/shared | PostgreSQL models and `ingestion/worker.py` / `ingestion/service.py` | Survive process replacement; leases/fencing and authorization remain transactional | Keep database and original source, no per-worker durable filesystem |
| Semantic | Input/output RDF, manifests, reports, proofs, durable/shared | `db/models.py:SemanticArtifact`, semantic artifact/job services store text/JSON in PostgreSQL | Results remain available across API/worker replicas and restarts | Retain existing tenant quotas and permission/freshness checks |
| Semantic | Engine state, certificate files, stdout, temporary | `semantic/engine.py:OpenOntologiesAdapter._run` uses TemporaryDirectory, bounded inputs/outputs and explicit engine data-dir | Disposable, no cross-pod dependency | `/tmp` emptyDir; failed jobs recover through existing leases and DB inputs |
| OWL authoring/import/export | Original axioms and derived canonical drafts, durable/shared | `interoperability/service.py` and PostgreSQL semantic artifacts; handlers accept bounded content, not arbitrary file paths | DB persistence; publication/activation remain separate governed services | No Protégé/WebProtégé server or shared local authoring directory |
| SDK | Generated source, manifest, reproducible/durable/shared | `sdk/service.py`, `db/models.py:SDKArtifact.files_json`; ZIP generated in BytesIO by `sdk/generator.py` | Database stores immutable generated files and metadata; downloads reconstruct ZIP | No separate SDK worker or persistent local package directory |
| SDK CLI | Explicit caller-selected output files, reproducible | `sdk/__main__.py` reads published export and OpenAPI and writes `--output` | Operator/developer owns downloaded output | Outside always-on pod workloads; use a scoped output volume if running CLI in a Job |
| Studio | Browser sessions, login state, durable/shared | `lib/server.ts` calls API internal browser-state service; `BrowserState.ciphertext` PostgreSQL | Shared persistent keys required across API/Studio replicas; no sticky-session assumption | Mount shared Secrets; browser holds opaque HttpOnly cookies only |
| Studio | Upload/request bodies, temporary | BFF JSON forwarding, bounded OWL content | No durable filesystem upload endpoint or current media attachment backend | Keep request limits; no object-storage backend needed |
| Studio | `.next` cache, reproducible | Next standalone runtime | Cache loss is safe | Symlink `.next/cache` into `/tmp/next-cache`; built assets remain immutable |
| Worker | Heartbeat, temporary | `jobs/supervisor.py` touches `/tmp/foundry-worker-heartbeat` | Local health only; not durable job truth | EmptyDir; restart rebuilds heartbeat; failed work uses lease expiry/fencing |
| Operations | Audit, durable/shared | PostgreSQL audit/outbox/history tables | Transactional alongside governed actions | Do not move to S3 |
| Operations | Encrypted logical backups, physical backups and WAL, durable | `scripts/backup_database.py`, `phase10_pitr.py`; explicit operator output and archive paths | Independent retained backups and keys must survive database/host loss | External DB administrator owns off-host recovery. No backups in app emptyDir or tracked evidence |
| Operations | Evidence and logs, operator artifacts | Scripts write selected output paths; workload logs stdout/stderr | Evidence retention belongs to release/operator system | Public sanitized summaries tracked; secrets/private traces/backups stay ignored |
| Runtime | Configuration, public CA files, templates/native executable, immutable inputs | Settings secret files, SDK templates, pinned semantic executable | Recreated from images/Secrets/ConfigMaps | Read-only mounts, no startup package installation/chown |

The portable base supports remote PostgreSQL ingestion registrations without a source volume.
For CSV/Parquet add the `infrastructure/kubernetes/components/file-sources` component to a site
Kustomization. It mounts an **existing** `foundry-sources` claim read-only into API and ingestion
workers at `/data/ingestion`. The storage owner must provide multi-node read access where those
pods can schedule, matching the registered catalog paths. Do not substitute pod-local hostPath.
No PVC is required for operational objects, semantic outputs, SDK artifacts, sessions or jobs.

Local real-PostgreSQL regression exercises SDK/artifact persistence, ingestion restart/fencing,
semantic worker recovery, shared sessions, governance and authorization. Arbitrary-UID image tests
exercise Polars reads, SDK ZIP generation, engine scratch writes, immutable-path denial and shutdown.
The combined disposable deployment separately tests actual supervised worker recovery and restored
applications; consult `evidence/phase-10-okd4-readiness/` for exact results rather than assuming PASS.
Actual pod replacement/rescheduling, cross-node source access and SCC volume group injection are
NOT RUN without an appropriate cluster. Local Docker replacement is not Kubernetes durability proof.

Future large datasets, retained uploads or media may justify an optional object-storage abstraction,
with DB metadata, tenant ownership, bounded transfers and explicit orphan recovery. That is outside
this Phase 10 change and must follow a separately approved storage requirement. PostgreSQL
transactional state and durable outbox must remain in PostgreSQL.
