# Phase 22 implementation and validation

Baseline revision `f4f8d45` plus the Phase 22 working tree. Local verification uses
macOS arm64, Python 3.12, disposable PostgreSQL 18.3, a signed browser test IdP,
and separate local Keycloak 26.8.1 and MinIO containers. The runtime regression
profile uses a non-superuser database owner. No deployment or external
resource changes were performed.

## Implemented

- First-login provisioning reuses the exact verified Keycloak issuer and subject,
  serializes creation with the existing identity-registration paths, and writes
  personal ownership, membership, roles, and the onboarding audit event in one
  PostgreSQL transaction. Read-only tenant discovery lists personal membership first.
  Studio selects that tenant on successful onboarding and offers a retry on failure.
- Tenant memberships and roles stay scoped. An accepted Viewer or Collaborator
  invitation can address a principal or a recipient tenant. The server derives the
  authoritative owner from the target and applies the owner policies. Studio provides
  inbound and outbound share lists, acceptance, revocation, owner attribution, and a
  scoped Project or Ontology view. The API and generated client contracts expose these
  operations.
- Workers verify the existing Keycloak service actor before looking for work. Claims
  use the tenant and ontology attached to due records. The existing lease, job grant,
  Project, ABAC, and attempt fencing checks govern execution. Explicit tenant
  permission remains necessary for outbox delivery. Shipped worker commands no longer
  require a startup tenant or ontology. Personal workspace onboarding can provision a
  bounded worker role for the configured issuer and service subject.

## Migration

`0029_personal_tenants` is additive and forward-only. Its ownership key enforces one
personal tenant per principal. It adds resource shares, audit correlation, and
partial worker indexes. Existing tenant, principal, membership, Project, ontology,
catalog-share, and job-grant records retain their identifiers. New tenants and grants
are created only by their governed API paths. The [OKD4 runbook](../operations/phase-22-okd4.md)
covers a coordinated upgrade, queue handling, backups, and recovery to a pre-upgrade
database and artifact checkpoint.

## Changed files

| Area | Files |
| --- | --- |
| Database and API | `services/api/migrations/versions/0029_personal_tenants.py`, models and readiness under `db/`, application configuration and dependencies, security identity/onboarding/sharing/role/audit/authorization modules, Project governance and query cursor binding |
| Workers | `security/workers.py`, `security/job_grants.py`, ingestion and semantic entry points, `execution/worker.py`, `jobs/supervisor.py`, outbox and webhook entry points, `scripts/run_execution_worker.py` |
| Studio | Auth callback, BFF, workspace and `features/sharing.tsx`, browser session and API wrappers, and generated OpenAPI and TypeScript contracts |
| SDKs | Platform SDK transport, generated TypeScript endpoints/schema and React hooks, SDK generator and generated ontology Python/TypeScript runtime templates |
| Infrastructure | OKD base ConfigMap and ingestion/semantic/outbox Deployments, production Compose and environment example |
| Tests and harnesses | `services/api/tests/test_phase22.py`, security and worker regression fixtures, head revision assertions, Studio auth/BFF/share tests, Playwright sign-in and sharing specs, capacity regression, Keycloak and MinIO worker harnesses, SDK transport tests |
| Documentation | `PLANS.md`, `README.md`, migration notes, this report, API and architecture guides, ADR 0049, worker documentation and the Phase 22 OKD4 runbook |

## Architectural decisions and limitations

The [architecture guide](../architecture/personal-tenants-and-sharing.md) and
[ADR 0049](../decisions/0049-personal-tenants-and-shared-work.md) describe transaction and
authorization boundaries. The [API guide](../api/tenant-sharing.md) specifies the
share lifecycle and operations. Ownership transfer remains disabled. Project shares
cover metadata and folders. Independently governed resources keep their own access
paths. Shared-resource jobs, exports, and downloads remain outside share authority.
Execution and automation retain explicit Project authorization. Ingestion uses
existing tenant-scoped source registrations. The OKD base does not add an execution
controller Deployment.

## Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Turtle parsing, CSV identity and foreign keys, RDF/CSV identity and cardinality | PASS | `test_fixtures.py` |
| RDF 1.1 SHACL conformance and fixture mutations | PASS | Normalized pySHACL checks and the pinned Open Ontologies adapter. |
| Raw pySHACL conformance | FAIL | Existing strict expected failure for simple versus typed string terms in RDFLib. |
| OWL reasoning | PASS | Open Ontologies 2.1.0 `owl-rl-ext` inferred the three fixture CriticalMachines. The executable matched the pinned macOS arm64 SHA-256. |
| CriticalMachine inference with base `owl-rl` | NOT SUPPORTED | The pinned base profile lacks this fixture's hasValue/intersection rule. |
| PostgreSQL clean and populated upgrade, schema drift | PASS | `0029_personal_tenants`, the pre-upgrade catalog share and queued grant case, and `alembic check`. A logical backup restored into two disposable databases verified both the forward upgrade with existing records and recovery at revision 0028. |
| Phase 22 API, isolation and workers | PASS | All five PostgreSQL cases passed. They cover concurrent onboarding and claims, repeat sign-in, membership selection, direct and tenant shares, ABAC, revocation, shared-query/aggregate/traversal bounds, two-tenant ingestion and semantic jobs, and tenant-scoped outbox delivery. |
| FastAPI object queries | PASS | The PostgreSQL share tests exercise ordinary object queries, traversal, aggregation, property denial, and isolation. |
| Targeted actions and reconciliation checks | PASS | The isolated maintenance action passed with transactional links and idempotent retry. The broad action run reported separate failures under concurrent validation. |
| Polars manufacturing ingestion | PASS | The isolated full-fixture check completed with 63 objects and 70 links. Repeating the load made no changes. The browser reference workflow passed against the built Studio app. |
| Existing worker security regressions | PASS | Executed grant expiry, revocation, lease recovery, mismatched context, Project permission, and scheduler checks. An isolated rerun passed consumed grants, API/worker owner startup, the ingestion and semantic CLIs, and the execution controller. |
| Ontology import/export | PASS | The API round-tripped supported fixture vocabulary with deterministic export. |
| Interactive Protégé compatibility | NOT RUN | The local API integration tests exercised OWL import/export. No Protégé desktop session was started. |
| Full Python regression in the non-superuser owner profile | PASS | 953 passed, 139 skipped, one documented SHACL expected failure. Four connector tests excluded from this invocation passed separately with their required role-creating setup account. The MinIO worker suite covered the storage-dependent paths. |
| Studio scoped functional tests | PASS | 73 auth, route and sharing tests. |
| Playwright on built Studio | PASS | Four tests passed on the standalone Studio deployment. They cover first and repeat sign-in, tenant selection, the share lifecycle, the manufacturing reference workflow, and CSRF and unauthenticated denial. |
| Studio broad regression | PASS | All 100 Vitest tests passed, including the Observability selector and Workspace selection-race regressions. The standalone build passed. |
| Platform SDKs and generated contracts | PASS | 64 TypeScript/React SDK tests, 24 Python SDK generation and startup checks, package builds, Studio and workspace TypeScript type checks, and generated contract drift check. |
| Python lint, formatting and types | PASS | Ruff, mypy and `git diff --check`. |
| Deployment configuration | PASS | Kustomize rendered and validated the 18-resource OKD overlay and the migration Job. The local Compose settings parsed. |
| MinIO-backed workers and pipelines | PASS | 639 passed with real MinIO, plus the documented SHACL expected failure. Four PostgreSQL connector fixtures required a role-creating setup account and passed separately. The disposable MinIO profile verified persistence across restart. A separate eight-case run passed all five Phase 22 API tests and all three built-SDK integration tests with MinIO. |
| Local Keycloak 26.8.1 | PASS | `scripts/test_keycloak.py --phase22` exchanged a real Studio authorization code with PKCE. The signed realm role onboarded one tenant, repeat onboarding reused it, and the actual worker token was denied onboarding. The service's exact subject was enrolled in the personal tenant. |
| Target OKD4 admission and target Keycloak rollout | NOT RUN | Requires separate authorization for the target. Local tests used disposable PostgreSQL, Keycloak and Studio services. |
| Ownership transfer and share-only job submissions | NOT SUPPORTED | The API exposes no transfer operation and rejects worker submissions made through resource shares. |

The interim runs hit action and ingestion deadlines and Studio development-server
startup timeouts. The follow-up used the standalone Studio build and completed the
full manufacturing fixture. The capacity test now uses the approved worker service
role and asserts the quota constraint error before validating rollback. The built-SDK
fixture now assigns its worker Project editor membership and exercises the real execution
controller. The PostgreSQL
connector fixture requires temporary read-only login roles, so those four tests pass
under the disposable setup account in a separate invocation.

## Reproducing the local acceptance checks

Use disposable PostgreSQL databases for both the non-superuser runtime owner and
the separate connector setup invocation. Set `TEST_DATABASE_URL` for each invocation.
Set `OPEN_ONTOLOGIES_BIN` to the verified executable for Python and browser validation.

- Run `FOUNDRY_ARTIFACT_BACKEND=disabled uv run pytest -ra --ignore=services/api/tests/test_ingestion_postgres.py`
  as the disposable runtime owner. Run `uv run pytest services/api/tests/test_ingestion_postgres.py`
  under the disposable account that can create test roles.
- Run `uv run python scripts/validate_phase14.py --workers` with the local MinIO images.
  To split the connector cases from that invocation, set
  `PYTEST_ADDOPTS=--ignore=services/api/tests/test_ingestion_postgres.py`. Add
  `--worker-selection "test_phase22 or test_platform_sdk"` for the focused storage run.
- Build Studio with `npm --prefix apps/studio run build`. Run
  `STUDIO_E2E_DURABLE=true uv run python scripts/test_studio.py personal-tenant.spec.ts`
  for the Phase 22 browser scenarios. The observed reference pass also selected
  the manufacturing and CSRF cases from `workflow.spec.ts`.
- Run `FOUNDRY_ARTIFACT_BACKEND=disabled uv run python scripts/test_keycloak.py --phase22`
  with the pinned Keycloak image cached locally.

## Recommended next phase

Schedule a separately approved OKD4 rollout rehearsal and target acceptance.
Use the target's namespace, image digests, Keycloak configuration and database and
artifact recovery checkpoints. The local evidence supports the rehearsal. Target
admission and release decisions depend on the results of that rehearsal.
