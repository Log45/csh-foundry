# Phase 13 — Independent governed dataset foundation

Date: 2026-11-03. Base revision: `4a424cc`; changes are uncommitted.
Scope: explicitly authorized Section 23A milestone C / Phase 13 only.
Status: **PASS — Phase 13 local development acceptance.**
Production: **BLOCKED / NOT PRODUCTION-CERTIFIED**, unchanged Section 23B requirements.

## Functionality and architecture

[ADR 0038](../decisions/0038-dataset-versions.md) was recorded before substantial implementation.
Datasets are first-class DATASET resources in the existing tenant/Project registry. They require no
ontology, object type, published schema or mapping. The registry remains the sole identity, Project,
folder, sharing and lifecycle authority. Stable IDs survive rename/description/folder changes.
Generic resource APIs supply discovery, rename, move, sharing/revocation and non-destructive archive.
Unsupported future registration types remain rejected; ontology and ARTIFACT behavior is preserved.

A dataset owns physical `artifact_versions` through its registry ID, using the existing ArtifactService
resource-kind adapter and ArtifactStore transport. Dataset-specific endpoints admit DATASET identities;
generic artifact endpoints continue requiring ARTIFACT. The configured Phase 12 artifact bucket is
reused; reserved dataset/media buckets are not granted new permissions or made public. No second byte
store, upload implementation, Project service, database or ACL system is introduced.

`dataset_versions` extends the physical version with format, immutable JSONB validation/schema/preview
result, state and completion time. The tenant/resource/version composite identity is also its foreign
key to `artifact_versions`; the dataset version UUID pins that exact physical version UUID. Artifact
metadata supplies immutable sequence, original filename, source byte size/SHA-256, uploading principal,
creation and physical commit times, backend identity and restricted source provenance. Database triggers
require DATASET resource authority and committed physical bytes before either validation outcome.
The shared identity prevents attaching a different tenant's or Project's physical artifact. Tenant
transaction locks plus physical-version uniqueness serialize simultaneous version reservations.

The schema snapshot contains column order/name, Polars logical type and observed nullability; Parquet
also records the Arrow source schema text. Immutable parser/version/format/count metadata records the
validation guarantee. Different dataset versions may have different schemas; historical schemas and
source relationships are never rewritten. Provenance represents actual source uploads, with no invented
derivations or lineage edges. Later approved operations may extend provenance for real derived outputs.

## Migration and datastore preservation

The actual initial head was inspected: `0019_artifacts`. The new additive, forward-only revision is
**`0020_datasets`**, after `0019_artifacts`. It extends registry type/authority checks and existing
resource/artifact guards, adds the dataset composite FK and format/state/timestamp checks, and prevents
terminal dataset updates or history deletion. It requires PENDING insertion and legal publication.
Historical migrations, canonical fixtures and prior evidence were not edited. ORM metadata drift passed.

Executed upgrades cover fresh installation, historical Project/ontology preservation and specifically
`0019_artifacts` with an existing committed artifact, retaining its resource metadata and exact bytes.
Only randomly named disposable PostgreSQL schemas were migrated. Read-only verification confirms the
shared developer schema remains **`0017_capacity`**. No developer volumes or existing data were reset.
The source checksum and source-artifact immutability remain enforced by Phase 12 constraints/transport.

## Upload, failure and recovery semantics

1. Create/select a governed dataset and initiate a version. Artifact reservation and dataset PENDING
   metadata commit in one PostgreSQL transaction; no reservation-to-registration orphan window.
2. Existing governed artifact transport spools and transfers bytes, verifies declared size/checksum,
   and handles conditional immutable writes, aborted multipart sessions and transfer retries.
3. Finalization durably commits integrity-verified physical bytes, then validates in a spawned process.
4. Before publication, current tenant/Project/write authority is checked again. One transaction records
   COMMITTED plus immutable schema/counts/preview, or FAILED plus sanitized validation diagnostics.
5. Retry after restart or failed database publication resumes PENDING validation against committed
   source bytes. Concurrent finalizers converge on one terminal result. Terminal finalization is
   idempotent; new/corrected content always needs a new version.

Interrupted uploads cannot publish; missing/corrupt storage stays uncommitted. A parser error cannot
publish valid dataset metadata. Parser-capacity admission returns retryable 503 with PENDING metadata.
A deadline/native process failure yields a terminal validation failure, requiring a new version.
Failed parsing retains committed source bytes for authorized diagnostics/download. Abandoned physical
PENDING/FAILED versions use the existing owner-only, dry-run-first exact-key cleanup; DELETED metadata
remains, and its dataset reservation cannot subsequently finalize. Committed bytes have indefinite
retention, including validation failures and archived resources. No automatic purge or scheduler.

Tests execute client disconnect, durable artifact commit before service restart, simulated publication
rollback, retry/idempotence, concurrent reservation/publication, parser rejection, direct SQL guards,
archive, retained history, and a preview that fails the test if it attempts any storage access.

## Formats, schema, validation and preview

The complete [API and validation contract](../api/datasets.md) documents supported structures and bounds.
CSV is UTF-8 (optional leading BOM normalized), comma-separated with strict quoting, a mandatory unique
nonempty header and exact row widths. Entire-file inference uses Polars with date inference; empty
fields become null, mixed numeric/text columns become String, and leading numeric zeros may normalize.
A zero-byte CSV is invalid; header-only data is valid. BOM-prefixed duplicate headers are rejected.

JSON is an array of nonempty objects; NDJSON has one nonempty object per nonblank line. Duplicate
keys, changing key sets and incompatible nonnull value types are rejected recursively. Numeric types
may widen using Polars semantics. Explicit null is allowed; omitted keys differ from null. Empty JSON
arrays/NDJSON have zero rows/columns. Empty record objects are rejected to avoid losing row identities
in a zero-column Polars frame. Parquet uses PyArrow footer validation (extensions disabled) and Polars,
retaining supported signed/unsigned integers, floats, booleans, temporal values, decimals, binary and
nested values. Source extension/MIME claims do not determine validation success. Pickle, paths, URLs,
executables and compressed text archives are unsupported.

Limits: 8 MiB source, 32 MiB decoded frame/declared Parquet row-group expansion, 100000 rows, 256 columns,
8 nesting levels, 200-character printable names, 64 KiB string/binary cells and 1 MiB preview JSON.
Every record/value is validated before publication; no sampled-conformance claim. A subprocess bounds
execution to 30 wall seconds/20 CPU seconds; Linux uses a 2 GiB address-space cap, macOS a soft 512 MiB
RSS watchdog. Admission allows two parser children per API process. Actual Linux container smoke tests
passed all four formats with the address-space limit enabled; this is not production certification.

Preview reads only the committed PostgreSQL cache, never reopens source storage, and returns the first
1–100 rows in original order with ordered columns and reliable full-content row count. Nulls are JSON
null, temporal values ISO strings, decimals strings, binary tagged base64, and nested values recursive
JSON. Nonfinite numbers and unsupported serializable types fail validation. Source rows are excluded
from history responses. Schema and preview reject invalid/uncommitted versions. There is no SQL engine,
filtering, transformation execution, joins, aggregations, ontology mapping or general lineage graph.

## Authorization, APIs and Studio

Every version/schema/preview/source operation uses existing GovernedService, current platform
permissions and Project membership. Ownership, explicit read-only sharing, revocation and archived
Project/resource rules are cumulative. Private/unknown IDs cannot bypass these checks. Dataset shares
do not grant generic artifact API access or unrestricted backend access. Audit uses the existing
transactional infrastructure, inherited artifact events, dataset reservation/validation events and
explicit preview events. No bucket names, object keys, credentials or native parser data diagnostics
are returned. Fixed application validation messages are safe; parser exceptions are sanitized.

New `/api/v1` endpoints cover Project dataset creation, direct dataset retrieval, version initiation,
streamed upload/download, finalization, bounded history, version metadata, schema, preview and owner
reconciliation. Generic `/projects/{id}/resources` and `/resources/{id}` APIs cover discovery and
rename/move/archive/share operations. Pydantic contracts and regenerated actual OpenAPI/TypeScript
contracts preserve API conventions. Dataset content paths receive the same streaming middleware
exception as artifact paths; a real upload over 1 MiB verifies the generic buffering limit is bypassed
only for governed content transfer.

Studio Project folders support dataset creation, explicit format selection, checksum/upload/validation
progress, immutable version history, validation errors, source download, schema/nullability inspection,
ordered nested/null previews and existing rename/move/archive/share controls. History pagination and
preview tables are bounded. The existing fixed-destination binary BFF admits only artifacts/datasets
and validates UUIDs, session/CSRF/current-and-expected tenant before transfer. Tokens and S3 credentials
stay server-side. Browser tests include valid upload/schema/preview, invalid upload, historical preview,
and existing ontology/action/branching/SDK/Project/artifact/durable-session workflows.

## Executed validation

Environment: macOS arm64, Python 3.12.0, supported Node 25.9.0, real PostgreSQL and disposable real MinIO,
Polars 1.44.2 and PyArrow 23.0.1; pinned local Open Ontologies 2.1.0 for existing semantic tests.
The Linux parser smoke uses an ephemeral cached Linux API image with the current source mounted
read-only and PyArrow installed only in its disposable filesystem; no image tag was changed/deployed.

Evidence: [full regression](evidence/phase-13/full-regression.txt),
[final targeted and browser run](evidence/phase-13/targeted-and-browser.txt),
[final parser checks](evidence/phase-13/parser-final.txt),
[Linux parser smoke](evidence/phase-13/linux-parser.txt),
[check summary](evidence/phase-13/validation.txt),
[changed-file inventory](evidence/phase-13/changed-files.txt).

| Command/check | Result | Actual result |
| --- | --- | --- |
| Initial `uv run alembic heads` | PASS | `0019_artifacts` |
| `uv run python scripts/validate_phase13.py --full` | PASS | 681 passed, one preserved strict xfail, zero skips; 403.70s; drift clean |
| Final `scripts/validate_phase13.py --browser` | PASS | 49 artifact/dataset tests; 8 browser workflows; zero skips; MinIO restart/init persistence |
| Final parser selection after empty-record hardening | PASS | 24 passed, 13 deselected; covers two added empty-object rejection cases |
| PostgreSQL fresh/previous-head upgrade and drift | PASS | Isolated schemas; source history retained through `0019` → `0020` |
| Real MinIO/source integration | PASS | All four dataset formats; immutable versions; repeated bootstrap; bytes survive restart |
| Python Ruff lint/format and strict mypy | PASS | Executed after implementation; final check summary records results |
| TypeScript typecheck and Prettier | PASS | Executed with supported Node |
| Studio Vitest | PASS | 39 passed across 8 files, including dataset and both binary BFF families |
| Studio production build | PASS | Next build compiled, types and generated routes passed |
| OpenAPI/TypeScript generation | PASS | Actual application export and openapi-typescript |
| Linux subprocess parser smoke | PASS | CSV/JSON/NDJSON/Parquet under Linux resource limit |
| Developer database preservation | PASS | Read-only revision is `0017_capacity` |
| Historical migration/fixture/evidence preservation | PASS | No modifications to historical files |
| Git whitespace/diff check | PASS | `git diff --check` |
| Standalone TypeScript lint | NOT SUPPORTED | No configured lint command; tsc/Prettier/build executed |
| Final production images/OKD/organizational acceptance | NOT RUN | Requires separate Section 23B approval, target environment and independent review |

The full suite ran before the final parser-admission/BOM/empty-record refinements. Its existing-domain
regression result is supplemented by the final targeted/parser/browser checks above; no claim is made
that 681 plus the later checks were a single combined full-suite run. No new tests were skipped or
assertions weakened. The sole strict expected failure is the pre-existing raw pySHACL compatibility
case, explicitly unsupported below.

Initial failures were corrected: the first parser-negative assertion omitted csv.Error; the first
sharing test unpacked its fixture incorrectly; an accidental default-shell Node invocation was too
old for Vitest and was rerun with supported Node; Prettier output was corrected. A redundant validation
run was interrupted to fix browser defaults; its child tests lost their disposable MinIO during
teardown and were stopped, then the complete final targeted/browser run passed. The new runner now
propagates interruption to children before tearing down infrastructure and defaults to durable browser
sessions and isolated test ports. No induced/interrupted failure is presented as passing evidence.

## fixtures/VALIDATION.md results

| Check | Result | Executed evidence |
| --- | --- | --- |
| Turtle parsing | PASS | Full fixture regression |
| CSV identities/counts/FKs and RDF/CSV consistency | PASS | Full fixture regression |
| Raw pySHACL compatibility | NOT SUPPORTED | Preserved strict expected failure: RDF simple/xsd:string mismatch |
| Normalized SHACL and negative cases | PASS | Full fixture/semantic regression |
| Open Ontologies SHACL | PASS | Pinned-engine full integration regression |
| OWL inference with supported `owl-rl-ext` | PASS | Existing CriticalMachine positive/noncritical-negative reasoning tests |
| Base `owl-rl` exact fixture axiom | NOT SUPPORTED | Preserved pinned-engine limitation; fixtures unchanged |
| PostgreSQL/FastAPI queries | PASS | Full real-database regression |
| Actions/reconciliation | PASS | Full regression |
| Polars operational ingestion | PASS | Full ingestion regression |
| Authorization and tenant isolation | PASS | Full existing plus dataset security tests |
| Protégé supported import/export | PASS | Full interchange regression and browser workflow |
| Manual desktop Protégé GUI inspection | NOT RUN | Requires desktop authoring session; no new ontology constructs introduced |

## Acceptance matrix

| Phase 13 criterion | Result | Evidence |
| --- | --- | --- |
| 1. First-class governed datasets | PASS | Resource/service/DB tests and browser creation |
| 2. Independent of ontology mapping | PASS | Dataset lifecycle creates no canonical ontology |
| 3. Stable rename/move identity | PASS | Service tests and generic registry regression |
| 4. Immutable versions | PASS | Direct SQL mutation/delete rejection and retained history |
| 5. Committed physical artifact reference | PASS | Composite FK and publication guard tests |
| 6. Four required formats | PASS | Real PostgreSQL/MinIO upload and Linux parser tests |
| 7. Deterministic documented discovery | PASS | Full-content parser tests and API contract |
| 8. Per-version schemas | PASS | Historical preview/schema differences retained |
| 9. Restart-safe/idempotent finalization | PASS | Restart boundary, retry and concurrent finalize tests |
| 10. Parser failures cannot publish | PASS | Failed state retained, preview denied; browser failure workflow |
| 11. Authorized bounded preview | PASS | Limit checks, sharing denial/revocation, storage-free cache test |
| 12. Immutable source provenance | PASS | Physical metadata/FK plus immutable result and audit |
| 13. Tenant/Project isolation | PASS | Dataset security and existing full security suites |
| 14. Sharing/revocation | PASS | Dataset service security, BFF guards and generic governance tests |
| 15. Studio dataset workflow | PASS | Final browser and frontend tests |
| 16. Migration/drift | PASS | Disposable fresh/upgrade and Alembic check |
| 17. Real PostgreSQL and MinIO | PASS | Final integration runner; private schema/volume cleanup |
| 18. Existing regressions | PASS | Full Python, frontend and eight browser workflows |
| 19. Documentation/ADR | PASS | ADR before implementation, API/README/roadmap/report/evidence |
| 20. No Phase 14 engine | PASS | Scope/diff inspection; no execution/mapping operations introduced |
| 21. Production blocked | PASS | Section 23B unchanged; no certification/deployment performed |

## Files and dependencies

Created: `datasets/{__init__,contracts,parser,routes,service}.py`, migration `0020_datasets.py`, dataset
backend tests, `features/datasets.tsx`, frontend dataset tests, `scripts/validate_phase13.py`,
`scripts/smoke_dataset_parser.py`, ADR 0038, API contract, this report and Phase 13 evidence.

Modified: resource model/type/governance readiness, Project resource authorization/discovery, shared
ArtifactService resource-kind adapter, API router and streamed transport middleware, Project Studio
integration and fixed binary BFF, frontend route/browser tests, generated OpenAPI/TypeScript, README
files and roadmap authorization addendum. Added PyArrow to API dependencies and locked 23.0.1. See
[exact inventory](evidence/phase-13/changed-files.txt) for every created/modified path.

## Limitations and Phase 14 prerequisites

- Intentional small-file validation; no large-file streaming execution platform. Parsing materializes
  only the bounded validation input/frame; preview never materializes the source. Mac RSS monitoring
  is soft, not kernel-enforced; replica-wide capacity/security certification remains future work.
- Nullability is observed, CSV inference can normalize numeric strings, JSON numeric widening can
  use floating-point semantics, and unsupported types fail rather than silently converting. Users
  needing exact types should use Parquet or explicit JSON strings. Preview is first-N inspection.
- No attach-existing-artifact workflow, schema-edit override, content transformation, arbitrary query,
  mapping, derived lineage, retention purge, dataset restore, upload resumable ranges or background
  validation scheduler. Interrupted byte transfer retries the immutable transport as in Phase 12.
- Committed failed sources retain storage indefinitely. Operational purge/retention and larger-data
  quotas need separate governed design; no deletion policy is silently applied to developer data.
- Existing upstream pySHACL compatibility, deprecation warnings and production readiness blockers are
  preserved. No external S3 provider/organizational SSO/target-cluster certification was performed.

Recommended next milestone, **not authorized or implemented**: separately scope Phase 14's engine-neutral
pipeline/run contract, immutable dataset-version inputs/outputs, deterministic schema/null/numeric
semantics, isolated execution, quotas/admission, failure-safe publication, retry/cancellation and real
lineage. Preserve PostgreSQL/service mutation authority and require separate approval. Stop at Phase 13.
