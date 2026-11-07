# Phase 21 — Shared development, lineage and observability

Implementation: November 6–7, 2026 (America/New_York). Base revision:
`149fe96cf05753f164a925a9bbbbba8f1cd3d51a` (verify the final evidence appendix for exact identity).
Changes are uncommitted. **Phase 21 is NOT FULLY ACCEPTED.** The shared rollout and functional
vertical slice have executed evidence, but a clean final whole-backend regression and all requested
acceptance coverage are not established. Do not equate focused checks with a passing full regression.
Production remains **BLOCKED / NOT PRODUCTION-CERTIFIED** under PLANS.md §23B.

## Delivered functionality

The existing PostgreSQL/resource/governance/ArtifactStore/execution architecture is preserved. Phase 21
adds a recoverable version-1 lineage projection, transactional invalidation, durable checkpoints,
bounded authorized upstream/downstream traversal, impact witness paths, metadata-only column lineage,
freshness policies and dependency status, resource execution health, safe node timelines and operational
state events. It does not introduce another ontology, authorization engine, scheduler, artifact store,
execution engine, microservice database, arbitrary code, Spark, Rust, connectors or production rollout.

Canonical ontology node identity is independent of registry aliases while each edge retains its own
resource authorization scope. This connects dataset → materialization → ontology type → published
application across different Projects/registry references, without granting access through an alias.
Published application manifests/query types/action pins and automation declarations/observed execution
receipts are indexed. Private drafts are excluded. DAG output derivation links to the exact contributing
published transform/source, with successful output edges emitted together from the committed manifest.
Prepared, failed and cancelled outputs never become successful lineage. Partial materialization uses
actual persisted batch records and does not imply complete synchronization.

The Studio navigation includes an interactive lineage graph, keyboard/table alternative, evidence and
impact tables, column dependencies, a bounded observability summary, execution inspection/history,
freshness configuration/upstream status and operational events. Background loads have independent
request tracking; buttons do not silently suppress dependent loads. Tenant selection is disabled during
workspace admission rather than dropping a tenant change while another request is busy. Existing
Project/application/pipeline authoring remains the canonical mutation surface.

Actual FastAPI OpenAPI, TypeScript SDK capability methods, React hooks and BFF query allowlists are
updated. The new `observability` family preserves existing APIs, session/principal/tenant scoping,
CSRF, bounded requests, classified read retries and no mutation auto-retries.

## Shared development before and after

| Item | Observed before | Executed after |
| --- | --- | --- |
| Application database | foundry / public / foundry, localhost:55432 | Same database/schema/user |
| Alembic revision | **0026_pipeline_dag**, not the historical 0024 | **0027_lineage_observability** |
| Projects/resources | 1 Project, 2 resources | Existing identities/fingerprints preserved; a named validation Project and resources added |
| Dataset versions / pipeline definitions / jobs | 0 / 0 / 0 | Real source, legacy output and two DAG outputs; immutable definitions and successful jobs retained |
| Object storage | Disabled in the API | Persistent MinIO; same S3ArtifactStore/settings in API and worker |
| Runtime | Older API/Studio; no execution worker container | Rebuilt targeted API, worker and Studio; image/source verification recorded |
| Keycloak | Two separately running protected containers; container-local H2 | Preserved; actual existing login and Code/PKCE smoke succeeded |

The Phase 20 historical report is not new Phase 21 evidence. Reconnaissance verified the live revision,
existing data, configuration and topology. Keycloak shares the existing Docker network but not the
Foundry PostgreSQL database or volume. It has no external H2 mount; preserving the existing container
is mandatory. Neither Keycloak container nor shared PostgreSQL was stopped/restarted/recreated.

Protected identities captured before rollout:

- `foundry-keycloak`: `352ae233e8cb29856593440399e330387a43311119ed74367441d961ebabfa33`,
  started `2026-11-03T02:24:28.100799334Z`.
- `foundry-keycloak-tls`: `026ca27afa2b1072402a06de5f77f2da3e8eac2330d08eedf6f0c6a4c22f5662`,
  started `2026-11-03T02:27:32.412283336Z`.

Mounts and networks were also captured and compared. A preservation comparison once failed; an
immediate read-only inspection showed unchanged IDs/start times/mounts/networks. Comparison now
normalizes mount/network enumeration order. No Keycloak lifecycle/configuration command occurred.
Credentials and tokens are not committed or printed in test logs. Private deployment configuration,
backups and TLS material remain ignored under artifacts/.

## Backup, migration and recovery

A mode-0600 logical custom-format backup was created at
`artifacts/phase21/foundry-20261106T221847Z.dump` (**30,580,277 bytes**). `pg_restore --list` read its
TOC; a full restore into the isolated disposable database
`phase21_restore_20261106t221847z` succeeded. Revision and Project/resource counts matched the source.
Only that owned rehearsal database and temporary container copy were removed. Shared data was not
reset, truncated, reseeded, dropped, downgraded or overwritten.

The canonical runner is the root **alembic.ini** (`script_location = services/api/migrations`):

```sh
# Run from repository root, with the verified target configuration.
uv run alembic -c alembic.ini current
uv run alembic -c alembic.ini heads
uv run alembic -c alembic.ini upgrade 0027_lineage_observability
uv run alembic -c alembic.ini check
```

Shared deployment used `scripts/migrate_shared_phase21.py`, which supplies a verified connection to
that same runner and exact revision. It checks the successful rehearsal, stopped Foundry writers,
expected host/database/user/schema/revision and absence of active jobs. Migration, canonical data
fingerprints and Alembic drift were verified transactionally. The shared revision was already 0026;
0024 → 0025 → 0026 → 0027 was separately tested in disposable schemas. No unqualified shared
`upgrade head` or redundant Alembic configuration was introduced.

Forward-only **0027_lineage_observability** creates lineage_edges, lineage_pending,
freshness_policies and operational_events, tenant-qualified foreign keys/indexes, append-only edge
guards and transactional canonical invalidation/job event triggers. Existing canonical tables and
immutable definitions are not rewritten. The runtime readiness revision is 0027. Recovery is a
verified **isolated restore and reviewed connection cutover**, never automatic downgrade or shared
overwrite. See [rollout](shared-dev-rollout.md) and [migration commands](alembic-migrations.md).

## Storage and authenticated shared acceptance

Persistent development MinIO reuses the existing volume, buckets, initialization and application
policy. Initialization ran twice. Credentials are server-side; no public bucket or browser MinIO
credential was introduced. Targeted Compose operations built/recreated API, worker and Studio with
`--no-deps`. Existing Keycloak/TLS/network settings were carried forward.

`scripts/smoke_phase21_shared.py` prompts for the existing development password, keeps Code/PKCE tokens
in memory only and invokes actual authenticated HTTP APIs. Its executed `shared-smoke.json` records:
existing Project preservation, a new named validation Project, artifact-backed dataset upload/finalize,
a legacy pipeline, a real v2 DAG, **two COMMITTED outputs**, previews of both, lineage, fresh policy,
column lineage, execution details and durable events. These resources are retained for operator review;
existing resources were not replaced or seeded to make checks pass. A separate existing-browser check
confirmed actual Keycloak sign-in and preserved manufacturing schema access.

## Lineage, backfill and privacy

Resource/edge catalogs and semantics are in [the contract](lineage-observability.md),
[impact analysis](lineage-impact-analysis.md), [backfill](lineage-backfill.md) and
[privacy](lineage-security.md). Project containment comes directly from persistent canonical registry
ownership. Immutable physical/logical versions, definitions, executions, v2 transforms, observed
materialization types, published application dependencies and automations/functions are covered.

Canonical writes invalidate a resource in the same transaction as publication; one coalesced pending
row/generation/checkpoint replaces an unbounded per-heartbeat queue. The existing worker reconciles
bounded batches. Versioned checkpoint prefixes distinguish older projections and force reconciliation;
manual governed reconciliation can also restart an already indexed resource. Stable edge identities
prevent duplicates. Queries report conservative indexing completeness across authorized origins.
Missing history is never silently presented as a complete absence of dependencies.

Each endpoint, supporting origin, version pin and alias scope is independently authorized. Pruning
precedes expansion, filters and counts. Private/missing roots use governed 404. No hidden placeholder,
sibling identity/count, source key, private draft, raw parser error or stack trace is returned. Node
identities/staging counts are suppressed if complete DAG binding visibility is absent. Operational
events contain fixed state/attempt/severity metadata and safe execution correlation, separate from audit.

## Column, freshness and observability contracts

The closed AST reuses the actual Polars metadata planner. Select/rename/drop/cast/derive/fill-null,
aggregate/join/union and filter/sort/deduplicate dependencies are supported. VALUE, ROW and ORDER
origins are distinct. Only full-join coalesced keys can take value origins from both sides; join keys
on either side still affect row membership. Limits return PARTIAL; unsupported schemas and historical
linear definitions without immutable pins return UNSUPPORTED. No dataset bytes are needed.

Freshness uses database time and the latest COMMITTED logical version. No enabled policy is DISABLED;
missing threshold/version is UNKNOWN. Failed production does not erase successful timestamps.
Authorized last successful/failed producing jobs and bounded upstream freshness are available.
Execution observations reuse persisted jobs/manifests/node states, measured numeric metrics and
safe fixed error classes. Missing measurements remain unavailable. Events begin at 0027 and retain
no fabricated pre-migration attempt history. Health summaries are page-scoped; dashboards explicitly
sample bounded authorized history. Operator ceilings and truncation are in [limits](phase-21-limits.md).

## Executed validation (final evidence appendix updated separately)

| Check | Result | Evidence |
| --- | --- | --- |
| Backup structural read and isolated restore | PASS | artifacts/phase21/backup-restore.json |
| Shared exact 0026 → 0027, preservation, drift | PASS | shared-migration.json / shared-migration.txt |
| Authenticated shared source/legacy/two-output DAG/observability | PASS | shared-smoke.json |
| Initial lineage/storage suite | FAIL: 13 passed / 1 fixture failure | initial-integration.txt; fixture corrected |
| Expanded initial alias/privacy checks | FAIL: 16 passed / 2 failures | expanded-integration.txt; disclosure and fixture corrected |
| Focused corrected lineage suite | PASS: 18, then 21 | lineage-recheck.txt; final-focused.txt |
| Broad compatibility/security slice | PASS: **195** | stable/focused.txt |
| Canonical alias + exact 1 GiB metadata regression | PASS: **23** | metadata-final.txt |
| Observed automation + private ontology alias | PASS: **2** | automation-alias-security.txt |
| Original complete Python attempt | FAIL: **940 passed / 6 failed / 1 strict xfail** | full-regression.txt |
| Recheck of those six failures | FAIL: **4 passed / 2 storage clock-skew failures** | regression-failure-recheck.txt |
| Later awake complete Python attempt | FAIL: **940 passed / 9 failed / 1 strict xfail** | awake/full.txt; clock sampling proves severe gaps |
| Early complete browser run | FAIL: new explorer request race | browser.txt |
| Later browser attempt during clock drift | FAIL: 6 passed / 9 failed | browser-corrected.txt |
| Corrected explorer browser run | FAIL: **14 passed / 1 tenant-switch failure** | visible/browser.txt; explorer/impact/columns/freshness/events passed |
| SDK unit tests | PASS: **63** | frozen/quality/sdk-tests.txt |
| Studio unit tests including asynchronous loading | PASS: **56** | studio-load-test.txt; frozen/quality/studio-tests.txt |
| Python types / Ruff / formatting | PASS in quality run | frozen/quality/; subsequent focused source checks recorded |
| Generated OpenAPI/SDK, packed consumer, TypeScript and builds | PASS in quality run | frozen/quality/results.json |
| Fixture parsing/CSV/SHACL/semantic profile | PASS: **12**, one preserved strict xfail | fixture-validation.txt |
| Raw pySHACL compatibility / supported OWL profile limit | NOT SUPPORTED | preserved strict expected failure and semantic compatibility docs |
| Manual Protégé GUI | NOT RUN | No GUI interoperability change; requires separate manual environment |
| §23B production certification | NOT RUN / BLOCKED | Not authorized or claimed |

All counts refer to executed selections, not summed into a fictional full run. The final source
includes separately tested late correctness/privacy changes; no passing frozen full-suite claim is
made. Test execution logs and private runtime evidence remain in ignored artifacts/phase21/.

## Clock diagnosis and remaining acceptance limitations

Host/Docker/PostgreSQL clock gaps caused observed S3 `RequestTimeTooSkewed`, interrupted leases and
login/expiry failures. One direct read showed 282 seconds offset; later samples exceeded **2,887
seconds** despite a process-scoped caffeinate assertion. Clocks/services were not reset and no TLS,
signature, lease, expiry, assertion or timeout was weakened. This reproduces the class of instability
historically documented in Phase 15, but does not prove that every failed assertion has that cause.
Earlier migration-head/message failures were separately corrected. Full acceptance requires a clean
final whole-suite run under stable clocks and resolution of any remaining failures. The later run
failed two CSV size tiers and seven ingestion/recovery checks; no passing result is inferred for them.

Other explicit limits: historical linear definition-level column provenance without pins is unsupported;
pre-0027 retry/node-attempt transitions are unavailable; graph-level ontology provenance is type-level,
with existing per-object/link provenance APIs preserved; health last-success/failure/consecutive counts
are page-scoped; dashboard summaries are bounded samples; impact returns one deterministic witness per
identity, not every path. Pending work is coalesced per resource, but no separate hard global dirty-
resource backlog admission ceiling is added. Complete requested browser/security/performance matrices
must be reviewed against executed evidence before Phase 21 can be fully accepted.

## Files and architectural decisions

ADR [0046](../decisions/0046-lineage-observability.md) and the Phase 21 PLANS addendum record scope and
boundaries. New backend files are observability/{contracts,index,columns,service,routes}.py and its
module initializer; migration 0027 and four ORM models are additive. main.py includes the router,
execution/worker.py advances the index, db/governance.py tracks readiness, and pipelines/dag_service.py
suppresses private DAG monitoring metadata. Compose adds the existing execution worker runtime and
shared storage settings. New tests cover lineage/columns/freshness/security/aliases/automations/migration;
DAG large-data and browser workflows now exercise observability. Existing migration-head assertions
advance to the approved additive head. No canonical fixture data or dependency lock changed.

Studio adds features/observability.tsx, navigation/loading/tenant-admission fixes and a real async
loading regression. OpenAPI/API schema, SDK schema/endpoints/React hooks and generation manifest are
updated. Operator tools are scripts/{phase21_shared_dev,migrate_shared_phase21,smoke_phase21_shared,
validate_phase21}.py. Documentation covers rollout, migrations, storage, lineage/backfill/impact,
freshness, observability, security, Studio and limits. See git diff/status for exact final paths.

Recommended next work is **remaining Phase 21 acceptance closure**, not an automatically authorized
Phase 22 or unrelated Milestone J feature. Production remains BLOCKED / NOT PRODUCTION-CERTIFIED.


## Final closure evidence — November 7

- **PASS: 15/15 complete durable browser workflows**, including real 1 GiB browser upload, the new
  lineage/impact/column/freshness/event workflow, application runtime, tenant switching and CSRF.
  Evidence: `artifacts/phase21/final-browser/browser.txt` and `browser-result.json`.
- **PASS: 23 frozen-source metadata/1 GiB checks**, with artifact chunk reads forbidden during
  observability. Final query: **0.1007 seconds**, 11 nodes / 18 edges. Source: **1,073,741,824 bytes**;
  262,080 rows; two atomic outputs; measured peak memory **1,525,989,376 bytes**, temporary disk
  **1,074,177,319 bytes**. These are measurements, not performance guarantees.
- **PASS: 2 additional observed automation / real private-alias authorization checks**.
- **PASS: 63 SDK and 56 Studio unit checks**, generated/packed-consumer/types/build/format checks.
- **FAIL: latest complete backend attempt: 940 passed, 9 failed, one preserved strict xfail**.
  All logs remain; no combined passing full-suite claim is made.
- The final shared smoke was repeated against the deployed runtime, retaining the original evidence
  as `shared-smoke-original.json`. Both legacy and DAG jobs succeeded through existing Keycloak
  authentication, and both outputs remain reviewable.
- Final preservation evidence is `final-shared-state.json`: original Keycloak and PostgreSQL identities/
  start times preserved, API/worker images identical, running API source matches workspace. Shared
  development is 0027, with **3 Projects / 12 resources / 8 dataset versions / 4 successful jobs**
  after additive validation workflows. Original data was not replaced.

A final shared inspection exposed old unversioned checkpoints that had equal generation counters:
manual/new-history queries worked but automatic version reconciliation did not select those rows.
The worker predicate was corrected to select dirty **or older-format** checkpoints, with a targeted
real PostgreSQL/MinIO recovery regression. This correction does not change canonical records or the
schema, and no additional broad test run was started for it.

Acceptance remains **NOT FULLY ACCEPTED**, with the complete-backend regression and the explicitly
listed coverage/operator limits still outstanding. The engineering/runtime delivery is recorded
without certifying those missing requirements. No subsequent phase or §23B rollout was begun.

### Required fixtures/VALIDATION.md status matrix

| Check | Result | Executed evidence / reason |
| --- | --- | --- |
| Turtle parsing | PASS | fixture-validation.txt; all three canonical Turtle inputs |
| CSV identity and foreign keys | PASS | fixture-validation.txt |
| SHACL conformance | PASS | supported normalized/pinned fixture checks; raw compatibility separately unsupported |
| OWL reasoning profile | NOT SUPPORTED | Existing engine profile does not establish OWL hasValue inference; fixtures preserved |
| PostgreSQL persistence/migrations | PASS (scoped) | Real disposable fresh/upgrade/drift/rollback/lineage suites; not a full-suite acceptance claim |
| FastAPI object queries | PASS | Executed complete-run query/API selections; failures are separately retained |
| Actions and reconciliation | PASS (scoped) | Executed action/authorization selections; ingestion recovery is separately failed |
| Polars ingestion/recovery | FAIL | Latest complete attempt has CSV/ingestion/lease recovery failures |
| Authorization | PASS (scoped) | 195-check compatibility slice, real alias/private-output checks and final browser workflows |
| Protégé import/export API | PASS (scoped) | Executed ontology interchange selections; no new OWL authoring constructs |
| Manual Protégé GUI | NOT RUN | Separate manual environment; not claimed by API checks |
| Production certification | NOT RUN / BLOCKED | §23B remains independently controlled |

The failed full-run selections require investigation/re-execution in a stable environment. Recorded
clock gaps are evidence of environmental instability, not blanket proof that each failure is harmless.

Final checkpoint closure: **PASS — one targeted real PostgreSQL/MinIO regression** in
`checkpoint-recovery.txt`; the corrected API/worker image was deployed and its actual running source
hashes were checked. `final-shared-state.json` now reports **zero dirty/older-format checkpoints**,
revision 0027, identical API/worker images and unchanged protected Keycloak/PostgreSQL identities.
The existing shared browser visibly rendered persisted upstream lineage and reported
“Indexed history is current for visited resources.” The working shared tab is left open.

Browser screenshot evidence: [validated Studio workflow](../../artifacts/phase21/lineage-observability.png).
No additional broad test run was started after the user's closure request. All validation processes
have finished; their temporary process-scoped keep-awake assertions ended with them.
