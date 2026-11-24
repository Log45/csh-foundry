# Acceptance ingress image mismatch — 2026-11-23

## Failure and correction

The supplied hosted log for `acceptance (operations) / test` at source revision
`9340cc9e3f911458594654a701fb97e69248623c` shows successful Keycloak, physical recovery
and authenticated load checks. The ingress build then tagged `csh-foundry-ingress:phase10`,
while `scripts/test_ingress.py` requested its default `csh-foundry-ingress:phase10-okd4`.
The requested image was absent; Docker attempted a pull and exited 125 with access denied.
The ingress assertions never ran in that hosted attempt.

The operational acceptance step now sets `FOUNDRY_INGRESS_TEST_IMAGE` to
`csh-foundry-ingress:acceptance` and uses that variable for the build tag. The existing
smoke runner reads the same variable. This tests the image just built without relying
on another local tag or a registry pull. The standalone runner's default and all ingress
security assertions remain unchanged.

Changed files: `.github/workflows/ci-suite.yaml`, `services/api/tests/test_ci_reports.py`,
`docs/development/ci.md`, and this report. No database migrations, runtime changes,
external deployment, repository settings changes or new roadmap phase are involved.

## Validation

Local environment: macOS, Python 3.12, Linux aarch64 Docker engine and the existing
pinned ingress Dockerfile. `fixtures/VALIDATION.md` was consulted. Local image verification
does not establish the hosted x86_64 result or production certification.

| Check | Result | Evidence |
| --- | --- | --- |
| Workflow build/test image contract | PASS | New test executes the actual operational shell with recording command stubs, then intercepts the real smoke runner's Docker command and verifies it requests the built tag |
| CI policy regression | PASS | `uv run --frozen pytest services/api/tests/test_ci_reports.py services/api/tests/test_ci_changes.py -ra`: 133 passed, zero skips, 17.33 seconds |
| Actual ingress image build | PASS | `docker build -t csh-foundry-ingress:acceptance -f infrastructure/docker/ingress.Dockerfile .` |
| Actual nginx smoke | PASS | `FOUNDRY_INGRESS_TEST_IMAGE=csh-foundry-ingress:acceptance .venv/bin/python scripts/test_ingress.py`: nginx configuration, trusted TLS, HTTPS redirect, HSTS, private paths, unknown host, untrusted certificate denial and callback/query log redaction |
| Python lint and formatting | PASS | Ruff check and format check on the repository; 341 files formatted |
| Workflow syntax and expressions | PASS | actionlint on `.github/workflows/ci-suite.yaml` |
| Whitespace | PASS | `git diff --check` |
| Full hosted acceptance and other acceptance matrix jobs | NOT RUN | No workflow was dispatched; the supplied log covers only the operations job |
| Full application/fixture/semantic/Protégé suites | NOT RUN | No application, schema, fixture or semantic changes; this correction is confined to the CI image setting and policy regression |

The disposable smoke container was stopped by the harness. The local acceptance image
remains available. Next check: rerun hosted acceptance after the correction is available
on the selected revision; its own results determine acceptance status. Production remains
subject to PLANS.md §23B.
