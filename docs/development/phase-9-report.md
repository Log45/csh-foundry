# Phase 9 report — governed ontology branching and Python/TypeScript SDKs

PHASE: **9 only**, 2026-10-30, America/New_York.
Base revision: `2aac02783bb71b1b71a4fe1463e7e2aa646a1440`; initially clean checkout.
STATUS: Implementation delivered; final validation evidence is recorded below.
Changes remain uncommitted. No external deployment, package publication, operational-data branching,
live Microsoft/Google SSO or Phase 10 implementation was performed.

## Implementation summary

Persistent tenant-owned branches pin immutable published canonical bases. Branch heads are independent
development drafts with mandatory revision preconditions and immutable predecessor snapshots. The
existing canonical Pydantic models, content hashes, security transactions and ontology locks govern
creation, reads, edits, deterministic comparisons, previews, explicit conflict resolutions, atomic
merge execution, history and abandonment. Merged results can explicitly become ordinary registry
drafts; existing migration approval/publication/activation remains separate and unchanged.

Published schemas compile into independent async Python/Pydantic/httpx and strict TypeScript/Fetch
packages. Both expose typed properties/create/patch/action inputs, typed field expressions, immutable
Object Sets, Boolean composition, sort/projection, cursor/offset pages, typed forward/inverse relationship
accessors, traversal, aggregates, governed CRUD/actions, preview, required action idempotency keys,
expected object revisions, structured server errors and async API bearer-token providers. No generated
package imports backend or Next internals. Current server authorization remains authoritative.

One shared compiler serves bounded authorized API artifact issuance and a reproducible local/remote
CLI. Manifests bind canonical/API/generator/language inputs, aliases and file hashes. PostgreSQL keeps
immutable artifacts with exact ZIP hashes, issuance actor/time, tenant/ontology/published-version FKs
and current schema-disclosure authorization. Existing Manager adds branch editing/graph/history,
comparison, resolved merge review/confirmation, draft handoff, SDK version/language selection,
compatibility, private manifests and downloads through the original authenticated BFF.

## Baseline review and discrepancy

Reviewed root instructions, roadmap, README, fixtures/VALIDATION.md, Phase 0–8 reports, Phase 9
preparation, decisions, canonical/schema/migration/security/frontend/API documentation and actual
registry, draft, hash, compatibility, plan, publication, activation, security, query, object identity,
action, OpenAPI and migration implementations. The checklist predates application edits.

The database initially was stopped. Started the existing local PostgreSQL service and verified
`0013_security`. Default shell Node 16 could not start Studio E2E; rerunning with installed Node 24
reproduced the browser baseline without changing application behavior. Python 3.12.0, PostgreSQL
17.6, Open Ontologies 2.1.0, RDFLib 7.1.4, pySHACL 0.30.1, OWLAPI 4.5.29 and pinned Next 16.4.3,
React 19.3.1, TypeScript 5.9.3 were retained. `uv sync --frozen` passed.

Configured baseline: **466 passed, one strict xfailed, zero skips**, 223.53s; frontend **24 passed**,
typecheck passed, browser **3 passed**. The requested 464-test baseline predates two OIDC CA-bundle
tests in the current revision; no unexpected initial code failure remained. Baseline lint/format,
strict mypy and Alembic drift passed. Evidence: `baseline-python.txt`, `baseline-e2e.txt`.

## Significant files created or modified

| Area | Files |
|---|---|
| Branch service | `services/api/src/ontology_platform/branching/{contracts,merge,service,routes}.py` and module description |
| SDK compiler/runtime | `services/api/src/ontology_platform/sdk/{generator,service,routes,__main__}.py`, `templates/runtime.{py,ts}.txt`, module description |
| Persistence/wiring | `db/models.py`, `db/governance.py`, `main.py`; no existing canonical schema/model change |
| Migrations | `services/api/migrations/versions/0014_branches.py`, `0015_sdk.py` |
| Studio | New `apps/studio/features/development.tsx`; Manager integration; regenerated actual OpenAPI and TypeScript contracts |
| Tests | New `test_branching.py`, `test_sdk.py`, independent SDK acceptance scripts; additional browser workflow |
| Timing-fixture correction | `test_security_oidc.py` calculates future `iat`/`nbf` claims at test execution, preserving rejection assertions |
| Tooling/CI | `scripts/benchmark_phase9.py`, `smoke_phase9_containers.py`; CI installs Node/npm dependencies before Python generated-package tests |
| Documentation | Branch/SDK API and usage, ADRs 0030–0031, checklist, this report, Phase 10 preparation, package README boundaries; root/Studio/API/canonical/migration references |
| Evidence | `docs/architecture/evidence/phase-9/` baseline, regression, browser, package/image/OWLAPI and performance records |

Service source paths abbreviated above are under `services/api/src/ontology_platform`.
No credentials, fixture bytes, upstream dependency pins, uv.lock, canonical ontology-schema package
or supplied AGENTS.md were changed. Existing work was not reset/discarded. Only the OIDC test's
clock-sensitive input construction was corrected; its security assertions and production verifier
were preserved. No old test was deleted or relaxed.

## Branch architecture, merge semantics and governance

`ontology_branches` stores tenant/ontology UUID identity, name/description, published base/hash,
revision/hash-qualified head, lifecycle and creator/updater/time. `ontology_branch_revisions` stores
immutable canonical snapshots, predecessor, hash, author/time/summary/provenance. `ontology_branch_merges`
references exact source/target/result revisions and records all hashes, base, resolutions, actor/time
and outcome. Composite FKs prevent cross-tenant/cross-ontology references; triggers protect immutable
history, base identity and terminal lifecycle. Names never substitute for branch identity.

Only ACTIVE branches sharing an exact immutable published base merge in this initial contract. This
is a true three-way comparison of base/target/source, not replacement or a two-way diff. ID collections
match stable IDs independently of display names or JSON object order. Existing target definition
order is preserved; new IDs append sorted. Ordered action bindings/operations remain atomic. Independent
changes combine, identical changes coalesce, and concurrent incompatible changes are explicit conflicts.
Canonical invalid combined references produce an explicit `/$schema` resolution context. Every manual
resolution is revalidated; absent and explicit null values remain distinct. Duplicate/unknown resolution
paths reject. Complexity, schema, conflict and provenance payloads are bounded.

Preview includes exact revision/hash inputs, changes, choices, diagnostics, proposed schema,
compatibility and migration/publication/activation implications. Execution recomputes under the same
ontology write/security locks, requires its exact preview hash, validates canonical identity and
rechecks mutation authority before commit. It atomically appends the target revision and merge record
and marks the source MERGED. Stale previews/heads, unresolved conflicts and late denials roll back.
Source revision history remains intact. ABANDONED branches retain snapshots and reject further edits.

Comparison applies the existing conservative compatibility classifier to affected definition slices;
SDK diagnostics reuse the same classifier for complete published versions. There is no second
compatibility or authorization engine. Branches may contain breaking development changes, but a
merged draft cannot publish until the existing approved migration-plan requirement is met. Draft
handoff uses RegistryService in a caller-owned transaction; publication and activation retain their
original separate permissions and validation. No branch/SDK operation mutates operational objects.

Phase 7 security context holds tenant security/principal locks throughout mutations. A waiting
revocation follows already-authorized transactions; no revocation can silently commit between the
protected permission snapshot and branch commit. New tests exercise late authorization denial and
rollback plus revoked roles; existing real security lock/revocation tests remain in the full suite.

## Database migrations

- **0014_branches** after 0013_security adds three branch/revision/merge tables, tenant-safe FKs,
  immutable published bases, deferred head hash FK, predecessor checks, scoped name uniqueness,
  state/base transition guards, immutable revision/merge triggers and payload checks.
- **0015_sdk** adds one immutable published-version SDK artifact table with tenant/ontology FKs,
  language checks, scoped content-hash deduplication and storage bound.

Current local revision is **0015_sdk**; Alembic drift reports no new operations. Existing operational
objects, schema snapshots/pointers, imports and security history are preserved. Clean upgrades,
existing-database upgrades, downgrade/re-upgrade and ownership/history constraints run against private
PostgreSQL schemas. Downgrade intentionally deletes Phase 9 artifact/branch history; it is not lossless.
During development the uncommitted predecessor check was synchronized on the local DB without
rewriting snapshots. No migration loads fixture data or grants new security permissions.

## SDK determinism, compatibility, APIs and CLI

Generated identifiers safely alias reserved words, Unicode, spaces, hyphens, leading digits and
collisions while preserving canonical IDs in requests. Ambiguous declarations/navigation names reject.
Read properties are optional for server projection/ABAC; create/patch/action models distinguish
required, omitted/defaulted and explicit-null inputs. Python preserves decimals through Decimal/string
inputs and JSON string serialization; TS uses exact decimal strings. Dates/timestamps/UUIDs retain
canonical representations, including aware timestamp checks in Python. TypeScript rejects nonfinite
numbers and unsafe integer values; full signed-64-bit values outside JS safe integers are unsupported.

Manifests use a fixed reproducible epoch; issuance timestamp/owner is separate DB metadata.
`artifact_content_hash` hashes the sorted source-file digest map excluding the manifest, and the DB
`content_hash` hashes the complete deterministic ZIP. Sorted paths, fixed timestamps and permissions
make repeated archives identical. No self-referential hash, random source identifier or token is used.
Compiler version is 9.0.0, with explicit canonical and actual OpenAPI contract hashes. Required HTTP
routes/methods and transport shapes are verified before emission. The source schema is included for
constraint inspection; it does not become a competing registry.

Generated clients call existing endpoints/AST and fail on schema-version mismatch. A package for an
older published version cannot select historical operational data. No automatic retries, cursor
restarts, conflict overwrites or new idempotency keys are introduced. SDKError retains structured
server status/code/body/response. Tokens come from async caller providers per request and never enter
artifacts. Browser/IdP/worker/connector credentials remain separate. Live SSO was not tested or added.

Authorized synchronous generation, metadata/list/download and compatibility APIs use schema:read.
The initial same-ontology generation concurrency is one under the existing PostgreSQL lock, with a
64 KiB input/4 MiB output bound. No queue/microservice/database is added. Downloads are deterministic
ZIP bytes in a JSON base64 envelope compatible with the existing private BFF. Current authorization
and archive hashes are rechecked at retrieval. Artifact IDs alone convey no access.

CLI `python -m ontology_platform.sdk` uses exactly the API compiler. It supports selected published
VersionView/OpenAPI exports or authenticated remote inputs, language/output selection, printed manifest,
empty-output safety and non-mutating deterministic `--check`. Local files are trusted operator exports;
remote authorization remains server-side. No production database password is embedded.

## Manufacturing and generated-package acceptance

New acceptance starts from the unchanged fixtures and **6 factories / 20 machines / 12 employees /
25 tasks = 63 objects, 70 forward links**. Two branches add an optional Machine property and an
independent Inspection type. Independent preview combines both. Subsequent conflicting names produce
an explicit conflict, resolved source selection and atomic merge. Source becomes MERGED with all
three prior revisions retained; provenance identifies all hashes/revisions/choices. Active remains
1.0.0 through merge and handoff. The ordinary 1.1.0 draft validates and publishes; only an explicit
activation updates the pointer. Every operational identity and all 70 forward edges are preserved.
A separate breaking-merge test proves publication remains blocked pending existing migration approval.

From the published 1.1.0 schema, both SDKs regenerate identically. Python builds/installs into a fresh
isolated virtual environment; import and strict mypy checks run. TypeScript builds separately using
the pinned standalone compiler in a temporary package directory, with no Next imports. Negative
static tests reject nonexistent properties, invalid operators and decimal floats in both languages.
The local/remote transport contracts are also exercised by CLI deterministic checks and all canonical
type-mapping serialization tests (including aliases, dates, timestamps, UUID, JSON, arrays and decimal).

Both real packages call an actual loopback Uvicorn/FastAPI server backed by PostgreSQL with signed
RFC 9068 API bearer tokens and the existing verifier. Controlled IdP discovery/JWKS transport is used;
JWT signature verification, platform membership/RBAC and actual HTTP/SQL remain real. They query
machines, filter `operationalStatus` and `temperatureCelsius`, page cursors without overlap, retrieve
MCH-005, traverse to Factory, preview/execute UpdateMachineStatus, replay the exact caller key,
reject stale optimistic revisions, reject invalid bearer tokens and reject foreign tenants. Revoked
business-action authority fails through **both generated packages**. Artifact generation rejects drafts,
foreign tenant retrieval and revoked schema authority; artifact source contains no browser credentials.

Browser E2E uses the existing local TLS OIDC test provider plus actual signed tokens, FastAPI and
PostgreSQL. The added workflow edits both branches, detects/resolves conflict, confirms merge,
inspects provenance, generates both SDK languages and downloads an authorized Python ZIP. Existing
three browser/security/manufacturing workflows remain intact. No live external identity provider or
production-image full signed browser session is claimed.

## Performance and resource limits

Measurements are single local developer samples, local authorizer, temporary migrated PostgreSQL
schema; they are not production load tests or percentiles. `scripts/benchmark_phase9.py` uses the
manufacturing schema with its published action declarations and a synthetic 36,192-byte schema.

| Measurement | Observed |
|---|---:|
| Branch create / revision persistence | 12.537 / 8.861 ms |
| Comparison / conflict detection | 9.124 / 11.300 ms |
| Merge preview / execution | 11.709 / 24.187 ms |
| Synthetic larger schema merge | 2.680 ms |
| Python / TypeScript generation | 18.785 / 18.060 ms |
| Python wheel / TypeScript build | 298.538 / 772.528 ms |
| Python / TypeScript source bytes | 49,442 / 28,606 |
| Python / TypeScript ZIP bytes | 9,433 / 7,764 |
| Larger schema Python generation | 33.610 ms |
| Python tracemalloc peak | 556,963 bytes |

Deterministic source/ZIP regeneration passed for both. Tracemalloc covers measured Python allocations,
not total RSS, native allocations or compiler subprocess memory. Hard process isolation and aggregate
production admission/quotas are not claimed. Bounds: HTTP POST/schema 64 KiB, branches/artifacts 100
per ontology, history/list page 100 and offset 10,000, merge depth/nodes 32/20,000, conflicts/resolutions
128, merge provenance 64 KiB, generated source 4 MiB, escaped file storage 8 MiB, SDK response 5 MiB.
History is indefinite; there is no automatic garbage collector or public artifact distribution.

## Regression and fixture validation

Final configured regression: **498 passed, one strict xfailed, zero skips**, 499 collected,
**271.96 seconds**. This retains 466 baseline passes and adds **32 Phase 9 cases** (16 branch/merge
and 16 SDK/compiler/package cases). Ruff lint/format and strict mypy (91 application/schema modules)
passed. Frontend **24 tests**, format/type checking and production build passed; browser **4 tests**
passed in 31.6 seconds. Actual generated packages compiled and ran through the full HTTP workflow.

| Check | Result | Executed evidence / limits |
|---|---|---|
| Phase 8 baseline | PASS | 466 passed, 1 strict xfailed, no skips; baseline logs and Node correction above |
| Complete final Python regression | PASS | `validation-final.txt`: 498 passed, 1 preserved strict xfailed, zero skips |
| New branching / merge / SDK tests | PASS | 32 cases included in final suite; PostgreSQL, package install/build/HTTP, CLI and static negative cases |
| Ruff lint / formatting / strict mypy | PASS | Final runner preamble; 154 formatted Python files, 91 typed source modules |
| Alembic clean/existing upgrade, downgrade/re-upgrade and drift | PASS | Full private-schema regression; local `0015_sdk`, no new upgrade operations |
| Tenant-safe FKs and immutable history | PASS | Direct PostgreSQL rejection cases and service/API tenant isolation |
| Revision and merge concurrency / stale preview / late denial rollback | PASS | Concurrent writers/merges and unchanged target/source/provenance on failure |
| Migration/publication/activation separation | PASS | New breaking-merge guard plus retained full lifecycle and data validation tests |
| Manufacturing counts and stable identities | PASS | 63 objects, 70 forward links; explicit 1.1.0 publication/activation retains identities |
| Generated Python package | PASS | Fresh isolated install, import, strict mypy, serialization, signed HTTP query/traverse/action/conflicts/denials |
| Generated TypeScript package | PASS | Separate strict compiler build/import and actual signed HTTP workflow; no Next dependency |
| Deterministic source, manifest and ZIP | PASS | Both languages regenerated byte-identically; CLI --check and modified-file rejection |
| Static rejection of invalid fields/operators/decimal floats | PASS | Three intended checker errors per language |
| SDK generation/retrieval authorization | PASS | Published-only issuance, revoked access, tenant isolation, BFF private downloads |
| CLI local export generation/check | PASS | Both languages, selected status/hash/identity, serialization matrix |
| CLI authenticated remote workflow | NOT RUN | Implemented/documented; remote CLI invocation itself not exercised separately |
| Frontend format/typecheck/tests/build | PASS | `frontend-checks.txt`: 24 tests and production Next build |
| Browser branch/merge and SDK acceptance | PASS | `browser-final.txt`: 4 total Chromium tests; local TLS OIDC/real API/PG |
| Docker API / Studio builds | PASS | `api-docker-build.txt`, `studio-docker-build.txt` |
| Final-image smoke / packaged compiler templates | PASS | `container-smoke.txt`: readiness, deterministic generator, private-route and startup denials, Studio security headers/non-root |
| Turtle parse / CSV identity/count/FK / RDF consistency | PASS | Retained fixture tests in complete configured regression; integrity hashes |
| Raw unchanged pySHACL conformance | FAIL | Preserved strict expected simple/xsd:string mismatch; never counted as raw conformance PASS |
| Normalized SHACL and nine negative fixture cases | PASS | Retained fixture validation executed |
| Open Ontologies SHACL / extended-profile inference / semantic jobs | PASS | Actual pinned 2.1.0 engine in complete configured regression |
| Equivalent base owl-rl CriticalMachine inference | NOT SUPPORTED | Preserved executed profile comparison; fixture unchanged |
| Independent proof certificate checking | NOT RUN | Certificates remain explicitly unverified |
| OWLAPI / Protégé-compatible file round trip | PASS | `protege.txt`: 4.5.29, known added xsd:date declaration, no lost axioms |
| Protégé GUI / deployed WebProtégé | NOT RUN | Optional GUI/deployment not invoked |
| API queries/actions/reconciliation/ingestion/security/import regressions | PASS | All retained real PostgreSQL suites executed in final regression |
| Final-image full signed browser/package workflow | NOT RUN | Full signed workflows run against host Uvicorn/PG; images receive separate smoke checks |
| Live Microsoft/Google/Workspace SSO | NOT RUN | Phase 10 only |
| Production deployment/load/DR testing | NOT RUN | No external deployment or production test scope |
| Remote GitHub CI | NOT RUN | Workflow updated; equivalent commands executed locally, no push requested |
| Fixture/upstream lock/instruction preservation and whitespace | PASS | `integrity.json`, clean targeted input diffs and `git diff --check` |

Evidence lives in `docs/architecture/evidence/phase-9/`. An earlier run passed 495 tests before the
final three cases were added. Intermediate runs caught enum-model generation and definition-order
issues, which were corrected and covered by independent installed-package tests. Browser testing
caught stale branch editor content during branch switching; the UI now binds visible heads to the
selected branch and guards unsaved navigation. These partial runs are not claimed as final success.

One full run reported two OIDC future-claim failures because their timestamps were constructed at
collection rather than execution. Only test input timing was corrected; all rejection assertions
and production verification remain unchanged. The final targeted OIDC suite passed 40 tests and the
complete final suite includes them. Another run observed an existing ingestion job still RUNNING
under a lease; the focused test passed in 12.56s, and the subsequent complete run passed without
changing ingestion behavior, deadlines or assertions. The intermediate failure logs are retained.
No unexpected failure remains in the final run. Existing Starlette/httpx and Java upstream warnings
remain. Local smoke containers and six task-owned residual test schemas were cleaned up. Eleven older
or unattributed test schemas were preserved instead of deleting unverified prior work; cleanup.json
records the distinction. PostgreSQL stays running.

## Known limitations and Phase 10 readiness

1. Branch merge requires the same explicitly pinned published base; no arbitrary merge-base DAG,
   rebase, operational-data branch, real-time collaboration, reopening or irreversible delete API.
2. The Manager uses canonical JSON for branch edits/manual values and a saved-head graph; graph diff
   highlighting is not implemented. UI exposes base/active comparisons and newest 50 history rows;
   bounded APIs expose other branch/version/revision comparisons and deeper history pagination.
3. SDKs target the active published schema, not historical operational snapshots. Read properties can
   be absent due to authorization. Backend constraints/security stay authoritative. TS safe-integer
   limits and Python typed serialization are documented; no lossless JS signed-64-bit promise exists.
4. SDK compilation is bounded synchronous work under coarse ontology locking. No production
   admission, global fairness, registry distribution/signing, aggregate storage quota or retention jobs.
5. Database owners remain trusted and can bypass triggers; this is application audit/history, not
   owner-proof archival or RLS. Current schema readers share artifacts within their authorized tenant.
6. Existing raw pySHACL mismatch, base owl-rl fixture limitation, unverified certificates, activation
   bounds and single-process browser sessions remain. No live Microsoft/Google or production deployment.
7. Container smoke validates runtime packaging, readiness and fail-closed boundaries; authenticated
   full browser/package acceptance runs on host FastAPI/PostgreSQL, not inside the final Docker images.

Phase 9 provides the bounded developer capabilities needed to review Phase 10. The recommended next
phase is separately approved production hardening and live SSO evaluation in `phase-10.md`. No Phase 10
implementation was started; stop here after final validation.
