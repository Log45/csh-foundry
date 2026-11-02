# Phase 10 implementation and acceptance report

Status: implementation delivered with successful application regressions; **production acceptance
is incomplete and promotion is blocked**. This is not a production-ready/certified declaration.
Keycloak is selected as requested. Phase 11 was not implemented. No external services, identity
organizations, public package registries or production resources were modified.

## Baseline and review

Initial revision: `769d68d9612fd4a06961fb8e8699d8199d1b250d`; working tree clean. Existing local
configuration/objects/Keycloak files were preserved. The Phase 10 brief, AGENTS, PLANS, root README,
fixtures/VALIDATION, previous reports/ADRs and actual authentication/session/BFF/worker/persistence/
SDK/container/CI implementations informed the [implementation checklist](phase-10-checklist.md).

An initial baseline attempt was invalidated by edits while it ran and was stopped. An isolated
checkout of the starting revision was then independently validated: **498 passed, one strict
expected failure, zero skips**, 274.13 seconds. Baseline frontend: 24 tests and type checking PASS;
browser: four tests PASS. PostgreSQL 17.6, Alembic `0015_sdk`, Python 3.12; semantic engine 2.1.0,
RDFLib 7.1.4/pySHACL 0.30.1, Next 16.4.3/React 19.3.1/TypeScript 5.9.3 were retained as the
baseline. New container bases use Python 3.12.16/trixie and Node 24/trixie; production PostgreSQL
configuration proposes 17.11/trixie. The existing development database/container was not replaced.
Dependency lockfiles remain authoritative; cryptography 50.0.2 is now an explicit dependency.

## Implemented functionality and architecture

- Production Compose profile with nginx TLS/host/private-path boundaries, segmented networks,
  nonroot API/Studio images, probes, bounded pools, process shutdown and maintenance-window release.
- Explicit production configuration and startup rejection of privileged/table-owner DB runtime roles.
  A real signed HTTP load sample uses a newly created restricted runtime role in an isolated schema.
- Replaceable Keycloak administrative realm renderer and standard runtime OIDC integration.
  Browser Code + S256 PKCE; separate confidential worker client; strict API audience/client_id/
  RFC 9068 profile retained. No custom token issuance or provider-role authorization added.
- Encrypted PostgreSQL login/session state accessed by Next through an authenticated internal
  governed service. Atomic consume/delete, bounded admission, expiration, CAS and key-ring rotation.
- Shared request budgets, transactional logical tenant artifact/staging accounting and combined
  active-job admission, with rollback and concurrency tests.
- Bounded ingestion/semantic/outbox child supervision, process-group deadlines/backoff, fresh
  standard client-credentials acquisition and existing principal/delegation/RBAC checks.
- Redacted JSON request spans/W3C trace identifiers, finite-label Prometheus histograms, private
  metrics endpoint, alert rules and operator incident/recovery/retention/rotation procedures.
- Encrypted logical backup tooling and an executed PostgreSQL physical-base/WAL target recovery drill.
- Independent SDK ZIP/inventory/file-digest/canonical-schema verification and tampering rejection;
  immutable scanner images, CycloneDX SBOMs, dependency audits, action SHA pins and gated release tooling.

The minimum profile remains a single-host failure domain with one API/PostgreSQL/Keycloak and one
or two Studio instances. Two built Next processes are tested; multi-host/HA/mixed-release rolling
operation is not certified. PostgreSQL remains canonical; existing governance, separate publication/
activation, authorization locks, action idempotency, branch history, worker fencing and semantic
approval/provenance are unchanged. See ADRs 0032–0034, the [threat model](../operations/threat-model.md) and [operator runbooks](../operations/production.md).

## Microsoft, Google and Workspace

Entra configuration pins one exact organizational tenant UUID and verified issuer/JWKS, with upstream
PKCE. Personal Microsoft accounts and common/multi-organization issuers are unsupported by this
profile. Google consumer and Workspace providers have separate configuration; Workspace requires an
exact hosted domain. Domains/emails/provider roles never establish platform membership.

Unknown upstream identities are denied by the configured first-broker-login flow. Operators must
verify issuer/subject ownership and explicitly prelink broker identities; platform bindings and
membership/role assignment remain separately governed. Automatic email merging and self-service
identity linking are unsupported. Initial organization routing uses a separate realm/Studio per
organization; no cross-tenant claim-based routing is introduced.

Actual pinned Keycloak Code/PKCE/token issuance is tested, including a service-client token. The
automated test uses a disposable loopback test transport; it is not a production TLS/upstream test.
Live Microsoft/Google/Workspace validation: **NOT RUN / NOT CERTIFIED**. Missing prerequisites:
approved external OAuth registrations, client credentials, Entra/Workspace administrator access,
test accounts/organizations, callback DNS/TLS and permission to exercise those external systems.
Their production certification remains a separate acceptance gate.

## Sessions, security and secrets

Only opaque cookie handles reach the browser; PostgreSQL stores their SHA256 digest and authenticated
Fernet ciphertext bound to row identity/kind. Session tokens remain server-side. Login consumption
and logout deletion are atomic; CAS rejects concurrent updates and deleted-row resurrection.
New login rotates handle/CSRF. Session lifetime never exceeds the signed token or one hour; selected
Keycloak access tokens last five minutes. No browser refresh/offline tokens are issued or retained.
Reauthentication is required at expiry. Standard broker logout uses a fixed redirect and no token
in the browser URL; local deletion succeeds even if broker logout is unavailable. Existing API JWTs
require platform revocation or expiry; browser logout is not instantaneous JWT revocation.

Production requires shared state and secrets; store/network failure has no memory fallback. Current
platform authorization is still checked by FastAPI for every governed request. Secret files and
rotation procedures are documented; no real credentials were committed. A private pre-migration
development backup is retained in ignored artifacts. Runtime DB credentials are separate from owner/
bootstrap credentials. Database-owner-proof audit storage and independently managed vault/archival
services are not claimed.

## Migrations and files

Development migration head is **0017_capacity**. Before upgrading, a private `pg_dump` backup was
saved. `0016_operations` adds encrypted browser state/request budgets; `0017_capacity` adds logical
usage accounting and active-job admission. Existing data is retained, with accounting backfill.
Metadata drift and migration round trips are covered by the actual PostgreSQL regression suite.
0016 downgrade destroys sessions; prior Phase 9 downgrades remain destructive to branch/SDK history.

Principal new/modified files:

| Area | Paths |
|---|---|
| API configuration/lifecycle | `services/api/src/ontology_platform/{config,main,dependencies,operations}.py`, `db/{models,session,governance}.py` |
| Sessions/broker/workers | `security/{browser,broker,oidc,workers}.py`, `jobs/{supervisor,outbox}.py` |
| SDK integrity | `sdk/integrity.py`, `scripts/verify_sdk.py` |
| Migrations/tests | `services/api/migrations/versions/0016_operations.py`, `0017_capacity.py`, `services/api/tests/test_operations.py` |
| Studio | `lib/server.ts`, auth/BFF routes, layout/workspace, `proxy.ts`, `instrumentation.ts`, security/browser tests and E2E backend |
| Images/deployment | `infrastructure/docker/{api,studio,semantic}.Dockerfile`, `studio-entry.mjs`, `infrastructure/production/*` |
| Validation/operations scripts | `configure_keycloak.py`, `test_keycloak.py`, `test_ingress.py`, `test_recovery.py`, `load_phase10.py`, `backup_database.py`, `maintain_operations.py`, `provision_production_database.py`, `validate_production_config.py`, `scan_images.py`, `smoke_phase10_containers.py`, updated `test_studio.py` |
| Delivery/dependencies | CI/release workflows, `services/api/pyproject.toml`, `uv.lock`, Studio format-check configuration |
| Documentation | README/PLANS, migrations guide, ADRs 0032–0034, Phase 10 checklist/report, production/readiness runbooks, alerts and Phase 11 preparation |

`AGENTS.md` and canonical fixtures are unchanged. No credentials, external provider accounts,
canonical schema changes or operational data rewrites were introduced by migrations.

## Validation results

All statuses below distinguish executed evidence from missing target acceptance.

| Check | Result | Evidence / limitation |
|---|---|---|
| Full configured Python regression | **PASS** | **521 passed, one strict xfail, zero skips**, 331.12 s; `validation-final.txt` |
| Ruff lint/format; strict mypy | PASS | Final checks, 97 typed application/schema files |
| Alembic head/drift/round trips | PASS | `0017_capacity`, no drift; disposable-schema reversals in regression |
| Turtle/CSV/RDF identities/FKs | PASS | Full fixture tests; six factories/20 machines/12 employees/25 tasks |
| Raw pySHACL fixture conformance | **FAIL (preserved expected failure)** | Raw simple-string/xsd:string mismatch; never called conformance PASS |
| Normalized SHACL / nine negative cases | PASS | Existing independent in-memory checks, fixtures unchanged |
| Open Ontologies validation / extended reasoning | PASS | Pinned engine integration in full regression |
| CriticalMachine under base owl-rl | NOT SUPPORTED | Existing documented upstream capability limit preserved |
| API queries, actions, idempotency, ingestion, security | PASS | Real PostgreSQL regressions, original security assertions preserved |
| OWL import/export / SDK generated-package tests | PASS | Full regression includes actual independent Python/TypeScript package tests |
| Protégé GUI / deployed WebProtégé | NOT RUN | No GUI session or deployed service; existing optional file harness is not a GUI claim |
| Independent proof-certificate verification | NOT RUN | No separate verifier executed |
| Frontend tests | **PASS** | **27 tests**; `frontend-final.txt` |
| Frontend type/format/build | PASS | Executed type/format checks and optimized/container builds |
| Browser manufacturing/security/authoring/branches/SDKs | **PASS** | **Five browser tests**, including two built replicas; `durable-e2e.txt` |
| Session replica restart/logout | PASS | Same shared session after restart; other replica denied after logout |
| Store expiry/CAS/consume/key rotation/capacity | PASS | Real PostgreSQL tests; frontend outage/no-fallback tests |
| Actual Keycloak RFC 9068 / PKCE / nonce / replay | PASS | `keycloak.txt`; real pinned broker, controlled transport |
| Ingress TLS/HSTS/Host/private paths | PASS | Actual disposable nginx, trusted certificate succeeds/untrusted rejects; `ingress.txt` |
| Physical backup/WAL/PITR | PASS | `recovery.txt`; restores committed post-backup data, excludes post-target record |
| Encrypted logical backup/restore | PASS | Actual dump → age → isolated PostgreSQL restore; source object count matches; `encrypted-backup.txt` |
| Off-host/disaster-site RPO/RTO drill | NOT RUN | Destination, custody, recovery host and named operators not configured |
| Worker process termination/recovery/deadlines | PASS | Existing actual crash/recovery tests plus bounded supervisor child test |
| Semantic worker image execution | PASS | Nonroot Linux/amd64 pinned engine in read-only/no-network container; `semantic-container.txt` |
| API/Studio image probes | PASS | Real DB readiness/nonroot/template packaging/security headers/denial; `container-smoke.txt` |
| Full combined production-profile deployment acceptance | **NOT RUN** | Individual controls tested; not one all-services deployed acceptance run |
| Runtime dependency audits | PASS | pip-audit and npm audit report no known runtime dependency vulnerabilities |
| CycloneDX SBOM generation | PASS | Immutable Syft; raw SBOMs retained under ignored `artifacts/` |
| Container vulnerability release gate | **FAIL** | Remaining high-severity OS findings; see below |
| Hosted CI/environment approval/provenance verification | NOT RUN | Workflow prepared, no hosted run/required-reviewer configuration executed |
| Live Entra/Google/Workspace | **NOT RUN / NOT CERTIFIED** | External prerequisites absent, not simulated as live success |

An intermediate full run had four ingestion recovery/concurrency failures; a focused rerun passed
all eight recovery tests and the final full suite passed. The earlier failed run remains in
`regression.txt`; it is not counted as a passing run. Initial browser integration failures were
also followed by the successful five-test built-replica run. After the final logging/driver-parameter hardening, 26 focused API/operation tests also passed.
No assertions or canonical fixtures
were weakened to obtain the passing final regression.

## Performance and workload governance

The restricted-role signed HTTP workload covers tenant/membership discovery, object/Object Set
queries, traversal, action preview/idempotent execution, branch comparison/merge preview, both SDK
languages, artifact retrieval and ingestion/semantic submission. Latest local sample: **70 requests,
eight concurrent clients, 52.34 requests/s, zero errors**, largest per-operation p95 **235.569 ms**.
CPU time 1.175 seconds; ending lock-wait/pool-checked-out samples zero. `load.json` records hardware/
platform, RSS, database counters, statuses and per-operation p50/p95/p99. Five samples per operation
are small; upper quantiles use conservative nearest rank. Shared database counters are not isolated
host utilization and no production capacity guarantee is inferred. Worker throughput/queue age and
target-scale memory/disk/load/fault exercises remain deployment gates. HTTP deadlines do not
forcibly terminate an already executing synchronous thread; database transaction budgets and
action idempotency remain necessary for safe retries. Worker children have separate hard
process/container deadlines.

Provisional targets (read p95 500 ms/write p95 two seconds/zero workload errors) are proposals, not
approved business SLOs. Quotas limit logical retained artifacts/staging and active jobs, not total
physical storage, audit retention or every object/history category. Monitor physical/WAL growth.

## Supply-chain findings and release gate

The first scan found fixable old-base/runtime-tool vulnerabilities. Python/Node container bases
were updated and unused npm/Yarn tooling removed from Studio runtime. Runtime Python/npm audits
pass. Remaining scanned matches include **57 high/zero critical API matches** and **56 high/zero
critical Studio matches**, with no fix version reported for those high matches by the scanner.
Match counts are not unique vulnerability counts. No fabricated exception/allowlist suppresses them.
Raw scanner/SBOM data and hash summaries are retained; `vulnerability-summary.json` records evidence.

These findings require further remediation or an explicitly authorized, evidence-backed risk review
before production promotion. A passing application regression does not override this failed gate.
Release CI uses frozen dependencies, immutable scanner/action identities, SBOMs, archive checksums
and an optional GitHub provenance attestation. It stops on high-severity scan failures and never
deploys automatically. Individually signed SDK artifacts and hosted provenance verification remain
unimplemented/unexecuted respectively; no such signature guarantee is claimed.

## Remaining acceptance and Phase 11 readiness

The [23-category readiness matrix](../operations/readiness.md) lists implementation, test,
deployment, owner and residual risk separately. Before claiming Phase 10 fully accepted: resolve
the vulnerability gate; execute the combined production-like profile's manufacturing/recovery/
supervised-worker/fault/alert/secret/role gates; assign named owners and off-host backup/alert
delivery; execute hosted release/provenance gates where supported. Real providers require their
separate live certification. This work is not silently deferred to Phase 11.

Recommended next work is closing these **Phase 10 acceptance gates**, not beginning Phase 11.
`phase-11.md` is preparation only. Production readiness and Phase 10 final acceptance are withheld
until the remaining evidence-backed gates are satisfied.
