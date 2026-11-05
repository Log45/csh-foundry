# Phase 17 — Governed Media Sets, Functions and Automations

Implementation date: 2026-11-04; final validation verified 2026-11-05 (America/New_York). Changes are uncommitted in the existing Phase 16 checkout.
Status: **PASS — Phase 17 implementation and complete local development acceptance.**
Base revision: `0d478bd`; Phase 16/17 changes remain uncommitted. This is not production certification.
Production remains **BLOCKED** under PLANS.md section 23B. No deployment, certification, package
publication, Code Workspace or Phase 18 implementation was performed.

## Verified scope and architecture

The explicit request authorizes milestone G in 23A.10, with media details in 23A.7, reusable logic and
orchestration in 23A.8 and shared execution in 23A.9. The roadmap's PDF acceptance is broader than the
prompt's proposed image/audio/video list, so PDF metadata and originals are included. Arbitrary code,
full visual workflow building, OCR/transcription, later application/workspace infrastructure and
production readiness are excluded. UTC daily scheduling is the supported calendar subset; general
cron/local timezone grammar is explicitly rejected. Functions are the initial automation targets;
existing canonical actions supply the allowlisted event source, not a second mutation framework.

[ADR 0042](../decisions/0042-media-functions-automations.md) was recorded before substantial
implementation. Phases 12–16 reports and ADRs 0037–0041 informed reuse of the registry, immutable
artifacts, version records, leases/fencing/admission, canonical action/outbox authority and SDK/BFF.
The existing dirty Phase 16 files/reports/evidence were preserved. No additional database, queue,
authorization hierarchy or semantic engine was introduced.

## Media model, storage and provenance

MEDIA_SET uses stable registry UUIDs and existing Project/folder, rename/description, share/revoke and
archive operations. `media_items` pins a committed source ARTIFACT version, immutable item UUID, MIME,
source filename, bytes/SHA-256, creator/time, parser metadata, processing metrics and optional derived
preview version. `governed_definitions` plus `media_memberships` freezes each published snapshot;
adding/removing membership requires another version. Empty snapshots are supported. Source references
are tenant-qualified FKs; duplicate attachments return the same item after authorization/type checks.

The existing artifact upload/initiate/verify/finalize protocol supplies source bytes. Transfers use
bounded spooling and full SHA-256 checks. Parsing runs outside governance transactions in bounded
spawned children; publication rechecks set write and source read. Previews are immutable artifact
versions owned by the set, without an independently shareable preview resource. Every media read,
lineage lookup, original download and preview requires both set and source access. Hidden items and
snapshot identities are filtered; sharing a set never grants private source access. The binary BFF
keeps tokens/store credentials server-side, requires CSRF and expected tenant, streams authenticated
no-store attachments and exposes no public store URL.

Supported formats are PNG/JPEG (full image verification/decode, dimensions/mode/orientation, stripped
512×512 JPEG thumbnail), PCM WAV (bounded complete frame scan, duration/rate/channels), H.264/AAC MP4
(bounded container/codec/dimension/rate/duration/first-frame probe and JPEG poster), and unencrypted PDF
(strict structural metadata/page count and original only). MP4 is not a full-playback validation claim.
Unsupported containers/codecs, malformed signatures and over-budget content fail explicitly. No
embedded script, PDF action or user metadata path is executed. Dependencies are pinned in uv.lock:
Pillow 13.0.0, PyAV 16.0.1 and pypdf 6.12.0, with installed/API-source checks documented in the API guide.

Media lineage is actual item/source/preview identity, immutable checksum and extraction metadata;
snapshots supply exact membership/version pins. Existing dataset/pipeline/materialization lineage is
unchanged. Stable item/resource references survive registry renaming. Failed attachment leaves the
source artifact retained and does not create a valid media item.

## Functions, authority and isolation

FUNCTION definitions pin versioned implementation IDs and strict flat input/output schemas. Supported
implementations are `identity.v1`, `text.normalize.v1` and `number.add.v1`. Contracts permit bounded
string, integer, number and boolean fields, explicit nullability, finite portable numbers, fixed
configuration, limits, required Project write permission, deterministic/idempotent declarations and
sanitized error categories. Unsupported nesting, imports, executable fields and implementations fail.
No draft is executable. Definition retrieval/publication has family-specific generated response types.

Invocations pin exact definition, values, actor/tenant/Project, implementation and CPU/memory/wall/disk
and input/output budgets. Inputs validate before admission; outputs validate in the child and again
before publication. Bounded scalar results use `function_results`; oversize output fails. These pure
implementations do not need artifact-backed output, and no unsupported large-result format is exposed.
There is no object/link read/write capability in the function registry. Existing action/ontology
mutation authority remains unchanged; functions cannot bypass it or create a competing Action Builder.

Existing execution_jobs supply queue admission, concurrency quotas, random-token fencing, PostgreSQL
clock leases/heartbeat, bounded retries, controller restart, cancellation and status/history. A live
transaction-local execution fence is mandatory for immutable result insertion; success requires a
committed result. Cancellation and publication serialize under current governance. Definition/input
and source pins are not reinterpreted using newer schemas. Idempotency keys are actor/function scoped;
replay returns the same job, and changed values/version conflict.

This is a closed trusted implementation registry, **not hostile-code sandboxing**. Spawn passes only
values/contracts/limits, clears nonallowlisted environment and passes no DB/store handles. POSIX CPU
and per-file size limits apply; Linux also uses address-space limits. RSS, aggregate disk and wall
limits are parent watchdogs on macOS. Pure adapters expose no network/process spawning capability;
hard egress/pid/cgroup isolation on a production target is not claimed or certified. New trusted
implementations need review and a new pinned identifier. Arbitrary tenant code remains rejected.

## Automations, dispatch and recovery

AUTOMATION versions pin typed trigger, target function resource/version, constant typed bindings,
coalescing missed-run policy and bounded idempotent retry policy. Target/version/event-source references
have physical tenant-qualified FKs. Triggers are manual, interval >=60 seconds, UTC daily calendar and
existing action.committed outbox events scoped through an authorized ontology resource. Event identity
and timestamp are consumed without private payloads; event scope follows that ontology across schema
versions. No user expressions, arbitrary event handlers, external side effects or action targets exist.

`automation_states` stores enabled state, next-run UTC instant, owner identity attributes (no bearer
token), activation UUID and checked-at rotation. The existing execution worker CLI drives bounded
scheduler ticks, then shared execution jobs. API replicas have no scheduler timers. Normal security,
tenant and row lock order serializes dispatch; receipt uniqueness, invocation and job commit atomically.
A controller crash leaves all committed or all rolled back. Schedule claims use PostgreSQL time;
backward jumps wait, forward jumps coalesce one missed run and advance past now. UTC daily times have
no DST overlap/gap; unsupported zones are rejected. Event dedup uses immutable receipts without a
commit-order-sensitive advancing cursor; webhook delivery state is untouched.

Every dispatch and publication rechecks owner identity/membership, automation/target permissions,
version and activation state. Archive/revocation/disable prevents future publication; committed results
remain history. Enable/disable rotates an activation UUID, so re-enable cannot revive earlier jobs.
Stale scheduler failures compare that UUID before disabling a newer activation. Only the bound owner
can activate/trigger; Project control does not borrow another actor's identity. No durable browser
token or alternative service-identity system is introduced.

At-least-once process execution is tolerated. Unique trigger receipts and invocation keys deduplicate
logical runs/results. Retry retains exact pinned inputs/version and follows existing bounded eligible
failure categories. Pure/idempotent implementations permit safe retries; non-idempotent effects are
not admitted. Cancellation never promises rollback. Permanent dispatch denials disable the automation
with a fixed error/audit; capacity failures remain enabled for later bounded admission. Function runs
cannot emit action events, so the supported event graph cannot recursively trigger itself.

Automation receipts, published definitions and invocation/result records supply version/trigger/job,
actor, state/attempts, inputs and output provenance. History rechecks target/source authority;
function provenance omits inaccessible automation identities. No fabricated edges or event payloads.

## Budgets, APIs, Studio and SDK

[Limits and enforcement](phase-17-limits.md) documents independent FOUNDRY_G settings: item bytes and
count, tenant/Project retained media bytes, pixels, probe/parse duration, preview bytes, function I/O,
CPU/memory/wall/disk, function concurrency, tenant/Project automations, rolling database dispatch rate,
backlog, retry attempts and retained history. Dataset source's 1 GiB contract is unchanged. Retention
caps reject new retained records; no automatic purge or destructive cleanup was added.

The [API inventory and examples](../api/media-functions-automations.md) lists all API v1 endpoints.
Families expose create/get, validate, publish/list/get immutable definitions. Media adds attach/list,
snapshot membership, metadata, content and lineage. Functions add invoke/history/result/provenance;
shared execution status/cancel/retry remain authoritative. Automations add activation, schedule, manual
trigger and receipts, whose jobs support the same status/cancel/retry/results. Generic Project/resource
APIs supply discovery and common lifecycle operations. Pagination and request bodies stay bounded.

Studio integrates these resource types into existing Projects/folders/lifecycle controls. Structured
JSON editors support validation/publication, authorized source attachment and membership snapshots,
metadata/provenance, image/poster preview, streamed original saving, function invocation/status/metrics/
results/errors/cancel/retry/history and automation enable/disable/manual trigger/schedule/history/job
inspection. Function polling is bounded to 120 polls and pauses hidden tabs. Original media saving
requires the browser streaming-save API; SDK callers receive cancellable ReadableStreams instead.

Existing @foundry/sdk and @foundry/react are extended to 0.17.0 without replacing their public clients.
Generated wrappers/hooks use actual synchronized OpenAPI, family-specific definitions and result types,
existing confirmation/error normalization, session/tenant-isolated caching, bounded pagination/polling
and request cancellation. Binary preview/original streams use the fixed BFF outside query caches.
The existing starter's dependencies are updated; no workspace provisioning or app hosting was added.

## Migration and preservation

Actual previous head was 0022_materialization. New forward-only **0023_media_functions** adds seven
metadata/state/history tables and extends existing resource/execution guards and checks. Frozen SQL
never imports evolving ORM metadata at migration runtime. Composite FKs, immutable published rows,
source/preview validation, live result fencing, target bindings, schedule state and unique trigger keys
are enforced. Fresh migrations, previous-head upgrade, preserved sentinel/data and Alembic drift are
covered in disposable schemas. The previous mapping-upgrade test's expected current head advances;
its preservation/drift assertions are retained. No historical migration was modified.

[Preservation evidence](evidence/phase-17/preservation.txt) records the shared developer database still
at **0017_capacity**, checked read only. Canonical fixtures and historical migrations are unchanged.
Only private random test schemas, Compose projects and MinIO volumes are created/removed; shared
MinIO is not reset. Earlier Phase 16 dirtiness and reports/evidence are preserved.

## Validation, security and acceptance

The final complete run starts after the final functional transport correction and all other
implementation changes. All 16 commands passed. Environment is macOS arm64, Python 3.12.0,
Node 26.7.0, Docker 28.3.0 and real PostgreSQL 17.6; exact package/native-library versions are in
[environment.txt](evidence/phase-17/environment.txt). Only disposable schemas and private digest-pinned
MinIO Compose projects/volumes were used; repeated init and restart retained verified sentinel bytes.

Final Python result: **834 passed, 1 preserved strict xfail, zero skips**, 1151.35s.
Final Studio browser result: **12 passed**, including actual media/preview, typed function and manual
automation workflows, 1 GiB dataset upload, legacy authoring/governance, durable session replication,
CSRF and tenant/session loss. The live SDK example browser workflow also passed. Core/React SDK tests:
**63 passed**. Studio unit tests: **47 passed**. Independent packed-package consumer passed.

[results.json](evidence/phase-17/final/results.json) records exact commands, exit codes and PASS/FAIL.
The full invocation is `PATH=/Users/log/.nvm/versions/node/v26.7.0/bin:$PATH caffeinate -dimsu uv run python scripts/validate_phase17.py`.
The runner delegates real-service integration to `scripts/validate_phase15.py --full --browser`, which
migrates only owned schemas and runs the complete Python suite plus durable Studio browser suite.
The example uses a separate private test runner and artifact directory. No mocks substitute for
required PostgreSQL/MinIO integration.

| Executed check | Result | Final evidence |
| --- | --- | --- |
| Ruff lint / format / strict mypy | PASS | python-quality.txt, python-format.txt, mypy.txt |
| Actual OpenAPI export / generated SDK drift | PASS | openapi-export.txt, generated.txt |
| SDK formatting / build / typecheck | PASS | sdk-format.txt, sdk-build.txt, sdk-typecheck.txt |
| SDK core/React tests / packed independent consumer | PASS | sdk-tests.txt, sdk-consumer.txt |
| Studio formatting / typecheck / unit tests / production build | PASS | studio-format.txt, studio-typecheck.txt, studio-tests.txt, studio-build.txt |
| Complete real PostgreSQL/MinIO/semantic/Python suite | PASS | full-platform-browser.txt; 834 passes, one strict xfail, no skips |
| Durable Studio browser workflows | PASS | full-platform-browser.txt; 12 passes |
| Live SDK example browser | PASS | example-browser.txt; one pass |
| Fresh/previous-head upgrade, data preservation and drift | PASS | Full new milestone G migration test and existing upgrade/drift suites |
| Git/changed-source whitespace and implementation hash stability | PASS | preservation.txt and implementation-sha256.txt; executed checks |

Security/operational coverage includes cross-tenant references, private shared-set source and preview
denial/revocation, pending/invalid/duplicate membership, unsafe signatures/content and pixel budgets,
implementation/schema/configuration injection, strict input/output budgets, unauthorized function
invocation and current owner revocation, lease expiry/stale tokens, fenced results, cancellation,
retry exhaustion, duplicate manual/event/schedule deliveries, multiple scheduler instances, UTC daily
calendar/DST semantics, coalescing, rolling dispatch quota and old-activation invalidation. The closed
registry exposes no credential/query/mutation/code capability; existing ontology/action authority and
canonical mutation tests remain passing. Private automation identities are filtered in provenance.
Existing CSRF, BFF/session and SDK cache-isolation tests also pass in the final run.

The new suite contains 40 cases, including a real 64 MiB PCM WAV through MinIO and extraction, measured
child RSS below 512 MiB, and an actual ASGI original download checked incrementally for exact size/SHA-256
and <=1 MiB body chunks. The parser deadline case uses a test-only stalled real child with real stored
source bytes, and verifies timeout prevents item publication. Actual PNG/JPEG/WAV/MP4/PDF paths are
separately executed; the controlled timeout is not a claim of hostile-code isolation.

Earlier failed/interrupted attempts are retained, not counted as final acceptance. They include the
initial multi-table trigger field-planning error, missing test imports/schema authoring mismatch,
SQL variable/table alias ambiguity, obsolete Node invocation, formatter correction and an empty
Next.js accessibility-announcer assertion in the new browser test. Interrupted complete runs were
stopped for final key/typed-contract work and for the discovered media streaming allowlist omission;
owned schemas/MinIO were cleaned by their runners. The final complete run includes the corrected
streaming path and regression assertion. No historical assertion or test was disabled; the prior
mapping-upgrade head expectation alone advances to 0023 while preservation/drift assertions remain.
A later complete attempt had 832 passes and two jobs left RUNNING after macOS maintenance sleep
exceeded their existing 60-second leases. Power logs recorded 123–267 second sleep periods
([host-sleep-attempt-4.txt](evidence/phase-17/host-sleep-attempt-4.txt)). The final unchanged suite ran
under temporary caffeinate assertions ([awake-validation.txt](evidence/phase-17/awake-validation.txt));
no lease, assertion, historical test or timeout was weakened. Sleep prevention ends with validation.

### fixtures/VALIDATION.md

The guide was read during reconnaissance and consulted again before completion. Results below refer
to this phase's executed final suite, not inherited earlier acceptance.

| Check | Result | Evidence / scope |
| --- | --- | --- |
| Turtle parsing | PASS | Final test_fixtures.py |
| CSV counts/identities/FKs and RDF/CSV consistency | PASS | Final fixture suite; 6/20/12/25, 63 typed instances |
| Normalized SHACL and negative mutations | PASS | Final fixture/semantic suites |
| Raw pySHACL simple/xsd:string compatibility | NOT SUPPORTED | Preserved strict expected failure, executed |
| Supported Open Ontologies SHACL and owl-rl-ext reasoning | PASS | Final pinned engine/compiler/semantic suites |
| Base owl-rl exact fixture axiom | NOT SUPPORTED | Existing pinned-profile limitation, fixtures unchanged |
| PostgreSQL integration / FastAPI object queries | PASS | Final complete real-database suite |
| Actions and reconciliation | PASS | Final action/edit/outbox/recovery suites |
| Polars ingestion | PASS | Final ingestion/connector/recovery and execution suites |
| Authorization / tenant and Project isolation | PASS | Final security, new media/function/automation denial, SDK and browser tests |
| Supported Protégé import/export | PASS | Final interchange/import suites and authoring browser workflow |
| Manual desktop Protégé GUI | NOT RUN | No desktop authoring session; no new OWL constructs |
| Linux hard isolation / target OKD4 / live external provider certification | NOT RUN | Separate target environment and section 23B scope; no production certification |
| Standalone TypeScript lint | NOT SUPPORTED | No standalone lint script; executed TypeScript/Prettier/build checks |

### Requested Phase 17 acceptance matrix

PASS is local implemented scope, with explicit exclusions/unsupported environments above. It does
not certify arbitrary code, every codec, non-UTC cron, external side effects or production.

| # | Criterion | Result | Evidence |
| --- | --- | --- | --- |
| 1 | Governed Media Set resources | PASS | Registry/common lifecycle, real API and browser |
| 2 | Immutable Media Set versions | PASS | Snapshot membership and direct SQL immutability tests |
| 3 | Media ingestion reuses ArtifactStore | PASS | Real committed source/preview versions and 64 MiB transfer |
| 4 | Bounded metadata extraction | PASS | Actual parsers, pixel limits and real-child deadline test |
| 5 | Secure supported previews | PASS | Real JPEG thumbnail/MP4 poster; BFF browser preview |
| 6 | Media authorization and lineage | PASS | Shared-set private source denial/revocation and snapshot filtering |
| 7 | Governed Function resources | PASS | Existing registry/Project API and browser creation |
| 8 | Immutable typed function definitions | PASS | Typed family contracts, fixed schemas, SQL guards and injection tests |
| 9 | Explicit safe function trust boundary | PASS | ADR 0042, closed pure registry, no privileged child handles |
| 10 | Durable function invocation | PASS | Shared execution_jobs, real worker and built SDK consumer |
| 11 | Function limits enforced as documented | PASS | Pinned limits, bounded I/O, rlimits/watchdogs and admission tests |
| 12 | Function results and provenance | PASS | Live-fenced immutable result and authorized history/provenance |
| 13 | Existing ontology/action authority preserved | PASS | Complete canonical regressions and real action/outbox integration |
| 14 | Governed Automation resources | PASS | Registry/Project lifecycle and Studio/API |
| 15 | Immutable typed automation definitions | PASS | Pinned target/version/event FKs and strict trigger/binding contracts |
| 16 | Supported triggers work | PASS | Manual, interval, UTC daily and action.committed tests |
| 17 | Durable restart-safe scheduling | PASS | Database schedule state, new controller instances and coalescing |
| 18 | Idempotent duplicate dispatch | PASS | Unique receipts, competing dispatchers and repeated manual/event delivery |
| 19 | Authorization rechecked | PASS | Current owner membership, source/target and publication checks; revocation tests |
| 20 | Safe retries and cancellation | PASS | Existing bounded job retry/cancel, pure idempotent registry, activation fencing |
| 21 | Automation provenance | PASS | Immutable receipt/definition/job pins, target-filtered history |
| 22 | Studio media/function/automation workflows | PASS | Final governed-processing browser plus Studio unit tests |
| 23 | Existing TypeScript/React SDK integration | PASS | 0.17.0 generated wrappers/hooks, streaming, builds and consumers |
| 24 | Synchronized OpenAPI/generated contracts | PASS | Final export and drift checks |
| 25 | Budgets/security denial tests | PASS | Full new 40-case suite and existing security/browser/SDK regression |
| 26 | Real PostgreSQL/MinIO | PASS | Final privately owned real-service integration, init/restart evidence |
| 27 | Existing Python/frontend/browser/SDK regressions | PASS | Final complete suite and all 16 validation commands |
| 28 | Fresh/upgrade migrations and drift | PASS | 0022 to 0023 preservation and full Alembic drift checks |
| 29 | Documentation and ADR | PASS | ADR 0042, API/limits/SDK docs, report and exact inventory |
| 30 | No later-phase infrastructure | PASS | Changed-file/scope review; no workspace/hosting/visual builder |
| 31 | Production remains blocked | PASS | Section 23B and exclusions preserved; no deployment/certification |

## Limitations and next prerequisites

Closed pure functions only; no arbitrary code, ontology query/mutation function adapter, action target,
artifact-producing function implementation, mutable event bindings, general cron/local timezones,
PDF rendering, media editing, OCR/transcription or new service identities. MP4 is a bounded first-frame
probe. Source bytes and committed previews are retained; crashes/concurrent attachment can leave
unreferenced preview reservations/versions. No automatic purge. Transfer verification may use two
bounded disk copies during media spooling. Metadata/history visibility can produce short pages.
Native original-download support depends on browser streaming-save capability.

Production security/provider/cluster/capacity/independent approval gates remain in section 23B.
Next milestone H / visual pipeline authoring requires separate approval and should compile to the
existing pipeline representation. Neither Phase 18 nor production work is authorized by this report.

## Exact changed-file inventory

[changed-files.txt](evidence/phase-17/changed-files.txt) enumerates every Phase 17 source/document
path, separately from pre-existing Phase 16 work. [implementation-sha256.txt](evidence/phase-17/implementation-sha256.txt)
records the implementation snapshot for final validation. Evidence files are inventoried separately
at completion. No commit or staging operation was performed.
