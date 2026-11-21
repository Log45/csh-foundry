# 0050 — Broad bounded regression with explicit acceptance suites

Status: accepted for the CI maintenance request.

A green push check must represent ordinary behavior across existing features. The former
single validation job combined development browser runs, large-data tests, and operational
drills while storage-dependent tests could silently skip without MinIO.

Run ordinary backend, Studio, SDK, and production-browser regression on every push/PR with
real PostgreSQL, isolated MinIO, and the pinned semantic engine. Run the non-superuser owner
and directory identity fixtures in distinct required jobs. Keep the operational schema and
all service boundaries unchanged. Explicit scale markers move only large-data cases to
scheduled/manual acceptance; new ordinary tests and browser specs join regression by default.

JUnit validation rejects absent, empty, failed, and unexpectedly skipped execution. Preserve
only the precisely identified existing strict RDFLib/pySHACL compatibility xfail as an
expected failure, never as PASS. A required aggregate job checks every dependency's result,
including failure, cancellation, and skipping. Tests are not retried automatically.

Release candidates and acceptance evidence cross jobs through explicit artifacts. Promotion
loads the exact candidate images rather than rebuilding after acceptance, and retains the
existing revision/image/evidence integrity checks. Infrastructure certification and deployment
remain governed by the existing production readiness requirements.

Tradeoffs: jobs repeat some dependency setup and Studio builds to remain isolated; caching
and parallel execution reduce wall time. Chromium alone bounds browser costs. The 10–15
minute push target must be checked against hosted timings before being claimed as achieved.
No database migrations, runtime architecture changes, or external settings changes result.
