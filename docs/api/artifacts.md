# Phase 12 artifacts

Artifacts are generic Project registry resources. This phase does not implement datasets or parse
uploaded files. PostgreSQL owns identities, versions and authorization. S3 owns bytes.
[ADR 0037](../decisions/0037-immutable-artifact-storage.md) describes the transaction boundaries.

## API

All routes require the existing authenticated tenant context and live Project permissions/membership.
Use the normal JSON structured error envelope; no buckets, credentials or endpoints are accepted
from clients. All IDs below are UUIDs. Unknown and private resources return identical 404s.

| Method / path under `/api/v1` | Behavior |
| --- | --- |
| POST `/projects/{project}/artifacts` | Create registry resource: name, optional description/folder_id |
| GET `/projects/{project}/resources` | Browse/search artifacts and permitted ontology references; limit 1–100, offset 0–10000 |
| GET `/resources/{artifact}` | Authorized logical artifact metadata |
| PATCH `/resources/{artifact}` | Rename/move, expected_revision; identity/ownership stay fixed |
| POST `/resources/{artifact}/archive` | Archive, expected_revision; retains all committed bytes/metadata |
| GET/PUT `/resources/{artifact}/shares` | Existing owner-managed explicit sharing/revocation |
| POST `/artifacts/{artifact}/uploads` | Reserve PENDING version; filename, size, lowercase SHA-256, optional source |
| PUT `/artifacts/{artifact}/versions/{version}/content` | Bounded binary upload; size and digest must match initiation |
| POST `/artifacts/{artifact}/versions/{version}/finalize` | Read-back verification then atomic COMMITTED transition; retry is idempotent |
| GET `/artifacts/{artifact}/versions` | Version history including pending/failure states, bounded descending sequence pagination |
| GET `/artifacts/{artifact}/versions/{version}` | Version metadata, no internal storage address |
| GET `/artifacts/{artifact}/versions/{version}/content` | Verified, streamed attachment; only COMMITTED bytes |
| POST `/artifacts/{artifact}/versions/{version}/presign` | Optional single-object GET capability; disabled unless endpoint is explicitly client reachable |
| POST `/artifacts/{artifact}/cleanup` | Owner + project:manage; `{ "dry_run": true }` default, max 100 old uncommitted versions per call |

Project roles compose with tenant permissions. Only owner/editor + project:write can upload;
shared users have read access through current destination membership, never write authority.
Artifacts do not require an ontology or schema:read. Ontology registry discovery still filters
ontology permissions before pagination, and direct references independently require schema:read.
No automatic administrator access or separate sharing tables exist. Audits use authorization_audit.

## Immutable upload and recovery protocol

1. Create artifact, then initiate with locally computed SHA-256 and byte count. The server verifies
   both against actual bytes; client claims cannot publish bytes. Sequence allocation is serialized
   by existing tenant locks; reservations are never reused. A retry of initiation creates a new
   pending version; preserve the returned version ID to retry the same upload.
2. PUT bytes. Filenames are display-only and reject separators/controls/dot paths. Content type is
   always `application/octet-stream`, independent of client MIME claims. Transfer is streamed to a
   disk temporary file with a bounded byte count and 60-second request deadline; the S3 adapter
   streams reads and uses fixed-size multipart buffers. A successful transfer remains PENDING.
3. Finalize separately. The service verifies size and full read-back SHA-256, then commits metadata.
   Multipart ETags and client-controlled object metadata are never trusted as full-content hashes.
   Retry finalization returns the same committed metadata. A committed DB row cannot be modified
   or deleted, including by ordinary direct DML, and conditional storage writes prohibit overwrite.
4. Interrupted transfers/finalizations stay pending. If storage succeeded before a DB rollback,
   repeat transfer checks the exact existing bytes instead of replacing them. Missing/corrupt objects
   cannot commit. A failed multipart transfer attempts abort; abandoned sessions are aborted by
   exact-key cleanup. Transient failures have bounded SDK retries; no indefinite application retries.

The storage SDK cannot join a PostgreSQL transaction. Existing tenant/security locks span bounded
storage work for ordering with revocation and finalization. This favors correctness over throughput;
long transfers can block Project operations and hit their lock timeout. Operators must size storage
latency and request limits accordingly. A disconnected response does not undo an already committed
metadata transaction; inspect the version state before retrying. No background execution system is
introduced. Temporary files close on ordinary success/failure, and the OS reclaims them on crash.

Downloads are fully verified into a bounded disk file before response headers, then streamed without
middleware buffering, with attachment/nosniff/no-store. The current API download filename is
`artifact.bin`; Studio uses the validated display filename when saving. Files are never executed,
previewed or treated as safe HTML. Malware scanning/quarantine is a future separately governed
integration; generic storage does not certify the contents. Studio limits files to 64 MiB, computes
SHA-256 in bounded browser memory and shows transfer stages and errors; API limits are configurable.

## Retention and reconciliation

Archive never deletes bytes. Committed versions have indefinite retention in Phase 12. There is
no committed purge, restore, object-prefix deletion or automatic bucket expiration. Future consumers
must reference immutable committed version rows and cannot authorize physical deletion on their own.

Cleanup targets only PENDING/FAILED versions older than abandoned_seconds. An owner may run it
for an archived artifact/Project. Start dry-run, then explicitly set dry_run=false. The tenant lock
excludes concurrent finalization; FAILED is flushed before exact-object deletion, then DELETED is
recorded. All history stays in PostgreSQL. Storage failures return `retry` and audit the decision and
failure. A crash before DB commit leaves a repeatable pending/failed record; the object may already
be absent, but cannot have committed references. Repeat calls safely converge. Call until no more
eligible rows; invoke manually or through existing approved operator tooling. No scheduled purge.

Presigned URLs are bearer capabilities scoped to one GET, default 60 seconds, maximum 300.
They may remain usable after revocation until expiration. There is no claim of instantaneous
capability revocation. Already authorized in-flight transfers may finish; subsequent requests
recheck live authority. Only enable when the configured HTTPS endpoint is reachable and appropriate
for clients; internal MinIO uses the server-mediated path. Provider-side policy must prohibit public
bucket access and arbitrary users' storage credentials.
