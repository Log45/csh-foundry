# Phase 11 — Projects, folders, resource registry and governance

Date: 2026-11-03. Base revision: `5998a0b` (implementation changes are uncommitted). Scope: PLANS.md v1.6, Phase 11 / milestone A only.
Status: **PASS — Phase 11 development acceptance complete.** No required development check failed.
The pre-existing raw pySHACL compatibility case remains NOT SUPPORTED, independently of passing
pinned-engine SHACL checks. Final production certification is not part of this acceptance.
Production: **BLOCKED / NOT PRODUCTION-CERTIFIED** under Section 23B. No Phase 12 work.

## Architecture and compatibility

[ADR 0036](../decisions/0036-project-resource-governance.md) records the design before substantial
implementation. PostgreSQL remains authoritative; Project governance uses GovernedService,
PlatformAuthorizer, live tenant memberships and existing authorization audit. It adds no identity
provider, policy engine, database, storage service, ontology copy or execution engine.

A Project owns resource references, has explicit owner/editor/viewer members and contains logical
folders. Resource UUIDs remain stable through presentation edits. A pinned kind/ontology/version/
entity reference points at an immutable existing published canonical definition. The four registered
adapters cover object types, link types, action definitions and published ontology versions.
Unimplemented resource types are rejected rather than pretending to support datasets or execution.

Existing assets keep their identifiers and authority, with no default Project or data backfill.
An authorized editor explicitly registers references or imports a bounded catalog page. Distinct
Projects can independently reference an already-readable canonical entity without revealing private
registrations through conflicts. Explicit shares instead expose the same resource UUID read-only
in another Project. Neither approach duplicates a canonical definition or grants operational rights.

Schema publication/activation, branches/merges, ingestion, object/property policies, actions and SDK
behavior remain in their existing modules. No external ontology API contract was added or invented.
Canonical manufacturing fixtures and historical Phase 10 evidence were not edited.

## Capabilities and authorization

[API contracts](../api/projects.md) specify all routes, request bodies, pagination and lifecycle rules.
All routes are versioned `/api/v1` and use typed Pydantic contracts and authenticated tenant context.

- Projects: create/get/list/name/description/archive; creation requires create/read/manage so its
  initial owner can administer it. Reads require Project read plus explicit membership; editing and
  administration additionally require the matching platform permission and Project role.
- Membership: bounded roster and revision-checked owner/editor/viewer updates/removal. Targets must
  be enabled tenant members/principals. Owner grants require read/manage permissions; removing the
  last currently authorized owner fails. Transfer is add-owner followed by remove/demote-old-owner.
- Folders: direct-child browsing and breadcrumbs, create/get/rename/move/archive. Stable UUIDs,
  tenant/Project-qualified parents, root/sibling uniqueness, no cycles/self-parenting, depth 32,
  at most 10,000 active folders, bounded iterative validation, no cross-Project moves.
- Resources: registered canonical adapters, explicit registration and restart-safe catalog pages,
  get/list/literal search/rename/move/archive. Provenance includes creator/modifier/time, revision,
  owning Project and canonical snapshot. Archive retains underlying ontology and registry history.
- Sharing: owners grant to a Project they can access, list bounded shares, or revoke without needing
  continued target membership. Source and target must be active for shared discovery. Consumers
  cannot mutate an owner's reference. Archived source Projects/resources expose no outgoing shares.
- Authorization is cumulative: schema read remains necessary; Project access grants no object,
  restricted property, action, worker or SDK authority. Existing worker delegation blocks Project
  operations. Missing/private direct IDs return identical 404s; SQL filters precede pagination and
  lists expose no totals. Private registration existence does not leak through tenant-wide uniqueness.
- Tenant row locks serialize Project operations after existing security locks. Required expected
  revisions return 412 on conflicts; database uniqueness is a backstop. Started operations complete
  before committed revocation; there is no cross-request grant cache.
- Mutations append committed redacted events to existing authorization audit. Membership/share change
  hashes bind principal/role/target/revision; independent platform decision evidence survives rollback.

## Database

Verified initial head: `0017_capacity`; new sole head: **`0018_projects`**.
Created tables: `projects`, `project_members`, `project_folders`, `platform_resources`,
`resource_shares`. Composite keys/FKs prevent cross-tenant and cross-Project folder/resource
references. Partial unique indexes protect active names, including NULL root folders. A database
trigger checks published canonical entity existence and makes a resource's authority/owning Project
immutable. Resource-reference uniqueness is within its owning Project, including archived rows.

No historical migration was changed. No existing ontology/object/action/branch/audit rows are
rewritten. Existing tenant-administrator assignments receive an additive immutable Project permission
role; existing security role definitions are preserved. Fresh bootstraps include the new permission
catalog normally. Other users need explicit permission provisioning and Project membership.

Populated installations are forward-only. Downgrade fails when any Project exists; restore a verified
backup if rollback is necessary. An unused installation can drop the five empty new tables/function
for legacy migration tests. Immutable additive security history is retained; repeat upgrades do not
duplicate grants. Migration locks/statements are bounded to 2/30 seconds. The task applied migrations
only in disposable schemas; the shared developer database remains at its existing revision.

## Studio

The Projects tab uses the existing session/tenant-bound BFF. It supports Project creation/selection/
management, explicit membership controls, nested navigation, folder/resource rename/move/archive,
search, incoming shares, share grant/revocation and published catalog registration. Resources navigate
to the existing Ontology Manager. Lists paginate; loading/empty/error/unauthorized states are explicit.
Invalidated asynchronous responses cannot restore stale Project views after refresh/navigation.

Actions reflect both global permissions and Project role; backend checks remain authoritative.
Cookie/token/origin/CSRF protections are unchanged. New routes are included in regenerated OpenAPI
and TypeScript contracts; only the new supported query keys were added to the BFF allowlist.
Existing Manager/Studio workflows remain available without Projects.

## Validation commands and results

Executed results:

| Command/check | Result | Actual outcome |
| --- | --- | --- |
| `uv run ruff check .` | PASS | No violations |
| `uv run ruff format --check .` | PASS | 214 files formatted |
| `uv run mypy` | PASS | 103 source files, no issues |
| `uv run python scripts/validate_phase11.py` | PASS | 637 passed, one preserved strict xfail, zero skips; 324.19 seconds |
| Disposable migration upgrade and Alembic drift | PASS | No new upgrade operations detected |
| Final focused `test_projects.py` | PASS | 12 passed, including the final disabled-owner removal edge check |
| Studio `npm test` | PASS | 36 tests / seven test files |
| Studio `npm run typecheck` | PASS | tsc, no errors |
| Studio `npm run format:check` | PASS | All matched files conform |
| Studio `npm run build` | PASS | Compiled, typed and generated successfully |
| Durable Studio browser E2E | PASS | Six passed, 26.1 seconds; includes both new and existing workflows |
| `git diff --check` | PASS | No whitespace errors |
| Shared developer revision (read-only query) | PASS | Remains `0017_capacity` |
| Fixture/historical evidence diffs | PASS | No changes |

Environment: Python 3.12.0, real PostgreSQL with random isolated schemas, Node 25.9.0 from the
installed supported runtime, and the pinned local Open Ontologies 2.1.0 binary. The full regression
and final focused ownership-edge check both passed. No production deployment or shared-database
migration was used for verification.

Evidence is local under
`artifacts/phase11/` (ignored; no private TLS keys or logs committed). Reproduce with:

```sh
# On this host; otherwise supply any supported Node >=22 on PATH.
export PATH=/opt/homebrew/opt/node/bin:$PATH
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run python scripts/validate_phase11.py
cd apps/studio
npm run typecheck
npm run format:check
npm test
npm run build
```

The runner creates a unique suite schema, migrates it, checks Alembic drift, runs the full Python
suite using the pinned local Open Ontologies binary, and removes only its own schemas. Both the
SQLAlchemy URL and application schema setting select the isolated schema; it never upgrades the
shared developer schema. Individual integration tests also create their own random schemas.

Browser execution used `scripts/test_studio.py` with `STUDIO_E2E_DURABLE=true`, ports
3100/8101/3101, and absolute `STUDIO_E2E_DIRECTORY` and `OPEN_ONTOLOGIES_BIN` paths. This starts
isolated test services and schemas, including two Studio processes, and stops only those processes.

Initial validation failures were retained: the default shell Node was too old for Vitest; the first
new Project response included ORM-only fields and was corrected; the initial full-suite runner did
not set the application's isolated schema and hit the unchanged developer revision assertion before
writing data; the first browser invocation used a relative TLS path and failed login. Corrected
runs use supported Node, filtered response fields and explicit isolated schema/absolute TLS paths.
No assertions, existing skips or timeouts were relaxed. The historical raw pySHACL strict expected
failure remains a documented unsupported compatibility case, not a passing conformance check.

## Phase 11 acceptance matrix

Every supported Phase 11 development acceptance item below passed executed validation. Explicit
unsupported/out-of-scope items retain their own status; no skipped test is counted as passing.

| Acceptance criterion | Result | Evidence |
| --- | --- | --- |
| Two Projects in one tenant | PASS | Project/folder integration and sharing tests |
| Project membership and permissions | PASS | Explicit membership, viewer mutation denial, owner authority tests |
| Nested folder creation/browsing | PASS | Integration and browser Project workflow |
| Stable folder/resource IDs after rename/move | PASS | Project/folder identity test |
| Cycle/self-parent and collision rejection | PASS | Identity test; concurrent opposing moves test |
| Invalid parent/cross-Project references | PASS | Identity and direct database FK tests |
| Conflicting concurrent mutations | PASS | CAS rename, opposing moves, read/revocation concurrency |
| Non-destructive Project archive | PASS | Registry rows retained; outgoing shares unavailable |
| Stable registry identities | PASS | Resource rename/move and adapter tests |
| Existing assets discoverable in authorized Project | PASS | Catalog import and browser registration |
| Canonical authority not duplicated | PASS | Canonical version unchanged; reference trigger; action adapter |
| Explicit sharing to second Project | PASS | Same resource UUID in consumer view |
| Unshared resources private | PASS | Direct ID, Project enumeration and incoming-share tests |
| Revocation takes effect | PASS | Live share removal and transaction-order test |
| Project grants cannot bypass ontology/object/property/action policy | PASS | Schema-denial test, restrictive query/property checks and action denial |
| Existing publication/actions/branches/SDK workflows | PASS | Browser reference, branching and SDK E2E; full Python regression |
| Cross-tenant Project/resource reads | PASS | Isolated second-tenant integration |
| Cross-tenant writes/references | PASS | Share/registration rejection and composite FK enforcement |
| Private search/count/page/error disclosure denied | PASS | SQL membership/share scoping, literal search, no totals, identical missing/private errors |
| Direct IDs enforce authorization | PASS | Private/unknown and shared/revoked direct reads |
| Unauthorized membership mutation | PASS | Viewer denial, last-owner protection and revoked-owner authority |
| Background/service tenant context | PASS | Existing delegation allowlist excludes Project operations; full delegated-worker/tenant-context regression |
| CSRF/token/session/secret regression | PASS | BFF Project CSRF test plus existing browser CSRF/durable-session E2E |
| Clean migrations | PASS | Disposable-schema migrations and Alembic drift check |
| Existing database upgrade preserves records | PASS | `0017_capacity` upgrade retains object/canonical version/historical roles |
| API validation and deterministic pagination | PASS | Bounds, names, unsupported types, SQL ordering integration |
| Studio Project navigation E2E | PASS | Browser create/nested folders/catalog/Manager/archive workflow |
| Existing Studio workflows | PASS | All six browser tests; 36 frontend tests |
| Python suite | PASS | 637 passed, one preserved strict xfail, zero skips |
| Python lint/format/types | PASS | Ruff check/format and strict mypy |
| TypeScript suite/format/types/build | PASS | 36 tests, Prettier, tsc, Next build |
| Standalone TypeScript lint | NOT SUPPORTED | Repository has no configured frontend lint command; existing tsc/Prettier/build checks pass |
| Future dataset/storage/execution families | NOT SUPPORTED | Deliberately excluded; unsupported registration rejected |
| Production image/OKD/organizational certification | NOT RUN | Not authorized; Section 23B remains mandatory |

## fixtures/VALIDATION.md checks

| Check | Result | Evidence |
| --- | --- | --- |
| Turtle parsing | PASS | Full fixture tests |
| CSV identities, counts and FKs; RDF/CSV consistency | PASS | Full fixture tests |
| Raw pySHACL compatibility | NOT SUPPORTED | Preserved strict xfail; documented RDF string-term mismatch |
| Normalized SHACL and nine negative cases | PASS | Fixture/semantic tests |
| Open Ontologies SHACL | PASS | Pinned engine integration |
| OWL reasoning (`owl-rl-ext`) | PASS | CriticalMachine inference matches canonical fixture; noncritical machine excluded |
| OWL fixture inference in base `owl-rl` profile | NOT SUPPORTED | Pinned base profile lacks the fixture axiom support; fixtures preserved |
| PostgreSQL integration/FastAPI queries | PASS | Full regression |
| Actions/reconciliation | PASS | Full regression |
| Polars ingestion (63 objects/70 forward links) | PASS | Full ingestion regression |
| Authorization/tenant isolation | PASS | Phase 11 integration and full existing security regression |
| Protégé supported import/export | PASS | Full interchange regression |

## Files created or modified

Created:

- `services/api/src/ontology_platform/projects/{__init__,contracts,adapters,service,routes}.py`
- `services/api/migrations/versions/0018_projects.py`
- `services/api/tests/test_projects.py`
- `scripts/validate_phase11.py`
- `apps/studio/features/projects.tsx`, `apps/studio/tests/projects.test.tsx`
- `docs/decisions/0036-project-resource-governance.md`, `docs/api/projects.md`, this report

Modified:

- `services/api/src/ontology_platform/db/{models,governance}.py`
- `services/api/src/ontology_platform/main.py`, `security/contracts.py`
- `apps/studio/components/workspace.tsx`, `lib/server.ts`
- `apps/studio/lib/{openapi.json,api-schema.ts}` (regenerated contract)
- `apps/studio/tests/routes.test.ts`, `tests/e2e/workflow.spec.ts`
- `README.md`, `apps/studio/README.md`, `docs/api/README.md`

No dependencies, secrets, canonical fixture definitions, historical migrations, historical Phase 10
evidence, developer volumes, Keycloak configuration or organizational infrastructure were changed.

## Limitations and risks

- Coarse tenant locks favor correctness over concurrent Project throughput; no performance or
  production capacity claim is made. Pagination is bounded offset navigation, not a historical snapshot.
- Sharing requires destination membership. No implicit administrator access or emergency takeover API.
  External security administration can intentionally revoke every owner; recovery then needs an
  authorized operator. Normal Project membership changes prevent loss of the last authorized owner.
- Archive has no restore/hard delete/retention purge; archived canonical references cannot be
  re-registered within the same Project. Existing ontology access is independently authorized and
  is not revoked by archiving a Project or registry reference.
- Existing ontology assets require explicit Project registration; there is no automatic synchronization
  on publication or activation. Version-pinned references preserve history; import new published
  versions explicitly. Catalog name collisions fail atomically and can be resolved by renaming.
- Studio moves/shares/membership use explicit stable IDs; resource navigation opens the canonical
  ontology Manager rather than an entity-specific deep link. No unrelated Manager redesign.
- No dataset bytes/media/code, lineage execution, artifact store, pipeline, function, hosted app,
  SCIM/group sync, Spark, Rust or AI infrastructure is implemented.
- Historical scanner findings and independent certification gaps are retained. No final image scan,
  production promotion, organizational deployment or live external SSO certification was attempted.

## Recommended next phase (not implemented)

Obtain separate authorization for milestone B / proposed Phase 12: pluggable artifact storage,
immutable artifacts, local MinIO with idempotent initialization, external S3-compatible configuration,
bounded uploads/downloads, lifecycle/retention, tenant/Project authorization and recovery tests.
Before implementation, agree on storage ownership/quotas, credentials, resource version contracts,
allowed content/size and acceptance tests. Dataset catalog/upload and pipelines require their own
later authorized milestones. Production release still requires the complete Section 23B gates.
