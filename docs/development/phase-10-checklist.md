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
