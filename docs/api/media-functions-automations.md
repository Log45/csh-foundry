# Governed media, functions and automations (Phase 17)

All endpoints use `/api/v1`, existing Principal/tenant/Project authority and bounded pagination
(`limit=1..100`, `offset=0..10000`). Common rename, description, folder placement, sharing, share
revocation and archive use `/resources/{resource_id}`. Discover all types in Project resource lists.
Create with `POST /projects/{project_id}/{media-sets|functions|automations}` and the existing
CreateArtifact contract (name, description, folder_id). GET each resource by family/UUID.

Each family supports `POST /{family}/{id}/validate`, `POST .../definitions` (immutable publication),
`GET .../definitions`, and `GET .../definitions/{definition_id}`. Validation never publishes a draft.
Media definitions are snapshots: `{"items":["<item UUID>"]}`. Membership removal publishes a new
snapshot, including an empty one. Item identity and original bytes never change.

Upload originals through the existing Artifact initiation/PUT content/finalization protocol.
`POST /media-sets/{set_id}/items` attaches a committed ARTIFACT version using `artifact_id`,
`artifact_version_id`, `media_type`; replaying the same reference/type returns the existing item.
No custom object-store key or upload URL is accepted. GET `/items` (optional `version_id` snapshot),
`/items/{item_id}`, `/items/{item_id}/lineage`, and `/items/{item_id}/content?preview=true|false`.
Every read checks set AND source authority. Hidden items and snapshot references are filtered.
Preview artifact versions live under the set, have no separate resource/share, and cannot be read
through generic artifact endpoints. Private source revocation prevents subsequent preview reads.
All binary delivery is authenticated, no-store, nosniff and attachment; no public object URLs.

Supported media: PNG/JPEG (verified decode, dimensions, mode, orientation and JPEG thumbnail),
nonempty PCM WAV (1–8 channels, 1–4 bytes/sample, up to 192 kHz; complete bounded frame scan),
MP4 with exactly one H.264 video and at most one AAC audio stream (bounded metadata/first-frame
probe and poster), and unencrypted PDF (strict structural metadata, <=1000 pages, no rendering).
MP4 validation is a bounded probe, not complete playback certification of every frame. Other
containers/codecs, SVG, encrypted PDFs and PDF thumbnails are unsupported and fail explicitly.
No scripts/actions in originals execute. Preview pixels are copied without original EXIF/ICC/text.
Pinned packages: Pillow 13.0.0, PyAV 16.0.1, pypdf 6.12.0; hashes in uv.lock. Parser APIs were checked
against installed source and official [Pillow](https://pillow.readthedocs.io/en/stable/reference/Image.html),
[PyAV](https://pyav.org/docs/develop/api/_globals.html) and
[pypdf](https://github.com/py-pdf/pypdf/blob/main/pypdf/_reader.py) documentation/source.

Function definitions use a closed `implementation`: `identity.v1`, `text.normalize.v1`, or
`number.add.v1`. Identity accepts matching input/output schemas; normalization requires input
`text:string`, output `result:string`; addition requires `left:number`, `right:number`, output
`result:number`. Types are flat strict string/integer/number/boolean, optional nullable. No nested
containers, imports, code, network, arbitrary configuration, side effects or ontology access.
Numbers must be finite and within JavaScript's safe portable range; booleans are distinct.
`POST /functions/{id}/runs` accepts definition_id, inputs and idempotency_key. Same actor/key/inputs
returns the same job; changed input/version conflicts. Status/history/cancel/retry reuse execution
jobs; `GET /function-runs/{job_id}/result` returns bounded values only after success, and
`GET .../provenance` returns authorized immutable pins. Initial implementations never produce large
output; oversize outputs fail. No unimplemented artifact-output format is advertised.

Automation definitions pin function_id, function_definition_id and typed constant inputs. Triggers:
`{"kind":"manual"}`, `{"kind":"interval","interval_seconds":60}`,
`{"kind":"daily","hour":2,"minute":30,"timezone":"UTC"}`, or
`{"kind":"action.committed","ontology_resource_id":"<ONTOLOGY_VERSION UUID>"}`.
No arbitrary cron, expressions, payload bindings or action target are supported in this initial subset.
Event sources cover committed actions for the resource's ontology across schema versions; only event
identity/timestamp are consumed, never private action payloads. Owner needs schema/action-history
permission in addition to Project rights. Pure functions cannot emit action events, preventing loops.

`PUT /automations/{id}/activation` uses definition_id and enabled; GET `/schedule` shows owner,
next_run_at and fixed last_error. POST `/trigger` uses idempotency_key for manual definitions.
GET `/runs` returns receipts, whose job_id uses existing execution status/cancel/retry and function
result/provenance APIs. Only the bound owner activates/triggers; Project ownership alone does not
borrow an owner's identity. Owner identity/membership, set/target access and enabled version are
rechecked at dispatch and publication. Revocation/archive/disable stops future publication, retains
committed history, and never promises rollback. No bearer tokens are stored for scheduled work.

Run the existing `uv run python scripts/run_execution_worker.py` controller against an explicitly
migrated database. It ticks schedules then claims shared execution_jobs; API replicas have no timers.
Dispatch, unique receipt and queued invocation are one PostgreSQL transaction using normal lock order.
Controller crash rolls back all three or leaves all three committed. Row/tenant locks fence competing
controllers, while execution uses leases and random tokens. Scheduling uses database UTC instants:
backward jumps wait; forward jumps coalesce to one occurrence then advance beyond database now.
Daily UTC schedules have no DST gap/overlap; non-UTC zones are rejected. Event receipts are checked
by identity without advancing a commit-order-sensitive cursor, so delayed commits cannot be skipped.
Scans rotate by checked_at across bounded candidate pages. Existing webhook delivery state is untouched.
At-least-once process execution is allowed; idempotency deduplicates logical jobs/results. Retries are
bounded pure-function retries only. No external side effects or exactly-once cross-system claims.

Activation changes also rotate a durable activation UUID. Jobs from an earlier activation cannot
publish after disable/re-enable, and a stale controller denial cannot disable a newer activation.
The MP4 parser explicitly disables external tracks/absolute references and restricts protocols,
following the official [FFmpeg demuxer options](https://www.ffmpeg.org/ffmpeg-formats.html#mov_002fmp4_002f3gp)
and [protocol allowlist](https://www.ffmpeg.org/ffmpeg-protocols.html#Protocol-Options).
