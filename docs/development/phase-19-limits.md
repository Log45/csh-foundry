# Phase 19 application limits

Format v1 rejects unknown fields and unsupported widget kinds. No source code, HTML interpreter,
CSS interpreter, dynamic imports, SQL or recursive event propagation exists.

| Boundary | Limit |
| --- | --- |
| Raw POST/PUT body | 64 KiB, using existing payload middleware before FastAPI parsing |
| Input and expanded document / draft | 60,000 UTF-8 JSON bytes |
| SQL draft/publication document guard | 128 KiB (expanded defaults and JSONB whitespace) |
| Raw JSON nesting | 24 levels |
| Pages | 16 |
| Widgets per page / total | 64 / 256 |
| Layout parent depth | 8 |
| States / dependencies / sources / actions | 64 / 16 / 16 / 16 |
| Interactions / diagnostics | 128 / 128 |
| Dynamic source filters | 16 |
| Action parameters | 32 |
| Text / labels | 4,000 / 200 characters |
| Select options / projected columns | 100 / 32 |
| Runtime query page | 100 rows; canonical query service retains stricter policy bounds |
| Runtime concurrent loads | 4, active page only; cancelled on state/page/client changes |
| Query filter nesting / nodes | Existing canonical limits: 8 / 128 |
| Publication budget | 5-second diminishing SQL deadline after governance lock acquisition |
| Action budget | Existing canonical 3-second diminishing deadline |
| Retained publications | 1,000 per application; no automatic deletion |
| History/resource discovery page | Existing 1–100 rows, offsets at most 10,000 |
| SDK request/response | Existing 64 KiB / 5 MiB |

No automatic polling, full collection downloads, persisted browser caches, or source assets are added.
Source results replace prior pages rather than accumulating. Input event updates are one-step and
never re-emit events, so propagation cycles cannot execute. Layout cycles reject publication.
Queries are deduplicated by source ID within the active page. Action refresh is conservative across
all active sources. No browser cancellation claim implies rollback of already committed actions.
The publication execution deadline begins after acquiring the existing governance lock; it is not a production wall-clock SLA.
