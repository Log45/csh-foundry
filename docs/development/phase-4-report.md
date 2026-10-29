# Phase 4 report — Governed Data Ingestion, Transformation and Source Reconciliation

PHASE: **4 only**. Date: 2026-10-29, America/New_York. Base commit: `3fc12ca`.
Changes remain uncommitted. Environment: macOS ARM64, Python 3.12.0, existing locked uv packages,
Polars 1.44.2, Docker PostgreSQL 17.6 and existing Java/Maven/pinned semantic engine.
Phase 5 implementation has not started.

## Implementation summary

Implemented tenant-owned immutable source/mapping versions; server-managed connector registrations;
CSV, Parquet, newline-delimited JSON and read-only PostgreSQL extraction; bounded Polars projection,
renaming, scalar conversion, null/default handling and registered equality filters; durable canonical
staging and redacted diagnostics; deterministic source identities; governed object upserts and
forward relationships; Phase 3 source/edit reconciliation; leased PostgreSQL jobs, retries,
cancellation, fencing, checkpoints and retention cleanup; versioned FastAPI endpoints; manufacturing
acceptance, recovery/security/connector tests and local measurements.

The modular monolith and authoritative PostgreSQL store are retained. Existing canonical metadata,
CRUD, relationships, queries/cursors/Object Sets, actions/idempotency/audit/outbox, semantic adapter
and Protégé compatibility remain regression requirements. No additional operational database,
broker, workflow engine, analytical engine, dependency, Rust, Studio, SDK or production OIDC was added.

## Files created or modified

| Area | Significant paths |
|---|---|
| Ingestion | New `services/api/src/ontology_platform/ingestion/{contracts,catalog,connectors,transform,service,materialize,worker,routes,__main__}.py` |
| Existing services | Updated `edits/service.py` with governed creation of source/pipeline-owned objects through ObjectService; no parallel reconciliation implementation |
| Shared request/SQL guards | Parameterized `actions/{limits,deadline}.py` without changing action defaults; ingestion reuses bounded request and diminishing SQL budgets |
| Configuration/application | Updated `config.py`, `main.py`, `.env.example`; server-owned catalog and ingestion router |
| Persistence | Updated `db/{models,governance}.py`; new migrations `0008_ingestion_governed_ingestion.py`, `0009_ingestion_diagnostics_ingestion_diagnostics.py` |
| Tests | New `services/api/tests/test_ingestion.py`, `test_ingestion_connectors.py`, `test_ingestion_postgres.py`, `test_ingestion_recovery.py`; existing tests unchanged |
| Developer tooling | New `scripts/benchmark_ingestion.py`, `smoke_ingestion.py`, `smoke_ingestion_container.py` |
| Documentation | New ingestion API, ADRs 0021–0023, this report and `docs/development/phase-5.md`; updated README/API/architecture/migration and worker boundary documentation |
| Evidence | `docs/architecture/evidence/phase-4/` with baseline/final validation, library signatures, benchmark data, HTTP/Docker/Protégé and fixture integrity |

Abbreviated service paths above are under `services/api/src/ontology_platform/`.
The requested `fixtures/README.md` was absent. PLANS.md required reporting that omission; the user
explicitly instructed proceeding with existing fixture documentation. `fixtures/VALIDATION.md`
and canonical fixtures were used without fabricating a replacement README.

## Source and mapping contracts

Source snapshots bind tenant/ontology, source ID/version, registered binding, stable source identity
namespace, source/pipeline ownership, edit policy, upsert and ignore-missing-row deletion policy,
actor/time and registration digest. Physical credentials/paths remain server configuration, never
client execution parameters or response fields. Source and mapping publication checks independent
create/publish permissions, and binding use requires its own permission. Config rows reject UPDATE/
DELETE through database triggers. A changed interpretation needs a new explicit version.

Mappings reference exact source versions, active schema, canonical object/property/forward-link IDs,
identity column, explicit conversions and null/default modes. They validate required/defaulted
properties, primary-key assignment, column/type/link/direction compatibility and duplicate assignments.
The existing ontology schema is reused; no second ontology model or executable mapping format exists.
Version numbers are positive signed 32-bit integers; mapping bodies are limited to 64 KiB.

Connectors are registered per tenant. Files resolve inside controlled roots, reject escaping paths/
symlinks and open resolved paths with no-follow protection. CSV uses strict UTF-8 parsing and explicit
string schemas; mappings perform conversions. JSON supports one object per line, not an unbounded
array/document. Parquet inspects schema and uses bounded Polars scan/slice collection. Literal
column aliases prevent source names from becoming Polars selector/regex expressions.

PostgreSQL reads use secret server-managed connection configuration, explicit table/view and column
allowlists, typed bound equality predicates, read-only repeatable-read transactions, SELECT-only
relation credentials, a three-second connection timeout and five-second statement budget. Tests
use a real generated read-only role, including real timeout and injection-value checks. No runtime
source SQL or connection string is supplied by a client. Input fingerprints are checked on resumed
staging reads, shared by mappings using the same source version. Operational writes never share an
atomic transaction with an external source snapshot.

## Polars transformation engine

Supported transformations are registered column selection, literal renaming, bounded equality
filters, explicit string/integer/float/boolean/decimal/date/timestamp/UUID conversion, null normalization,
validated defaults, required fields and relationship-reference extraction. Polars uses explicit
schemas and casts; invalid casts never silently receive defaults. Existing canonical validators
apply enums, precision/scale, nullability, defaults and stable primary keys. Decimal strings retain
exact representation, dates are canonical ISO and timestamps require offsets. JSON/array properties,
nested extraction, arbitrary joins/scripts/general expressions are explicitly unsupported.

| Resource | Bound |
|---|---|
| Ingestion HTTP body / canonical mapping | 64 KiB each |
| Mappings per run | 8 |
| Registered columns / mapped properties | 64 |
| Forward relationships per record / predicates | 8 each |
| File/source snapshot read size | 16 MiB |
| Rows per source / staged records per run | 10,000 each |
| Canonical row / NDJSON line | 16 KiB |
| Canonical staging payload per run | 16 MiB, plus bounded identities/row metadata |
| Batch size | 1–100; default 25 |
| Ingested source/object key | 512 UTF-8 bytes |
| Extraction / Polars work | Cooperative five / three second checks |
| Step SQL budget | 15 seconds, diminishing before each statement |
| Whole-run atomic mode | At most 100 staged records |
| Lease / maximum claims | 60 seconds / three total claims |
| Steps per bounded runner invocation | 40,000 maximum |

File input snapshots buffer at most 16 MiB so hashes cover the bytes parsed. Parsing and transforms
are batched; this is not a fully streaming file-I/O claim. Parquet compressed row groups/native
allocations and a PostgreSQL value before width validation can exceed the logical batch-memory
bound. No hard OS memory sandbox or whole-process native/DNS/commit deadline is claimed. Production
admission/container limits and suitably bounded source views remain necessary.

## Staging and validation

PostgreSQL stage rows record run, mapping/version, original record position, source/object identities,
canonical proposal, relationships and validation/materialization state. The run records source hashes,
configuration versions, active schema, phase/checkpoints/counters and redacted errors. Diagnostics
include stable category/code, mapping/version and source record number when available. Global failures
do not invent a row location. Values, credentials and raw invalid payloads are not echoed in errors.

Duplicate source/target identities are checked after staging and before operational materialization.
Source parsing/header/type failures are distinguished from conversion/canonical/identity/reconciliation/
relationship and job errors. Invalid properties/enums/decimals/dates, missing identities/endpoints,
uniqueness/cardinality conflicts, stale schemas and source ownership conflicts remain structured.

reject_run applies no operational effects when staging/operational validation fails, and explicitly
rejects runs above 100 records. reject_batch rejects an invalid staging group or rolls back a failing
operational batch. quarantine isolates permitted failures with record savepoints inside atomic
batches. Invalid object records never materialize. A later relationship failure is LINK_REJECTED,
with a relationship diagnostic; previously committed valid object batches remain. Authorization/
transient failures roll back a step rather than being disguised as bad source data.

Terminal staging/diagnostics have a seven-day minimum retention and explicit bounded cleanup, at
most 100 terminal runs per call. Run/configuration/identity history remains; staging_purged_at reports
cleanup. Operators must invoke maintenance; no autonomous retention scheduler is implied. Historical
raw input is not archived, so reproduction after cleanup requires retained external input versions.

## Identity and upsert semantics

Object IDs derive from configured stable columns, never random source-row identifiers or display
labels. Canonical tenant/ontology/type/object identity and deterministic RDF IRI compatibility remain
unchanged. Source ID/namespace/key associations reject unrelated-source collisions and identity
rewrites. Source ordering does not determine identity. Filtered source positions still advance durable
checkpoints. Missing source records never delete operational objects.

Object creation passes through ObjectService and a small ReconciliationService creation method that
atomically registers source/pipeline provenance; existing objects cannot be silently adopted by that
method. Existing upserts use ReconciliationService.refresh and its expected revisions. Canonical
uniqueness/identity checks are reused under retained ontology locks. Reprocessing unchanged values
creates no objects, relationships or unnecessary object revisions, and does not change ownership.

## Relationship materialization

Objects materialize before relationship batches so later-batch endpoints are available. All links
use the existing forward-link service with endpoint/type/cardinality checks and inverse navigation.
One reference per forward link is supported per row; no redundant inverse edges are stored.

Managed link state records the accepted endpoint and operational edge timestamp. Unchanged repeats
create no duplicate links. Source changes can replace only unchanged managed edges; user/action
replacement/deletion is protected by default and explicit overrides recheck authorization. Previously
sourced objects deleted through governed services are also protected against automatic resurrection.
Missing endpoints and cardinality conflicts produce diagnostics/failure according to policy. Batch
mode can preserve earlier objects when a later link fails; whole-run mode rolls everything back.

## Reconciliation

Existing Phase 3 source/pipeline/user/action categories and policies are reused. Default edit_wins
preserves governed edits while accepting same-source-owned changes. Equal observations do not release
ownership. Source/pipeline ownership is explicit in versioned source configuration. source_wins requires
current override permission; unrelated sources cannot silently take ownership. reject/manual policies
produce diagnostics and, in quarantine mode, can preserve Phase 3 conflicts for explicit resolution.

Resolved value changes increment object revisions through existing services; unchanged observations
only refresh provenance where necessary. Schema versions/revisions and property permissions remain
enforced. Action execution history/audit/outbox behavior is unchanged. No implicit deletion or arbitrary
reconciliation scripts are introduced.

## Durable jobs

The run row doubles as its durable job: PENDING/RUNNING/COMPLETED/FAILED/CANCELLED; stage/validation/
object/link phase; principal and immutable plan; claim count/token/expiry; timestamps/errors; counters
and checkpoint state. Claims use FOR UPDATE SKIP LOCKED; normal steps renew the 60-second lease and
explicit renewal is available. Expired owners/tokens and stale prepared checkpoints cannot commit.
The worker checks lease validity again before committing effects/checkpoint.

Three total claims bound retry/recovery. Transient failures requeue up to that limit; terminal errors
remain durable. Unexpected process death leaves a leased RUNNING job for recovery. The bounded CLI
processes one job and exits. It uses the configured initiating principal, not an unrestricted service
identity. Cancellation fences the token between transactions and preserves completed batches.
Production scheduling, supervision, retry backoff and admission are operator responsibilities.

Recovery tests include actual SIGKILL before checkpoint advancement and before commit, plus actual
os._exit after a partially committed batch. A replacement worker completes without duplicate effects
or repeated revisions. Lease expiration is advanced in the disposable database to avoid waiting a
minute in tests; that part is simulated clock state, not an actual timed production outage. Separate
simulated exception/lease tests cover rollback, fencing, renewal, concurrent claims and exhaustion.

## Transaction guarantees

Operational effects, source identities, ownership, stage transitions, counters and checkpoints commit
in one PostgreSQL transaction per step. A checkpoint cannot independently precede durable effects.
No external read or HTTP side effect executes inside the operational mutation transaction.

Whole-run rejection is truly atomic only inside its 100-record bound. Other policies provide batch
atomicity and explicitly retain completed batches after later failure/cancellation. Per-record
quarantine savepoints do not make a whole run atomic. Schema version is pinned and rechecked before
each step; activation changes stop stale jobs instead of silently reinterpreting mappings. Ontology
locks prevent activation racing through a mutation batch. Phase 1 activation limits remain unchanged.

## Authorization

All operations use server-derived tenant/principal context. Source create/publish/read/binding-use,
mapping create/publish/read, run execution/claim/history/diagnostic/cancel/cleanup and existing object/
property/link/reconciliation permissions are checked. List pages authorize each returned source/run.
A mapping persistence row from another tenant/ontology is rejected even at the internal helper boundary.
Source config bodies contain registered keys only and cannot select another tenant, credentials or SQL.

A worker claims only runs initiated by its configured principal and rechecks current permissions at
claim, step and each governed mutation. Overrides require current permission. Missing/invalid context
fails closed. Composite tenant FKs and service predicates remain; production OIDC/RBAC/ABAC, RLS and
cross-tenant sharing are not implemented in this phase.

## Database migrations

| Revision | Changes / rollback |
|---|---|
| 0008_ingestion | Seven tables: ingestion_sources, ingestion_mappings, ingestion_runs, ingestion_stage, ingestion_diagnostics, source_object_identities, source_link_state. Tenant-safe FKs, identity/request/stage uniqueness, lookup indexes, counters/state limits and immutable configuration/run-plan triggers. Downgrade removes Phase 4 structures/history/provenance while preserving prior operational objects. |
| 0009_ingestion_diagnostics | Adds diagnostic mapping/version FK, purge time, lease/policy/count checks and LINK_REJECTED state. Downgrade restores the older state check (folding LINK_REJECTED into REJECTED) and removes added provenance/constraints. |

Both use bounded DDL lock/statement settings. Tests perform fresh/base/head and Phase 3 → head →
Phase 3 → head reversals only in disposable schemas, including constraints/drift/data preservation.
Development is upgraded to 0009_ingestion_diagnostics with existing user data retained; no migration
loads fixtures or silently rewrites existing published schemas.

## Manufacturing acceptance test

| Contract | Expected | Observed |
|---|---:|---:|
| Factory | 6 | 6 |
| Machine | 20 | 20 |
| Employee | 12 | 12 |
| MaintenanceTask | 25 | 25 |
| Total objects | 63 | 63 |
| Forward links | 70 | 70 |

The actual API workflow registers/publishes new source and mapping versions, submits a PENDING run,
executes the worker separately, queries counts and traverses relationships. An unchanged repeat has
zero created/updated/link-created effects. Tests compare every identity/revision before and after;
source ownership is persisted. An HTTP action edits machine status; changed source data updates its
source-owned name while preserving action-owned status. Query/action/ingestion APIs remain consistent.

Negative tests cover malformed data, duplicate identities, required fields/types/enums, missing
endpoints, uniqueness/cardinality rollback, ownership collisions, source changes during staging,
unsupported mappings, authorization and path/SQL/credential attempts. Changed relationship references
update managed edges and preserve governed replacements. Missing source records preserve existing
objects. Job/diagnostic history and actual process recovery are verified on real PostgreSQL.

## Performance

Measured local workloads include the 63-object/70-link fixtures at batch sizes 10/25/100, unchanged
and changed-source ingestion, ten governed machine edits, quarantine, simulated checkpoint retry,
concurrent queries/actions, controlled shared-lock contention, and 506 objects/500 links with an
unchanged repeat. Instrumentation records extraction/Polars time, writer transaction durations,
throughput, Python traced memory and whole-process RSS.

| Workload | Seconds | Rows/s | Extract / Polars ms | Writer total / median ms | Python peak MiB |
|---|---:|---:|---:|---:|---:|
| manufacturing_batch_10 | 11.33 | 5.56 | 13.27 / 37.14 | 10801.14 / 184.99 | 18.40 |
| manufacturing_batch_25 | 10.37 | 6.07 | 7.38 / 12.41 | 10172.09 / 31.88 | 19.35 |
| manufacturing_batch_100 | 10.15 | 6.21 | 7.14 / 12.25 | 9980.71 / 28.61 | 19.53 |
| unchanged_repeat | 8.62 | 7.31 | 8.56 / 13.56 | 8406.07 / 32.07 | 19.56 |
| changed_source | 9.03 | 6.97 | 8.56 / 13.82 | 8766.99 / 44.81 | 19.66 |
| reconciliation_heavy | 9.55 | 6.60 | 7.45 / 12.19 | 9322.85 / 31.75 | 20.01 |
| quarantine | 9.11 | 6.92 | 10.84 / 21.50 | 8819.57 / 63.12 | 20.08 |
| checkpoint_retry | 8.79 | 7.16 | 8.39 / 13.06 | 8542.88 / 37.51 | 20.12 |
| synthetic_506_objects | 70.06 | 7.22 | 50.09 / 94.19 | 69537.71 / 555.07 | 20.45 |
| synthetic_unchanged | 66.51 | 7.61 | 72.26 / 103.59 | 65717.00 / 2533.14 | 20.80 |

Whole-process peak RSS: **136.34 MiB**. Concurrent query: **28.25 ms** (20 rows) while ingestion took **1684.97 ms**; concurrent action: **114.46 ms** while ingestion took **2034.10 ms**. Both succeeded. A controlled 100 ms shared ontology lock produced an observed PostgreSQL `transactionid` lock wait with one blocker; the ingestion step took **1177.67 ms**. The 506-record workload created 506 objects/500 links; unchanged repeats had zero mutation effects. Quarantine rejected one of 63 records. Checkpoint retry used two claims after a simulated failure. Raw samples and per-transaction timings are in `docs/architecture/evidence/phase-4/ingestion-benchmarks.json`.

These are small instrumented local observations, not production guarantees or percentiles. Tracing
adds overhead. Writer transaction duration includes governed Python work and metadata/lease/checkpoint
writes; it is not pure database CPU time. RSS is the whole benchmark process including libraries;
tracemalloc excludes native Polars allocations. Source/database server memory is not included.
Repeated service validation/round trips dominate these small workloads; no measurement justifies
changing correctness-preserving ontology locks or adding speculative databases/index infrastructure.

## Validation results

Before implementation: clean base tree, observed head 0007_edit_provenance, full configured runner
**238 passed, 1 xfailed, no skips**, 77.35s; lint/format/strict mypy/drift passed. Focused existing
reconciliation baseline: **7 passed**. No unexpected preexisting failure was observed. The raw
pySHACL incompatibility, base owl-rl rule limitation, Starlette/httpx and Java warnings are preexisting.

Final configured runner: **320 passed, 1 xfailed, no skips**, 321 collected, **165.60s**.
The 82 new cases comprise 47 ingestion, 23 connector/transformation, four PostgreSQL source and
eight recovery tests. Ruff lint passed, all 100 Python files were formatted, and strict mypy passed
for 62 source files. Final output: `docs/architecture/evidence/phase-4/validation.txt`.

| Check | Result | Evidence / limits |
|---|---|---|
| Full configured pytest regression | PASS | 320 passed, one preserved strict expected failure, zero skips; 165.60s |
| Ruff lint / formatting / strict mypy | PASS | Current checks; source guards and existing application modules |
| Alembic fresh/Phase 3 upgrade/downgrade/re-upgrade/drift | PASS | Private-schema real PostgreSQL regression and object preservation |
| Source/mapping versioning, immutability and tenant FKs | PASS | Source/mapping/run-plan guards and request uniqueness tests |
| CSV/Parquet/NDJSON extraction and governed ingestion | PASS | Bounded connector cases plus real pipeline tests |
| PostgreSQL source connector | PASS | Generated SELECT-only role, parameter injection value, writable-role denial, actual 5s timeout |
| Polars scalar conversions/nulls/schema validation | PASS | Strict canonical validators and positive/negative transformation tests |
| Manufacturing identities/counts/repeat/reconciliation/relationships | PASS | 63 objects/70 forward links, zero-effect repeat, protected edits and managed edges |
| Durable claims/checkpoints/cancellation/fencing/retries | PASS | Real PostgreSQL job tests and concurrency |
| Actual process crashes and recovery | PASS | SIGKILL before checkpoint/commit, os._exit after partial commit; simulated lease expiration explicitly distinguished |
| Authorization and source/path/SQL/credential boundaries | PASS | Local identity denials, denied execution/mutations/overrides and allowlist tests |
| Host Uvicorn HTTP | PASS | Publication → run → 63/70 → query/traversal/action/refresh; no handler executes jobs |
| Docker image build/readiness/OpenAPI/identity rejection | PASS | Final image startup smoke; no external deployment |
| Turtle/CSV/RDF identities, normalized SHACL/negative cases | PASS | Existing fixture regressions and SHA256 preservation |
| Raw unchanged pySHACL conformance | FAIL | Preserved strict expected failure, not converted into raw conformance success |
| Open Ontologies parse/raw SHACL/diagnostics/owl-rl-ext | PASS | Existing pinned semantic regression executed |
| Equivalent base owl-rl inference | NOT SUPPORTED | Existing executed unsupported-profile comparison preserved |
| Protégé-compatible file interchange | PASS | OWLAPI 4.5.29 re-run; known extra xsd:date declaration retained |
| Protégé GUI / deployed WebProtégé / expanded import | NOT RUN | Not Phase 4; existing file harness only |
| GitHub-hosted CI | NOT RUN | No push/remote run requested; equivalent local runner executed |
| External production data sources / scheduler / production security | NOT RUN | Registered disposable local fixtures/PG only; deferred production deployment |
| Phase 5 materialization / Studio / generated SDK / Rust | NOT RUN | Outside approved scope |

Intermediate implementation/test issues were corrected without weakening existing tests, including
new-test imports, migration downgrade trigger/constraint cleanup and a test-owned reader session
that initially blocked private-schema teardown. The reader was closed, that specific disposable
schema cleaned up and recovery tests rerun successfully. A host HTTP smoke attempt observed a
RUNNING lease instead of completion; its cause was not established. A fresh complete smoke rerun
passed publication, ingestion, repeat, query/traversal and action/edit preservation. That rerun is
recorded in `http-run.txt` and `http-smoke.txt`; intermittent long pauses can require lease recovery.
An additional manual Alembic invocation initially used the wrong config path; root-config current
and drift checks were rerun successfully. No final unexpected failure is accepted.

## Known limitations

1. Trusted local identity only; worker delegation is restricted to the initiating configured
   principal. Public/production identity and policy administration remain future work.
2. Scalar mapping language, registered local files and allowlisted PostgreSQL only. No uploads,
   arbitrary expressions, nested/array transformations, general joins or source-driven deletion.
3. Whole-run atomicity is limited to 100 records. Batch modes can retain earlier objects when
   relationships later reject, and cancellation preserves completed batches.
4. Strict memory isolation/native preemption is not implemented. File snapshots buffer 16 MiB;
   Parquet/native/source-value decoding can exceed logical row memory limits. Production admission
   and OS/container limits remain necessary.
5. One operator-invoked bounded worker run, three total claims, no scheduler/supervisor/exponential
   backoff service. Maintenance must invoke staging cleanup; raw historical input is not archived.
6. Existing ontology locks and Phase 1 activation limits (1,000 objects / 5,000 links) remain. Large
   ingestion does not silently increase schema activation capabilities.
7. Measurements are local/instrumented; repeated service round trips limit throughput. No production
   scalability, hard process deadline or exactly-once external-source transaction is claimed.
8. Immutable run/config history and source identity state have no automatic expiry. Database owners
   can bypass triggers; tamper-proof audit or complete external snapshot archival is not claimed.
9. Raw pySHACL and base-profile inference limitations remain. Semantic export/materialization and
   the full cross-phase MVP semantic workflow are not claimed complete.

## Phase 5 readiness

The Phase 4 foundation is suitable for separately approved Phase 5 work within its documented
local-development, batch, identity and resource bounds. This is not production readiness or a
claim that the entire ingestion-to-semantic MVP is validated. Stable source/run/schema provenance,
checkpoint patterns and existing semantic adapters are available for the next phase.

## Recommended Phase 5 tasks

Follow [the Phase 5 checklist](phase-5.md): verified pinned engine contracts; deterministic RDF/OWL/
SHACL compilation; authorized tenant-safe export; versioned artifacts/jobs/reports; separate derived
facts with provenance/approval; supported validation/reasoning/proof checks; durable job failure
handling; typed APIs; security/performance/regression evidence. No Phase 5 implementation was
started. Stop here pending review and explicit approval.
