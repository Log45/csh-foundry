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

---

# Acceptance closure — 2026-11-02

This section supplements the implementation report above. Its historical results remain intact.
Starting revision: `e7de0616c37b4afe7f5b2eddcbde99687d63f10e`; the checkout had no pre-existing
uncommitted changes. The closure changes remain reviewable in the working tree. Phase 11 was not
started. No external infrastructure, provider organization, repository protection rule, existing
local credentials, developer database or existing Keycloak configuration was modified.

## Executive decision

| Decision | Status | Reason |
|---|---|---|
| Phase 10 implementation delivered | PASS | Existing architecture preserved; documented deployment defects remediated; regressions executed |
| Locally accepted (all mandatory gates) | BLOCKED | Container gate FAIL; remaining comprehensive operational scenarios itemized below |
| Production-like accepted | BLOCKED | No representative target capacity/SLO acceptance; incomplete operational/security gates |
| Production certified | BLOCKED | Actual target, named owners, off-host custody/recovery, production alerting, hosted controls and live SSO unavailable |

**Phase 10 has not met complete acceptance criteria. Production readiness is withheld.** A successful
local script is scoped evidence, not an override of the failed security gate or an owner approval.
Recommended next work remains Phase 10 closure; Phase 11 is still unapproved.

## Baseline and regression

Both Alembic source head and configured database current revision are `0017_capacity`. Drift checks
pass. No migration was added or applied to change application schema. Existing `0016_operations`
and `0017_capacity`, strict raw pySHACL expected failure and the base `owl-rl` limitation remain.

The original configured baseline was reproduced: **521 passed, 1 strict expected failure, zero
skips** (354.24 seconds). The closure adds four tests for the resolved Compose runtime/security
contract, semantic import boundary and release evidence rejection. The configured full regression
subsequently passed **525 tests, 1 strict expected failure, zero skips** (367.98 seconds in
`final-regression.txt`); the repeated run passed the same **525/1/0** result in **351.39 seconds**
(`regression-final.txt`); the final release repeat passed **525/1/0 in 353.28 seconds**
(`regression-release.txt`).
Ruff lint/format and strict mypy pass (97 application/schema source files). Frontend tests pass
**27/27**; typecheck, formatting and production build pass. The final durable browser run passes
**5/5**. An initial browser activation assertion failed, and an unchanged rerun passed; both outputs
remain. No assertion, canonical fixture or strict expected failure was weakened.

All closure evidence paths in this section are beneath
`docs/architecture/evidence/phase-10-closure/` unless stated otherwise. The evidence index gives
commands, environments, limitations and explicit NOT RUN/NOT SUPPORTED statuses.

## Security remediation and disposition

Fresh production builds and current-database Grype scans retain **60 high/zero critical API
matches, 59 high/zero critical Studio matches, and 60 high/zero critical semantic-image matches**.
There are **18 distinct high advisories per image**. The retained reports confirm the historical 57/56 counts; the refreshed
scanner database adds three SQLite advisories. No fix
version is reported for the remaining high matches in the selected maintained distribution.

The [vulnerability disposition](../operations/vulnerability-disposition.md) and machine-readable
per-match inventory record image identity, scanner/database version/time, installed package/version,
source/layer, available fix, repeated matches, bounded reachability observations, residual exposure,
evidence hashes and required owner approval. All severities are retained. Read-only runtime probes
show Pod::Text and Archive::Tar cannot be loaded in API/Studio; those package-origin findings are
still retained for review. No VEX assertion, suppression or risk exception was fabricated.

Python/Node/uv base references now pin the observed reviewed multi-platform digests. Production
Python/npm audits and SBOM generation pass. Infrastructure scanning additionally found critical
PostgreSQL/libxml2 and Keycloak/Java-CA findings and fixable ingress findings; see the extended
disposition below. Essential base packages were not force-purged or replaced
with unstable distribution packages. **The existing high-severity scanner gate still exits nonzero**.
Fixes or explicitly authorized owner dispositions are required; no such approval exists.

## Combined production deployment

`scripts/accept_phase10.py` provisions a uniquely named disposable Compose project with actual
production Dockerfiles/configuration: nginx, Studio (then two replicas), FastAPI, PostgreSQL 17.11,
Keycloak 26.8.1, supervised ingestion and semantic workers, and the pinned semantic engine. Artifact
state remains in PostgreSQL; no second datastore was introduced. The outbox profile is optional and
was not enabled because no receiver/destination was configured.

Test-only overrides select loopback ports, private test CA mounts, separate subnets/trusted proxy
address and a disposable database management network/port. No target DNS/public certificate or
production immutable-image approval is inferred. The production preflight correctly does not
approve `.test` hostnames or local image tags. API/Studio/workers retain their production internal
networks, least-privilege roles, read-only filesystem and limits.

Actual startup exposed and remediated: YAML splitting an unquoted tmpfs option into an invalid
mount; missing API catalog configuration; and API OIDC warmup before broker readiness. The broker
now has a real management readiness probe. Ingress has exact-host HTTP redirects and internal DNS
aliases. API uses the non-owner runtime role, never the superuser/migrator credential. Owner
migrations and post-migration grants are explicit; no startup migration was added.

## Authentication and external SSO

Actual HTTPS broker → Studio Code/PKCE → API sessions pass. Secure/HttpOnly/SameSite cookies,
state/nonce/single-use callback and current platform authorization remain. Independent pinned-broker
checks cover discovery/JWKS, RFC 9068 audience/client/issuer/signature, ID-token rejection, code replay,
required PKCE and no refresh-token issuance. Existing security regressions cover expired/forged/wrong
issuer/audience tokens, JWKS/key behavior, disabled identities, ABAC and tenant isolation.

The pinned broker imports the rendered Entra, Google and Workspace provider configurations using
**disposable dummy configuration credentials** without invoking those providers. This verifies import
compatibility only. Live Microsoft/Google/Workspace authentication is **NOT RUN / BLOCKED**. Exact
prerequisites and procedures remain in the operator runbook: approved organizations and OAuth
registrations/consent/callbacks, protected test credentials/users, verified immutable subject links,
organization/domain restrictions and operator authorization. Email/provider roles confer no platform
membership. No Graph token or Google ID token is accepted as a platform API credential.

## Sessions and lifecycle

The combined profile verifies PostgreSQL encrypted storage, two Studio containers, each container's
restart while the other serves the same session, shared logout rejection on both, database/session
store outage failure, key overlap and rejection after removing a required decryption key. Existing
race/expiry/CAS/tamper tests pass. Sessions contain API tokens only; refresh tokens/localStorage token
storage were not introduced. Actual per-credential maintenance rotation results appear individually
in `deployment.json`; procedure text alone is not counted as execution.

## Manufacturing acceptance

The deployed governed fixture workflow creates exactly **6 factories, 20 machines, 12 employees,
25 tasks, 63 objects and 70 forward links**. A worker is killed after durable checkpoint ownership;
a later attempt reclaims the expired lease and completes without duplicate objects/links. Operational
queries, MCH-005 retrieval, Object Sets, relationship traversal, preview, action execution, replay and
stale expected-version rejection pass.

Branches are created/edited/compared; a conflict is detected/resolved, preview hash checked, merge
executed and provenance inspected. A normal draft is handed off, validated and published; active
version remains 1.0.0. Development/merge/publication and semantic inference do not silently activate
schemas or mutate operational objects. Explicit activation is independently covered by the browser
and application regressions; the closure's new draft deliberately remains unactivated.

Both SDKs are generated/downloaded through authorized deployed APIs and independently verified
against manifest inventory, canonical schema hash and expected archive digest. Tampering fails.
The actual Python archive is installed in a separate virtual environment; TypeScript is independently
compiled. Both query and execute/replay governed actions over the real HTTPS API, rejecting forged
credentials and foreign tenants. Test DNS mapping and an explicit private CA trust only the disposable
listener; no HTTP mock or disabled TLS verification substitutes for these requests.

## Workers and semantic isolation

The actual supervised ingestion SIGKILL drill verifies durable checkpoint/lease recovery, a second
claim and final fixture state. Semantic validation and extended-profile reasoning run through the
actual supervisor/engine and preserve provenance without automatic operational mutation.

An amd64-emulation crash was traced to the semantic worker importing the ingestion worker merely
for its clock helper, which initialized AVX-dependent Polars. The helper now lives in the database
module; both worker types retain the same PostgreSQL clock/fencing semantics. A subprocess regression
ensures semantic imports do not initialize Polars. Ingestion still uses Polars.

The running semantic container verifies nonroot execution, failed writes to the application root,
128 MiB tmpfs, cgroup memory 805306368 bytes, one CPU, 128 PIDs and blocked direct Internet egress.
The internal database/frontend networks remain available to its supervisor; this is not a separate
arbitrary-code sandbox. Existing process-group cancellation/deadline/fencing/output-limit tests pass.
The engine pin, semantic provenance and base `owl-rl` limitation are unchanged; independent proof
checking and universal OWL completeness are not claimed.

## Database recovery

The combined profile streams an age-encrypted logical dump and restores to a new disposable
database. Row-count/content checksums match across 21 selected tables, including objects/links,
active schema/version history, branches/merges, SDK metadata/artifacts, identities/memberships/roles,
audit/action history, ingestion/semantic state and encrypted browser sessions. It does not overwrite
the serving database or write a plaintext backup file.

The earlier separate physical/WAL drill passed on PostgreSQL 17.6. The November 2 continuation
also passes named-target PITR against the actual combined-profile PostgreSQL **17.11** image.
A streamed physical base backup plus archived WAL restores into a new network-isolated volume.
All **46 Foundry and 101 Keycloak public tables** match target row-count/content hashes; governed
records committed before and at the target are present, and the later record is excluded. The
source retains all three records and is never overwritten. The disposable broker is stopped during
the snapshot/target interval to make its table comparison stable. This proves same-host database
recovery, not restored broker/application startup, broker-cluster recovery or disaster recovery.
See `phase-10-closure-2/physical-recovery.json` and `deployment-pitr.txt`. Off-host/disaster-site
recovery, encrypted-volume loss, key custody and target RPO/RTO remain **NOT RUN**. Production
recovery objectives remain proposals.

## Observability, quotas and performance

The unchanged two-minute API outage rule is evaluated by actual pinned Prometheus and Alertmanager;
a disposable receiver records firing and resolution. This is **PASS local delivery mechanics** with
a synthetic scrape target. Production scrape topology, approved receiver/on-call owner, host/WAL/
backup/queue/storage probes and production delivery remain **NOT RUN**. Earlier harness attempts
failed resolution because the synthetic target omitted the required Prometheus content type; those
failures are retained, the fixture was corrected, and the actual rule was not weakened.

Atomic request budgets, tenant logical byte/job quotas, concurrency and reservation rollback pass
real PostgreSQL regression tests. The continuation also passes deployed one-tenant ingestion-job
admission with 24 submissions from 12 clients against the shared 20-job limit (20 accepted, four
constraint rejections), rejected-admission rollback, cancellation release and slot reuse. Tenant
logical-byte/cross-tenant saturation and physical storage capacity remain unverified. Logical accounting excludes object/audit/index/TOAST/WAL growth and backup retention.
Runbooks now state separate capacity/alerting requirements and provisional headroom thresholds.

The combined HTTPS BFF sample runs 260 paced requests over about 60 seconds at 1/4/8 clients across
queries, Object Sets, traversal, action preview and SDK generation. `deployed-load.json` records exact
throughput, latency samples/quantiles and errors. This is a short fixture-scale sample, not saturation
or representative production load. Compare final per-operation p95 against proposed 500 ms reads /
2 s writes; no business SLO or capacity guarantee is approved. Continuous CPU/memory/pool/lock/queue/
worker/storage distributions and sustained concurrent branch/artifact/ingestion/semantic workloads
remain **NOT RUN**. Earlier samples show host-load variability and must not be silently discarded.

## Failure injection, rotation and rollback

Executed combined-profile checks include ingestion SIGKILL with state recovery, Studio restarts,
API outage/rollback, PostgreSQL/session-store interruption, callback replay, invalid/foreign SDK
credentials, stale action revision, SDK tampering, active-session role/membership revocation,
shared logout, decryption-key overlap/removal and actual runtime isolation. Actual confidential-worker OIDC secret rotation rejects the old credential, then workers reacquire
the new one; queued delegation revocation prevents claims until reauthorized and the repeat remains
idempotent. API/Studio internal credential and runtime database password rotation preserve the
session while rejecting old database logins. Ingress tests verify exact-host HTTP redirects, HSTS,
unknown hosts, untrusted certificates, forged origins/forwarded hosts, fixed callbacks, CSRF and
request-size rejection. Each result appears in the final `deployment.json`.

Rollback deliberately stops API traffic, starts the retained previous Phase 10 API image against
the compatible 0017 schema, verifies the same session/object/active pointer/SDK history, and restores
the current candidate. No database downgrade or branch/SDK-history deletion is used. Mixed-release
rolling operation, database downgrade safety and complete worker behavior during a failed rollout
are not claimed.

Signing-key/JWKS outages, live-provider outages, artifact-store/SDK interruption, outbox delivery
interruption, all merge/action/revocation races and all queued/executing credential scenarios have
**not all been injected into the combined profile**. Existing isolated security/worker regressions
are useful evidence, not a replacement for those missing deployment exercises. Browser client-secret
rotation is **NOT SUPPORTED** because Studio is a public PKCE client. Individual artifact-signing-key
rotation is **NOT SUPPORTED** because individual artifact signing is not implemented. No real
production secret was rotated.

## Release and supply chain

Release CI keeps frozen dependencies, immutable action/tool pins, restricted permissions, tests,
audits, SBOMs, high-severity scanning and manual environment approval. It now builds/scans/archives
the semantic image as well as API/Studio and retains scanner JSON on failure. An evidence verifier
rejects absent/non-PASS mandatory local gates, mismatched candidate revision/image identities,
path escapes and changed evidence bytes before archive/provenance/promotion. Its negative tests pass;
actual missing evidence blocks the local command as expected. It does not manufacture approvals.

Hosted CI execution, reviewers/branch/environment enforcement, attestation verification and retention
are **NOT RUN** without an authorized hosted run. The exact-candidate evidence handoff must be
configured before hosted release promotion can succeed. The workflow does not deploy automatically.
SBOMs/checksums do not imply individual SDK signatures or production provenance certification.

## Files, architecture and remaining work

Changes comprise production Compose/nginx/Dockerfile fixes, shared database-clock imports, focused
regressions, disposable acceptance/alert/disposition/evidence-verifier scripts, the release workflow,
operator/readiness/vulnerability documentation and this report/checklist/roadmap/README addendum.
`files.txt` lists the exact changed/new files. No schema migration or canonical fixture change exists.
ADRs 0032/0033 remain in force; ADR 0034 gains the tested operational decisions.

The [23-category matrix](../operations/readiness.md) distinguishes implementation, validation,
deployment, owners, evidence, residual risk/actions and acceptance. Required named owners are still
unassigned. Every mandatory gate with missing evidence remains NOT RUN/BLOCKED. Close retained
container findings and the remaining Phase 10 operational/target/external gates; do not begin Phase 11.

## Infrastructure security closure addendum

Scanning was extended to the actual PostgreSQL, Keycloak and nginx images. The retained ingress
base had 154 high/45 critical matches. OS updates and removal of unused vendor modules eliminated
most; a same-line nginx package update still retained two core advisories. The supplier's security
advisory identifies stable **1.30.6** as fixed, so the final ingress Dockerfile uses that maintained
official release, pins its observed digest and applies Alpine updates. The actual TLS/host/private
path/redirect and callback-log sentinel tests run against the resulting image. Its final scanner
result is recorded in `ingress-stable-scan.txt`, not inferred from the version change.

Keycloak remains 26.8.1, refreshed to supplier digest
`3f3c5f8e03c614774b4bd9173b88391fefa4153bfc010d8012d59ad825377332`.
The fresh image removes the reported fixable OpenJDK package finding, but retains 3 high/1 critical
matches. The critical Java CA-store issue requires a reviewed supplier/trust-store remediation.
Guava has a reported library fix (33.7.2), but the current supported supplier image still bundles
the affected library. No ad-hoc jar replacement is presented as supplier-certified; obtain a
supplier update or separately reviewed/tested custom distribution before promotion. Local Code/PKCE
and all three provider-configuration imports pass with the refreshed image; live federation remains
NOT RUN. PostgreSQL's selected current 17.11-trixie image retains 92 high/1 critical matches, including
libxml2 CVE-2026-6653 with no scanner-reported stable-distribution fix. Mixing unstable Debian
packages or silently switching an existing cluster's libc/collation distribution was not attempted.

The complete disposition includes every selected image, observed package/fix metadata and residual
exposure. A version/source assessment does not override scanner exit status or approve an exception.
The release workflow scans all six selected images, archives all four custom images, and requires
exact-candidate evidence including ingress. `INGRESS_IMAGE` is now an explicitly required production
input; the example, preflight, harness and regression fixture are updated together.

A callback sentinel also exposed inherited nginx URI logging in HTTP redirect/default-host blocks.
All server blocks now explicitly use status/duration-only access logging. The unchanged production
template is tested both in a disposable isolated ingress container and in the full profile. An
intermediate custom package image failed full-profile configuration generation despite isolated
nginx syntax passing; it was corrected and superseded by the maintained official stable release.
Those failed runs remain in the evidence directory.

## Final selected-image execution and performance result

`acceptance-stable.txt` and `deployment.json` record **34 PASS assertions (32 distinct checks)** for
the final selected profile, including stable patched ingress and the refreshed same-version broker.
The ingestion crash recovered on attempt 2, advancing its durable checkpoint from 29 to 65. The
final selected ingress scan **passes** with zero high/critical and three medium findings. Remaining
API/Studio/semantic high findings and PostgreSQL/Keycloak critical findings keep overall security
acceptance blocked. `vulnerability-disposition.json` covers all six selected images; source hashes
and image identities are retained.

The final 260-request, 60-second paced HTTPS sample has zero errors. Throughput at 1/4/8 clients
is approximately **0.996 / 3.982 / 7.955 requests/s**. Largest per-operation p95 at eight clients is
**343.183 ms for reads/preview/traversal and 359.103 ms for SDK generation**. Proposed engineering
targets pass for this scoped sample. Earlier contended samples missed the read target and remain
in `contended-deployed-load.json` and `contended-load-summary.json`. Investigation also identified
a Docker port-lookup control command inside each timed request; the final runner resolves that
fixed disposable port once before sampling. HTTP/TLS/client overhead remains included, assertions
and request counts are unchanged, and no production performance improvement or capacity guarantee
is inferred from this measurement correction. The target remains paced, not saturated, and does
not replace the missing representative sustained workload/resource distributions.

`backup-rotation.json` additionally verifies local age recipient rotation using the actual tested
combined-profile backup: old and new recipients decrypt identical archive payloads, the old key
cannot decrypt new ciphertext, and the historical backup remains readable with its retained key.
No plaintext backup file is written. Production/off-host custody, owner authorization and host-loss
recovery remain NOT RUN. Browser public-client and unimplemented artifact-signing key rotation remain
NOT SUPPORTED, as explained above.

Final local workflow syntax/action-pin checks pass (`workflows.txt`), four focused closure tests pass,
and Ruff lint/format, strict mypy and diff whitespace checks pass after the operational edits. No
canonical fixture or migration changed. The final acceptance decision remains **BLOCKED**, with
implementation delivered and scoped local checks passing; complete local, production-like and
production certification are not claimed.

## User-requested local UX recovery

After closure validation, the user requested recovery of their missing local Keycloak for Studio UX
testing. The October 29 full-filesystem backup checksum was verified and restored to new identity
containers, preserving its embedded H2 realm/users/signing keys and the existing Foundry database.
The original backup, credentials, CA and configuration were not overwritten. The restored `dev`
subject/client contract, HTTPS discovery/macOS certificate trust, existing membership, login form,
API readiness and Studio HTTP 200 were verified. `scripts/start_local_studio.py` provides the safe
startup order; the recovery steps are documented in `docs/development/keycloak-local.md`.

This user-requested local snapshot is distinct from the production profile and its selected
release images. No production certification or successful browser password entry is inferred.
The original tenant (**Phase 1 local smoke**) retains active manufacturing 1.0.0 and its existing
one object; the 63-object acceptance fixture remained confined to disposable test deployments.


## Acceptance continuation — combined PITR and concurrent admission

The user requested continued Phase 10 acceptance after local UX recovery. The continuation keeps
all developer services and the recovered Keycloak separate from new disposable acceptance projects.
Evidence is retained in `docs/architecture/evidence/phase-10-closure-2/`, alongside the earlier
closure evidence. No migration is added; the head remains `0017_capacity`.

The first complete continuation passes PostgreSQL 17.11 physical/WAL named-target recovery, including
all 46 Foundry and 101 Keycloak public tables. The source retains the post-target governed object;
the recovered cluster contains only the pre-backup and target objects. The restore container has
no network and uses the exact source PostgreSQL image. This is same-host database recovery; restored
application/broker startup, disaster-site recovery and approved RPO/RTO remain separate requirements.
Three guard tests reject developer containers, unrelated archive paths and incorrect Docker Desktop
bind translations before archive ownership changes. Initial guard failures and the later passing
run are preserved, rather than silently replacing them.

A subsequent 24-submission/12-client ingestion-admission exercise exposed a real API defect:
23 requests returned HTTP 500 after lock/pool timeouts, while only one succeeded. All ordinary
connections could be occupied by transactions waiting for the ontology lock; its holder then needed
an additional connection to flush independent authorization audit before commit. This was connection
pool starvation, not proof that the tenant quota was reached. The failed run is retained in
`deployment-admission-failed.txt/json`; its downstream checks were NOT RUN.

The API now provides authorization audit with a distinct two-connection pool, no overflow, using
the same restricted role, database and schema. Ordinary pool limits and lock/statement timeouts
remain unchanged. Audit failure still aborts the business mutation, and decision evidence still
survives business rollback. A real PostgreSQL regression exercises four concurrent governed API
creates with only one ordinary connection, then verifies objects and audit persistence. Four focused
audit tests pass, including existing rollback and audit-failure behavior (`audit-tests.txt`).
Default per-process API connection capacity is now 12, requiring explicit capacity accounting in
the runbook/ADR. Sequential single-job worker children retain their existing pools. No new service,
datastore, authorization authority or Phase 11 capability is introduced.

The rebuilt-profile admission retest passes: 24 submissions from 12 concurrent clients result in
exactly 20 accepted jobs and four HTTP 409 `constraint_conflict` rejections. Another rejected
submission leaves usage unchanged; cancellation reduces active usage to 19, a new submission
reuses the slot, and cancelling the remaining runs returns active usage to zero. Median/max request
latency is 344.316/638.910 ms. The 20 ms lock sampler observed zero lock waiters; this does not prove
there were no shorter waits. Only ingestion submissions to one tenant's combined job limit were
saturated; concurrent semantic-vs-ingestion admission, cross-tenant saturation, logical-byte limits
and physical disk/WAL capacity are not certified (`admission.json`).

The continuation's 260-request/60-second paced HTTPS sample has zero errors. Its largest read/
preview/traversal p95 is **556.513 ms**, so the provisional 500 ms read target is **FAIL**; SDK p95
peaks at **582.937 ms**, below its provisional 2 s target. Full regression and image scans ran
concurrently; this is context, not a proven explanation or waived target. Earlier passing scoped
samples remain historical evidence. Representative target capacity and approved business SLOs
remain **NOT RUN**. See the continuation's `deployed-load.json` and `load-summary.json`.

Fresh API/semantic builds and SBOM generation pass; both exact rebuilt image scans retain 60 high
and zero critical matches. The current six-image disposition is retained in the continuation folder;
unchanged images retain their earlier evidence and identities. The vulnerability release gate
remains **FAIL / BLOCKED**, without a risk exception.


The final rebuilt-profile run passes **38 assertions across 35 distinct checks**, including the
new WAL ownership guard, concurrent admission and full-profile physical recovery, followed by
compatible-image rollback, encryption-key overlap/rejection, ingress negatives, both Studio replica
restarts, PostgreSQL outage fail-closed behavior and shared logout (`deployment-final.txt/json`).
Generated source/restore containers and volumes were removed; private evidence and the existing
developer services remain intact. SHA-256 comparisons inside both rebuilt images match the reviewed
API/audit/database source (`image-source-check.txt`).

Final configured regression (`PATH=/opt/homebrew/opt/node/bin:$PATH uv run python
scripts/validate_phase0.py`) passes **529 tests, one preserved strict xfail, zero skips**, in
**463.55 seconds**. Ruff lint/format, strict mypy, Alembic drift and fixture/semantic/OWL/security/
branching/SDK integrations pass in that run. The raw pySHACL expected failure and base `owl-rl`
limitation remain unchanged. Frontend tests pass **27/27**, typecheck/format and production build
pass. Browser E2E was not rerun in this continuation because its configured localhost:3000 endpoint
is serving the user's recovered UX environment; earlier closure evidence retains five passing E2E
checks and the frontend source is unchanged. Optional Protégé GUI/live external providers remain
NOT RUN; individual artifact signatures remain NOT SUPPORTED. No migration was created.

Continuation files: `scripts/phase10_pitr.py`, acceptance-runner extensions, three recovery-guard
tests, one audit pool regression, and API database/security/lifespan changes. Operations, readiness,
vulnerability disposition, ADR 0034, checklist and roadmap documentation record the results and
capacity implications. The continuation evidence README inventories commands, scope and limitations;
its `source-files.json`, `images.json` and `SHA256SUMS` bind the retained evidence to the patch/images.

**Final acceptance remains BLOCKED.** Implementation is delivered; complete local acceptance,
production-like acceptance and production certification are not achieved. Security findings,
provisional read-latency misses, remaining deployed byte/cross-tenant/fault scenarios, representative
capacity, named owners, off-host custody/recovery, production monitoring delivery, hosted release
approval/provenance and live provider certification remain explicit Phase 10 requirements. No
production approval or risk waiver is inferred, and Phase 11 remains unapproved.
