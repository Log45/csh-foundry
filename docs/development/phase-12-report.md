# Phase 12 — S3-compatible artifact storage and immutable artifacts

Date: 2026-11-03. Base revision: `6143049`; implementation changes are uncommitted.
Scope: explicitly authorized milestone B / Phase 12 only. Phase 13 is not authorized or implemented.
Status: **PASS — Phase 12 implementation and local development acceptance complete.**
External/fresh-host validation limitations are explicitly recorded below; no production claim.
Production: **BLOCKED / NOT PRODUCTION-CERTIFIED**, unchanged Section 23B gates.

## Design and functionality

[ADR 0037](../decisions/0037-immutable-artifact-storage.md) was written before substantial implementation.
The logical artifact is an `ARTIFACT` registry resource, using Phase 11's Project ownership, folders,
sharing, revocation, archive, current tenant permissions and explicit memberships. PostgreSQL remains
metadata authority; no second hierarchy, identity provider, policy engine, sharing table or database.

The typed ArtifactStore contract separates opaque ObjectKey, physical metadata and categorized storage
failures from API/service code. The S3 adapter uses pinned boto3/botocore contracts, verified against
actual installed SDK models and current AWS API documentation. It supports endpoints, regions,
path/virtual addressing, CA trust, credential injection/SDK discovery, bounded timeouts/retries,
conditional writes, multipart/abort, streaming reads, head/existence, full read-back SHA-256,
exact-key deletion and optional short-lived single-object GET capabilities. No ETag checksum shortcut.
There is no filesystem production adapter or provider endpoint supplied by clients.

`0019_artifacts`, after actual head `0018_projects`, adds immutable artifact_versions. Resource ontology
columns become nullable **only** for the new ARTIFACT kind; type/authority checks and the existing
ontology trigger continue protecting all historical references. Composite tenant/resource FKs, unique
sequences and physical addresses, key-format/state/checksum constraints and an immutable-history
trigger enforce identities and legal transitions. Committed rows cannot be updated or deleted.
The migration is strictly forward-only, even for an unused installation. Existing migrations and
canonical fixtures are unchanged. Read-only checks confirm the shared database remains `0017_capacity`.
Only disposable schemas were migrated. Clean/head drift and upgrade from existing Phase 11 resources
are tested, including preserving canonical references and historical operational/security data.

A version reserves an opaque tenant/artifact/version key and monotonic sequence under the existing
tenant lock. Its states are PENDING → COMMITTED or FAILED → DELETED. Registry state is ACTIVE or
ARCHIVED. A content change creates a new version; committed bytes cannot be replaced by the API.
Version metadata includes immutable size, SHA-256, octet-stream media type, validated display filename,
creator/time, commit time and bounded source provenance. Bucket/backend/key stay internal. Configuration validation errors hide
input values, and a regression test verifies credential strings do not enter their error text.

Upload initiation commits independently before streaming bytes. The API authorizes before reading,
spools to disk under the declared/configured size bounds, calculates SHA-256 itself and reauthorizes
before storage. A simulated client disconnect leaves PENDING metadata and no uploaded object.
Storage success does not publish a version. Finalization independently verifies stored
size and full checksum, clears abandoned exact-key multipart sessions and atomically commits metadata.
Retrying finalization returns the same committed version. Retry transfer verifies already-present
immutable bytes after a storage-success/database-failure window. Missing/corrupt/incomplete objects
cannot commit. Process restarts reconstruct state from PostgreSQL; no in-memory upload authority.

Cleanup is explicit, owner-only and dry-run by default. It selects at most 100 old PENDING/FAILED
versions, serializes with finalization, records failure before deletion, aborts exact-key sessions and
retains DELETED history. Failures return retry and audit decisions/outcomes; another run converges.
Committed data has indefinite retention and is never selected. Archive retains bytes/history; cleanup
can still maintain abandoned uploads under an archived Project. No prefix deletion or scheduled purge.

## Governance, API and Studio

The versioned [artifact API](../api/artifacts.md) provides creation, initiation, bounded binary transfer,
finalization, metadata/history, download, optional presign and owner maintenance. The existing resource
endpoints provide browse/search, direct metadata, rename/move, sharing and archive. Pagination and
search are bounded; inaccessible IDs do not disclose private resources. Generic artifacts do not need
an ontology/schema:read; ontology resources remain independently authorized and filtered before
pagination. All operations use existing GovernedService/ProjectService/PlatformAuthorizer boundaries
and authorization_audit, with committed artifact mutation/download/capability/deletion events.

Downloads verify into bounded disk storage before headers, then stream as attachment with nosniff and
no-store. Artifact binary routes bypass the old request/response memory buffering while retaining a
60-second deadline; other routes keep their existing bounds. MIME claims are ignored; generic bytes
are always application/octet-stream. No file is executed, rendered or parsed as a dataset.

Studio extends the existing Project/folder resource view with artifact creation, a 64 MiB file upload,
checksum/upload/verification stages and failure messages, metadata and paginated version history,
exact-byte download, archive and sharing controls. The separate fixed-path binary BFF enforces durable
session, CSRF, selected tenant and expected-tenant checks, UUID validation, size/deadline limits and
sanitized errors. Tokens remain server-only; no storage credentials or unrestricted endpoints reach
browser code. OpenAPI and TypeScript contracts are regenerated from the real FastAPI application.

## MinIO and deployment configuration

Opt-in Compose services use immutable server/client digests, a dedicated named volume, health checks
and idempotent init. Three private buckets are prepared (generic artifacts, reserved datasets/media),
with a separate scoped application user permitted only the generic-artifact bucket. No s3:* grant.
Init never deletes data or users; credential reconciliation supports leading-dash secrets without
option parsing or credential-command output. Tests deliberately exercise this case. Base Compose
publishes no MinIO ports; a separate loopback-only optional overlay supports host-run development.
Ontology-only development does not start or require storage. API storage is disabled by default.

[Storage operations](artifact-storage.md) documents all settings, local startup/persistence/cleanup,
SDK credential sources, TLS/CA verification, externally managed S3 for OKD4, private network access,
retention, backup/recovery and provider compatibility. No organizational deployment was performed.
The tested server is RELEASE.2025-09-07T16-13-09Z; mc is RELEASE.2025-08-13T08-35-41Z, verified through
actual version output. Cached upstream immutable images were used. Remote image supply is a limitation
listed below; no floating tags, insecure TLS workaround or unreviewed replacement images were added.

## Executed validation

Environment: macOS arm64, Python 3.12.0, uv, Node v25.9.0 from `/opt/homebrew/opt/node/bin`, Docker 28.3.0,
real PostgreSQL 17.6 and isolated real MinIO; boto3/botocore 1.43.123. Semantic tests use the existing pinned Open Ontologies
v2.1.0 contract and binary. All test schemas/buckets/volumes belong to disposable random test projects.
No shared database upgrade, volume reset, credentials commit or production mutation occurred.
[Validation evidence](evidence/phase-12/validation.txt) and the
[exact changed-file inventory](evidence/phase-12/changed-files.txt) accompany this report.

| Command / check | Result | Actual evidence |
| --- | --- | --- |
| `uv run alembic heads` before changes | PASS | `0018_projects (head)` |
| `uv run python scripts/validate_phase12.py` | PASS | 14 artifact tests; repeated initialization; sentinel retained across MinIO restart |
| `uv run pytest -m pre_artifact` with TEST_DATABASE_URL and pinned semantic binary | PASS | Seven historical migration tests, 645 deselected |
| Full `scripts/validate_phase12.py --full` | PASS | 651 passed, one preserved strict xfail, zero skips/failures; 425.06 seconds; no schema drift |
| `scripts/validate_phase12.py --browser`, STUDIO_E2E_PORT=3100/API_PORT=8101 | PASS | Six browser workflows, 39.0 seconds; 14 artifact tests also pass |
| Same runner with STUDIO_E2E_DURABLE=true, replica port 3101 | PASS | Seven production-build browser workflows, 36.4 seconds; replica restart/logout plus exact-byte artifact workflow |
| `npm --prefix apps/studio test` with Node >=22 | PASS | 37 tests across seven files |
| `npm --prefix apps/studio run build` with Node >=22 | PASS | Next production build includes binary BFF route |
| Ruff check / format, mypy, tsc, Prettier | PASS | Executed checks; final evidence retained below |
| OpenAPI export and TypeScript generation | PASS | Actual app schema exported; openapi-typescript executed |
| Guarded MinIO startup and final storage rerun | PASS | Missing credentials rejected; valid credentials/init/restart and all 14 tests pass in 8.83 seconds |
| Disabled-profile Compose inventory | PASS | Only postgres without profiles; no MinIO credentials required |
| Shared developer revision, read only | PASS | Remains `0017_capacity` |
| Fresh upstream image pull | FAIL | Docker Hub denied; Quay 401; legacy binary URLs 410; cached exact digests run successfully |
| Fresh-host image provisioning | NOT RUN | Requires trusted cached image archive/mirror or separately reviewed pinned replacement |
| Live AWS/external organizational S3 and OKD4 | NOT RUN | No external credentials/resources or deployment approval; configuration contracts are locally tested |
| Standalone TypeScript lint | NOT SUPPORTED | Repository uses tsc/Prettier/build; no standalone frontend lint command |

The initial full run was 642 passed / seven failed / one preserved strict xfail; all seven failures
were legacy tests attempting to downgrade through the newly forward-only head. They now explicitly
start at pre-artifact schemas via the pre_artifact marker and retain their original assertions.
A subsequent full run was 645 passed / one strict xfail / six setup errors from one remaining
`database_fixture` alias that called the newly request-aware helper without its request argument.
That wrapper was corrected; all six cross-service security workflows then passed a targeted run.
The final full-suite result below supersedes those initial failures without hiding them.
No test is disabled, changed to a permissive xfail or represented as passing without execution.
The first browser attempt correctly refused an occupied port; the existing service was not stopped.
An initial initializer failure with a randomized leading-dash password was fixed and deliberately
covered by subsequent real initialization. The default shell's obsolete Node 16 failed Vitest;
subsequent frontend commands use the installed supported Node runtime. These corrected setup failures
are not hidden or substituted for final results.

## Acceptance matrix

PASS below is scoped to implemented development behavior, not unexecuted external certification.

| # | Phase 12 acceptance criterion | Result | Evidence / qualification |
| --- | --- | --- | --- |
| 1 | Typed ArtifactStore implemented/tested | PASS | Adapter, SDK model and transport tests |
| 2 | Working S3-compatible backend | PASS | Exact bytes, head, size/hash, missing/corrupt objects, multipart, retry/timeout/TLS |
| 3 | Opt-in local MinIO starts | PASS | Actual digest-based Compose startup using cached images; fresh pulls fail as recorded |
| 4 | Non-destructive repeatable bucket init | PASS | Init three times, including after restart with existing sentinel |
| 5 | Ontology-only development without MinIO | PASS | Disabled-profile inventory and disabled-storage Project service test |
| 6 | Phase 11 registry integration | PASS | Generic resource plus preservation of historical canonical references |
| 7 | Committed versions immutable | PASS | Conditional single/multipart writes; DB update/delete rejection; two versions |
| 8 | Restart-safe, idempotent finalization | PASS | Reconstructed service, repeated transfer/finalize, abandoned multipart recovery |
| 9 | PostgreSQL/S3 partial failure handling | PASS | Missing/corrupt objects denied, retry after bytes-before-finalize, cleanup failure/retry |
| 10 | Tenant and Project authority | PASS | Existing security plus direct IDs, member/write checks and tenant-safe FK tests |
| 11 | Sharing and revocation | PASS | Existing Project shares; read-only consumer; revocation denies subsequent access |
| 12 | Narrow presigned access and limitations | PASS | SDK single-object GET/expiry tests, default-disabled client access, documented bearer revocation window; live external HTTPS retrieval NOT RUN |
| 13 | Safe lifecycle/retention | PASS | Archive retains bytes; cleanup dry-run/retry/idempotence and committed exclusion |
| 14 | Studio artifact workflows | PASS | Actual authenticated browser upload/two versions/exact-byte download/archive |
| 15 | Migration upgrade and drift | PASS | Existing Phase 11 references retained, cross-tenant constraints, Alembic check |
| 16 | Real MinIO coverage | PASS | Single/multipart transfers, abort/recovery, init and persistence through restart |
| 17 | Existing regression suites | PASS | Full Python 651 passed / one strict xfail, 37 frontend tests, six dev and seven durable browser workflows |
| 18 | Documentation and ADR | PASS | ADR 0037, API/operations/report, README/Studio docs and roadmap authorization addendum |
| 19 | No Phase 13 | PASS | No dataset schema/catalog, preview, query or transformation implementation |
| 20 | Production remains blocked | PASS | Section 23B gates preserved; no deployment/certification |

## fixtures/VALIDATION.md

The validation guide was consulted before implementation completion. Results refer to executed
regression tests and the existing pinned semantic engine, not a newly invented reasoner API.

| Check | Result | Evidence |
| --- | --- | --- |
| Turtle parsing | PASS | test_fixtures parses all canonical graphs |
| CSV identities, counts, foreign keys and RDF consistency | PASS | test_fixtures; expected 6/20/12/25 and 63 typed instances |
| Raw pySHACL compatibility | NOT SUPPORTED | Preserved strict xfail for RDF simple/xsd:string term mismatch |
| Normalized SHACL / negative mutations | PASS | Fixture and semantic tests |
| Open Ontologies SHACL | PASS | Pinned engine semantic tests |
| OWL reasoning with owl-rl-ext | PASS | CriticalMachine inference and exclusion checks |
| Fixture axiom under base owl-rl | NOT SUPPORTED | Existing documented profile limitation; fixtures unchanged |
| PostgreSQL/FastAPI operational queries | PASS | Full regression |
| Actions and reconciliation | PASS | Corrected historical migration tests and final action suite pass |
| Polars ingestion | PASS | Full regression, including recovery and manufacturing reference workflow |
| Authorization/tenant isolation | PASS | Full regression and focused artifact security/cleanup error-disclosure checks |
| Protégé supported import/export | PASS | Initial executed full regression; unchanged interchange code |

## Limitations and architectural tradeoffs

- Fresh upstream MinIO image retrieval failed. A new host needs the exact trusted cached images or
  reviewed mirror/replacement; only local cached-digest startup is claimed. Other host architectures
  and production vulnerability/capacity certification are NOT RUN.
- Existing tenant/security locks span bounded storage work to serialize revocation/finalization.
  This can block Project operations or hit lock timeouts; no throughput/scaling claim. API temporary
  disk space is bounded per transfer, not globally; operators must provision concurrent capacity.
  File limits do not constitute tenant-wide object-storage quotas.
- Committed versions are retained indefinitely; no purge/restore or reference-graph manager is
  implemented. Future consumers must reference committed immutable versions. There is no automatic
  maintenance scheduler. Interrupted uploads can consume storage until explicit owner cleanup.
- Download verification reads the complete object before streaming. This uses bounded temporary disk
  and adds latency. API uses artifact.bin; Studio saves the validated display filename. MIME is always
  octet-stream. No malware scanning, parsing, execution, media preview or dataset feature is claimed.
- Studio uses bounded browser memory for checksum/download and stages rather than numeric transfer
  percentages. It can retry finalization; restarting a failed file selection creates a new pending
  version. The API supports same-version transfer retries with the retained initiation ID.
- Conditional S3 writes and read-after-write verification are provider requirements. A changed bucket
  or backend fails closed for old versions; storage relocation needs a separate verified migration.
  No claim is made that privileged out-of-band object-store operators cannot corrupt bytes; reads
  detect missing/corrupted bytes. No public bucket policies or end-user storage credentials are used.
- Presigned capabilities can outlive membership/share revocation until expiration. Only explicitly
  client-reachable HTTPS configurations permit them; internal storage uses governed mediated transfer.
- Live external provider, organizational network, backups/DR, IAM/encryption operations and deployment
  certification remain NOT RUN and subject to Section 23B. No release gate was weakened.

## Files created and modified

Created: artifact module `{__init__,config,contracts,storage,s3,service,routes}.py`, migration
`0019_artifacts.py`, `test_artifacts.py`, `scripts/validate_phase12.py`, Studio
`features/artifacts.tsx` and `app/bff/artifacts/route.ts`, MinIO `{start.sh,init.sh,artifacts-policy.json,
localhost.yaml}`, ADR 0037, API artifact docs, storage operations guide, this report and validation evidence.

Modified: db models/governance, app wiring and transport bounds, Project contracts/service, API
pyproject and uv.lock, root pyproject/.gitignore/PLANS/README, Studio Project/workspace components,
regenerated OpenAPI/TypeScript, routes/E2E tests and backend fixture, Studio/API README files.
Historical migration tests and their fixture wrappers/benchmark/smoke direct generator callers were
updated to propagate pytest request context or explicitly pass None; historical migration files and
assertions are unchanged. The marker starts historical rollback tests at `0018_projects`, while
normal tests and the new upgrade/drift tests exercise `0019_artifacts`.

## Recommended next phase — not authorized or implemented

Phase 13 should separately approve independent dataset catalog/upload/schema/version contracts,
consumer references to committed artifact versions, storage quotas, tabular content policies, schema
registration/provenance and isolated integration tests. Dataset preview/query/profiling and Polars
pipelines require their own approved scope. Keep dataset identity independent of an existing ontology.
Resolve fresh-host MinIO image supply before onboarding another developer host. Production requires
all deferred Section 23B gates; this phase does not grant production or Phase 13 authorization.
