# Phase 10 acceptance continuation (2026-11-02)

This continues the uncommitted acceptance patch based on
`e7de0616c37b4afe7f5b2eddcbde99687d63f10e`. Earlier evidence remains in
`../phase-10-closure/`. No migration or application schema changed; head is `0017_capacity`.
Developer services, credentials, backup files and volumes were preserved. Only disposable
`foundry-accept-*` projects and their newly created restore volumes were torn down.

Environment: macOS ARM64/Docker Desktop, actual production Compose template and previously
built/scanned closure images; isolated test CA, identities, database roles, networks and ports.
The upstream semantic binary runs under amd64 emulation. Private credentials and detailed logs
remain in ignored `artifacts/foundry-accept-*/`; do not publish those directories.

| Validation | Command / procedure | Result | Evidence / limitation |
|---|---|---|---|
| Combined-profile PostgreSQL 17.11 PITR | `PATH=/opt/homebrew/opt/node/bin:$PATH uv run python scripts/accept_phase10.py --output docs/architecture/evidence/phase-10-closure-2` | PASS | `deployment-pitr.txt`, `physical-recovery-first.json`; streamed physical base backup, actual archived WAL, named target, 46 Foundry/101 Keycloak public-table content hashes |
| Recovery source guards | `uv run pytest -q services/api/tests/test_pitr_guard.py` | PASS, 3 tests | `recovery-guard-tests.txt`; rejects developer project/container, unrelated archive and incorrect Desktop mount translation |
| Audit behavior and pool starvation regression | Configured real PostgreSQL, `pytest -q services/api/tests/test_security_platform.py -k audit` | PASS, 4 tests | `audit-tests.txt`; concurrent writes with one business connection, preserved independent audit and rollback semantics |
| Frontend tests/typecheck/format/build | `npm test`; `npm run typecheck`; `npm run format:check`; `npm run build` in `apps/studio` with Node on PATH | PASS | `frontend-*.txt`; 27 tests |
| Final rebuilt combined profile | Same acceptance command above | PASS, 38 assertions / 35 distinct checks | `deployment-final.txt/json`; includes concurrent job admission, PITR, rollback and multi-replica/logout faults |
| Final configured Python / migrations / fixtures / semantic integrations | `PATH=/opt/homebrew/opt/node/bin:$PATH uv run python scripts/validate_phase0.py` | PASS, 529 tests / 1 strict xfail / 0 skips, 463.55 s | `regression.txt`; raw pySHACL xfail and base owl-rl limitation preserved |
| Rebuilt API/semantic SBOMs and scans | `uv run python scripts/scan_images.py IMAGE --output artifacts/phase10-closure-2/NAME-scan` | SBOM PASS; high gate FAIL | `scan-api.txt`, `scan-semantic.txt`, six-image `vulnerability-disposition.json`; 60 high/zero critical each |
| Rebuilt image source identity | SHA-256 inside both images vs checkout | PASS | `image-source-check.txt`; API/audit/database sources |
| Paced HTTPS load | 1/4/8 clients, 60 seconds total | PASS execution/zero errors; read p95 target FAIL | `deployed-load.json`, `load-summary.json`; peak read/preview/traversal p95 556.513 ms, SDK 582.937 ms; regression/scans ran concurrently; no approved capacity/SLO |
| Concurrent job admission | 24 ingestion submissions/12 clients | PASS | `admission.json`; 20 accepted/four rejected, cancellation releases/reuses slot, final active usage zero; no byte/cross-tenant saturation claim |
| Static checks | Ruff check/format, strict mypy, diff whitespace | PASS | `static.txt`; 184 Python files formatted, 97 source files typechecked |

The first two continuation attempts stopped at the source-mount safety check because Docker
Desktop reports the bind source with a `/host_mnt` prefix. No recovery mutation occurred.
`deployment.txt` and `deployment-retry.txt` retain these failures. The guard now accepts only
the exact native path or its exact Desktop translation; it still rejects unrelated mounts.
The next complete run passed PITR and all downstream restart/rollback/logout checks.

Recovery scope: same-host database recovery into a network-isolated container, not startup of
the restored application/broker, off-host DR, encrypted-volume loss, key custody or approved
RPO/RTO. The disposable broker is stopped for the comparison interval. The original source
retains the post-target record while the restored cluster excludes it.

Container security remains FAIL/BLOCKED under the existing high/critical gate; no exception
is approved. Live external SSO, target hardware/capacity, production alert delivery, off-host
recovery and hosted release approvals/provenance remain NOT RUN as detailed in the main report.
No Phase 11 work was performed.

The admission run before the audit-pool fix failed: 23 of 24 simultaneous submissions returned
HTTP 500 after database lock/pool timeouts. `deployment-admission-failed.txt/json` retains the
failed scope and private diagnostic path. The API's lock holder needed an independent audit
connection while ordinary pool connections were exhausted by lock waiters. A separate bounded
two-connection audit pool now preserves audit failure/rollback semantics without consuming
ordinary connections; default API connection capacity is 12 per process. See the runbook and
ADR 0034 for the capacity implication. The API and semantic images were rebuilt for this change.

Browser E2E was not rerun in this continuation: the developer's active UX services occupy its
fixed localhost:3000 endpoint. Earlier closure evidence retains 5 passing E2E tests; the frontend
source is unchanged. Live user login/password entry is not claimed by this test evidence.

Final source/restore containers and volumes were removed. The developer's Studio/API/PostgreSQL,
recovered Keycloak/TLS proxy and unrelated services remain running. This does not represent a
user browser password-entry test or production deployment. Final acceptance remains BLOCKED.

Developer preservation was rechecked after teardown: Studio, API readiness and trusted Keycloak
HTTPS discovery return 200; the existing manufacturing ontology still contains one object and
Alembic remains `0017_capacity` (`developer-preservation.txt`). No migration was added.
