# Phase 20 — General DAG pipelines and atomic multi-output publication

Date: 2026-11-06 (America/New_York). Base revision: `495e4611cdc5898dd654ae76df03d885fe7f2180`.
Status: **locally accepted for Phase 20 development**, subject to the limitations below.
The complete backend snapshot passed before the final compatibility fixes; those fixes have separate
117-test pipeline and final privacy-regression evidence. No combined full-suite claim is made.
Production remains **BLOCKED / NOT PRODUCTION-CERTIFIED** under PLANS.md §23B.

## Initial state, authorization and assessment

The explicit Phase 20 request authorizes general closed DAG IR, reusable Polars intermediates,
fenced durable execution, atomic multiple-output publication, Studio/SDK integration and development
validation. It does not authorize arbitrary code, Code Workspaces, hosting, Spark/Rust, production
release, shared database mutation or any Keycloak change. ADR 0045 preceded substantial implementation.
The initial index was empty; initial-status.txt and the saved zero-byte staged patch record it.
The index remains identical. Nothing was reset, committed or rebased. Only the separately described
0024-compatible storage-disabled hotfix was applied to the existing development API. Phase 14–19 reports, ADRs 0039–0044, PLANS §§23A.5/23A.10/23B,
fixtures/VALIDATION.md, execution/storage/governance code, migrations and Compose were inspected.

Repository head was verified as 0025_applications; the shared developer database was read-only queried
as 0024_pipeline_graphs. The Phase 19 report/evidence records 871 passes/one strict xfail, 14 browser
workflows, local acceptance and incomplete container builds. These are historical observations, not
Phase 20 reruns. The existing ordered engine starts at the first input, resolves binary right inputs
only from raw named sources, and publishes one output. The visual compiler follows a primary chain.
Phase 20 extends those existing components rather than creating another engine/scheduler/datastore.

Development Compose has postgres→api→studio dependencies and optional isolated MinIO/init services.
Protected separately running foundry-keycloak and foundry-keycloak-tls IDs/start times/mounts were
recorded before operations. Neither is a Compose target or a test identity provider. No shared
PostgreSQL restart, reset, seed, migration or volume deletion was performed. All test migrations use
owned random schemas; MinIO projects/volumes are independently generated and removed by their harness.

## IR, planning, compatibility and catalog

Canonical v2 contains strict immutable source pins/contracts, stable node IDs, explicit input/right
ports, closed Step configurations, and stable independently targeted outputs. JSON/node/edge order and
canvas coordinates do not affect semantics. Sorted canonical serialization and deterministic Kahn
layers/lexical IDs supply semantic and execution-plan SHA-256s. Plans additionally bind checksums,
engine version, tenant and captured limits. Schema-only planning uses the actual Polars operation
adapter and metadata frames; it does not read source bytes or retain recursively expanded branch plans.

The supported transformation catalog is select, rename, drop, filter, sort, cast, derive, fill_null,
deduplicate, aggregate, join and union. Both binary inputs may be transformed branches. Equal-named
compatible join keys and exact ordered union schemas retain existing semantics. Outputs may reference
sources or transformations and use Parquet/CSV/NDJSON, subject to logical-schema roundtrip validation.
Output targets are existing governed datasets or newly created resources in explicitly authorized
Projects. Duplicate output targets are rejected. Scalar Function references still block execution.

Historical definitions/identities are not rewritten. Legacy canonical JSON and graph v1 retain their
old compilation/execution path; Studio explicitly upgrades drafts to v2. Three output-checksum goldens
were measured using actual base-revision engine source and checked against the upgraded engine.

## Execution, persistence, recovery and cancellation

One existing parent execution job owns admission, leases, attempts, cancellation and final outcome.
Sequential existing isolated Polars children materialize each transformation once into streaming
Parquet. Shared downstream branches scan the same result. Per-node state/attempt/token/timestamps,
plan-bound deterministic result UUIDs, input checksums, output checksum/schema/row count and measured
metrics persist in PostgreSQL. Private intermediates have no registry/dataset identity and cannot be
resolved through ordinary content APIs. Local file lifetime follows remaining consumer references;
remote recovery bytes remain until terminal cleanup under aggregate quotas.

A replacement worker verifies the immutable plan and exact input/result checksums before reuse.
Missing private bytes are recomputed; mismatches fail closed. Live DB-clock fences prevent stale
node/manifest writes and publication. An ambiguous acknowledgement after commit reads SUCCEEDED/
COMMITTED as authority, so publication cannot repeat. Cleanup sweeps bounded terminal manifests,
locks the parent against manual retry, retains committed output objects and records completion so
interrupted cleanup can safely resume. Abrupt host death may leave local scratch requiring ordinary
filesystem maintenance; no production kernel/cgroup isolation is inferred from macOS watchdogs.

Cancellation and publication serialize in the existing security/tenant/parent lock domain. A
pre-commit cancellation prevents every output; a committed job remains successful after later cancel.
Failed/cancelled jobs can leave private bytes briefly until cleanup, never visible partial outputs.

## Publication transaction, concurrency and provenance

Admission allocates stable target/version reservations without visible placeholder resources/versions.
Preparation serializes, validates, hashes, uploads and verifies all bytes at their final immutable
ObjectKeys. Durable output manifests progress through preparation without creating dataset metadata.
Commit rechecks current authority/pins/lease/deadline/cancellation, locks target resources in sorted
order, verifies objects, and uses DatasetService to create every new resource and every artifact/
dataset version in one transaction with manifest commit UUID, lineage, audit and parent success.
An audit/database error rolls all metadata back. Deferred physical/logical visibility triggers reject
an individual output committed without the entire committed manifest and successful parent.
S3/MinIO and PostgreSQL are explicitly not a distributed ACID transaction; no post-commit move remains.

Overlapping target runs append immutable versions under serialized governed locks. Disjoint runs
may execute independently, with the existing coarse tenant publication lock retained. No replacement
or last-writer-wins head mutation. Source ancestry is deduplicated and output-specific. Inputs,
pipeline metadata and output references are independently authorized; sibling declarations are
never included in an output's lineage. Definition reads additionally require binding visibility,
so sharing a pipeline cannot disclose private pinned dataset/output metadata.

## API, Studio and SDK

Existing canonical/graph validation/publication/drafts, run/history/status/cancel/retry and dataset
lineage endpoints carry explicit legacy/v2 types. Typed status adds plan digest, publication state,
prepared count, durable node state/attempt/error and independently filtered committed outputs.
Studio retains React Flow, adds v2 edges/branches/convergence/multiple output configuration, explicit
v1 draft upgrade, real node monitoring, bounded polling and per-output preview/lineage controls.
No staged object keys or invented percentages enter browser responses. Generated OpenAPI, SDK models,
wrappers/hooks and React execution observation preserve session/tenant/principal isolation, CSRF,
cancellation and no automatic mutation retries. Pipeline envelopes support 512 KiB while semantic
graph JSON remains 256 KiB; other families retain their 64 KiB envelope bound.

## Migration, security and limits

Forward-only **0026_pipeline_dag** follows 0025_applications. It adds dag_runs, dag_nodes and dag_outputs;
tenant-qualified FKs, unique target/version reservations, state/commit constraints, fenced/immutable
record guards, atomic success/visibility constraints and terminal cleanup metadata. Existing immutable
version metadata is reused, not duplicated. Fresh/prior-head/drift tests use disposable schemas and
preserve application, pipeline and dataset records/checksums. No shared developer migration ran.

Hard graph and operator quotas, retained-node admission, aggregate intermediate/output/manifest bytes,
output rows, temporary disk and per-node/parent deadlines are documented in phase-20-limits.md.
Existing 1 GiB sources, 2 GiB memory, 4 GiB temporary disk and child CPU/address limits remain.
No client resource-budget overrides or executable expressions are introduced. High-cardinality joins
may exceed limits; safe failure does not imply arbitrary DAGs fit old chain budgets.

## Executed evidence

| Check | Result | Evidence |
| --- | --- | --- |
| Initial DAG PostgreSQL/MinIO integration | PASS: 14 | dag-integration-attempt-1.txt |
| Expanded legacy/DAG run | FAIL: 3 failed / 78 passed | dag-integration-attempt-2.txt |
| Corrected DAG, graph and 1 GiB integration | PASS: 34 | dag-integration-attempt-3.txt |
| Security/recovery/quota suite | PASS: 27 | dag-security-recovery-attempt-1.txt |
| Final focused + measured 1 GiB run | PASS: 32 | dag-final-measured-attempt-1.txt |
| Python, generated, SDK, consumer and Studio quality | PASS: all 14 commands | quality/results.json |
| Focused real visual DAG browser workflow | PASS: 1 | browser-attempt-3.txt |
| Initial full backend regression | FAIL: 892 passed / 2 failed / 1 strict xfail | full-backend-attempt-1.txt |
| Second full backend attempt | FAIL: 911 passed / 1 drift failure / 1 strict xfail | full-backend-final.txt |
| Frozen-source full backend regression | PASS: 919 passed, 1 strict xfail, zero skips; drift clean | full-backend-frozen.txt |
| Final pipeline/legacy/execution/migration regression after compatibility fixes | PASS: 117 | final-pipeline-regression.txt |
| Final private sibling aggregate-metrics regression | PASS: 1 | private-metrics-final.txt |
| Final quality delivery | 14 commands PASS; Studio test mock corrected and suite rerun separately | quality-delivery/results.json; studio-tests-delivery-corrected.txt |
| Initial full browser regression | FAIL: 6 passed / 9 failed | browser-complete-attempt-1.txt |
| Final DAG browser cancellation/restricted principal | PASS: 1 | browser-dag-final.txt |
| Complete browser suite after Project navigation fix | PASS: 15 workflows, including exact 1 GiB upload | browser-complete-final.txt |
| Focused DAG reopen / reference / Project navigation | PASS: 3 | browser-navigation-with-setup.txt |
| Studio unit suite with navigation/pin regressions | PASS: 55 | studio-tests-navigation.txt |
| Existing Keycloak/Studio authentication | PASS: user signed in; authorized workspace observed | manual-keycloak-authentication.json |
| Isolated API and Studio image builds | PASS: both final validation tags built/exported | container-build-final.txt; container-build-delivery.txt |
| Protected containers and shared migration head | PASS: unchanged identities/start times/mounts; shared head 0024 | preservation-final.txt; keycloak-after.json |
| Production/external provider/OKD4 certification | NOT RUN / BLOCKED | separate §23B authority required |

The final measured exact 1 GiB run had 262,080 source rows, 524,160 cumulative output rows,
74,229 intermediate bytes and 49,486 staged output bytes. Peak child RSS was 1,586,429,952 bytes,
peak sampled temporary usage 1,074,177,319 bytes, and execution wall time 29.539 seconds. Cleanup
passed. Source SHA-256 was `9df705da678f9418b4a8e9601677fb6eb234b5c91850ff34d871a21cea91b158`;
both outputs were `23e5d6d7585aa51a64db0d3a1c7f2145e380f299e59755b5c508f4ccffa4eff3`.
This is one local development measurement, not a controlled throughput or production capacity claim.
Raw final measurements are in large-measurement-final.json and final-pipeline-regression.txt.

## Failed/corrected attempts and validation limitations

Two initial test failures were missing ExecutionJob imports in new tests; one historical graph test
had to move its unsupported version from newly supported 2 to future 3. The original semantic assertions
were retained. The first UV call lacked sandbox cache access; installed .venv tools were used and
subsequent authorized disposable runners used the normal cache. A mistaken Studio generate script
name was corrected to the existing generate:api command. Initial style/type issues were fixed.

Automatic approval review initially could not establish browser database isolation. Source inspection
proved the harness creates/migrates/drops a random schema and binds API/BrowserStore/workers to its
sessions; that evidence was provided before approval of the next launch. No shared-data exception was
requested. The first two browser startups timed out because readiness still required 0025 against a
fresh 0026 schema. SCHEMA_REVISION was corrected without changing tests or readiness guarantees.
The first full backend attempt retains that readiness failure. A later full browser DAG run timed out
while its first node was still RUNNING under concurrent large-data validation; no passing result is
claimed for that attempt, and host-load attribution remains an inference; the subsequent complete isolated browser rerun passed.

## Acceptance, inventory and next phase

The approved Phase 20 vertical slice is locally complete. changed-files.txt lists every changed/new
implementation, migration, test and documentation path (evidence files are inventoried separately).
implementation-sha256.json captures the delivered files; evidence-inventory.txt lists raw evidence.
The forward-only migration is **0026_pipeline_dag**; the shared developer database remains on **0024**.
Phase 20 has not been deployed against that database. No shared reset, seed or migration occurred.
The existing authentication flow passed using the user's existing account. The protected Keycloak
containers retained identical IDs, original start times, running states, mounts, network and declared
database settings. No administrative realm/client/user/credential/configuration operation occurred.
Normal user sign-in necessarily creates ordinary session state; preservation does not mean a
byte-for-byte database comparison. Checks did not read private key or credential contents.

Stop after this phase. The recommended next work is a separately authorized development rollout
of the migration/storage configuration, followed by a separately approved roadmap phase.
Production certification remains an independently authorized §23B program and is **BLOCKED**.

## User-reported development storage_disabled correction

During validation the user reported that pipeline creation returned storage_disabled. Inspection of
the actual running development API found storage backend disabled and code/schema 0024. Pipeline
resource creation was incorrectly gated on ArtifactStore availability even though it creates only
PostgreSQL metadata. PIPELINE now joins FUNCTION/AUTOMATION as metadata-only creation; dataset and
artifact bytes retain their storage requirement. A dedicated disabled-storage disposable-schema
regression passed. Only this one-line change was copied into the existing 0024-compatible API and
that API alone restarted; the full Phase 20 runtime was not deployed to the unmigrated shared DB.
The runtime's non-root account correctly could not edit root-owned source on the first attempt; the
reviewed file was copied through Docker, preserving the non-root execution configuration. Readiness
returned HTTP 200 and source inspection confirmed the loaded exemption. No shared test resource,
credential, schema, configuration or Keycloak change was made. The tracked source retains the fix
for later builds; the running-container hotfix alone is ephemeral across recreation from an older image.
Evidence: storage-disabled-hotfix.json. Execution still requires storage-backed datasets.

## Final validation refinements

A second complete backend run passed 911 tests with one strict xfail, but its migration drift check
failed because the agent added the cleanup index while that process retained older imported ORM
metadata. This invalidated that attempt as a passing full regression. Python source, tests and
migrations were then hashed and frozen before the next full run. No Python changes were made during
that completed run; frozen-python-sha256.json records the actual snapshot. Subsequent documentation/UI work is
separate from that Python snapshot.

Final backend guards additionally preserve legacy non-null output requirements using SQL COALESCE
(avoiding CHECK's acceptance of UNKNOWN), reject v2 success without a committed manifest, and persist
the first DAG execution timestamp so recovery cannot reset the total graph deadline. Terminal cleanup
can run again after a stale worker returns and manifests are rechecked daily for late private bytes.
A cleanup index bounds discovery work. New tests exercise those constraints and cleanup behavior.

The complete browser retry passed 14 workflows including the 1 GiB upload, but exposed an old Project
navigation assumption: returning from Ontology Manager remounted Projects and chose the first sorted
Project. The new earlier DAG Project made that visible. Workspace now remembers the selected Project
only in tenant/principal/session-scoped memory; discovery still rechecks current visibility. A focused
selection without the reference workflow could not register unpublished ontology assets; it is not
counted as passing evidence. The follow-up includes the actual reference setup. Studio adds a regression
for restoring the authorized selection and another for reopening a published DAG with exact input
pins (excluding schema-only columns from StartRun). The initial new navigation test used an unsupported
Testing Library exact option, caught by TypeScript and corrected without changing its assertion.

## Post-full compatibility and privacy refinements

After the frozen full pass, four added spot-check cases initially failed: shared raw JSON/NDJSON
normalization reused a directory, aliases for one physical source attempted duplicate ORM expunges,
and parameterized datetime/decimal metadata was rejected. Each issue was fixed and the complete
117-test pipeline/legacy/execution/migration selection rerun successfully. Child-owned normalized
files are released only after successful child exit; repeated physical sources expunge once;
a closed, non-evaluating scalar metadata parser accepts supported timestamp/decimal types.
Nested list/struct metadata remains unsupported in DAG v2. The legacy cast catalog stays closed.
A subsequent private-output response refinement removes aggregate metrics when a committed sibling
is hidden; its own disposable-schema test passed after that edit. Earlier red evidence is retained
in compatibility-spotcheck-before.txt. The final Studio quality run exposed an old incomplete session
mock without a principal; the fixture was corrected to match the required session contract, and all
55 Studio tests plus formatting passed. The original quality-delivery FAIL is deliberately preserved.

## fixtures/VALIDATION.md status

| Applicable check | Status and basis |
| --- | --- |
| Turtle parsing; CSV/RDF identities/counts/foreign keys | PASS, full-backend-frozen fixture tests |
| RDF 1.1 normalized SHACL baseline and negative mutations | PASS, full-backend-frozen fixture tests |
| Raw pySHACL baseline | NOT SUPPORTED: recorded strict xfail for RDFLib simple/xsd:string mismatch |
| Open Ontologies parse/SHACL and supported reasoning profiles | PASS, full-backend-frozen semantic tests |
| Exact unnormalized OWL-RL datatype-restriction inference | NOT SUPPORTED under documented compatibility profile |
| PostgreSQL/FastAPI objects, relationships, actions, reconciliation, Polars workflows | PASS, full-backend-frozen integration and final pipeline regression |
| OWL import/export and roundtrip | PASS, full-backend-frozen authoring/semantic tests |
| Manual Protégé GUI workflow | NOT RUN: optional desktop authoring, no GUI session exercised |
| Real authenticated browser, tenant isolation, principal authorization | PASS, 15 browser workflows and existing-account sign-in |
| ESLint standalone command | NOT SUPPORTED: repository has no standalone lint script; TypeScript/Prettier/build executed |
| Production, external provider and OKD4 target certification | NOT RUN / BLOCKED under §23B |

## Known limits

Execution is sequential within one parent job, using the existing isolated Polars child. Every
transform materializes Parquet, trading I/O for deterministic shared-result reuse. Join keys must
have matching names/types (rename first); union schemas must match exactly. Scalar metadata is
closed; nested list/struct DAG planning is unsupported. Output formats are Parquet, CSV and NDJSON,
with logical-schema roundtrip requirements; JSON-array output is unsupported. Explosive joins can
fail bounded memory/disk/rows limits. macOS sampled watchdog evidence is not Linux cgroup certification.
Abrupt host death can leave local scratch for operator maintenance; remote late private bytes are
revisited by bounded daily cleanup. Publication retains the existing coarse tenant governance lock.
No arbitrary user code, Spark, Rust, second datastore or second execution engine was introduced.
The shared development environment still has object storage disabled: metadata-only pipeline creation
works after the one-line hotfix, while byte-backed dataset ingestion and execution require configured
storage. Full Phase 20 rollout to shared schema 0024 was not authorized and was not performed.
