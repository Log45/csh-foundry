# Hosted CI failure follow-up — 2026-11-21

Scope: diagnose the six supplied job logs and fix CI setup while retaining regression
coverage. Base revision: `fd59ee7`; changes remain in the working tree. No database migration,
deployment, remote image publishing, repository settings update, or hosted rerun occurred.
`fixtures/VALIDATION.md` was consulted as part of this CI maintenance work.

## Findings and changes

### Formatting — confirmed cause, corrected

The static job failed because npm executes scripts through `/bin/sh` on Linux. The script
relied on shell brace expansion and supplied a directory brace pattern to Prettier. The
runner reported no matching files for `apps/sdk-example/{src,app,tests}`.

Both root format commands now quote explicit recursive file globs. Prettier performs glob
expansion independently of shell behavior, including the existing TypeScript/TSX and SDK
integration MJS files. The check passed through `/bin/sh` on the host and inside a real
Linux Node container using the updated package script.

### Storage — confirmed cause, corrected

All four supplied backend shard logs failed before pytest while pulling `minio/minio` or
`minio/mc`. The pinned local images had hidden that dependency during earlier validation.
Fresh checks confirmed that Docker Hub pulls failed, Quay did not serve the selected
release anonymously, and the upstream server/client binary archive URLs returned HTTP 410.

The same releases are now built from verified upstream source in
`infrastructure/docker/minio.Dockerfile`:

| Component | Release | Upstream source commit |
| --- | --- | --- |
| Server | RELEASE.2025-09-07T16-13-09Z | 07c3a429bfed433e49018cb0f78a52145d4bedeb |
| Client | RELEASE.2025-08-13T08-35-41Z | 7394ce0dd2a80935aded936b09fa12cbb3cb8096 |

Each source archive has a committed SHA-256 checksum. Go 1.24.6 and Alpine 3.22.1 bases are
pinned by multi-platform digest. Builds use upstream go.sum verification and readonly
module files, and retain the corresponding source archives in the image.

`ci-storage.yaml` builds one image on a cache miss, exports/checksums it, caches the result
by Dockerfile content plus runner OS/architecture, and uploads a short-lived artifact.
Backend/browser jobs verify and load that artifact rather than pulling removed images.
CI and acceptance both require the storage build. The final aggregate gate and its tests
also reject storage build failure/cancellation/skipping. A first cache miss adds build time;
normal runs restore the image. No hosted timing claim is made here.

Compose uses this one image for the existing server and client services and uses Alpine's
wget for readiness. Existing credentials, buckets, policy scripts, private volumes and
cleanup remain intact. No mock S3 replacement or test exclusion was introduced.

### Owner worker — hosted cause remains unconfirmed

The supplied owner job ran 31 tests: 30 passed and
`test_execution_controller_main_uses_owner_mode_for_startup_and_refresh` failed because its
job state was FAILED. The log did not include the job's persisted error or resource metrics,
so it does not establish whether authorization, execution, or a resource bound caused it.

The failing assertion now includes `status.error` and `status.metrics`. Its success
requirement is unchanged, and CI still fails if it does not succeed. No retry, timeout,
resource budget, token verification, or authorization assertion was relaxed.

The test passed in Linux arm64 with both pytest invocation styles. An amd64 reproduction
with uv-managed CPython **3.12.12**, locked API dependencies, the actual non-superuser
PostgreSQL role, and checksum-verified Linux semantic engine passed **all 31 owner tests**.
Local amd64 emulation cannot execute the regular AVX2 Polars wheel, so that diagnostic
container alone used Polars' portable runtime at the same 1.44.2 version. This did not
change repository dependencies or CI configuration. That environment limitation means the
original hosted failure is not conclusively diagnosed or claimed fixed.

## Files

- `.github/workflows/ci-storage.yaml`: new cached source-image build/export job.
- `.github/workflows/ci.yaml`: required storage dependency and aggregate gate input.
- `.github/workflows/acceptance.yaml`: shared source-image prerequisite.
- `.github/workflows/ci-suite.yaml`: artifact download, checksum verification and load.
- `infrastructure/docker/minio.Dockerfile`: pinned source build and runtime image.
- `infrastructure/compose.yaml`: local source image and compatible readiness probe.
- `package.json`: shell-independent format/write and format/check commands.
- `services/api/tests/test_ci_reports.py`: required storage-gate failure cases.
- `services/api/tests/test_owner_runtime_postgres.py`: persisted worker failure diagnostics.
- `docs/development/ci.md`: updated local setup and CI cache contract.
- Decision `0051-ci-storage-source-build.md` and this report: rationale and validation.

## Executed validation

| Check | Result | Evidence |
| --- | --- | --- |
| Linux `/bin/sh` formatting check | PASS | Actual root npm script inside Linux Node container; every pattern matched |
| Host POSIX-shell formatting | PASS | `npm run format:check --script-shell=/bin/sh` |
| Cold source image build | PASS | Built linux/amd64 from pinned public base images and checksum-verified source; `artifacts/ci/minio-source-build.log` |
| Server/client version and commits | PASS | Both binaries report the intended release and commit; linux/amd64, Go 1.24.6 |
| Image archive transport | PASS | Exported 79,360,000-byte self-contained image, inspected manifest, calculated SHA-256, loaded successfully |
| Real MinIO initialization/restart | PASS | Repeated policy initialization and persisted sentinel after restart; `artifacts/ci/storage-source-tests.log` |
| Storage, dataset and canonical fixtures | PASS | 27 passed, 1 existing strict xfail; all 14 artifact checks, a dataset lifecycle, and fixture suite |
| Turtle, CSV/RDF identities and references | PASS | Executed `test_fixtures.py` |
| Normalized SHACL/negative fixtures | PASS | Executed conformance and all negative cases |
| Raw RDFLib/pySHACL term compatibility | NOT SUPPORTED | Existing documented strict xfail, not counted as PASS |
| Linux arm64 owner-controller test | PASS | Real worker/database, both module and console entrypoint invocations |
| Linux amd64 managed-Python owner suite | PASS | 31 passed, with the emulation caveat above; `artifacts/ci/owner-linux-managed-complete.log` |
| Required-gate/report policy | PASS | 40 tests, including failed/cancelled/skipped storage prerequisites; `artifacts/ci/hosted-fix-policy.xml` |
| Workflow syntax and expressions | PASS | actionlint v1.7.7 against all workflows |
| Python lint and formatting | PASS | Ruff check and format check across the repository |
| Python types | PASS | mypy: 171 source files |
| Patch whitespace | PASS | `git diff --check` |
| GitHub cache/artifact execution | NOT RUN | Local image archive roundtrip tested; actual hosted actions need the next push |
| Full backend/browser regression | NOT RUN | Scoped follow-up; application runtime source did not change |
| Independent OWL inference / interactive Protégé | NOT RUN | Unchanged by this follow-up; not revalidated here |
| Production readiness / deployment | NOT RUN | Outside this CI maintenance scope |

Initial local amd64 probes failed on AVX2 import under emulation and, separately, on a
missing Linux semantic executable. Those were diagnostic environment failures; they were
not treated as passing runs. The completed owner run used the pinned Linux executable and
portable Polars runtime described above. Temporary databases, volumes and networks were
removed after the checks.

Historical limitation at this report's revision: the original hosted owner failure remained unconfirmed and could still block
CI. The improved failure message will expose its persisted error and metrics if it recurs.
Recommended next step: run the updated workflows on GitHub, inspect those diagnostics if
needed, and measure cold versus warm storage-cache timing. No new product phase was started.

The subsequent hosted diagnostics exposed inherited Linux peak-memory accounting. See
[the worker regression follow-up](ci-worker-regression-validation.md) for its diagnosis,
corrective changes, and new validation results.
