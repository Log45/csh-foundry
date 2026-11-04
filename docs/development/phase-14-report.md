# Phase 14 — Governed Polars execution and bounded dataset ingestion

Date: 2026-11-03 (America/New_York). Scope: explicitly authorized milestone D only.
Base revision: `23c237d`; Phase 14 changes are uncommitted in this workspace.
Status: **PASS — Phase 14 local development acceptance complete**; production remains **BLOCKED** under
Section 23B. No Phase 15 functionality, deployment or production certification was performed.

## Architecture and implemented functionality

[ADR 0039](../decisions/0039-governed-pipeline-execution.md) was recorded before substantial coding.
Dataset ingestion, immutable pipeline definitions and execution are separate modules. PostgreSQL owns
resources, definitions, leases, pinned identities and publication. The existing ArtifactStore/S3 adapter
remains the only byte store. No Spark, Rust, arbitrary Python, query engine or additional database.

PIPELINE resources use existing Projects/folders, stable resource IDs, archive, sharing and revocation.
The structured editor publishes append-only definition versions; no mutable draft can execute. A closed,
typed JSON AST supports select, rename, drop, filter, sort, strict cast, derive, fill-null, deduplicate,
grouped aggregation, joins and union. Columns/types/collisions are checked during planning; input/output
schema contracts are supported. Expressions have bounded depth/arity and finite scalar literals. Checked
integer arithmetic and sums reject overflow, casts are strict, null filters exclude unknown values and
nonfinite outputs (including division by zero) fail validation. Decimal/temporal/nested values retain
bounded schema/preview serialization. See [API and operation semantics](../api/pipelines.md).

An engine-neutral Protocol and portable persisted specification separate planning from resolution,
authorization, admission, execution, materialization, validation and publication. The Polars adapter uses
lazy scans and streaming Parquet sinks; JSON normalization writes bounded pieces with reconciled types.
Sorting, grouping, joins and deduplication may require state and may fail a budget. This is not a claim
that every operation streams or every 1 GiB cardinality fits the configured worker.

Runs pin definition UUID, dataset/version UUIDs, physical SHA-256s, parameters (currently empty), engine
identifier/version, authenticated identity and limits before queueing. Queued/admitted/running/cancelling/
succeeded/failed/cancelled states, attempts, admission/start/completion timestamps, heartbeats, sanitized
errors and metrics are durable PostgreSQL records. SKIP LOCKED, database-clock leases, random fencing
tokens, bounded retries and global/tenant/Project admission protect dispatch/publication. The controller
runs separately with `scripts/run_execution_worker.py`; no in-memory HTTP background task owns a job.

Artifact transfers now release broad governance transactions before S3 I/O and reauthorize afterward.
Upload slots are PostgreSQL session advisory locks across API processes, released on disconnect. Workers
renew leases during processing/transfers, execute only trusted declarative adapters in owned children with controller credentials removed from
the environment and owned native/Python scratch directories,
and fence publication after cancellation/revocation/deadline. A durable internal admission retains
identity attributes rather than bearer credentials; current identity bindings, membership and permissions
are checked again before input resolution and publication, even after the original browser token expires.

Output reservation is persisted once per run. Reserved derived versions reject user upload/finalize/validation
requests. Both physical and logical database commit guards require the current live worker lease and
transaction-local execution fencing token. Starting and publishing a run require current pipeline
Project write permission, input read permissions and output write permission; a read-only pipeline share
cannot launch a run. Execution writes private temporary Parquet, validates its
entire content/schema and checksum, then commits immutable S3 bytes. One PostgreSQL transaction commits
physical metadata, dataset result and successful run/lineage. A bytes-before-metadata failure retries the
same reservation and verifies bytes; changed checksums fail closed. Inputs and committed versions cannot
be overwritten. S3 and PostgreSQL are explicitly not one transaction. Normal failure/cancellation cleans
attempt files; abrupt host death can require ordinary temporary-directory maintenance. Committed bytes,
including abandoned output reservations, retain the existing indefinite retention policy.

Lineage is derived only from successful run records and immutable input rows, referencing both logical
and physical versions (the existing dataset/artifact version UUIDs coincide). Definition/specification,
engine/version, actor and timestamps are returned only with current pipeline access. Inputs and output
identities are filtered independently; sharing a pipeline grants no private dataset identities/content,
and sharing an output grants no private input/definition identities. Retrieval is bounded to one hop.

## Dataset ingestion redesign and limits

New validation streams records/batches rather than reading an entire source into a Python bytes object
or collecting a whole dataset frame. CSV checks strict quoting, UTF-8/BOM, duplicate headers, exact row
widths and every record, reconciling types across all batches (including later null/text batches). JSON
arrays use a bounded incremental decoder; NDJSON is line oriented. Both preserve recursive duplicate-key
and key/type consistency checks. Key order alone is not a schema change. Parquet uses footer/schema
metadata plus bounded Arrow batches, rejects excessive declared expansion and excludes arbitrary footer
key/value metadata from source-schema display. Every decoded value is validated before publication. Parquet page checksums are verified when present;
decoded counts must match footer counts. Execution rechecks source schema/order and row count against
the immutable snapshot, disables Parquet statistics-based pruning and verifies the materialized output
schema against the planned schema before publication.

Default source ceiling is **1,073,741,824 bytes** for CSV, NDJSON, JSON arrays and Parquet. Independent
limits cover source bytes, decoded bytes (16 GiB), batch target (8 MiB), record bytes (1 MiB), Parquet
row-group expansion (256 MiB), rows (100 million), columns (256), cells (64 KiB), nesting (8), preview
rows (100), memory (2 GiB), address space (8 GiB), temporary disk (4 GiB), CPU (1200 seconds), wall time
(1800 seconds), jobs (2 global / 2 tenant / 1 Project), queue (100) and uploads (2 global / 1 tenant).
Source/row/schema limits can be lowered administratively. Full settings and provisioning requirements:
[worker operations](execution-workers.md). Only bounded metadata/previews/provenance enter PostgreSQL.

`/validate` always enqueues a durable job. Finalize retains synchronous compatibility through 8 MiB and
queues larger sources; both use bounded parsing. Repeated enqueue/completion is idempotent. Permanent
malformed data is distinct from retryable infrastructure failures. Existing historical terminal results
are not rewritten. The legacy in-memory `parse(bytes)` helper retains Phase 13 bounds for its historical
unit contract; actual service parser children use the new bounded implementation. The small synchronous compatibility path retains its additional 30-second wall / 20-second CPU,
512 MiB macOS RSS watchdog / 2 GiB Linux address-space and two-parser-per-API-process bounds; use
`/validate` to select durable worker budgets explicitly. Small synchronous parser admission is per process; durable workers have database-wide admission.

Studio supports pipeline creation, definition grammar validation/publication, explicit pinned-input JSON,
run launch/history/metrics, cancellation/retry, output preview and authorized lineage. Dataset uploads
hash 1 MiB slices with pinned @noble/hashes 2.0.1 and stream through the existing fixed-destination,
session/CSRF/tenant-protected binary BFF. The binary BFF is excluded from Next Proxy matching to avoid
its request-cloning body buffer; the route retains independent authorization and a restrictive response CSP. Validation status can be refreshed/polled after navigation.
Interrupted browser transfers retry the same immutable version from the beginning; browser byte-range
resume is not implemented. S3 transfer uses the existing bounded multipart protocol. No credentials or
worker endpoint are exposed. Existing Project, artifact, ontology, action and SDK workflows remain.

## Migration and developer-data preservation

Initial code head: `0020_datasets`. New forward-only head: **`0021_execution`**. Adds
`pipeline_definitions`, `execution_jobs`, `execution_inputs`; extends registry PIPELINE authority and
adds tenant-qualified FKs, immutable published definitions/input lineage, immutable output reservation,
legal job transitions and lease/state checks. Frozen migration SQL does not import evolving ORM models.
No historical migration, fixture, schema snapshot, object key or checksum was modified.

Executed checks cover fresh installs, upgrade from `0020_datasets` with committed source/schema/preview
preservation, and Alembic drift. Only disposable schemas were upgraded. Read-only initial/final checks
confirm the shared developer database remains **`0017_capacity`**. MinIO runners create/remove only their
randomly named test projects/volumes; existing developer volumes were not reset.

## Executed 1 GiB and resource evidence

Hardware: Apple M1 Pro, 10 logical CPUs, 16 GiB RAM, macOS 15.6.1 arm64. Python 3.12.0, Polars 1.44.2,
PyArrow 23.0.1, real PostgreSQL and disposable real MinIO. Child limits: 2 GiB RSS watchdog, 8 GiB Linux
address-space limit, 4 GiB temporary disk, 1200 CPU / 1800 wall seconds. Node 25.9.0 ran Studio checks.

[All 16 tier measurements](evidence/phase-14/large-tiers.md),
[machine-readable checksums/metrics](evidence/phase-14/large-measurements.json), and
[real integration output](evidence/phase-14/large-integration.txt) preserve actual evidence.
The final [maximum-source rerun](evidence/phase-14/final-maximum.txt) repeated all four 1 GiB formats
and the representative transformation after parser/column-reference refinements. Parser timings exclude
source download/queue time. Each exact-byte source is generated deterministically at runtime, uploaded through governed service/
ArtifactStore transport to MinIO, downloaded/checksummed by a new controller, validated and committed
with verified row count/schema/preview and idempotent enqueue. These performance uploads exercise the
service/storage path. A separate real Chromium/Studio/BFF/API/MinIO upload of an exact 1 GiB CSV
passed asynchronous validation and preview assertions for all 262144 rows; see
[final browser evidence](evidence/phase-14/final-browser.txt). Browser throughput/RSS was not benchmarked.

| Exact 1 GiB source | Rows | Upload seconds | Validation seconds | Peak child RSS MiB | Temp MiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| CSV | 262080 | 24.59 | 17.32 | 236.52 | 1024.39 |
| NDJSON | 261187 | 19.53 | 7.17 | 164.52 | 1024.39 |
| JSON array | 261187 | 19.60 | 7.55 | 161.95 | 1024.39 |
| Parquet | 255620 | 18.88 | 3.38 | 222.73 | 1024.39 |

A final [1 GiB CSV/source-contract rerun](evidence/phase-14/final-pipeline-maximum.txt) passed after the
source schema/count and output roundtrip checks: validation 16.54 seconds, peak 284934144 bytes; upload
17.51 seconds. The select pipeline succeeded, producing a committed output and real lineage: 17.77 seconds
inside the child, **1,505,132,544 bytes peak RSS (1.40 GiB)** and approximately 1024.42 MiB temporary disk,
within the configured 2 GiB / 4 GiB budgets. Sources contain deterministic repeated 4 KiB text values;
Parquet is uncompressed with bounded row groups and bounded metadata padding to exact file size.
Outputs compress well. No claim is made that arbitrary high-cardinality joins fit these budgets.

Tests also constrain an actual sort to 128 MiB, verify clean failure and no published output, preserve
source checksum, fence end-to-end deadline expiry, and exercise real controller-process exit/restart,
expired leases, stale tokens, cancellation, retry, duplicate dispatch and storage-success-before-metadata
recovery without duplicate output versions. Successful large jobs stay within the measured memory cap.

Linux smoke used cached image `sha256:293585428a908cf37a46b219acef8c11a33ab1498dc82013e83e1318636b476d`,
read-only root/source, UID 10001, 2 CPUs, 2 GiB cgroup memory, PID limit 128 and a 1 GiB temporary volume.
Pinned PyArrow was installed only in the disposable filesystem. All four isolated parsers and a Polars
pipeline passed; [evidence](evidence/phase-14/linux-isolation.txt). This is a small-source Linux smoke,
not Linux 1 GiB acceptance or production certification. macOS RSS monitoring and aggregate-directory
polling are soft safeguards; Linux CPU/address-space/per-file-size and container limits are distinct
kernel controls. Deployments need an appropriately sized container/temp volume and restricted egress.

## Validation results

| Command/check | Status | Actual result |
| --- | --- | --- |
| Initial/final `uv run alembic heads` | PASS | `0020_datasets` → `0021_execution` |
| `scripts/validate_phase14.py --full` final regression | PASS | 742 passed, one preserved strict xfail, zero skips; 705.55 seconds; drift clean |
| `scripts/validate_phase14.py --large` | PASS | All 16 cases; all four formats at 8/100/500/1024 MiB, plus 1 GiB transformation; 291.96 seconds |
| Final 1 GiB verification after refinements | PASS | Four maximum-format cases plus CSV transformation; 186.39 seconds; twelve smaller tiers deselected explicitly |
| Focused final PostgreSQL/MinIO suite | PASS | 99 passed, zero skips; 60.05 seconds; latest source checks and publication guards |
| Final CSV maximum/source-contract rerun | PASS | One 1 GiB case plus pipeline; 67.66 seconds; fifteen other format/tier cases explicitly deselected |
| Durable Studio browser regression | PASS | Ten workflows, zero skips; 1.9 minutes, including actual 1 GiB CSV upload |
| Studio Vitest | PASS | 42 tests across nine files |
| Python Ruff lint / formatting / mypy | PASS | Executed; no violations; 126 source files type checked |
| Studio typecheck / Prettier / production build | PASS | Executed with supported runtime |
| OpenAPI / TypeScript generation | PASS | Exported from actual application; existing semantic JobView name preserved |
| Fresh/previous-head upgrade and drift | PASS | Disposable schemas; committed dataset bytes/results retained |
| Linux isolation smoke | PASS | Four formats and pipeline under constrained non-root container |
| Developer database preservation | PASS | Read-only revision `0017_capacity` |
| Historical fixtures/migrations/evidence preservation | PASS | Git diff inspection |
| Standalone TypeScript lint | NOT SUPPORTED | No configured standalone lint script; typecheck/format/build executed |
| Real target cluster/external provider/production certification | NOT RUN | Separate Section 23B approval/environment required |
| Linux 1 GiB cgroup benchmark | NOT RUN | Four maximum-format service tests ran on macOS; constrained Linux smoke used small sources |

The full suite ran before final narrow worker/authorization/parser refinements and additional focused
tests. The [latest targeted results](evidence/phase-14/final-targeted.txt),
[browser results](evidence/phase-14/final-browser.txt) and final maximum reruns supplement that full regression; counts are not combined into a
fictional single run. No tests were weakened or silently skipped. Evidence includes actual commands,
results and the exact changed-file inventory in `evidence/phase-14/`.

Initial failures were corrected and are not counted as passing evidence: the new malformed-CSV test
omitted csv.Error; the first exact-byte Parquet generator omitted explicit footer metadata; a new
JobView name collided with an existing semantic schema; the shell's old Node rejected NODE_OPTIONS;
and rebuilding Studio during a running browser suite invalidated that suite's assets. The first full
regression read migration changes after importing older ORM metadata and correctly reported two drift
failures; the subsequent frozen-schema full run passed. Linux smoke exposed missing `ps` in the minimal
image (fixed with `/proc` RSS reads), then an executable-library install on a noexec test tmpfs (corrected
only in the disposable dependency-install harness). Browser maximum testing exposed Next Proxy body
buffering (fixed in route matching) and Playwright interception/trace memory overhead (maximum test
disables capture and removes the login-only interception before the upload). Functional maximum-size
assertions remain active. No production image/security policy was loosened.

## fixtures/VALIDATION.md

The guide was consulted before completion. Results refer to the executed real full regression.

| Check | Status | Evidence |
| --- | --- | --- |
| Turtle parsing | PASS | Canonical fixture regression |
| CSV counts/identities/FKs and RDF identity consistency | PASS | Canonical fixture regression |
| Raw pySHACL compatibility | NOT SUPPORTED | Existing strict xfail for simple/xsd:string mismatch |
| Normalized SHACL and negative mutations | PASS | Fixture/semantic regression |
| Open Ontologies SHACL | PASS | Existing pinned-engine integration tests |
| OWL supported owl-rl-ext inference and noncritical exclusion | PASS | Pinned-engine reasoning tests |
| Base owl-rl exact fixture axiom | NOT SUPPORTED | Existing documented profile limitation |
| PostgreSQL / FastAPI queries / actions / reconciliation | PASS | Full real-database regression |
| Polars operational ingestion | PASS | Existing ingestion regressions |
| Authorization and tenant isolation | PASS | Full security plus focused pipeline/dataset checks |
| Protégé supported import/export | PASS | Interchange regression and browser workflow |
| Manual Protégé GUI inspection | NOT RUN | No new ontology authoring construct; no desktop session |

## Phase 14 acceptance matrix

PASS is local development acceptance on the executed evidence, with the platform limitations above.

| # | Required criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Governed pipeline resources | PASS | Registry/service/browser tests |
| 2 | Immutable versioned definitions | PASS | Direct SQL guard and publication tests |
| 3 | Declarative Polars transformations | PASS | Typed grammar and operation tests |
| 4 | Exact immutable input pins | PASS | Tenant-qualified input FKs/checksums and run tests |
| 5 | New immutable output versions | PASS | Artifact/dataset publication and checksum tests |
| 6 | Durable restart-safe runs | PASS | Real process crash, lease expiry and fenced recovery |
| 7 | Cancellation/retry | PASS | Queued/running cancellation, infrastructure retry, immutable reservation |
| 8 | Isolated resource bounds | PASS | Spawned children, memory failure, deadline fencing, Linux smoke; macOS limitations explicit |
| 9 | Real lineage | PASS | Successful-run input/output edges and provenance |
| 10 | Authorization/revocation | PASS | Current resource checks, revoked-input failure, private lineage/output filtering |
| 11 | Studio creation/execution/monitoring | PASS | Actual durable browser pipeline workflow and UI tests |
| 12 | 1 GiB ingestion | PASS | Exact-byte real MinIO/PostgreSQL acceptance |
| 13 | Four-format 1 GiB contract | PASS | CSV/NDJSON/JSON-array/Parquet maximum tier |
| 14 | Bounded upload memory | PASS | File-backed transport/multipart and sliced browser checksum implementation/tests |
| 15 | Bounded validation/schema discovery | PASS | Full-content batched parsers; measured peaks below budget |
| 16 | 100/500/1024 MiB executed | PASS | Sixteen measured tier cases |
| 17 | Representative 1 GiB Polars run | PASS | CSV select; committed output; 1.40 GiB peak within 2 GiB budget |
| 18 | Resource-intensive safe failure | PASS | Constrained sort, no output publication, source retained |
| 19 | PostgreSQL/MinIO recovery | PASS | Crash, publication failure/retry, immutable bytes and MinIO restart |
| 20 | Existing regressions | PASS | Full Python, frontend and ten browser workflows |
| 21 | Migrations/drift | PASS | Fresh/0020 upgrade, checks and retained snapshots |
| 22 | Documentation/ADR | PASS | ADR, API/operations/report/evidence |
| 23 | No later-phase features | PASS | Scope/diff review; no mapping/materialization/visual builder |
| 24 | Production remains blocked | PASS | Section 23B unchanged; no deployment/certification |

## Files, limitations and next phase

Exact created/modified inventory: [changed-files.txt](evidence/phase-14/changed-files.txt).
Main additions are the execution/pipeline modules, streaming dataset validator, transfer admission,
`0021_execution`, pipeline Studio/editor/tests, deterministic scale fixtures/runners, worker CLI and
architecture/API/operations documentation. Existing transport, governance/type registry, routes and
generated contracts were updated; canonical operational/RDF schemas and historical evidence were not.

Limits: one output dataset per run; empty execution parameters; JSON editor uses explicit immutable IDs;
no drag-and-drop builder, Spark, user Python, browser range resume, full graph traversal, automatic
committed-byte retention purge or hostile-code sandbox. Small synchronous validation retains its bounded
compatibility path. Abrupt host death may leave staging/temp files requiring operator maintenance.
RSS/aggregate temp monitoring on macOS are soft controls, not cgroups. Performance fixtures are
representative deterministic workloads, not a universal 1 GiB operator/cardinality guarantee. Existing
upstream SHACL/profile limitations and production security findings remain. Linux large-source, external
S3, target-cluster recovery, organizational review and final certification remain separate work.

Phase 15 is **not authorized or implemented**. Prerequisites for a separately approved Phase 15 include
reviewing this execution/limits contract, defining governed mapping identity/property ownership and
materialization semantics, and preserving immutable dataset provenance and existing action authority.
