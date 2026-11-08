# Dynamic shared-worker implementation and validation

Approved task: dynamic multi-user worker execution and job-scoped delegation, 2026-11-08.
Base revision: `66fe6a5`; implementation is uncommitted in this checkout.
Environment: macOS, Python 3.12, real local PostgreSQL, disposable MinIO containers, installed
Node 24.14.0 for SDK checks, pinned Open Ontologies 2.1.0
(`ef6e781c71aaccaa35c2a1cd06169f0c862d5769`).

## Architecture and functionality

Worker authentication now resolves only the OIDC service principal. Ingestion/semantic queues
select across submitting users within the explicitly configured tenant/ontology; per-job authority
comes from immutable durable grants created in authorized admission transactions. The execution
controller also authenticates as a service and resolves initiating identity from grants rather than
its historical serialized principal snapshot. No administrator identity fallback exists.

Grant contexts contain job/tenant/initiator/service/grant/attempt identifiers. Each protected
transaction intersects current user permissions, service permissions, grant scope, tenant and
resource/Project policies. Row/property restrictions intersect both identities. Security revision,
job and grant locks protect revocation and commit decisions. Transaction-local caches and a
DB-anchored clock avoid repeated authority queries per property; actual DB time is rechecked before
commit. Lease expiration, retries, fencing, recovery, quotas and isolated execution remain in place.
Workers outside an execution job's Project scope leave it queued for another eligible worker and
continue to eligible candidates. Subject/grant denials are explicit failures with audit correlation.

The inspected and modified paths are ingestion, semantic execution, dataset validation, legacy
pipelines, pipeline DAGs, mapping materialization, functions, and manual/scheduled/event automations.
Automation activation keeps its explicitly bound owner; scheduler service authority and current
owner/target access are independently checked. Outbox/webhooks already execute as authorized
services and retain that model. Media preview/parser work is synchronous isolated service work,
not another shared queue. Lineage maintenance and DAG scratch cleanup are tenant-filtered
control-plane operations. No other fixed-subject queue was found.

Semantic grants also bind the source/run provenance needed to revalidate ingestion-backed input
artifacts. Their private scope covers the same bounded 101 references per selected type that fresh
access checks, even when public provenance truncates the merged display list to 100.

Audit decisions and lifecycle events retain initiating and executing actors, job ID, grant ID and
fencing token. Grant creation, claims, worker eligibility denials, retry/cancel requests, execution
denials and terminal outcomes are recorded. Optional audit correlation fields are omitted for
ordinary historical inserts, preserving upgrade fixture compatibility.

See [ADR 0047](../decisions/0047-job-scoped-worker-authority.md) and the
[operator guide](../operations/dynamic-workers.md) for detailed boundaries and lifecycle behavior.

## Migration and configuration

Forward-only Alembic revision **`0028_job_execution_grants`**, following
`0027_lineage_observability`, creates `job_execution_grants`, adds optional audit correlation
columns and shared-queue/audit indexes, and installs immutable-scope/irreversible-revocation guards.
Composite FKs bind tenant membership and specific ingestion/semantic/execution jobs; uniqueness
permits one grant per job. Existing job/audit records are retained. No authority is backfilled.
Legacy jobs without grants fail closed and require authorized resubmission with fresh keys.

Removed settings: **`FOUNDRY_WORKER_SUBJECT_ID`**, the Python `worker_subject_id` field and Compose
`WORKER_SUBJECT_ID` placeholders. No replacement global user setting or compatibility fallback was
added. Existing tenant/provider/client/service-secret/access-token configuration remains. Added
RBAC capabilities: **`execution:claim`** and **`automation:dispatch`**.
Semantic `JobInput` additionally accepts an optional `idempotency_key`, allowing fresh authorized
submission after revocation, expiry or legacy quarantine without changing input artifacts. Omitting
it preserves the old content fingerprint. OpenAPI and TypeScript SDK contracts were regenerated. Existing persisted roles are
not automatically broadened. Grant validity is seven days from authorized admission.

Rollout: pause workers/schedulers, back up, run owner migration, refresh runtime table grants,
provision bounded service roles and required Project memberships, remove subject configuration,
then deploy coordinated API/worker versions. Resubmit legacy work; re-export semantic inputs if
security revisions changed. See the operator guide for the exact sequence and Alice/Bob example.
No production deployment, external resources, shared-schema migration or credentials were changed.

## Executed checks

Consulted `fixtures/VALIDATION.md`. Test counts below are separate runs and overlap; do not add
them as unique-test coverage. The full broad suite was not rerun after the final semantic-provenance/resubmission refinements;
those refinements were covered by the final PostgreSQL/semantic run and regenerated SDK checks.

| Check | Result | Evidence |
| --- | --- | --- |
| Broad affected regression suite | FAIL initially; sole remaining failure corrected and rerun PASS | `scripts/validate_phase14.py --workers`: **631 passed, 1 failed, 1 expected xfail**. The failure was `test_upgrade_24_26_27_preserves_registry`, which stopped at old revision 0027 before checking current model drift. Updated to current head and passed in final acceptance selection. |
| Final MinIO-backed review/acceptance selection | PASS | Same harness with `--worker-selection 'test_job_execution or test_security_workflows or test_mappings_recovery or test_observability or private_ or test_phase7_upgrade or test_ingestion_recovery or test_daily_schedule or test_function_automation_current_owner'`: **73 passed**, 565 deselected. Included multi-user pipeline publication, eligibility skipping, grant expiry at commit, legacy upgrade, all observability cases, migration fix and recovery. |
| Final security + semantic regression | PASS | With explicit `OPEN_ONTOLOGIES_BIN`, `pytest -q services/api/tests/test_job_execution.py services/api/tests/test_security_workflows.py services/api/tests/test_semantic.py services/api/tests/test_semantic_platform.py`: **63 passed, 1 skipped**. The skipped pipeline test requires MinIO and passed in the acceptance run above. Includes real-engine provenance tests with 1 and 101 retained run references and fresh-key resubmission after revocation. |
| Regenerated API/SDK contracts | PASS | `npm run check:generated` reports no drift; `npm run build` and `npm run typecheck` succeed with Node 24.14.0. |
| SDK unit tests | PASS | `npm test`: **63 passed in 3 test files**. |
| Application migration/ORM drift | PASS | `pytest -q services/api/tests/test_applications.py -k fresh_migration_and_drift`: **1 passed**, 25 deselected. |
| Ruff lint and formatting | PASS | Changed runtime, migration, worker/acceptance scripts and new test helpers pass lint; **169 files already formatted** in the selected format check. |
| Strict mypy | PASS | **No issues found in 165 source files**. |
| Whitespace/diff integrity | PASS | `git diff --check`. |
| Turtle parsing | PASS | Executed `test_fixtures.py::test_turtle_parse` in the broad suite. |
| CSV identities, counts and FKs; RDF consistency | PASS | Executed `test_csv_rdf_consistency`: 6 factories, 20 machines, 12 employees and 25 tasks with consistent references. |
| SHACL, RDF 1.1 normalized shapes and negative cases | PASS | Fixture normalized-baseline and negative tests executed in broad suite. Canonical fixtures were not changed. |
| Raw pySHACL compatibility | FAIL, expected existing xfail | `test_raw_pyshacl_compatibility`: existing simple-literal/xsd:string `sh:in` mismatch. Not claimed as successful raw SHACL validation. |
| OWL reasoning | PASS | Existing real-engine manufacturing ingestion/export/reasoning test checks the three expected `CriticalMachine` identities independently of SHACL. |
| PostgreSQL integration | PASS | Real isolated migrated schemas; admission rollback, revocation, concurrent claims, recovery, fencing, migration preservation and drift executed. |
| FastAPI object queries | PASS | Broad `test_queries.py` and security HTTP tests executed. |
| Actions and reconciliation | PASS | Broad action, ingestion, mapping and recovery suites executed; final targeted revocation/recovery checks also pass. |
| Polars ingestion and pipeline publication | PASS | Broad ingestion/mapping/pipeline/DAG suites and real MinIO outputs; final Alice/Bob pipeline test passes. |
| Authorization and tenant/resource isolation | PASS | Forged subject/grant/tenant/job contexts, worker permissions, Project boundaries, source/type scope, current property policy intersection, disablement, membership/access loss, revocation and commit-time expiry tested. |
| OWL import/export subset | PASS | Broad `test_ontology_import.py` executed. |
| Interactive Protégé/WebProtégé validation | NOT RUN | No interactive ontology-authoring session was used; no new integration contract was introduced. |
| Target OKD4/restricted-SCC rollout and live Keycloak rotation | NOT RUN | No target cluster deployment was authorized/performed. Manifests/production configuration tests pass; updated live acceptance harness was linted, not deployed/executed. |
| Lean proof checking | NOT RUN | Existing optional checker not part of this worker task; no proof-certification claim. |

An intermediate direct semantic run had **29 passes and 35 skips** because its environment omitted
the optional engine path and MinIO. It was superseded by the explicit-engine 63-pass run above;
no skipped check is counted as passed.

The earlier broad run exposed historical audit-insert compatibility, old worker-test identity setup,
stale migration-head assertions and environment assumptions. These were corrected and relevant
checks rerun. Node 24 was used instead of the shell's Node 16. A daily-schedule test now compares
UTC explicitly rather than assuming PostgreSQL's returned timezone is UTC.

## Limitations and next work

- Grants expire seven days after submission and cannot be extended, widened or unrevoked. Expired,
  revoked and legacy jobs require authorized resubmission. Terminal job state consumes authority;
  only existing authorized transient-failure retries can reactivate the same job within expiry.
- Shared pools are scoped to one explicitly configured tenant per authenticated worker context.
  There is no automatic all-tenant scheduling.
- Revocation prevents subsequent protected transactions/publication. Already committed ingestion
  batches remain visible. Authorized reads/pure computation already in flight may finish before the
  next boundary; execution children are interrupted through authorization-checking heartbeats.
- The base OKD4 manifests instantiate ingestion and semantic pools. The existing execution
  controller script is updated; creating/operating its Deployment is an operator rollout action.
- Existing raw pySHACL compatibility and optional proof-checker limits remain documented above.
- Production certification is not claimed. Recommended next work is the controlled target OKD4
  migration/rollout and live Keycloak/restricted-SCC acceptance using this implementation. No
  additional roadmap phase or new subsystem has been implemented.

## Files created or modified

- `PLANS.md`
- `README.md`
- `apps/studio/lib/openapi.json`
- `docs/api/security.md`
- `docs/api/semantic.md`
- `docs/architecture/migrations.md`
- `docs/architecture/overview.md`
- `docs/decisions/0047-job-scoped-worker-authority.md`
- `docs/development/dynamic-workers-report.md`
- `docs/operations/dynamic-workers.md`
- `docs/operations/okd4-deployment.md`
- `docs/operations/okd4-infrastructure-request.md`
- `docs/operations/production.md`
- `docs/operations/threat-model.md`
- `infrastructure/kubernetes/base/configmap.yaml`
- `infrastructure/production/compose.yaml`
- `infrastructure/production/environment.example`
- `packages/typescript-sdk/src/schema.ts`
- `scripts/accept_phase10.py`
- `scripts/run_execution_worker.py`
- `scripts/validate_phase14.py`
- `services/api/migrations/versions/0028_job_execution_grants.py`
- `services/api/src/ontology_platform/artifacts/service.py`
- `services/api/src/ontology_platform/automations/service.py`
- `services/api/src/ontology_platform/config.py`
- `services/api/src/ontology_platform/datasets/service.py`
- `services/api/src/ontology_platform/db/governance.py`
- `services/api/src/ontology_platform/db/models.py`
- `services/api/src/ontology_platform/execution/worker.py`
- `services/api/src/ontology_platform/functions/service.py`
- `services/api/src/ontology_platform/ingestion/service.py`
- `services/api/src/ontology_platform/ingestion/worker.py`
- `services/api/src/ontology_platform/mappings/service.py`
- `services/api/src/ontology_platform/observability/index.py`
- `services/api/src/ontology_platform/pipelines/dag_service.py`
- `services/api/src/ontology_platform/pipelines/dag_worker.py`
- `services/api/src/ontology_platform/pipelines/service.py`
- `services/api/src/ontology_platform/projects/service.py`
- `services/api/src/ontology_platform/security/admin.py`
- `services/api/src/ontology_platform/security/audit.py`
- `services/api/src/ontology_platform/security/contracts.py`
- `services/api/src/ontology_platform/security/interfaces.py`
- `services/api/src/ontology_platform/security/job_grants.py`
- `services/api/src/ontology_platform/security/routes.py`
- `services/api/src/ontology_platform/security/service.py`
- `services/api/src/ontology_platform/security/workers.py`
- `services/api/src/ontology_platform/semantic/contracts.py`
- `services/api/src/ontology_platform/semantic/service.py`
- `services/api/src/ontology_platform/semantic/worker.py`
- `services/api/tests/test_applications.py`
- `services/api/tests/test_execution.py`
- `services/api/tests/test_job_execution.py`
- `services/api/tests/test_mappings.py`
- `services/api/tests/test_mappings_recovery.py`
- `services/api/tests/test_media_functions_automations.py`
- `services/api/tests/test_observability.py`
- `services/api/tests/test_pipeline_dag.py`
- `services/api/tests/test_pipeline_graphs.py`
- `services/api/tests/test_production_profile.py`
- `services/api/tests/test_security_workflows.py`
- `services/api/tests/worker_support.py`
- `services/worker/README.md`
