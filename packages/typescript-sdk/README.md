# @foundry/sdk — platform TypeScript client

Phase 16 ESM package, version 0.16.0. Framework independent, browser Fetch, no global client.
The Phase 9 ontology-specific archive generator remains available separately through
[SDK generation](../../docs/api/branching-sdk.md); this package consumes the platform API.

```ts
import { createFoundryClient, createSessionClient } from '@foundry/sdk';
const sessions = createSessionClient();
const session = await sessions.session(); // Existing HttpOnly BFF session
// Select an authorized tenant through sessions.selectTenant(tenantId, session.csrf).
// Derive principalId from the current session.me principal after tenant selection.
const foundry = createFoundryClient({
  baseUrl: '/api/v1', bffUrl: '/bff', tenantId, principalId,
  sessionKey: crypto.randomUUID(), auth: { csrf: session.csrf },
  onSessionExpired: () => showSignIn(),
});
const page = await foundry.objects.query({
  path: { ontology_id: 'manufacturing', type_id: 'Machine' },
  body: { object_type: 'Machine', limit: 50, pagination: 'cursor' },
}, { signal: controller.signal });
// Request the next page explicitly with body.cursor = page.next_cursor.
```

All operations accept generated `{path, query?, body?}` contracts and optional `{signal}`.
`EndpointInput['objects.query']` and `EndpointOutput['objects.query']` are public type lookups.
`components`, `operations`, and `paths` are generated directly from FastAPI. Do not edit schema.ts.
The wrapper return type is unknown where the server OpenAPI does not specify a response shape
(e.g. parts of provenance/preview); narrow those values before use. Do not infer stronger guarantees.

## Public operations

- `ontologies`: list, get, objectTypes, version (includes property/link schema and schema version).
- `objects`: query, get (canonical object_id query parameter), links, create, update (expected_version).
- `actions`: preview, execute (required body.idempotency_key), history, execution, audit.
- `projects`: list, resources. Discover DATASET, PIPELINE, MAPPING through the existing resource
  listing; filter resource_type on each explicit bounded page. Shared resources remain server filtered.
- `datasets`: get, versions, version (validation status/result), schema, preview, lineage,
  materializations, download (ReadableStream, caller owns cancellation/consumption).
- `pipelines`: get, validate, publish, definitions, definition, start, history.
- `mappings`: get, validate, publish, definitions, definition, preview, start, history,
  provenance, objectSources, linkSources. Full-source validation uses start with mode=full_validation.
- `execution`: get, cancel, retry. Output dataset/version IDs and reconciliation metrics are unchanged.
- `context`, `cacheId`, `active`, `invalidationError`, `invalidate()`, `subscribe(listener)`.
- `createSessionClient`: session (paginated tenant memberships), login, selectTenant, logout.

## Security and transport

Supported browser deployment: same-origin existing Studio BFF or approved BFF with the same envelope
and fixed binary route. The example imports existing server route implementations. API baseUrl and
bffUrl are relative paths only, without query, fragment, credentials, traversal or encoded separators.
The stock BFF accepts `/api/v1`; alternate prefixes require an approved BFF adapter. API version v1
is explicit; unsupported requested versions fail closed. There is no server-version handshake endpoint.
No arbitrary request API, Authorization header option, token storage or cross-origin cookie mode exists.
For server use, inject a trusted Fetch adapter implementing that BFF contract; direct bearer transport
is deliberately outside the browser SDK. Never inject secrets into public build environment variables.

Client configuration is captured once. Invalidate the old client **before** logout, tenant/identity/
policy changes; discard private host UI state and create a new client after fetching the new session.
Rotate sessionKey on login/identity/policy changes. CSRF is held only in memory. The session's expiry is
in milliseconds; hosts must expire their UI at that deadline (see example). 401 and 403 invalidate the
client and abort its requests; 401 invokes onSessionExpired. A 403 remains a permission error, never an
empty result. Refresh identity/session and create a new client after resolving the denial.

No SDK logging or raw response diagnostics. FoundryError includes category, sanitized machine code,
optional HTTP status and retryable classification. Categories: authentication (401), permission (403),
not_found (404), validation (400/413/415/422), conflict (409), admission (429/503), unsupported (405/501
or local version checks), network, timeout, cancelled. `executionState` in React distinguishes a failed
job from an HTTP/transport error; HTTP success alone does not mean the durable job succeeded.

Only explicitly selected reads (including object-query, sample/validation POSTs) retry, by default
once, at most twice. Network/timeouts/429/503 may retry within the original request deadline, with
250/500ms delay. Caller aborts and authorization/validation/conflict failures never retry. Mutations
never retry automatically. Preserve an action idempotency key when explicitly replaying that intent;
start-run APIs have no invented idempotency header. Durable job retry is an explicit server operation.

## Resource bounds and partial publication

JSON requests are limited to the existing BFF's 64 KiB; responses to 5 MiB using streamed counting.
GET page sizes are 1–100 with offsets 0–10000. Object-query body limits follow server validation
(up to 200), with opaque cursor semantics unchanged. Previews fetch cached 1–100 rows, never sources.
No automatic infinite pagination. AbortSignal cancels transport; cancellation cannot undo a server commit.
Default JSON timeout 45 seconds, configurable 1–120000ms. Backend authority/timeouts still apply.

Download uses the existing 1 GiB fixed binary BFF and returns its response stream without reading it.
Pipe to a browser-supported file sink; do not collect chunks, call blob() or JSON.parse giant sources.
The caller must cancel the reader or supplied signal. No upload helper or second transfer protocol.
A stream read can fail after admission; treat it as an incomplete file. No browser rendering/memory
promise for a full dataset; worker cardinality and operator budgets remain independent of source size.

Materialization publishes **visible transactional batches**. RUNNING/FAILED/CANCELLED can contain
committed objects, links and provenance. Inspect state and metrics together. No rollback, deletion,
atomic activation, successful-run filtering or optimistic hiding is performed by this SDK.

## Development and release

At repository root (Node 26.7 tested; Node >=22 with dependencies' engine constraints):
`npm ci`, `uv run python scripts/export_openapi.py`, `npm run generate`, `npm run build`,
`npm run check:generated`, `npm run typecheck`, `npm test`, `npm run test:consumer`.
Generation requires synced Python environment for export; no service/credentials are needed.
Commit the generated files and root package-lock.json. Build before local file/workspace consumption.
See [release guidance](CHANGELOG.md). No publication/deployment command is automated.

Optional nullable query parameters are omitted when null/undefined, matching the API's absent-value
semantics. Explicit JSON body nulls are preserved.

Phase 17 adds `mediaSets`, `functions` and `automations` to the existing client (0.17.0).
Definitions and invocations pin immutable UUID versions. `functions.invoke` returns a durable queued
job; use `execution.get`/cancel/retry, then `functions.result` after success. Automation receipts
reference that same job model. Only trusted pure implementations are supported; no source code.
`mediaSets.download(setId, itemId, {signal})` and `mediaSets.preview(...)` return authenticated
ReadableStreams through the fixed binary BFF, with tenant/CSRF/session protections. Consume/cancel
the stream yourself; never put media bytes in a query cache. Snapshot/item pages can be short after
authorization filtering; advance explicit offsets. Sharing a set does not grant source artifact access.

Visual application authoring/publication/runtime operations are generated under `client.applications`.
Discovery retains the Project resource registry. See [application examples](../../docs/api/applications.md).
Runtime gateways call the existing governed query/action services in the application transaction;
registration or publication never grants ontology/data/action access.

Phase 20 retains the pipeline API names and adds typed DAG v2 definitions/compilation and multi-output
ExecutionJobView results through generated OpenAPI contracts. Supply exact definition input pins and
omit output_dataset_id for v2. Use execution.get and datasets.lineage as before; each committed output
is individually authorized. Pipeline request envelopes permit 512 KiB, independently bounded by the
server's 256 KiB semantic graph budget. See docs/development/pipeline-dag-execution.md in the repository.
