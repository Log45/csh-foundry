# Phase 10 — approved scope and implementation checklist

Approved by the user with Keycloak selected. Phase 11 is not authorized. Initial revision:
`769d68d9612fd4a06961fb8e8699d8199d1b250d`, clean working tree. AGENTS, roadmap, fixture validation,
previous reports/ADRs and service/UI/infrastructure implementations were reviewed. This maps the
brief's deliverables to changes and evidence. Implementation is not production acceptance.

| Brief items | Baseline | Changes / acceptance |
|---|---|---|
| 1–2 topology/reproduction | Local Compose | Production Compose/networks/runbook; target deployment remains a gate |
| 3 images | API root; Studio nonroot | Both nonroot, current Python/Node bases, npm removed from Studio runtime; scans enforced |
| 4–5 TLS/network | Local CA/proxy | Exact hosts, HSTS/proxy boundaries/private paths; actual nginx TLS test |
| 6 configuration | Explicit OIDC/local modes | Production mode, required durable keys/origins/hosts, runtime DB privilege rejection |
| 7–9 lifecycle/releases | API probes, bounded CLI | Container probes, graceful shutdown/supervision, release/restore procedures |
| 10 broker | Generic OIDC, private local Keycloak | Realm renderer, isolated admin config, ADR, actual pinned token tests |
| 11–13 external SSO | Deferred | Entra exact tenant, Google, Workspace configs; live NOT RUN / NOT CERTIFIED |
| 14–18 sessions/rotation/logout | Local maps | Encrypted PostgreSQL state, consume/CAS/revocation/logout; two built replicas/restart test |
| 19 outages | JWKS fail closed | Preserve OIDC tests; shared-store outage/no-memory fallback tests |
| 20–21 onboarding/linking | Governed Phase 7 identities | Operator workflow; deny unlinked upstream login; no email merge |
| 22–24 secrets/roles/audit | Existing security triggers | Mounted secrets/key ring; owner/runtime provisioning and startup checks; audit archival operational gate |
| 25–27 backups/recovery | Deferred | Encrypted dump tool, actual physical/WAL recovery drill, DR runbook; off-host drill remains |
| 28–30 telemetry/alerts | Probes | JSON request spans/private histograms/rules; receiver and host/WAL integration remain |
| 31–33 admission | Per-request limits | Shared identity budgets, edge address limits, tenant byte/job triggers, concurrency/rollback tests |
| 34–36 workers | One-job CLIs/leases/fencing | Supervisor, fresh service tokens, process-group deadlines/backoff/container isolation; crash tests retained |
| 37–38 maintenance/storage | Immutable artifacts/staging cleanup | Logical quota; bounded state cleanup and physical-capacity/retention runbook |
| 39–44 supply chain | Locks/deterministic SDKs | Frozen builds, audits, immutable scanners, SBOMs, independent SDK verifier, release provenance workflow |
| 45–46 CI/gates | Regression CI | Immutable action pins/restricted permissions; broker/recovery/session/load checks/manual release; hosted NOT RUN |
| 47–49 integration/load | PostgreSQL/browser/SDK tests | Two built replica tests; signed real HTTP workload and percentiles/CPU/RSS/DB statistics |
| 50–52 faults/security | Crash/revocation/key tests | Session races/expiry/key rotation/outage, process deadlines, ingress and SDK tampering tests |
| 53 live providers | No external credentials | NOT RUN; missing test organizations/registrations/credentials/approvals documented |
| 54 manufacturing | Existing 63-object/70-link workflow | Preserve full browser/API/worker/semantic/SDK checks; deployed profile acceptance remains distinct |
| 55 report | None | Report/readiness matrix/actual evidence statuses |
| 56 Phase 11 preparation | None | Checklist only; no Phase 11 implementation |

No external infrastructure/provider resources were modified. Remaining production gates are not
silently reclassified as Phase 11 work.

## Acceptance closure (2026-11-02)

- [x] Starting revision and initially clean checkout reviewed; head remains `0017_capacity`.
- [x] Full baseline reproduced: 521 passed, one strict expected failure, zero skips.
- [x] Production profile startup defects corrected without a migration.
- [x] Semantic-worker/Polars import crash corrected; shared database-clock semantics retained.
- [x] Fresh builds/scans and per-match vulnerability disposition; high gate still **FAIL**.
- [x] Actual local broker/HTTPS, manufacturing ingestion/actions, branching/publication, both SDK
  artifacts and supervised semantic validation/reasoning exercised in the combined profile.
- [x] Actual nonroot/read-only/tmpfs/cgroup and direct egress restrictions checked.
- [x] Local Prometheus/Alertmanager firing, webhook delivery and resolution verified.
- [x] Release rejects missing/tampered/non-PASS evidence; semantic image included in scanning.
- [ ] Full security release gate, complete mandatory fault/rotation/admission scenarios and
  representative target load acceptance. See the final report for precise executed coverage.
- [ ] Named operational owners, off-host DR/custody, production alert delivery and hosted release
  controls/provenance verification.
- [ ] Live Microsoft, Google and Workspace certification with approved test registrations/users.

A checkmark records the stated scoped execution only. It does not make Phase 10 locally accepted
or production certified. The report retains intermediate failures and the final exact results.

Final selected-profile closure evidence: 34 passing assertions (32 distinct checks), including
SIGKILL/checkpoint reclaim, independent HTTPS SDKs, 21-table encrypted restore, supported credential
rotations, both replica restarts/shared logout, runtime cgroups and compatible API rollback. Local
backup-recipient rotation passes separately. Stable nginx 1.30.6 ingress now passes scanning (zero
high/critical); its preceding image/layout experiments remain evidence, not accepted builds.
PostgreSQL/Keycloak critical and application-base high findings still block promotion. Final Python
release regression: **525 passed, one preserved strict xfail, zero skips**. The scoped final load
targets pass; representative target capacity and comprehensive fault certification remain open.


## Acceptance continuation — recovered UX environment preserved

- [x] Combined PostgreSQL 17.11 physical base/WAL named-target recovery; 46 Foundry/101 Keycloak
  public-table hashes match, later governed record excluded, source unchanged.
- [x] Disposable-source/WAL mount guards tested before archive ownership changes.
- [x] Actual concurrent admission exposed pool starvation; API independent audit now has a
  separate bounded two-connection pool. Audit rollback/failure semantics retained; no migration.
- [x] Rebuilt-profile retest: 24 submissions/12 clients, 20 accepted/four quota rejections,
  cancellation release/reuse, final active usage zero; 38 passing assertions/35 distinct checks.
- [x] Final configured regression: 529 passed, one strict xfail, zero skips; frontend 27 tests,
  typecheck/format/build PASS. Earlier five browser E2E passes retained; not rerun against user UX.
- [x] Rebuilt API/semantic scans and SBOMs: SBOM PASS, vulnerability gate FAIL (60 high each).
- [ ] Latest paced read p95 target: FAIL, maximum 556.513 ms; zero request errors. Representative
  target capacity, byte/cross-tenant quotas and complete fault certification remain unverified.

See `docs/architecture/evidence/phase-10-closure-2/` and the appended report. Existing local Studio,
Keycloak, credentials and databases were preserved. Overall acceptance remains BLOCKED.

## Acceptance continuation 3 — 2026-11-02

- [x] Full configured regression: 552 passed, one strict xfail, zero skips; frontend 27 tests,
  typecheck/format/build; five isolated durable browser E2E tests; fixture hashes/OWLAPI roundtrip.
- [x] All six selected images rescanned with raw SBOM/scan archives and real image/config/SBOM binding.
- [x] Release verifier reads actual six-image findings; negative integrity/identity/exception tests.
- [x] Shared locked Grype cache; fifteen files hashed, twelve duplicate DB files removed; 37.8 GiB
  reclaimed without deleting scan evidence, backups or credentials.
- [x] Warm-up, three original 1/4/8-client samples, 90-second sustained run and separate contention.
- [ ] Consistent 500 ms read target: FAIL, isolated repetition peaks 391.657/528.441/283.601 ms;
  sampled SDK write p95 PASS only; representative mixed/write-heavy capacity NOT RUN.
- [x] Real mixed admission at 2/8/12 clients; independent deployed two-tenant admission and logical
  byte saturation/replay/cancellation/authorization checks; staging rollback/cleanup PostgreSQL tests.
- [x] Bounded ordinary/audit exhaustion/recovery/shutdown tests; broker pool capped at ten with
  explicit connection-budget/headroom example.
- [x] PITR extended to recovered Keycloak/API/Studio login, readiness, objects, metadata, history,
  SDK and authorization checks; 46/101 table hashes match the target.
- [x] Deployed JWKS/broker/invalid-key/expired-token faults; actual signing-key rotation/overlap;
  interrupted SDK publication, retry, concurrent generation, tamper/tenant retrieval checks.
- [x] Real authenticated API scrape, unchanged outage rule firing, local receiver delivery/resolution.
- [ ] Complete target-level fault/capacity/host-WAL-backup-worker monitoring and actual outbox delivery.
- [ ] Security promotion gate remains FAIL: 274 high/two critical matches; no approved exception.
- [ ] Live providers, off-host DR/custody, production alert receiver/owners, hosted approval/provenance.

See `docs/architecture/evidence/phase-10-closure-3/README.md` for exact per-scope status and retained
failed attempts. Existing developer containers/data were restored after the user-authorized Docker
restart. No migration or Phase 11 work was introduced.

- [x] Final integrated profile: 58 passing assertions/50 distinct checks; two API governance races
  and shared admission, two Studio sessions/restarts, restored application and real API alerts.
- [x] Exact own-resource cleanup audit: fifteen projects absent; six orphan restore volumes removed,
  asynchronous cleanup race fixed, ownership/control-error guards and actual removal smoke pass.

## Acceptance Closure 4 — 2026-11-03

- [x] Preserve starting uncommitted work, previous evidence and developer services/data/keys/trust.
- [x] Review all 32 distinct advisories; retain six fresh SBOM/scan/hash bindings and vendor snapshots.
- [x] Verify already-present Keycloak system-CA correction; retain scanner critical finding.
- [ ] Security policy remains FAIL: 274 high/two critical; libxml2 UNFIXED; no approved exception.
- [x] Final broker cap ten verified; unchanged ordinary/audit and PostgreSQL budgets.
- [x] Correlated API/BFF/SQL/curl/ingress timing and corrected bounded resource/span retention.
- [x] Current read protocol PASS: 3,320 measured mixed requests, zero errors, highest read p95 363.552 ms.
- [ ] Shared-tail causal root remains UNRESOLVED; historical target failures preserved.
- [x] 246 timed writes; final highest operation p95 296.980 ms; queue/worker/total async timing separated.
- [x] Concurrent publication, real outbox post-effect process loss/retry/dedup and bounded tmpfs recovery.
- [x] 558 Python passes/one strict xfail/zero skips; 29 frontend tests; five isolated browser passes.
- [ ] Complete representative target fault/capacity and external certification gates.

See [Closure 4 evidence](../architecture/evidence/phase-10-closure-4/README.md). No migration, security
waiver, developer restart or Phase 11 work. Implementation PASS; local/production-like BLOCKED;
production certification NOT RUN. Original failed probe/resource-attribution attempts remain retained.

## Security remediation — 2026-11-03

- [x] Review all 32 baseline IDs with current authoritative vendor snapshots and package simulations.
- [x] Remove PostgreSQL GnuPG build tools through supported apt; preserve core runtime/restore libraries.
- [x] Exclude uv/cache from API/semantic runtime through the same-base multi-stage build.
- [x] Exact candidate image/config/scan/SBOM bindings; four changed-image scans and two verified
  unchanged image/database reports, without redundant rescans.
- [x] Advisory-specific Keycloak CA dossier and independent 118-anchor default-Java-store verification.
- [x] Fail-closed disposition interface/negative tests; no production authorizer or self-approval path.
- [x] 585 Python passes/one strict xfail/zero skips, 29 frontend and five isolated browser passes;
  lint/format/strict mypy/migration drift and dependency audits PASS.
- [ ] Raw security gate: FAIL (251 high/two critical, 31 distinct IDs); independent decisions absent.
- [ ] Production certification: actual providers, off-host custody/recovery, owners/alerts/target/hosted gates.

Exact combined deployment and final decision are in
[security closure](../architecture/evidence/phase-10-security-closure/README.md). No migration,
authorized risk acceptance, developer restart or Phase 11 work. Historical causal latency uncertainty
is retained but is not independently release-blocking under the approved security scope.

The final candidate additionally removes the optional `mount` command package from API, Studio,
semantic and PostgreSQL using apt. Sixteen util-linux source-package matches disappear; required
util-linux/libmount components and their four advisories remain unresolved. No full advisory fix
is inferred from these command removals. The earlier 267-high candidate and its deployment evidence
are retained separately; final candidate counts are 251 high/two critical.

Final exact-candidate combined deployment **PASS: 58 assertions / 50 distinct checks**, including
physical PITR/restored applications, worker recovery, authorization/governance, durable sessions,
TLS, rotations and rollback. Final isolated browser E2E **five PASS**; an earlier final attempt
retains one stale activation-header failure despite successful activation. Its cause remains
unresolved and is recorded as an intermittent validation limitation, not erased by the passing
rerun. Final security/release/recovery focused suite: **55 PASS**. No assertions/timeouts changed.

Aggregate regression acceptance remains BLOCKED pending review/remediation of the retained
intermittent browser activation-header failure. Final passing executions do not erase that FAIL.
The release verifier also blocks the actual raw high/critical findings and unauthorized dispositions.

### OKD4 continuation (2026-11-03)

- [x] Portable base, OKD Route and self-hosted overlays; external PostgreSQL and Keycloak references.
- [x] Arbitrary UID/GID runtime tests, restricted contexts, read-only roots and scoped temporary paths.
- [x] Dedicated migration credentials/Job, advisory serialization and explicit rollout ordering tests.
- [x] Source-backed storage audit: PostgreSQL artifacts retained; shared file sources documented; no S3.
- [x] Studio refresh race regression/fix, health routes and bounded concurrent browser evidence.
- [x] Deployment guide, administrator request, deployment-specific BOM and fail-closed profile verifier.
- [ ] Actual target SCC admission, external service/security assurances and production-like certification.
- [ ] Independent security/release approval; raw application high findings still block acceptance.

See [the evidence matrix](../architecture/evidence/phase-10-okd4-readiness/README.md) for executed
counts, combined deployment/replica results, failures and NOT RUN checks. Earlier evidence and
roadmap authorization are unchanged; no Phase 11 work was implemented.
