# Production readiness matrix

Implementation, automated verification and deployment approval are distinct. No target production
deployment/certification is claimed. Assign named operators to each role before promotion.
Evidence is under `docs/architecture/evidence/phase-10/` and private local `artifacts/`.

| Capability | Implementation / test | Deployment | Owner | Residual risk / evidence |
|---|---|---|---|---|
| Authentication | Strict RFC 9068; actual Keycloak PASS | NOT RUN | Identity | Upstream federation untested; keycloak.txt/security tests |
| Authorization | Transactional platform RBAC/ABAC retained | NOT RUN | Security/tenant admin | Coarse locks; regression |
| Tenant isolation | Scoped services/FKs/current memberships | NOT RUN | Platform/security | DB owner trusted; security/browser tests |
| Sessions | Encrypted state, CAS/revocation; two built replicas PASS | NOT RUN | Platform | Single database failure domain; durable-e2e.txt |
| SSO | Entra/Google/Workspace configurations | NOT CERTIFIED | Identity | Live credentials/registrations/test organizations unavailable |
| Database | Additive migrations; runtime privilege rejection; restricted-role load | NOT RUN | Database | Target grants/collation review; migration/load evidence |
| Backups | Encrypted dump and isolated logical restore PASS | NOT RUN off-host | Database | Custody/destination/retention must be assigned |
| Recovery | Physical base/WAL named-point recovery PASS | NOT RUN disaster site | Database | RPO/RTO provisional; recovery.txt |
| Ingestion | Checkpoints/fencing/supervised child | NOT RUN target worker | Platform | Source policy/credentials/capacity; crash/regression tests |
| Semantic | Separate bounded container/engine deadline/provenance | NOT RUN target workload | Platform | No independent proof verification/complete OWL claim |
| Actions | Atomic mutation/idempotency retained | NOT RUN | Platform | Outbox at-least-once effects; regression/load |
| Branching | Immutable revisions/merge preconditions | NOT RUN | Platform | Same-published-base only; browser/load |
| SDK generation | Deterministic compiler/private authorization | NOT RUN registry | SDK owner | Bounded synchronous compilation; package tests |
| Artifact integrity | Independent archive/manifest/schema verifier PASS | NOT RUN signing | SDK/release | SDK archives unsigned; trusted expected digest required |
| Observability | JSON request spans/private metrics/alert rules | NOT RUN receiver | Platform | Request-level tracing only; no distributed collector |
| Rate limiting | Shared identity budget/edge address limits | NOT RUN target abuse | Platform | Fixed windows/per-host edge; atomic budget test |
| Quotas | Transactional logical artifact/job limits | NOT RUN sizing | Platform/database | Excludes object/audit/index/WAL physical growth |
| Worker scheduling | Supervised deadlines/backoff/client credentials | NOT RUN target | Platform | Initiator/delegation configuration and alerts required |
| Secrets | Mounted files/key ring/rotation runbook | NOT RUN key custody | Security/database | Host root trusted; no external vault claimed |
| CI/CD | Pinned actions/tests/scans/approval/provenance workflow | NOT RUN hosted | Release | Required environment reviewers need configuration |
| Supply chain | Dependency audits/SBOMs/scans executed | BLOCKED by findings | Security/release | High-severity OS findings; report scan summary |
| Performance | Signed HTTP/PostgreSQL local sample | NOT RUN target | Platform | Small fixture/sample; load.json, provisional SLOs |
| Incident response | Revocation/exhaustion/restore procedures | NOT RUN exercise | Incident owner | Named owners/delivery/disaster-site drill missing |

Release requires passing regression, remediation or an explicitly authorized review of remaining
scan findings, and executed target DNS/TLS/secrets/roles/readiness/manufacturing/worker/recovery
acceptance. Assign operational owners and alert delivery. Microsoft/Google/Workspace live validation
remains a separate NOT RUN / NOT CERTIFIED gate. No open requirement is converted to PASS merely
because code/configuration exists or deferred silently to Phase 11.
