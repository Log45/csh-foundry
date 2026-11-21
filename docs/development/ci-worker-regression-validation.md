# CI worker regression follow-up — 2026-11-21

Scope: corrective work for the supplied hosted regression, owner-runtime, browser, and
static-check failures. Base revision: `7b36d28`, plus this working-tree patch. No new
roadmap phase, deployment, repository-setting change, dependency change, or database
migration is included.

## Diagnosis and changes

The `CalledProcessError` in `validate_phase15.py` correctly propagated failing pytest
cases. The wrapper and strict report gate remain intact.

- Schema export required ambient database settings on a clean runner. It now constructs
  explicit offline settings; a subprocess test compares the generated schema with the
  committed contract without a `.env`, database, or service.
- Python integration tests imported SDK distribution files that the backend job had not
  built. Each regression shard now installs root dependencies and builds both SDK packages
  before installing Studio's TypeScript compiler.
- Linux inherited the controller's pre-exec `ru_maxrss`, causing small function workers to
  report a false memory-limit violation. Measure the child's own `/proc/self/status`
  `VmHWM`; keep the live RSS watchdog and all existing budgets. A 350 MB-controller probe
  reproduced the failure before the fix and succeeded afterward with about 50 MB worker RSS.
- Native allocator reservations exhausted address-space limits for tiny Parquet sources.
  Configure bounded Polars arenas and Arrow's system memory pool before native imports.
  Move the legacy parser's spawn target into the neutral isolation module so this setup
  also precedes its imports. A two-row Parquet validation now fits a 1 GiB address-space
  limit; the 512 MiB diagnostic still fails. No resource ceiling was increased.
- Lineage maintenance depended on queued executions. The existing governed worker pool
  now discovers dirty lineage generations even when execution is idle. Its existing
  membership, permission, and control-transaction checks apply. Tests verify metadata-only
  indexing and membership revocation. Production and browser-fixture controllers use the
  same path. The browser assertion refreshes the read-only snapshot within its existing
  five-second bound; whole-test retries remain disabled.

See [decision 0052](../decisions/0052-worker-memory-and-idle-maintenance.md) for the
architectural rationale. PostgreSQL remains authoritative; no queue service or datastore
was added. Public schemas and SDK contracts did not change.

## Environment and evidence

Local macOS arm64 host; disposable PostgreSQL 17 and source-built pinned MinIO; real
Open Ontologies 2.1.0; Node 24 for Studio builds. Linux worker checks use a nonroot
linux/amd64 container with uv-managed CPython 3.12.12, matching the hosted Python line.
Linux semantic checks mount the checksum-verified Linux executable.

The local amd64 container runs under emulation. Its diagnostic environment uses the
portable runtime of the same Polars 1.44.2 release because the normal AVX2 runtime cannot
execute under this emulator. Repository dependencies and hosted installation are unchanged.
These results exercise Linux accounting and address-space limits, but do not certify the
hosted AVX2 build or GitHub Actions orchestration. Browser tests use the actual backend,
disposable services, and two replicas of the production standalone Studio build on macOS.

| Check | Result | Evidence |
| --- | --- | --- |
| Focused Linux API regression | PASS | 214 passed across eight complete modules; `artifacts/ci/linux-api-final.log` and `artifacts/ci/linux-api-final-output/results.xml` |
| PostgreSQL transactions, datasets, functions, automations, and DAG publication | PASS | Same 214-case run against real PostgreSQL/MinIO; includes genuine memory-failure/no-publication, recovery, and schema-preservation cases |
| Linux worker memory regressions | PASS | 2 passed after explicitly touching the controller's 300 MB allocation; small function and bounded Parquet |
| Linux non-superuser owner runtime | PASS | 31 passed, `artifacts/ci/owner-linux-managed-complete.log` |
| Production Studio browser regression | PASS | 16 passed, `artifacts/ci/browser.xml`; no retries or skipped cases |
| Directory identity/sharing browser | PASS | 1 passed, `artifacts/ci/directory.xml` |
| Offline schema export / CI policy / isolation | PASS | 43 passed, `artifacts/ci/linux-fix-unit.xml` |
| Worker authorization and revocation | PASS | New idle-maintenance case in the eight passing `test_phase22.py` cases; separate owner-runtime suite |
| Turtle parsing | PASS | `test_fixtures.py`, `artifacts/ci/worker-fix-fixtures.xml` |
| CSV/RDF identities, keys, and references | PASS | Same fixture suite |
| Normalized SHACL and nine negative mutations | PASS | Same fixture suite; 12 passing fixture cases overall |
| Raw pySHACL string-term compatibility | NOT SUPPORTED | Existing exact strict xfail; reported separately, not counted as PASS |
| Studio production build and types | PASS | `artifacts/ci/linux-fix-studio-build.log` |
| TypeScript formatting | PASS | Root POSIX-shell and Studio Prettier checks |
| SDK and React package builds | PASS | Actual root workspace build commands; SDK integration exercised in Linux regression |
| Python lint/format | PASS | Ruff check; format check across 339 files |
| Python types | PASS | mypy across 171 source files |
| Workflow syntax/expressions | PASS | actionlint 1.7.7 across all workflow YAML files |
| Patch whitespace | PASS | `git diff --check` |
| Complete ordinary backend sweep / four-shard union | NOT RUN | Targeted eight-module regression plus separate owner/browser/policy/fixture checks in this follow-up |
| Full canonical object-query/action/reconciliation acceptance | NOT RUN | Targeted browser/API checks do not replace the complete manufacturing reference workflow |
| Independent OWL critical-machine inference | NOT RUN | Unchanged reasoning integration; not revalidated by these targeted checks |
| Interactive Protégé / OWL authoring roundtrip | NOT RUN | Unchanged by this corrective scope |
| Hosted workflow and timing | NOT RUN | Requires the next authorized push/run on GitHub |
| Extended scale/production/recovery acceptance | NOT RUN | Outside this corrective scope; existing acceptance workflow retained |

An earlier Linux diagnostic run had 11 failures and 203 passes. Four failures were due to
the diagnostic container resolving the host's macOS semantic executable; the remaining
seven exposed the legacy parser bootstrap problem fixed here. That failed run is retained
as `artifacts/ci/linux-api-regression.log`, not counted as successful validation.
The completed corrected run passed all 214 cases with no failures or skips. Strict JUnit
verification accepted that report and the browser, directory, unit, and fixture reports.
Disposable test databases, storage volumes, and networks were removed after completion.

## Modified files and next check

Workflow: `.github/workflows/ci-suite.yaml`. Runtime: the dataset parser, execution
isolation/worker, and security worker pool under `services/api/src/ontology_platform`, plus
`scripts/run_execution_worker.py`. CI tooling: `scripts/export_openapi.py`. Browser fixture
and assertion: `apps/studio/tests/e2e_backend.py` and `tests/e2e/pipeline-dag.spec.ts`.
Regression coverage: `test_execution_isolation.py`, `test_ci_reports.py`, and
`test_phase22.py`. Documentation: this report, the CI guide, historical follow-up link,
and decision 0052. Database migrations: **none**.

Next: run the existing full push gate on hosted Linux and inspect all shard reports and
native allocator behavior. Measure warm/cold setup and total critical-path duration there;
local emulation timings are not a CI performance estimate. No new product phase is proposed.
