# CI maintenance validation — 2026-11-21

Scope: the explicitly requested CI redesign, not a new product roadmap phase.
Base revision: `e7e2049`, with the working-tree changes described below.
Environment: macOS, Python 3.12.0, disposable PostgreSQL 17.6 Docker services,
digest-pinned MinIO, the existing pinned Open Ontologies executable. Frontend unit tests
and directory acceptance ran on Node 24.14.0; production builds and the main browser
profile also ran on Node 25.9.0. Hosted workflows select Python 3.12 and Node 24.
`fixtures/VALIDATION.md` was consulted before validation.

## Changes

- `ci.yaml`: independent static/contracts, SDK, Studio, four backend shards, production
  browser, directory identity, and unprivileged-owner jobs; aggregate `CI / regression`.
- `ci-suite.yaml`: reusable isolated PostgreSQL/MinIO setup, migrations, OWL compatibility,
  strict JUnit checks, scoped owner bootstrap, acceptance commands, and failure artifacts.
- `acceptance.yaml`: weekly/manual scale, 1 GiB browser, Keycloak, recovery, load, and
  built ingress validation, outside normal push checks.
- `release.yaml`: separate candidate creation and reviewed promotion; explicit candidate
  and acceptance run IDs; archive/source revision checks; load tested images without
  rebuilding; preserve mandatory evidence and image identity verification.
- `scripts/validate_phase15.py`: named CI profiles, strict reporting, optional sharding.
- `scripts/ci_shard.py`: deterministic partition after normal marker selection.
- `scripts/check_test_report.py`: reject missing, empty, failed, or unexpectedly skipped
  results; preserve only the exact existing strict RDFLib/pySHACL compatibility xfail.
- `pyproject.toml`, the three `test_*large.py` modules, and
  `test_owner_runtime_postgres.py`: explicit scale/owner markers.
- Studio Playwright configuration: regression/directory/scale profiles and zero retries.
- Studio browser backend fixture: signed local worker credentials and actual `WorkerPool`
  enrollment, rather than assuming a tenant role grants access to private Projects.
- Directory browser test: await tenant navigation and use current ontology search.
- Owner test helper: explicitly select pre-provisioned worker mode for its mocked identity;
  automatic enrollment retains separate integration coverage.
- SDK acceptance test: issue the normal short-lived token after package installation and
  compilation, immediately before live HTTP use; no TTL or verification changes.
- Semantic compiler test: deterministic UUID parameter for stable cross-process collection.
- `test_ci_reports.py`: report rejection, real aggregate-gate failure/cancellation/skip
  handling, and disjoint/complete shard coverage tests.
- `docs/development/ci.md` and decision `0050-ci-regression-scope.md`: operating contract,
  exclusions, release handoff, and architectural rationale.

Database migrations: **none added or modified**. Existing migrations were applied and
checked only against disposable databases. Application runtime source was not changed.

## Executed validation

| Check | Result | Evidence |
| --- | --- | --- |
| Workflow syntax and expressions | PASS | Pinned `actionlint` v1.7.7 against all four workflows |
| Python lint and formatting | PASS | `ruff check .`; `ruff format --check .` — 338 files formatted |
| Python typing | PASS | `mypy` — 171 source files |
| Frontend formatting and typing | PASS | Root and Studio format/type checks |
| Generated OpenAPI/SDK drift | PASS | Export current backend, regenerate Studio schema, SDK generated check, zero Git diff in generated contracts |
| SDK and example production build | PASS | Root `npm run build`; `artifacts/ci/local-sdk-build.log` |
| Studio production build | PASS | Studio `npm run build`; `artifacts/ci/local-studio-build.log` |
| SDK Vitest tests | PASS | 64 passed on Node 24; `artifacts/ci/sdk.xml` |
| Studio Vitest tests | PASS | 110 passed on Node 24; `artifacts/ci/studio.xml` |
| Packed ESM consumer | PASS | `npm run test:consumer` — imports, declarations, peer resolution, negative types |
| CI policy and aggregate failure cases | PASS | 36 passed; `artifacts/ci/policy-final.xml` |
| Actual missing storage prerequisite | PASS | A storage test deliberately skipped without MinIO; the report checker returned failure, as required; `artifacts/ci/intentional-missing-storage.xml` is intentionally a nonpassing report |
| Actual collection partition | PASS | Current 1,121 ordinary cases divided 281/280/280/280; union equals full collection with zero duplicates; `artifacts/ci/shard-coverage.json` |
| Fresh migration and model drift | PASS | `alembic upgrade head` and `alembic check` against private PostgreSQL; `artifacts/ci/local-regression.log` |
| Initial full backend sweep | FAIL | 1,092 passed, 3 failed, 27 deliberately deselected, 1 strict xfail; 1,172.69 seconds; `artifacts/ci/regression.xml` and `local-regression.log` |
| Corrected owner job | PASS | 31 passed under a real non-superuser migration/table owner; `artifacts/ci/owner.xml`, `local-owner.log` |
| SDK and owner-policy diagnostic rerun | PASS | 38 passed in a fresh database; host/PostgreSQL clock observations in `artifacts/ci/local-sdk-rerun.log`; `sdk-owner-rerun.xml` |
| Final SDK credential-timing change | PASS | Live generated Python and TypeScript SDK acceptance, real JWTs and PostgreSQL; 1 passed; `artifacts/ci/sdk-final.xml`, `local-sdk-final.log` |
| Production-browser regression | PASS | All 16 passed with real API, PostgreSQL, MinIO and two Studio replicas; no skips; `artifacts/ci/browser.xml` |
| Directory onboarding/invitation browser | PASS | 1 passed on Node 24 after navigation/search correction; no skips; `artifacts/ci/directory.xml`, `local-directory-rerun.log` |
| OWLAPI import/export compatibility | PASS | Maven/OWLAPI 4.5.29 RDF/XML roundtrip; 5 classes, 13 data properties, 6 object properties, 4 keys, 3 inverses, 1 equivalent class |
| Pinned Keycloak candidate export | PASS | Docker exported the exact pinned digest to a temporary archive; archive inspected and removed |
| Git whitespace/diff integrity | PASS | `git diff --check`; no generated contract drift |

The initial backend sweep ran before the final fixture corrections and additional CI-policy
cases. Its failure is preserved, not relabeled as PASS. The two owner unit failures came
from mocking pre-provisioned identities while implicitly selecting automatic enrollment;
those paths passed in the corrected owner and policy reruns. The SDK test received an
`invalid_token` response in the full sweep but passed unchanged in isolation. The original
authentication failure's cause was not conclusively established. Token issuance now occurs
after setup, and that final test also passed. No automatic retry, token lifetime extension,
clock-skew relaxation, or assertion removal was introduced. There was no second full backend
sweep after these changes; the changed paths were verified with focused reruns.

## Manufacturing validation required by fixtures/VALIDATION.md

| Check | Result | Evidence |
| --- | --- | --- |
| Turtle parsing | PASS | Executed fixture tests in full sweep and focused fixture runs |
| CSV identities and foreign keys | PASS | Executed CSV/RDF consistency tests |
| SHACL conformance and negative cases | PASS | Normalized RDF 1.1 shapes and actual pinned engine tests executed |
| Raw pySHACL/simple-string compatibility | NOT SUPPORTED | Existing strict xfail for the exact pinned RDFLib/pySHACL mismatch; never counted as PASS |
| OWL critical-machine inference | PASS | Actual `owl-rl-ext` profile tests in full sweep |
| Base `owl-rl` critical-machine axiom | NOT SUPPORTED | Actual profile test confirms the pinned build lacks that inference; fixture preserved |
| PostgreSQL persistence and rollback | PASS | Real-database tests in full sweep; separate owner suite |
| FastAPI objects, filtering and traversal | PASS | Executed API/query suites and production browser reference workflow |
| Actions, idempotency and reconciliation | PASS | Executed action/ingestion suites and browser workflow |
| Polars ingestion and materialization | PASS | Real PostgreSQL/MinIO ingestion, datasets, pipelines and mappings suites |
| Authorization and tenant isolation | PASS | Executed security suites, owner checks, and browser authorization/revocation scenarios |
| Operational OWL import/export | PASS | Ontology import suite and Maven roundtrip |
| Interactive Protégé desktop inspection | NOT RUN | No manual desktop authoring session performed for CI maintenance |

## Limitations and remaining checks

- **NOT RUN:** hosted GitHub Actions execution, hosted cache/install behavior, and actual
  hosted wall-time measurement. The 10–15 minute target is not a measured guarantee.
- **NOT RUN:** a second complete backend sweep after the focused corrections. All final
  changed test paths passed focused reruns; the original failing report remains available.
- **NOT RUN:** 1 GiB/large-data acceptance, operational recovery/load/real Keycloak drills,
  full release image builds/scans, reviewed promotion, target infrastructure certification,
  and deployment during this maintenance task. These remain explicit scheduled/manual or
  release checks, not claimed successes.
- The directory browser uses a deterministic directory connector fixture, not a live
  enterprise LDAP service. External organization configuration still needs target acceptance.
- One existing raw SHACL compatibility xfail remains documented. Studio tests also emit
  an existing React list-key warning; all component assertions pass.
- Repository branch rules were not modified. Configure **CI / regression** as required when
  adopting the workflow; the aggregate rejects failed, skipped and cancelled dependencies.

Architectural decision: broad ordinary regression on every push, with real existing
infrastructure dependencies, explicit scale exclusions, and separate exact-image release
acceptance. See decision 0050. No product architecture or datastore boundaries changed.

Recommended next step: run the first hosted push, verify the job and artifact results, and
measure shard/browser durations before tuning budgets. No subsequent product phase is
implemented or authorized by this change.
