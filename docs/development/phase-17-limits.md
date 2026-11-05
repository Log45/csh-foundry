# Phase 17 operator budgets and trust boundary

`FOUNDRY_G_` settings are independent of `FOUNDRY_EXECUTION_` and do not alter dataset source's
1 GiB maximum. G defaults (all can be lowered; typed upper bounds apply where specified):

| Setting suffix | Default |
| --- | --- |
| MEDIA_BYTES | 256 MiB per original |
| MEDIA_ITEMS | 1000 retained items per set / snapshot |
| TENANT_MEDIA_BYTES / PROJECT_MEDIA_BYTES | 10 GiB / 5 GiB retained source references |
| PIXELS | 20 million decoded image/video pixels |
| PREVIEW_BYTES | 1 MiB; 512×512 JPEG |
| PARSE_SECONDS | 30 seconds wall and CPU for extraction/probe |
| INPUT_BYTES / OUTPUT_BYTES | 16 KiB each; max 32 fields, 8192 characters per string |
| FUNCTION_JOBS | 2 active functions globally, within existing global/tenant/Project limits |
| SCHEDULES / PROJECT_SCHEDULES | 100 per tenant / 50 per Project enabled automations |
| DISPATCH_BATCH | 20 occurrences per controller cycle |
| DISPATCH_PER_MINUTE | 60 receipts per tenant per database rolling minute |
| BACKLOG | 100 outstanding tenant execution jobs before automation admission |
| HISTORY | 10000 retained definitions/invocations/receipts per resource; no automatic purge |

Function definitions can lower limits: wall 30s (max60), CPU10s (max30), RSS256MiB (128–512MiB),
temporary8MiB (64KiB–16MiB). Effective limits also respect administrator ExecutionSettings.
Retries use existing FOUNDRY_EXECUTION_ATTEMPTS (default3, max10), including lease recovery and
manual retry eligibility. Queue/global/tenant/Project admission uses the existing worker settings.
Media ingestion reuses transfer admission slots; extraction child RSS512MiB, fixed local paths,
media-sized temporary processing budget, no ambient credentials. Verified transfer spool plus source
copy can temporarily use twice the item bytes before the spool closes. Preview provenance stores
parser version, immutable source checksum, timestamps and processing metrics. Retained quotas count
references (same original attached to two sets counts twice). Storage retention includes archived sets.
Committed source/preview bytes are retained; abandoned preview reservations can remain after crashes.
No destructive cleanup is introduced.

CPU and per-file size: POSIX RLIMIT_CPU / RLIMIT_FSIZE. Linux address space: RLIMIT_AS.
RSS, aggregate temporary size and wall: parent watchdog, not kernel-hard limits on macOS.
Closed pure implementations expose no process/network or privileged-service capabilities. Spawn
removes nonallowlisted environment before dispatch and receives no SQL sessions or S3 handles.
Hard network/pid/cgroup enforcement is not claimed on this development host. The closed registry
is the security boundary; new implementations require reviewed trusted installation and a new pinned
identifier. Arbitrary tenant code is rejected, not sandboxed by this worker. Action mutation authority
is unchanged. Future hostile code requires separately approved enforceable isolation.

Originals are attachments; browser native streaming-save support is required for Studio original
media downloads. Thumbnails are bounded blobs outside React caches. SDK originals/previews expose
ReadableStreams with AbortSignal, immutable session clients and the existing BFF CSRF/tenant gate.
Artifact-backed function outputs, local-zone cron, mutable input/event bindings, non-idempotent
functions, OCR/transcription, PDF rendering and workspace/hosting infrastructure remain excluded.
Production remains blocked under PLANS.md section 23B.

Input/output byte budgets are pinned in immutable invocation requests as well as rechecked against
current administrator ceilings. A later increase cannot expand an admitted job's budget. Function
versions have no separate mutable archive flag; archiving the owning resource blocks all versions.
Media content URLs participate in the existing transport middleware's binary streaming allowlist;
metadata routes retain their original buffering bounds.
