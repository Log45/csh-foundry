# ADR 0042: Governed media, trusted functions and durable automations

Status: Phase 17 design, recorded before implementation. Acceptance is separate.

Milestone G and sections 23A.7–9 authorize these vertical slices. PDF is included because the
roadmap's media acceptance explicitly requires it. OCR/transcription/embeddings, code hosting,
workspaces, arbitrary executable code, application hosting and Phase 18 remain excluded.

MEDIA_SET, FUNCTION and AUTOMATION use the existing registry, Project membership, shares,
folders, archive and audit services. References never grant access. Immutable published records
have tenant-qualified keys and database immutability guards. Media item identity is independent
of filename; snapshots explicitly pin item IDs. Membership changes publish a new snapshot.
Media items reference committed ARTIFACT versions, retaining checksum, creator and provenance.
Every item read/download/preview rechecks both set and source access. Shared sets do not reveal
private artifact identities. Media bytes and derived previews use ArtifactStore, with the existing
upload protocol and verified bounded spooling. No byte arrays are persisted in SQL.

Parsing is outside governance transactions in the existing spawned execution adapter, using pinned
Pillow/PyAV/pypdf and stdlib wave. Initial allowlist: PNG/JPEG, PCM WAV, MP4 H.264/AAC and PDF.
Only image thumbnails and MP4 poster frames are rendered; PDF is metadata/download only. Embedded
PDF actions are never executed. Fixed local file objects, not metadata paths/URLs, reach parsers.
Independent media limits bound bytes, pixels, probe wall/CPU time and preview bytes. Tenant/Project
quotas count retained immutable items; no automatic destructive retention is introduced.

Functions are closed, trusted, pure implementations with versioned identifiers: typed scalar identity,
text normalization and numeric addition. Definitions have flat bounded typed input/output contracts,
fixed implementation version, no code/imports/URLs, explicit deterministic/idempotent policy and
limits. They have no ontology, network, filesystem or credential capability. Actions remain the sole
business mutation orchestration authority; these initial functions cannot mutate ontology state.
Inputs and outputs are validated strictly and bounded independently; oversize results fail rather than
silently entering PostgreSQL. Artifact-backed results are reserved for a future trusted implementation
that needs them; no initial implementation produces large output.

Function invocations reuse execution_jobs, admission, leases, heartbeat, fencing, cancellation,
bounded retries and immutable inputs. A dedicated invocation record pins the exact definition and
actor; immutable result publication requires a live transaction-local fencing token. The child receives
only values and contracts. Spawn clears ambient environment before adapter dispatch; no database or
store handles are passed. This is trusted-code containment, NOT hostile-code isolation. CPU and
per-file limits use POSIX rlimits, Linux address-space uses RLIMIT_AS; RSS, aggregate temporary disk
and wall time are watchdogs on development hosts. No process spawning/network APIs are exposed by
the registry. Hard process/network/cgroup enforcement is an operator deployment prerequisite, not
claimed by this phase or a substitute for the closed trust boundary.

Automation definitions pin a function resource/version and typed constant inputs. Initial triggers:
manual, UTC interval, UTC daily calendar, and existing action.committed outbox events scoped to an
explicit authorized ontology resource. No arbitrary cron grammar or user expressions. UTC calendar
semantics intentionally avoid local DST ambiguity; other timezones are rejected. PostgreSQL stores
next-run and event cursor, enabled state and owner identity attributes (never bearer tokens). A
controller invoked by the existing worker CLI scans bounded candidates, then takes normal security/
tenant locks and row locks. Dispatch, unique trigger receipt and execution job commit atomically.
Multiple controllers serialize by the same lock order; no API timers or second queue. Missed intervals
coalesce to one due occurrence then advance strictly beyond database now. Backward clock movement
waits until the stored instant; forward jumps coalesce. Events scan an ordered durable cursor; each
receipt is unique and retries preserve the same logical job. No target emits action events, preventing
recursive loops; event payloads are never copied into input bindings or public history.

Owner current identity, tenant/Project membership, automation write, function access and pinned target
are rechecked on dispatch and publication. Revocation/archival/disable prevents publication of pending
work; already committed results remain history. Enable/republication requires current owner authority;
manual trigger requires the owner so it cannot borrow another actor's privileges. Failures remain
bounded audited receipts. Only pure idempotent functions retry; cancellation never promises rollback.
Schedules and trigger backlog/dispatch rate have independent operator caps. No service-identity or
browser credential system is introduced: existing durable internal principal bindings are reused.

API v1, Studio BFF/CSRF and generated @foundry/sdk/@foundry/react contracts remain the integration
boundary. Metadata is bounded JSON; binary originals/previews remain authenticated streaming
ArtifactStore transfers and never enter query caches. Provenance is immutable pinned definition,
source/version and trigger/job references; retrieval checks every referenced resource and filters
private identities. Retention is bounded by admission and per-resource retained-history caps; no purge.
Production remains BLOCKED under section 23B. Shared developer database and MinIO are not migrated
or reset. Tests use disposable PostgreSQL schemas and privately owned MinIO Compose projects.

Implementation refinements: previews are artifact versions owned directly by MEDIA_SET, with no
separate registry resource/share. The media content service checks both set and original before
resolving those versions; generic artifact endpoints reject MEDIA_SET. This prevents copying private
preview bytes into an independently shareable Project artifact. Automation definitions have physical
tenant-qualified FKs for pinned target resource/version and event source. Enable/disable rotates a
durable activation UUID, pinned in jobs, so re-enabling never resurrects older work. Scheduler failure
updates compare that UUID before disabling state. A checked_at rotation prevents scan starvation.
Event scanning uses unique receipts rather than advancing a timestamp cursor past uncommitted rows;
only the activation lower-time boundary is retained. Existing webhook status is never consumed.
UTC daily scheduling is the initial calendar subset; other cron/timezones fail validation explicitly.
