# Phase 17 — Governed Media Sets, Functions and Automations

Date: 2026-11-04 (America/New_York). Changes are uncommitted in the existing Phase 16 checkout.
Status: **Final validation running; local acceptance is not yet declared.**
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

Final results will be recorded after the complete run finishes. Intermediate failed/interrupted runs
are retained under evidence/phase-17 and are not passing acceptance evidence. Targeted validation has
executed real PostgreSQL/MinIO, image/audio/video/PDF parsing, secure preview/source access and
revocation, typed contracts/injection denials, durable worker/fencing/retry/cancellation, duplicate
manual/event/schedule delivery, UTC calendar/coalescing, owner revocation, activation invalidation,
parser timeout, a 64 MiB media memory check, actual API contracts and a built SDK consumer.

No production acceptance is inferred from local tests. Linux hard isolation, target OKD4, live external
OIDC/S3 certification and manual Protégé GUI inspection remain NOT RUN; historical raw pySHACL and
base owl-rl limitations remain NOT SUPPORTED. Full fixture-guide and 31-criterion matrices follow
when executed final evidence is available.

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
