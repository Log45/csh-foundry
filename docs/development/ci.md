# Continuous integration

Every push and pull request runs the same broad regression checks. `merge_group` also
validates a queued merge. The required aggregate check is **CI / regression**; configure
that name in the repository ruleset after the first hosted run. Repository settings are
not changed by these workflow files.

The jobs run in parallel: Python lint/types and generated contracts, SDK tests/builds and
consumer installation, Studio component tests/types/formatting, and isolated integration
suites. The backend is divided into four deterministic collection shards; their union
runs every ordinary test exactly once. There are no per-shard feature allowlists. The
integration matrix covers production Studio browser workflows, directory onboarding/sharing with its distinct identity fixture, and database
startup/jobs under a non-superuser migration/table owner. Browser jobs build Studio's
standalone production output; they do not run Next's development server. Chromium is the
only browser in the push gate, and retries are disabled.

Backend jobs also install Node 24 and Studio's locked TypeScript compiler because the
generated SDK integration tests compile and execute real standalone TypeScript packages.
Scale jobs need Node during collection of that test module, even though it is deselected.

PostgreSQL 17, the checksum-verified Open Ontologies binary, and digest-pinned MinIO are
real dependencies. `validate_phase15.py` gives each invocation a private Compose project,
volume, port, and storage credentials, and cleans up its own resources. Backend fixtures
create isolated migrated PostgreSQL schemas. The browser fixture signs a local service
token and uses the actual `WorkerPool` enrollment path for new private Projects, preserving
worker/initiator authorization checks. The ordinary database suite also checks migration
to head and Alembic model drift. The owner job provisions an unprivileged role
only inside its disposable service database. It does not use development database roles.

## Scope and reporting

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
or fixtures before removing coverage. No version matrix, path filtering, or automatic retry
is used. New pushes cancel obsolete regression runs; acceptance runs do not cancel each
other. Separate workflow/event concurrency groups prevent releases from cancelling PR CI.

## Local commands

Install locked dependencies, the pinned semantic engine, Node 24, Studio dependencies and
Chromium, and pull the pinned `minio` and `minio-init` images from Compose. Point
`TEST_DATABASE_URL` at a disposable PostgreSQL database, never production. For clean-schema
checks set `FOUNDRY_DATABASE_URL` to that same database.

```sh
uv run alembic upgrade head
uv run alembic check
uv run python scripts/validate_phase15.py --ci regression
# Optional single hosted-equivalent shard:
uv run python scripts/validate_phase15.py --ci regression --ci-shard 0/4
npm run build -w @foundry/sdk
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
