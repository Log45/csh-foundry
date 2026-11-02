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
