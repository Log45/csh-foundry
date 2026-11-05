# Phase 16 — React SDK and developer experience

Date: 2026-11-04. Base revision: `6a589f4594de157e243dcacf03892844cc3ddc25`; changes uncommitted.
Scope: explicitly authorized milestone F SDK/starter/workspace design only. **PASS — Phase 16 implementation and local development acceptance complete.**
Production remains **BLOCKED / NOT PRODUCTION-CERTIFIED** under Section 23B; Phase 17 is not implemented.

## Architecture and functionality

[ADR 0041](../decisions/0041-react-sdk.md) preceded substantial implementation. PostgreSQL, canonical
services, governance and immutable definition/version semantics remain server authority. No operational
backend source/schema, authentication system, mutation service, ArtifactStore or scheduler was added.
The roadmap's application-registration and Action Builder additions are outside the explicit prompt's
SDK boundary; this difference is recorded in the ADR and Phase 16 roadmap authorization addendum.

Two independently buildable ESM packages use the existing @foundry naming convention:

- `packages/typescript-sdk` / **@foundry/sdk 0.16.0**: browser Fetch transport, generated API models,
  typed capability wrappers, session integration, errors, bounded JSON and streaming source download.
- `packages/react-sdk` / **@foundry/react 0.16.0**: provider-owned TanStack Query v5 cache, generated
  query/mutation hooks, bounded durable execution observation and small execution status primitive.

The Phase 9 ontology-specific archive generator remains separate and unchanged. Studio had no existing
cache dependency; TanStack Query was selected after checking official reference documentation and the
installed types/source. React is a peer dependency; the core package imports no React or server modules.
Root npm workspaces/lockfile manage the two packages and example, leaving Studio's lockfile independent.

Public API inventory: [core README](../../packages/typescript-sdk/README.md) and generated
[endpoints](../../packages/typescript-sdk/src/endpoints.ts); [React README](../../packages/react-sdk/README.md)
and [hooks](../../packages/react-sdk/src/hooks.ts). Core covers ontology/type/version schema; canonical
object queries, cursor/filter/projection/links, create/update and revision conflicts; actions, preview,
idempotency, history and audit; Project/resource discovery; dataset metadata/version/schema/preview/
validation/lineage/source streams; pipeline and mapping immutable definitions, validation, publication,
runs/history; execution status/cancel/retry; sample mapping preview and authorized provenance.
Datasets/pipelines/mappings are discovered through existing Project resource pages, as the API has no
separate family listing endpoint. Full-source mapping validation is start with mode=full_validation.

## Generated contract strategy

`scripts/export_openapi.py` exports the actual FastAPI app into the existing Studio OpenAPI file.
`npm run generate` uses pinned openapi-typescript plus a reviewed public endpoint manifest in
`scripts/generate_platform_sdk.py`. The manifest selects capabilities, not model definitions; generated
wrappers derive path/query/body and successful response types from actual OpenAPI operation IDs.
Generated React hooks share those core types. No public arbitrary-path request interface exists.
`npm run check:generated` verifies wrapper/hook bytes and complete generated schema bytes deterministically.
Nullable/optional and request/response distinctions remain generated. Loosely specified backend
responses remain unknown/dictionary types, requiring consumer narrowing; no stronger response schema
was invented to make TypeScript convenient. API version v1 is explicit; no unsupported server handshake
or semantic-engine endpoint was invented. Export leaves existing Studio contracts unchanged.

## Authentication, tenant handling and errors

The SDK uses the current same-origin BFF JSON envelope, HttpOnly session, CSRF and expected_tenant.
Service credentials and verified access tokens remain inside existing server routes. Same-origin
relative API/BFF paths are validated against traversal/credentials/query/fragment/cross-origin forms.
Configuration is captured immutably. No localStorage, long-lived token option or browser Authorization
header is provided. `createSessionClient` uses existing login/session/tenant/logout endpoints; the
identity members reuse generated API types, while the BFF envelope reflects the existing route source.

A client binds tenant, principal, opaque login generation, optional Project and API/BFF context.
Call invalidate before context/logout changes, cancel outstanding reads and discard private host UI;
create a new client after session refresh. 401/403 invalidate the client and abort requests; 401 invokes
session-expiration handling. Errors preserve status even when a proxy supplies malformed JSON.
The example observes the session expiry deadline and restores sign-in. Server permissions remain
cumulative, including read-only sharing restrictions and current worker admission/publication checks.

FoundryError categories: authentication, permission, not_found, validation, conflict, admission,
execution, network, timeout, unsupported and cancelled. Only sanitized bounded machine codes are
retained, never arbitrary response text/stacks/source values. Explicit safe reads retry at most twice
(default once) within the original deadline; 401/403/validation/conflict/cancellation do not retry.
Mutations never auto-retry; action idempotency stays in its generated body and explicit durable retry
uses the existing endpoint. Execution HTTP success is distinguished from durable job failure.

## React contracts and resource behavior

Each provider owns a separate QueryClient, remounted on SDK client identity replacement. Keys contain
API, BFF, tenant, principal, session generation, Project, unique client ID, operation and full input.
Even accidental generation reuse across client instances cannot reuse a private cache. No singleton,
persistent cache or cross-user SSR dehydration exists. Strict Mode cleanup cancels reads and clears
provider cache without invalidating the caller's reusable client. Query signals cancel Fetch on unmount.
401/403 synchronously disable queries, clear private data and expose the invalidation error. Permanent
query failures hide prior data, including private-resource 404; job polling stops on non-retryable
failures without invalidating unrelated capabilities.

Hooks expose loading/data/error/refetch and mutation pending/success/error states. Pagination is explicit
in generated input; there is no infinite eager scan. Durable monitoring also invalidates observed domain reads on changed state/metrics/output identity,
excluding execution queries to avoid monitor loops. Mutation settlement cancels stale reads and
invalidates active queries in that provider, including ambiguous error outcomes that could follow
committed work. No optimistic mutation, automatic rollback or success-before-confirmation behavior.
The conservative invalidation scope favors correctness over more complex dependency tracking.

Metadata/previews use 64 KiB request and counted 5 MiB response bounds. GET pagination is 1–100 and
offset 0–10000; object query bodies retain server limits up to 200 and opaque cursor semantics.
Previews fetch cached bounded rows. Source download returns the existing binary BFF response stream;
caller owns piping/cancellation and must not collect a 1 GiB source in browser memory. No upload helper,
second transfer protocol, full-source browser JSON parse or large-dataset render guarantee is added.

Execution polling: default two seconds, 120 polls, ten minutes; configurable independently bounded
interval/count/duration. It stops when disabled, terminal, unknown future state or authorization denial;
background-tab polling pauses. Transient transport failures can retry within the remaining budget;
manual refetch remains available afterward. No backend scheduling or event infrastructure was added.

**Materialization retains visible transactional batch publication.** RUNNING, FAILED or CANCELLED can
already have committed canonical objects/links/provenance. Metrics and state pass through unchanged;
executionState and ExecutionStatus explicitly flag possible partial commits. No atomic activation,
hiding of incomplete-run objects, rollback or cleanup is implied. An integration test observes a real
cancelled run with 100 committed objects and provenance records through the built SDK.

## Example, packaging and future workspace design

[React/TypeScript example](../../apps/sdk-example/README.md) uses existing Next.js and imports Studio's
actual BFF/auth server route handlers. It demonstrates SDK initialization, OIDC sessions, tenant change,
object query/cursor pagination, dataset schema/preview, pipeline monitoring, mapping metadata,
materialization state/metrics, typed error display and session-expiration UI reset. Browser tests seed
resources through governed APIs and exercise live workers and private MinIO.

Builds emit ESM/declarations with exports and no server-only package dependencies. The packed-consumer
smoke installs actual tarballs into a temporary independent consumer, tests ESM imports/declarations/
React peer resolution and negative types for missing idempotency and forbidden arbitrary requests.
READMEs, version metadata and changelog/release guidance are included. No npm publication pipeline is
added. The repository has no explicit license file; a future public release must settle licensing.

[Code Workspace contract](code-workspace-sdk-contract.md) specifies template identity, dependencies,
endpoint injection, auth, tenant/Project context, local/build/preview commands, lifecycle assumptions,
future Git/container integration and deployment boundaries. The template currently needs this monorepo
for shared BFF source; standalone extraction needs a separately reviewed BFF distribution/mount.
No repository provisioning, container/IDE/terminal/workspace resources, volumes, ingress or hosting.

## Validation evidence

Reproducible final entry point: `PATH=<supported-node-bin>:$PATH caffeinate -dimsu uv run python scripts/validate_phase16.py`.
Caffeinate is a process-scoped macOS keep-awake assertion, not a change to service timeouts, system
clocks or shared database configuration. Other platforms can omit it. The runner refuses overwriting
existing final evidence. [Machine-readable commands/results](evidence/phase-16/results.json),
[run log](evidence/phase-16/validation-run.txt), and per-command logs record actual executions.

| Final command/check | Result | Evidence |
| --- | --- | --- |
| Ruff check / formatting / mypy | PASS | python-quality.txt, python-format.txt, mypy.txt |
| Actual OpenAPI export / generated SDK drift | PASS | openapi-export.txt, generated.txt |
| SDK/example build / typecheck / formatting | PASS | sdk-build.txt, sdk-typecheck.txt, sdk-format.txt |
| Core/React automated tests | PASS | 61 tests; sdk-tests.txt |
| Independent packed-package consumer | PASS | sdk-consumer.txt |
| Studio tests / typecheck / formatting / build | PASS | 45 tests; studio-tests.txt and associated checks |
| Corrected SDK + real governed PostgreSQL/MinIO integration | PASS | Three tests; sdk-integration-final-targeted.txt |
| Final complete PostgreSQL/MinIO/semantic/browser regression | PASS | full-platform-browser.txt; 794 passed, one strict xfail, zero skips; 931.79 seconds; 11 durable browser workflows passed in 2.1 minutes |
| Final example live OIDC/data/execution browser regression | PASS | example-browser.txt; one workflow passed in 10.0 seconds |

All 16 final validation commands passed after the last source/test changes. The Python suite collected
795 cases: 794 passed, one preserved strict expected failure, zero skips. Studio retained 45 passing
unit tests; the SDK has 61 passing tests. The final durable browser suite includes exact 1 GiB upload,
CSRF denial, tenant/session loss, private SDK download, replica restart/logout, datasets, pipeline
lineage and mapping materialization. The example uses actual OIDC, governed data/worker APIs and a
controlled 401 response to verify expiration UI handling. Earlier failed/interrupted invocations are
retained separately and are not combined with these final results.

## Migrations, security and preservation

No migration was created or changed. Actual code head remains **0022_materialization**. The shared
developer database remains **0017_capacity**, verified with a read-only query; it was not upgraded.
[Preservation evidence](evidence/phase-16/preservation.txt) also checks unchanged canonical fixtures and
historical migrations and inspects built browser chunks for server credential/configuration symbols.
This targeted bundle inspection is not production security certification. Real integration runners
create/remove only private random schemas, Compose projects and volumes; shared MinIO is not reset.

Earlier implementation/test failures remain distinct from final results: share fixture omitted required
enabled/revision; the test HTTP authorizer initially rejected test identities; JSON-line test adapter
needed explicit readline cleanup; an action fixture import needed retention by Ruff; browser tenant
label association was corrected; unknown object types correctly return validation, not not_found.
The new npm workspace changed Next.js standalone tracing layout; pinning Studio outputFileTracingRoot
preserves its existing launcher/Docker entry point. The first complete-regression attempt was deliberately
interrupted after this packaging finding and is retained under evidence/phase-16/attempt-1; it is not
passing acceptance evidence. A second attempt was deliberately interrupted for a narrow timeout-category correction during read
retry backoff, with a new regression assertion; evidence is retained under attempt-2. The next full run exposed a new SDK test that incorrectly assumed source-order batch publication.
The test now compares all 100 visible canonical identities against committed provenance and fetches
an identity from that provenance; the corrected real SDK suite passed all three tests. The failed full
run is retained under attempt-3, and the complete regression was restarted after this test change. A fourth run was deliberately interrupted for a cached-running-job monitor
remount correction and regression test (attempt-4). All 58 core/React tests then passed. A fifth attempt was deliberately interrupted for the final
nullable-query serialization audit and non-enumerating resource-denial handling (attempt-5). Optional
nullable query values now omit the URL parameter; body nulls remain explicit. Permanent query errors
hide previous data, and non-retryable job status failures (including private-resource 404) stop polling.
The final complete regression starts after these last source/test changes. Initial unit wall-clock waits encountered host scheduling gaps; some elapsed polling assertions now use virtual
timers and retain their stop-count assertions. No backend policy, canonical fixture or existing test
assertion/timeout was weakened. Prior phase evidence remains unchanged.

## Limitations and next milestone prerequisites

Same-origin approved BFF contract only; direct cross-origin/browser bearer access is not supported.
Server Fetch use requires a trusted BFF adapter. Some backend dynamic responses have weak OpenAPI
types. Discovery filters explicit resource pages; short authorized pages do not prove end-of-history.
The starter is deliberately small, with explicit UUIDs and no full design system/app builder.
No SDK upload implementation, persisted/offline cache, SSR private hydration, production capacity,
Linux 1 GiB cgroup certification, live external SSO/S3 certification or new ontology authoring behavior.
Existing raw SHACL/base-reasoner limitations and Section 23B blockers remain. The new full Python
SDK/API tests require supported Node and built SDK packages; use validate_phase16.py for their complete
setup/check sequence. Chromium/React 19.3.1 were locally tested; other browser/React peer-version
combinations were not separately exercised. Modern Fetch, AbortSignal.any/timeout, ReadableStream,
TextEncoder and crypto.randomUUID are required. JavaScript numeric precision follows the existing
JSON/TypeScript contract; canonical identities and string-encoded decimal contracts should remain
strings. BigInt and nonfinite request values are rejected rather than implicitly coerced.

Exact changed-file inventory: [changed-files.txt](evidence/phase-16/changed-files.txt).
Recommended next milestone: separately scope and approve Section 23A milestone G (Media Sets and
functions/automations), after reviewing this SDK/BFF/template contract. Application registration, Action Builder expansion and future workspace packaging need
explicit scope decisions; this report does not authorize or implement Phase 17.

## fixtures/VALIDATION.md

The guide was read during reconnaissance and consulted again before completion. Results below refer
to this phase's executions, not inherited successful runs from earlier reports.

| Check | Result | Evidence / reason |
| --- | --- | --- |
| Turtle parsing | PASS | Final test_fixtures.py in full-platform-browser.txt |
| CSV counts/keys/FKs and RDF/CSV identity consistency | PASS | Final test_fixtures.py |
| Normalized SHACL and nine negative mutations | PASS | Final test_fixtures.py |
| Raw pySHACL simple/xsd:string compatibility | NOT SUPPORTED | Preserved strict expected-failure contract, executed in final fixture suite |
| Supported Open Ontologies SHACL / owl-rl-ext reasoning | PASS | Final pinned-engine/compiler/semantic suites in full-platform-browser.txt |
| Base owl-rl exact fixture axiom | NOT SUPPORTED | Existing pinned-profile limitation remains; fixture unchanged |
| PostgreSQL / FastAPI object queries / actions / reconciliation | PASS | Final complete real-database suite, including three built-SDK integration tests |
| Polars ingestion | PASS | Final ingestion/connector/recovery suites |
| Authorization / tenant isolation | PASS | Final security/identity/workflow suites; 11 durable browser workflows; SDK context/cache/denial tests |
| Supported Protégé import/export | PASS | Final ontology-import/interchange suite and durable browser authoring workflow |
| Manual Protégé GUI inspection | NOT RUN | No new authoring constructs or desktop authoring session in this client-library phase |
| Linux 1 GiB cgroup / external SSO/S3 / production target certification | NOT RUN | Separate environment and Section 23B approval; no production certification requested |
| Standalone TypeScript lint | NOT SUPPORTED | No standalone lint script; TypeScript/Prettier/build checks executed |

## Acceptance matrix

All 28 Phase 16 local development acceptance criteria passed on the executed evidence below.
The explicitly unexecuted/out-of-scope environments and unsupported historical semantic cases above
remain separate; this is not production certification.

| # | Criterion | Result | Evidence |
| --- | --- | --- | --- |
| 1 | Framework-independent TypeScript SDK | PASS | sdk-build.txt; packed consumer |
| 2 | React SDK | PASS | sdk-build.txt; sdk-tests.txt |
| 3 | Actual generated contracts | PASS | openapi-export.txt; generated.txt |
| 4 | Existing authentication integration | PASS | example-browser.txt; full-platform-browser.txt; real OIDC/HttpOnly/CSRF/session workflows |
| 5 | Tenant/session isolation | PASS | sdk-tests.txt; sdk-integration-final-targeted.txt |
| 6 | Ontology querying | PASS | Built SDK integration; live example browser |
| 7 | Governed object mutations | PASS | sdk-integration-final-targeted.txt; actual create/update/action/audit |
| 8 | Dataset APIs | PASS | sdk-integration-final-targeted.txt; real schema/preview/version metadata |
| 9 | Pipeline APIs | PASS | sdk-integration-final-targeted.txt; real worker success/lineage |
| 10 | Mapping/materialization APIs | PASS | sdk-integration-final-targeted.txt; real worker/provenance |
| 11 | React providers | PASS | sdk-tests.txt; Strict Mode and missing-provider checks |
| 12 | Query hooks | PASS | sdk-tests.txt; loading/error/refetch/deduplication |
| 13 | Mutation hooks | PASS | sdk-tests.txt; confirmation/conflict/no retry |
| 14 | Bounded execution polling | PASS | sdk-tests.txt; disabled/terminal/budget/revocation checks |
| 15 | Cache invalidation | PASS | sdk-tests.txt; mutations, invalidation and durable publication |
| 16 | Partial materialization visibility | PASS | Final test_platform_sdk.py in full-platform-browser.txt and sdk-integration-final-targeted.txt; all 100 visible IDs match committed provenance after cancellation |
| 17 | Typed/documented errors | PASS | sdk-tests.txt; core/React READMEs |
| 18 | Bounded pagination/memory behavior | PASS | sdk-tests.txt; stream and request/response bounds |
| 19 | Working example application | PASS | sdk-build.txt; example-browser.txt; real OIDC, objects, dataset preview, workers, metrics and expiry handling |
| 20 | Reproducible package builds | PASS | sdk-build.txt; pinned root lockfile |
| 21 | Packed consumer smoke | PASS | sdk-consumer.txt; independent ESM/types/peer/negative types |
| 22 | Future workspace contract only | PASS | code-workspace-sdk-contract.md; scope review |
| 23 | Existing security controls intact | PASS | Final full security/browser suite; CSRF, tenant/session, revocation and read-only sharing denial tests |
| 24 | Existing regressions | PASS | Final 794 Python passes, one strict xfail, zero skips; 45 Studio tests; 11 durable browser workflows |
| 25 | Synchronized generated contracts | PASS | generated.txt; unchanged Studio contracts |
| 26 | Documentation and ADR | PASS | ADR 0041; READMEs; design contract; this report |
| 27 | No later-phase infrastructure | PASS | Changed-file and scope review |
| 28 | Production remains blocked | PASS | Section 23B preserved; no deployment/publication |
