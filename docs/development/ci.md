# Continuous integration

Every push, pull request and `merge_group` starts a lightweight change-detection job.
Confirmed documentation-only changes skip the expensive regression jobs; all other changes
run the same broad checks. The required aggregate check is **CI / regression**; configure
that name in the repository ruleset after the first hosted run. Repository settings are
not changed by these workflow files. Keep that aggregate required rather than requiring
individual jobs that intentionally skip on documentation-only changes.

## Documentation-only changes

The implemented plan is to classify the complete Git comparison first, gate every expensive
job on that result, and retain an unconditional aggregate check. `scripts/ci_changes.py`
uses only Git and Python's standard library, so this decision needs no dependency install,
storage image, database, Node setup or application build.

The documentation allowlist is deliberately narrow:

- Files named `README.md`, `CHANGELOG.md` or `AGENTS.md` anywhere in the repository.
- Root `PLANS.md` and `fixtures/VALIDATION.md`.
- Markdown files ending in `.md` beneath `docs/`.

All changed paths must match. Code, dependencies and lockfiles, workflows, infrastructure,
canonical fixtures, executable examples, MDX and unclassified files run full regression,
including when mixed with documentation. Documentation images and other assets also run
full regression under this policy. A rename checks both the removed and added paths.

Existing-branch pushes compare event `before` and `after` commits. Pull requests compare
their merge base to the PR head, so a documentation follow-up does not hide earlier code
changes in the same PR. Merge queues compare the group's base and head. Checkout fetches
full history; comparison uses NUL-delimited local Git output without an API file-list cap.
New/deleted refs, missing history, malformed payloads, ambiguous merge bases, empty diffs
and unknown events conservatively request full regression. Manual dispatch always requests
the full suite. Reusable calls use the caller's event context; unsupported contexts run full CI.

For confirmed documentation-only changes, storage, static/contracts, SDK, Studio, all backend
shards and all browser/directory/owner jobs skip. The aggregate requires successful change
detection, an exact `run_ci=false` output, and every expensive dependency to be `skipped`.
It reports those tests as intentionally **NOT RUN**, not passed tests. For full regression,
every dependency must succeed. Detector failure, cancellation, missing output or an unexpected
dependency result fails the gate. The job summary records the scope decision.

Workflow triggers stay active: GitHub can leave required checks pending when an entire workflow
is filtered out. Job conditions plus the always-running aggregate preserve a terminal required
check. See [GitHub's required-check guidance](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)
and [ADR 0053](../decisions/0053-documentation-only-ci.md).

Weekly/manual extended acceptance and release workflows retain their existing behavior.
This change does not deduplicate push and pull-request runs for code changes.

After change detection requests full regression, jobs run in parallel: Python lint/types and
generated contracts, SDK tests/builds and
consumer installation, Studio component tests/types/formatting, and isolated integration
suites. The backend is divided into four deterministic collection shards; their union
runs every ordinary test exactly once. There are no per-shard feature allowlists. The
integration matrix covers production Studio browser workflows, directory onboarding/sharing with its distinct identity fixture, and database
startup/jobs under a non-superuser migration/table owner. Browser jobs build Studio's
standalone production output; they do not run Next's development server. Chromium is the
only browser in the push gate, and retries are disabled.

Backend jobs also install Node 24, build both SDK packages, and install Studio's locked
TypeScript compiler because the generated SDK integration tests compile and execute real
standalone TypeScript packages. Schema export uses explicit offline settings and requires
no developer `.env` or running database.
Scale jobs need Node during collection of that test module, even though it is deselected.

PostgreSQL 17, the checksum-verified Open Ontologies binary, and source-pinned MinIO are
real dependencies. `ci-storage.yaml` builds the existing MinIO server/client releases from
checksum-verified upstream source archives on digest-pinned Go/Alpine images. It caches the
result by Dockerfile content, then distributes one checksummed image artifact to all storage
jobs. A cold cache adds compilation time; subsequent pushes restore the image. Removed
upstream Docker repositories and binary archives are not required. `validate_phase15.py` gives each invocation a private Compose project,
volume, port, and storage credentials, and cleans up its own resources. Backend fixtures
create isolated migrated PostgreSQL schemas. The browser fixture signs a local service
token and uses the actual `WorkerPool` enrollment path for new private Projects, preserving
worker/initiator authorization checks. The ordinary database suite also checks migration
to head and Alembic model drift. The owner job provisions an unprivileged role
only inside its disposable service database. It does not use development database roles.

## Regression scope and reporting

All ordinary Python tests are collected, including new tests in the configured test roots.
Do not select regression tests by phase number or changed filenames. Dependency markers
are documentation, not the basis of the regression selection: tests often import shared
PostgreSQL fixtures without a module-level integration marker.

Only these categories are deliberately excluded from the ordinary backend job:

- `scale`: the explicit large execution, materialization, and multi-output DAG tests.
- `owner_runtime`: tests run by the separate non-superuser job on every push.

Small-data correctness tests for datasets, formats, mappings, worker recovery, transactional
publication, DAGs, authorization, isolation, and lineage stay in the ordinary suite.

The browser regression profile runs every browser spec except `maximum.spec.ts` (the
1 GiB upload) and `directory-sharing.spec.ts` (different identity setup). The directory
profile runs the latter separately on every push. New ordinary specs join automatically.
The scale browser profile runs the maximum upload. Keep each profile nonempty.

Python, Vitest, and Playwright produce JUnit reports. `scripts/check_test_report.py` fails
for missing/empty reports, failures, errors, and skipped tests. There is one exact exception:
`test_raw_pyshacl_compatibility` may retain its existing strict expected failure for the
pinned RDFLib/pySHACL string-term incompatibility. This is reported as **EXPECTED FAILURE
(not PASS)**; an ordinary skip with the same name still fails. Its strict xfail also fails
on unexpected success, requiring the compatibility policy to be revisited. This does not
replace the independent normalized SHACL conformance and negative fixture tests.

Reports, browser failure traces/screenshots, and backend/Studio logs upload even on failure.
Test IdP keys and certificates are not uploaded. Inspect job results and reports rather
than treating an artifact upload or an excluded test as successful validation.

## Extended acceptance

`acceptance.yaml` runs weekly on Monday at 07:23 UTC and on manual dispatch. Its independent
jobs run all `scale`-marked Python cases, the 1 GiB browser upload, and operational checks
(real Keycloak, PostgreSQL recovery, bounded load, and built nginx ingress). Each has a
90-minute timeout. This schedule keeps heavy measurements out of the push gate while
preserving explicit acceptance coverage. It does not certify production or automatically
create a complete release acceptance manifest. Target-specific security, nonroot-container,
monitoring, rollout, and production drills remain governed by the release runbooks and
`fixtures/VALIDATION.md`.

The normal regression jobs have 15–20 minute timeouts. The wall-time target is 10–15 minutes,
with a roughly 20-minute cold-cache budget. These are targets pending hosted measurements,
not measured guarantees. Use `--durations=20`, report timings, and job timings to tune setup
or fixtures before removing coverage. No version matrix, workflow-level path filtering, or automatic retry
is used. New pushes cancel obsolete regression runs; acceptance runs do not cancel each
other. Separate workflow/event concurrency groups prevent releases from cancelling PR CI.

## Local commands

Install locked dependencies, the pinned semantic engine, Node 24, Studio dependencies and
Chromium, and build the pinned local storage image with the command below. Point
`TEST_DATABASE_URL` at a disposable PostgreSQL database, never production. For clean-schema
checks set `FOUNDRY_DATABASE_URL` to that same database.

```sh
docker build -t csh-foundry-minio:2025-source -f infrastructure/docker/minio.Dockerfile .
uv run alembic upgrade head
uv run alembic check
npm ci
npm run build -w @foundry/sdk
npm run build -w @foundry/react
npm ci --prefix apps/studio
uv run python scripts/validate_phase15.py --ci regression
# Optional single hosted-equivalent shard:
uv run python scripts/validate_phase15.py --ci regression --ci-shard 0/4
npm run build --prefix apps/studio
uv run python scripts/validate_phase15.py --ci browser
uv run python scripts/validate_phase15.py --ci directory
uv run python scripts/validate_phase15.py --ci scale
uv run python scripts/validate_phase15.py --ci browser-scale
```

The existing local non-superuser harness remains available as
`uv run python scripts/validate_owner_runtime.py --selection owner_runtime` when PostgreSQL
`initdb`/`pg_ctl` are installed. Hosted CI uses its disposable PostgreSQL service instead.

## Release evidence handoff

A manual `release.yaml` run with both inputs empty builds and scans a **candidate**, then
uploads `reviewed-candidate` containing `images.tar`, `SOURCE_REVISION`, and `SHA256SUMS`.
It does not create a
reviewed release or request production approval.

Download and test that exact candidate using the release acceptance runbooks. A separate,
trusted workflow run must upload a `release-acceptance` artifact containing
`release-manifest.json` at its root and all referenced evidence. Evidence paths in the
manifest must start with `artifacts/acceptance/`, relative to the repository root, because
the artifact is downloaded there. Preserve the complete directory structure inside that
artifact. The manifest must bind all required checks, supply-chain evidence, the source
revision, and all six immutable image identities, including Keycloak.

Dispatch release again at the **same source revision**, supplying both `candidate_run_id`
and `acceptance_run_id`. It checks the candidate's source revision and archive checksums,
loads the prior images without rebuilding, reruns scans, and
passes their actual image IDs and the selected commit to the existing evidence verifier.
Missing, failed, altered, mismatched, or expired evidence blocks promotion. Only a verified
promotion uploads `reviewed-release` and reaches the production approval environment.
Deployment remains an explicit operator action. Scheduled acceptance logs alone do not
satisfy the complete production-readiness evidence contract.
