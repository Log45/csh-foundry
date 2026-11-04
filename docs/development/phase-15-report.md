# Phase 15 — Governed dataset-to-ontology materialization

Date: 2026-11-04. Base revision: `23c237d`; work is uncommitted. Existing uncommitted Phase 14
implementation was preserved. Scope: explicitly authorized Section 23A milestone E only.
Status: **PASS — Phase 15 local development acceptance**, on the executed evidence below.
Production: **BLOCKED / NOT PRODUCTION-CERTIFIED** under Section 23B. Phase 16 is not implemented.

## Architecture and implemented functionality

[ADR 0040](../decisions/0040-governed-materialization.md) was recorded before substantial implementation.
MAPPING uses the existing Project/resource registry, stable UUIDs, folders, rename/description,
sharing/revocation, archive and authorization. No competing ontology, ACL, storage backend or queue was
introduced. Definition publication creates append-only sequence-numbered closed JSON specifications.
The canonical ONTOLOGY_VERSION registry reference, ontology identity, exact published active schema,
object/property/link identities and source schema contract are resolved before admission.

Runs pin immutable definition, dataset/artifact UUID, SHA-256 and schema metadata. A changed active
ontology schema rejects historical mapping execution until explicit republication; historical definitions
are not rewritten. Source formats retain Phase 14 CSV/JSON/NDJSON/Parquet and the 1 GiB source ceiling.
Source bytes use the existing ArtifactStore transport and streaming integrity checks.

The exact canonical mutation path is:

- Mapping adapter `object_operation` → `ReconciliationService.create_from_source` or `refresh` →
  `ObjectService.create` / `patch`, within the same governed SQLAlchemy session and transaction.
- Link adapter → `ObjectService.create_link`, retaining endpoint/type/cardinality/authorization checks.
- Existing edit overlays, action audit/outbox and canonical object/link tables remain authoritative.
  Workers do not issue SQL inserts/updates for canonical objects or links.

Ownership is an immutable association from canonical object identity to a stable mapping UUID. It
rejects unrelated existing objects and different mappings. Property overlays use `owner=pipeline`,
`source=mapping:<UUID>` and `edit_wins`; user/action changes remain authoritative. Insert-only permits
identical replay and rejects changed values. Ownership survives governed deletion as a tombstone,
preventing silent resurrection without blocking the existing action deletion service. No automatic
transfer, ownership release, source-absence deletion or destructive replacement is implemented.

Single identity components match the canonical string/UUID/integer primary-key type. Composite keys
require a string primary key and hash a versioned typed JSON tuple. NFC Unicode, numeric decimal
normalization, timezone normalization, null rejection and unambiguous tuple serialization are explicit.
Boolean/date/decimal/timestamp components work in composite keys while canonical primary-key rules
remain unchanged. CSV String columns are forced to String before batch inference so leading zeros and
row ordering cannot change identity. Duplicate object keys reject by default; explicitly identical
coalescing supports repeated source rows; conflicting duplicates always fail. Duplicate links coalesce.

Property conversion is a closed scalar subset: direct columns or constants, explicit reject/allow/default
null policy, strings, signed 64-bit integers, finite floats, booleans, dates, timezone timestamps, UUIDs
and decimals up to 38 digits. Existing required/enum/precision/scale validators apply. Unsupported
nested/binary/array values, decimal-to-float coercion, invalid casts, overflow and nanosecond truncation
fail. Restricted transformations remain in the existing Phase 14 declarative pipeline service; arbitrary
Python and user scripts remain excluded. Diagnostics are bounded and exclude source values.

## Execution, publication and recovery

The existing ExecutionWorker dispatches MATERIALIZATION jobs using execution_jobs leases, random
fencing tokens, heartbeats, global/tenant/Project admission, deadlines, cancellation and bounded retries.
The existing worker CLI handles all job kinds without another daemon or queue. Definitions cannot
provide executable plans, paths, imports, callbacks, object-store credentials or worker credentials.

An isolated trusted conversion child uses bounded Polars batches. Its attempt-local disposable SQLite
index detects duplicate identities and cardinalities without keeping the entire source in memory. This
is a temporary processing index, not an authoritative database. Existing memory/CPU/wall/record/decoded/
temporary disk limits apply. Source plus staging must fit the configured 4 GiB temporary default;
default target caps are 100,000 objects and 100,000 links, independently configurable up to one million.
The source-size promise does not imply unlimited distinct ontology targets within a fixed budget.

Full-source conversion completes before mutation. A second preflight checks ownership, endpoints and
live cardinality. Actual mutation rechecks current domain constraints and authorization. Objects commit
before links in batches of 100. Each batch rechecks current mapping write, source read, target Project
write, schema, mutation permissions, lease/token/deadline; mutation, ownership, provenance and progress
commit together. Database triggers additionally fence ownership/provenance writes. Revocation takes
effect at the next transaction boundary under existing security/tenant locking semantics.

**Publication is visible transactional batches, not atomic activation.** Partial committed results are
visible during RUNNING and remain visible/auditable after failure or cancellation. Incomplete runs are
never labeled successful. A replacement worker rebuilds staging from the original pins and skips that
run's committed provenance keys; new runs reconcile owned targets. Existing links are observed rather
than deleted/replaced or claimed as action-independent ownership. No cross-transaction atomicity is
claimed. Schema activation, endpoint deletion or action changes between preflight and commit can still
prevent a later batch; committed earlier batches remain explicit partial state.

## Validation, APIs, provenance and Studio

[API documentation](../api/mappings.md) covers structural validation, draft/published sample preview,
immutable definition publication/history, full-source validation, materialization, status/history,
reconciliation metrics, cancellation/retry and lineage. OpenAPI and TypeScript are generated from the
actual application. Existing generic resource and execution endpoints are reused. Pagination is bounded
and deterministic; authorized filtering can shorten lineage pages.

Preview uses cached source samples, labels results `sample-only`, and bounds mapped targets and bytes;
it does not claim full-source validity. Full-validation runs scan every source record and perform a
read-only preflight, with no canonical objects, links, ownership or materialization provenance changes.
They remain point-in-time checks; live mutation authorization and invariants are rechecked separately.

One immutable provenance record per run/target stores source ordinal within the pinned checksum/version,
canonical target, operation and timestamp. Immutable input and definition joins supply mapping/version,
run, dataset/artifact/checksum, ontology/version and actor. Counts are bounded by target budgets, avoiding
per-cell amplification. Source, run, object and link lineage queries check current mapping/source/target
access and canonical endpoint visibility. Responses omit source rows/property values. Private sources
are not disclosed through shared ontology objects or mappings. Existing pipeline lineage is preserved.

Studio adds Project mapping creation, stable resource IDs, a JSON editor for target/identity/properties/
conversions/relationships, draft sample preview, publication/version selection, explicit dataset/version
selection by UUID, structural and full-source validation, launch/refresh/cancel/retry, reconciliation
counts, canonical object inspection and authorized provenance. Its partial-write/sample guarantees are
visible. Existing BFF session, CSRF and tenant protections apply. No visual Pipeline Builder or Phase 16
SDK expansion was added.

## Migrations and data preservation

Initial repository head: `0021_execution`. New forward-only head: **`0022_materialization`**. Adds
mapping_definitions, mapping_ownership and materialization_records; extends execution_jobs with a
mapping-definition FK and MATERIALIZATION job kind, and extends registry type/authority checks.
Tenant-qualified FKs, immutable definitions/contracts/provenance, unique version/checkpoint identities,
legal execution transitions and fenced publication are enforced. Frozen migration SQL imports no ORM
metadata. Fresh migrations, upgrade from Phase 14 with preserved pipeline/dataset metadata and drift
are exercised against disposable schemas. No historical migration or canonical fixture was changed.

[Preservation checks](evidence/phase-15/preservation.txt) confirm the shared developer database remains
`0017_capacity` through read-only inspection. Only generated PostgreSQL schemas and private random MinIO
projects/volumes are created/removed. Existing MinIO volumes are not reset. No deployment or production
certification is performed.

## Representative 1 GiB measurements

The [machine-readable measurement](evidence/phase-15/large-measurements.json) and
[raw integration output](evidence/phase-15/large-recovery.txt) record an exact 1,073,741,824-byte CSV,
SHA-256 `9fce52a4176518a4c9a263bb3d936bcafcf4ee20a5d5cb23aa7382d3f2d57200`.
It has 262,143 deterministic rows with 4 KiB padding and 256 repeated identities; explicit identical
coalescing yields 512 objects, 256 canonical links and 768 per-target provenance records. It is a
representative source-scan/reconciliation workload, not a million-distinct-object throughput claim.
Fixtures are generated at runtime and giant files are not committed.

Environment: local macOS arm64 / Apple M1 Pro, Python 3.12.0, real PostgreSQL and private real MinIO,
existing pinned Polars/PyArrow runtime. Source upload, dataset validation, mapping, replay, actual
conversion-child cancellation and a new pinned recovery run completed in 259.10 seconds overall.
These timings include concurrent local validation load and are not a production SLO.

| Attempt | Objects / links | New targets | Conversion seconds | Peak child RSS | Peak attempt temporary disk |
| --- | ---: | ---: | ---: | ---: | ---: |
| Initial materialization | 512 / 256 | 768 | 34.45 | 272171008 bytes | 1074031770 bytes |
| Idempotent replay | 512 / 256 | 0 | 35.76 | 294535168 bytes | 1074031771 bytes |
| Recovery after cancelled child | 512 / 256 | 0 | 34.56 | 263847936 bytes | 1074031771 bytes |

Controller RSS was sampled independently at 0.5-second intervals: **213630976 bytes peak**. Adding
that peak to the largest measured child peak gives a conservative combined observed peak of
**508166144 bytes (484.63 MiB)**, below the configured 2 GiB budget. Attempt disk was approximately
1024.28 MiB, below 4 GiB. Sampling is not a hard kernel guarantee; the limits and watchdog caveats above
remain. The controller sample includes pytest overhead. Generated input fixture disk outside the owned
worker attempt is separate from worker scratch. Linux 1 GiB cgroup certification remains NOT RUN.

## Executed validation evidence

| Check | Result | Evidence |
| --- | --- | --- |
| Initial real PostgreSQL/MinIO focused suite | PASS | 129 passed; `targeted-final.txt` |
| Final focused contracts, controller loss, cancellation/revocation and regressions | PASS | 136 passed in 142.27 seconds; `final-contracts.txt` |
| Representative 1 GiB materialization and idempotent replay | PASS | `large.txt`; 262143 source rows, 512 objects, 256 links |
| Expanded 1 GiB cancellation/recovery and parent RSS | PASS | `large-recovery.txt`; 1 passed in 264.35 seconds |
| Broad regression before final refinements | PASS | 783 passed, one preserved strict xfail, zero skips; `full.txt`; 953.12 seconds; clean drift |
| Later regression during clock instability | FAIL | 9 failed, 780 passed, one xfail; `full-final.txt`; 1122.48 seconds |
| Additional run interrupted by host/VM clock gaps | FAIL | 4 failed, 787 passed, one xfail; `full-clean.txt`; 780.27 seconds |
| Final awake complete Python regression | PASS | 791 passed, one preserved strict xfail, zero skips; 936.79 seconds; `full-awake.txt`; clean drift |
| Durable browser workflows, including mapping and real 1 GiB upload | PASS | 11 passed; `browser-final.txt` |
| Frontend Vitest | PASS | 45 passed across ten files; `frontend-latest.txt` |
| Frontend typecheck / formatting / build | PASS | `frontend-latest.txt`, `build-final.txt`; earlier formatting failure corrected |
| Python Ruff / format / mypy | PASS | `python-final.txt`; 133 source files type checked |
| Alembic fresh/previous-head/drift | PASS | Focused upgrade test plus final full regression and clean drift; `full-awake.txt` |
| OpenAPI / TypeScript generation | PASS | Actual application export and openapi-typescript executed |
| Shared developer database / historical fixture preservation | PASS | `preservation.txt` |
| Manual Protégé GUI / real production target / Linux 1 GiB cgroup acceptance | NOT RUN | Separate environments/certification; no new ontology-authoring constructs |
| Standalone TypeScript lint | NOT SUPPORTED | No standalone lint script; typecheck/format/build used |

Earlier failed invocations remain in evidence. Clock sampling in
`clock-observations.jsonl` observed host/PostgreSQL offsets as large as 2091.58 seconds and gaps over
1000 seconds between nominal five-second samples. Later failures affected durable leases, recovery,
login lifetime and SDK authorization; no timeout or assertion was relaxed. The final run uses a
process-scoped local caffeinate assertion to prevent idle sleep, leaving system clocks and shared
service configuration unchanged. A redundant focused run was interrupted and its private resources
cleaned before the final whole-suite run; its incomplete log is not passing evidence.

The final full suite follows the latest source/authority refinements; earlier clean/full evidence is
retained separately rather than combined into a fictional single passing run.

Earlier implementation failures also remain in evidence. The first run exposed column/constant serialization on
immutable definition reload; corrected without weakening assertions. A stale imported ORM during an
in-progress ownership-FK refinement produced drift in an early invocation; clean-process reruns passed.
Tests initially used incorrect registry archive API names and collided with preexisting security fixture
objects; fixtures were corrected to use the actual API and distinct source keys. A draft-preview import
was corrected before clean validation. Preview expansion/decimal limits and CSV leading-zero behavior
have explicit regression tests. No historical test or expected-failure policy was weakened.

## fixtures/VALIDATION.md

The guide was read before implementation and consulted before completion. The final awake full
regression executed the static fixtures, ingestion, object/query/action/reconciliation, authorization,
semantic engine and import/export checks. No result below relies on historical Phase 14 evidence.

| Check | Result | Evidence |
| --- | --- | --- |
| Turtle parsing; CSV keys/counts/FKs; RDF identity consistency | PASS | Executed `test_fixtures.py`; `full-awake.txt` |
| Normalized SHACL and negative mutations | PASS | Executed `test_fixtures.py`; `full-awake.txt` |
| Raw pySHACL simple/xsd:string compatibility | NOT SUPPORTED | Preserved strict expected-failure contract |
| Pinned Open Ontologies SHACL and supported owl-rl-ext inference | PASS | Executed pinned-engine/compiler/platform suites; `full-awake.txt` |
| Base owl-rl exact fixture axiom | NOT SUPPORTED | Existing documented engine profile limitation |
| PostgreSQL / object queries / actions / reconciliation / Polars ingestion | PASS | Executed real integration suites including Phase 15; `full-awake.txt` |
| Authorization and tenant isolation | PASS | Full real platform/identity/workflow and Phase 15 denial/revocation suites; `full-awake.txt` |
| Supported Protégé import/export | PASS | Executed `test_ontology_import.py`; `full-awake.txt`; browser authoring workflow |
| Manual Protégé desktop inspection | NOT RUN | No desktop authoring session |

## Acceptance matrix

All required Phase 15 local development checks below passed executed validation. Historical failed
attempts and unsupported/separately scoped environments are retained explicitly above.

| # | Criterion | Result |
| --- | --- | --- |
| 1–7 | Governed resources, immutable pins, source validation, identity, properties, links | PASS |
| 8–9 | Idempotence and recovery from partial failure | PASS |
| 10–12 | Canonical authority, action protection, explicit ownership conflict handling | PASS |
| 13–15 | Durable jobs, cancellation/retry/fencing, full validation and dry run | PASS |
| 16–19 | Publication model, real lineage, authorization and Studio | PASS |
| 20–21 | Final 1 GiB materialization/recovery with bounded child/controller memory and disk | PASS |
| 22 | Real PostgreSQL and MinIO integration | PASS |
| 23 | Final full regressions | PASS |
| 24–27 | Migrations/drift, documentation/ADR, Phase 15 scope, production blocked | PASS |

## Changed files, limitations and next phase

Exact Phase 15 inventory: [changed-files.txt](evidence/phase-15/changed-files.txt). This distinguishes
Phase 15 edits from the substantial preexisting uncommitted Phase 14 work. Historical fixtures, prior
migration files, prior reports and prior evidence remain intact.

Limits: scalar mapping subset; no nested/binary/array target conversion or arbitrary expressions;
canonical primary-key rules unchanged; no deletion/replace-all/ownership transfer; historical schemas
must still be active to execute; visible partial batches; one source dataset per run; JSON/UUID Studio
configuration and explicit refresh rather than a visual builder; no automatic provenance retention purge.
Source and target cardinality/resource budgets are independent. macOS watchdogs are soft controls, not
Linux cgroups or production isolation certification. Existing semantic profile limitations and Section
23B production security/certification blockers remain. Production acceptance is not inferred from local
PostgreSQL/MinIO or browser results.

Recommended Phase 16 prerequisites only: review these ownership/partial-publication semantics, preserve
current pins and generated contracts, define any separately approved SDK access/provenance interfaces,
and authorize Phase 16 explicitly. No Phase 16 implementation is included.

Previously observed materialized links that have been removed through governed mutations are not
silently recreated. Immutable provenance detects the missing edge and the run fails with a conflict;
existing replacement edges and action-managed values remain authoritative.

Final awake clock evidence: 183 samples; maximum observed absolute host/PostgreSQL
offset 0.067378 seconds, maximum sample gap
5.08 seconds. See `clock-summary.json`. The successful final run
required no timeout, assertion, lease-policy or security-control changes. The temporary keep-awake
assertion ended with its owned validation process. Earlier clock-instability failures remain recorded.
