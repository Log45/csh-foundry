# Existing-owner runtime support and validation

Approved task: consistent owner-role exception for the permanent single-account OKD4 constraint.
Date: 2026-11-08. Base revision: `c6756ce`; changes are uncommitted in this checkout.

## Implemented behavior

`FOUNDRY_ALLOW_OWNER_RUNTIME_ROLE=true` now consistently permits the existing PostgreSQL owner
account for API and worker runtime. Migration and runtime use the same existing database URL.
No second application database role, CREATEROLE permission, administrator URL or post-migration
runtime table-grant refresh is needed in this mode. Default-false non-owner mode remains supported.

The exception is centralized in `db/session.py::require_runtime_role`. It covers ownership only:
SUPERUSER, CREATEDB, CREATEROLE and REPLICATION flags remain rejected. API startup always calls
the validator, correcting the earlier flag behavior that skipped the whole check. All worker
startup/refresh paths pass the same configured value. OIDC discovery/signature verification,
service-principal type and permission checks still execute. No authorizer, grant validator, tenant
predicate, revocation/fencing code, constraint or immutable trigger is bypassed or disabled.

| Inspected path | Result |
| --- | --- |
| API lifespan | Calls the common validator with configured owner exception, then OIDC warm-up |
| Ingestion CLI | Shared `worker_context` gate; actual authorized ingestion completed using owner login |
| Semantic CLI | Shared gate; actual pinned-engine semantic job completed using owner login |
| Outbox and webhook entry points | Both use the shared worker gate; real signed service-token startup checked |
| Execution controller | Shared gate at startup and credential refresh; actual controller loop completed a function job |
| Alembic environment | Already permits DDL by the existing owner; no role-separation exception needed |
| OKD migration utility | Same owner URL, configured schema, advisory lock, upgrade and drift check; checked on real PostgreSQL |
| Provisioning utility | Owner path verifies account only; no CREATE ROLE/DATABASE, GRANT/REVOKE, admin URL or secrets-path requirement |
| Optional load validator | Owner branch reuses configured connection; skips creating and dropping a separate runtime login |
| Disposable Compose acceptance role probe | Passes its configured flag to common validator; its named-role password-rotation assertions are specific to that separate-role test fixture, not OKD startup policy |
| Historical shared-development migration preflight | Fixed target database/username assertions identify its specific local installation, not role separation; unchanged |
| PostgreSQL ingestion connector | Independent read-only source credential policy remains unchanged and rejects a writable owner source even with the runtime flag enabled |

## Database and rollout

No new database migration was introduced. **0028_job_execution_grants is unchanged**. The disposable
suite applied migrations, including a real legacy upgrade to 0028, and executed runtime operations
using the same non-superuser application database owner. Grant scope mutations and audit deletion
still fail under that owner through the existing triggers.

The Kubernetes base ConfigMap explicitly enables owner mode; API, ingestion/semantic/outbox workers
and the separately rendered migration Job reference that shared configuration. The production Compose
alias forwards the flag to API/workers, retaining false as that profile's default. Environment examples,
Secret instructions, operator rollout and migration documentation distinguish owner mode from existing
non-owner deployments. Owner mode no longer requires separate runtime grants or credential files.

For the existing installation:

1. Keep the existing owner account and configure its URL in the API, worker and migration Secret
   mounts. Different Secret object names may contain the same URL; they do not imply different roles.
2. Set `FOUNDRY_ALLOW_OWNER_RUNTIME_ROLE: 'true'` in the shared `foundry-config` ConfigMap.
3. During the approved maintenance window, run migrations with the same owner URL and application
   schema, then restart matching API/worker images with the shared setting. The migration command
   still serializes changes and checks drift. Do not disable constraints or triggers.
4. Skip the separate-role runtime-grants refresh. Verify readiness, service authentication, user job
   processing, both audit identities, revocation and fencing using the existing platform roles.

See [OKD4 deployment](../operations/okd4-deployment.md),
[worker rollout](../operations/dynamic-workers.md) and [ADR 0048](../decisions/0048-owner-runtime-role.md).
No target deployment, shared PostgreSQL migration, existing-role alteration or external resource
change was performed.

## Executed validation

Consulted `fixtures/VALIDATION.md`. The reproducible command is:

```bash
uv run python scripts/validate_owner_runtime.py
```

The harness creates a private Unix-socket-only PostgreSQL cluster. Its test bootstrap initializes
one application owner without elevated flags; **every application migration and runtime connection
uses that same owner**. The bootstrap is only test setup and is not a second target runtime account.
The harness isolates the database and disables remote artifact storage for this test run. PostgreSQL
is stopped and the private cluster removed afterward.

Final result: **167 passed, 1 skipped, 1 expected xfail** in 59.05 seconds on PostgreSQL 18 / Python 3.12.
Counts include owner-specific unit/integration cases and existing job, security, recovery, semantic,
fixture and deployment regressions. Initial test setup/rendering issues were corrected before this
final successful run; no unresolved test failures remain.

| Check | Result | Evidence |
| --- | --- | --- |
| Ownership/privilege matrix | PASS | Both flag values, owner/non-owner catalog states and elevated privileges tested; env loading/default false checked |
| Production API owner startup | PASS | Same owner with flag disabled rejects; enabled reaches ready; valid signed token succeeds, missing authentication/cross-tenant requests reject |
| All worker startup types | PASS | Ingestion, semantic, execution and outbox accept owner opt-in and reject disabled mode, while validating signed service tokens and Foundry permissions |
| Entry-point execution | PASS | Real ingestion/semantic CLI `main()` and execution-controller `main()` plus refresh and function completion |
| Worker authentication failures | PASS | Missing credentials, invalid token, human identity and denied service permissions still reject in owner mode |
| Migration 0028 and schema drift | PASS | Same-owner migrations and migration utility upgrade/drift check, configured schema and advisory-lock regressions |
| Immutable grants/audit | PASS | Normal owner UPDATE of grant operations and DELETE of authorization audit reject through unchanged triggers |
| Provisioning without admin URL | PASS | Verification-only owner mode executes with no admin URL or separate grant refresh; unit test prohibits admin connection |
| Shared Alice/Bob jobs, grants, revocation/fencing | PASS | Existing `test_job_execution.py`, security workflows/platform and ingestion recovery tests run on same unprivileged owner |
| Kubernetes/Compose propagation | PASS | Shared ConfigMap references and both Compose flag modes, including outbox profile, tested |
| Turtle parsing / CSV IDs, counts and FKs | PASS | Executed canonical fixture tests |
| SHACL normalized conformance/negative cases | PASS | Executed RDF 1.1 normalized fixture and negative tests |
| Raw pySHACL compatibility | FAIL, expected existing xfail | Existing simple-literal/xsd:string `sh:in` mismatch; not claimed as passing raw SHACL |
| OWL reasoning / semantic adapter | PASS | Pinned Open Ontologies 2.1.0 tests including manufacturing inference, input reauthorization and crash recovery |
| PostgreSQL integration / FastAPI authorization | PASS | Real owner-backed fixtures and production readiness/authentication/tenant-boundary requests |
| Actions/reconciliation and Polars ingestion | PASS | Governed ingestion/edit workflows and bounded recovery tests executed through existing security workflows |
| MinIO-backed multi-user pipeline publication | NOT RUN | One existing storage-dependent test explicitly skipped; no MinIO instance in this isolated owner-role harness. Controller startup and function execution were executed. |
| Interactive Protégé / full import-export regression | NOT RUN | No affected authoring contract; no interactive session or full import suite run for this task |
| Full load benchmark / full container acceptance preset | NOT RUN | Utilities linted; no performance or container-production-certification claim |
| Target OKD4 SCC/TLS/live Keycloak rollout | NOT RUN | No target deployment authorized/performed; real JWT cryptography uses test-owned discovery/JWKS transport |
| Strict mypy | PASS | No issues in 165 source files |
| Ruff lint / formatting | PASS | Changed runtime/scripts/tests pass; 13 selected files formatted |
| Diff integrity | PASS | `git diff --check` |

Known limitations: the owner connection is a trusted backend credential; elevated PostgreSQL flags
are deliberately outside this ownership exception. Existing raw SHACL compatibility behavior is
unchanged. Target rollout remains an operator action, with no requirement to obtain another role.
Recommended next step: apply the documented ConfigMap/image rollout with the existing account and
run target readiness/job smoke checks. No additional roadmap phase was implemented.

## Files created or modified
- `PLANS.md`
- `docs/api/security.md`
- `docs/architecture/migrations.md`
- `docs/decisions/0048-owner-runtime-role.md`
- `docs/development/owner-runtime-report.md`
- `docs/operations/dynamic-workers.md`
- `docs/operations/okd4-deployment.md`
- `docs/operations/okd4-infrastructure-request.md`
- `docs/operations/production.md`
- `infrastructure/kubernetes/base/configmap.yaml`
- `infrastructure/production/compose.yaml`
- `infrastructure/production/environment.example`
- `scripts/accept_phase10.py`
- `scripts/load_phase10.py`
- `scripts/migrate_kubernetes.py`
- `scripts/provision_production_database.py`
- `scripts/validate_owner_runtime.py`
- `services/api/src/ontology_platform/config.py`
- `services/api/src/ontology_platform/db/session.py`
- `services/api/src/ontology_platform/main.py`
- `services/api/src/ontology_platform/security/workers.py`
- `services/api/tests/test_kubernetes.py`
- `services/api/tests/test_owner_runtime_override.py`
- `services/api/tests/test_owner_runtime_postgres.py`
- `services/api/tests/test_production_profile.py`
