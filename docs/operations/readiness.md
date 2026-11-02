# Production readiness matrix

Phase 10 implementation and local evidence do **not** authorize production promotion. The
high-severity container release gate is **FAIL / BLOCKED**. Production certification is **BLOCKED**.
The original 23 capability categories are retained below. PASS applies only to the stated scope.
Named owners have not been assigned; role names identify required responsibilities, not approvals.
Historical implementation evidence remains in `docs/architecture/evidence/phase-10/`; closure
commands, final logs, inventories and limitations are in
[`phase-10-closure/`](../architecture/evidence/phase-10-closure/) and the subsequent
[`phase-10-closure-2/`](../architecture/evidence/phase-10-closure-2/).

| Capability | Implementation | Validation | Deployment | Evidence | Owner (unassigned) | Residual risk / required action | Acceptance |
|---|---|---|---|---|---|---|---|
| Authentication | PASS strict RFC 9068 | PASS actual pinned broker, TLS, PKCE, nonce/replay/token rejection | PASS disposable profile; NOT RUN target | keycloak-final.txt; deployment.json | Identity | Certify target issuer/signing lifecycle and actual providers | BLOCKED target |
| Authorization | PASS RBAC/ABAC | PASS regression and active-session role/membership revocation | PASS scoped local checks | regression-final.txt; deployment.json | Security/tenant | Executing-job/merge/action revocation coverage also in isolated DB tests; target exercise required | BLOCKED target |
| Tenant isolation | PASS scoped services/FKs | PASS DB/browser/independent SDK negative cases | PASS local SDK scope | browser-final.txt; deployment.json | Platform/security | Owner remains trusted; target policy review required | BLOCKED target |
| Sessions | PASS encrypted PostgreSQL/CAS | PASS two replicas, both restarts/logout, outage, key overlap/rejection | PASS disposable profile | deployment.json; runtime.json | Platform | One database failure domain; no refresh-token retention or HA claim | BLOCKED target |
| SSO | PASS provider configurations | PASS actual broker import; NOT RUN live providers | NOT RUN external organizations | keycloak-final.txt | Identity | Approved registrations/organizations/test users/verified subject links required | BLOCKED certification |
| Database | PASS additive schema/runtime roles | PASS head/current/drift and restored table checksums | PASS local restricted role | migrations.txt; deployment.json | Database | No migration added; target grants, encryption and custody review | BLOCKED target |
| Backups | PASS encrypted logical tooling | PASS local encrypted dump/decrypt/restore | PASS disposable profile; NOT RUN off-host | deployment.json; recovery.txt | Database | Key custody/retention/destination unavailable; no host-loss guarantee | BLOCKED off-host |
| Recovery | PASS physical/WAL and logical paths | PASS combined PG 17.11 named-target PITR; all 46 Foundry/101 Keycloak public-table hashes match | PASS same-host database recovery; NOT RUN disaster site | phase-10-closure-2/physical-recovery.json; deployment-pitr.txt | Database | Restored application/broker startup, off-host recovery and target RPO/RTO unverified | BLOCKED target |
| Ingestion | PASS checkpoints/fencing | PASS actual SIGKILL/lease/checkpoint reclaim and 63 objects/70 links | PASS disposable supervised worker | deployment.json | Platform | All sources/long-duration fault scenarios need target acceptance | BLOCKED target |
| Semantic | PASS pinned engine/provenance | PASS deployed validation/reasoning/no mutation; import crash remediated | PASS amd64 emulation | deployment.json; runtime.json | Platform | No complete OWL/independent proof claim; base owl-rl limitation retained | BLOCKED target |
| Actions | PASS atomic/idempotent services | PASS deployed replay/stale revision and both SDK actions | PASS fixture scope | deployment.json; regression-final.txt | Platform | Outbox delivery interruption not exercised in combined profile | BLOCKED target |
| Branching | PASS immutable revisions/governance | PASS conflict/resolution/merge/provenance/draft/publish; active pointer unchanged | PASS local manufacturing | deployment.json; browser-final.txt | Platform | Same-base merges only; comprehensive target concurrency drill remains | BLOCKED target |
| SDK generation | PASS deterministic packages | PASS independent Python installation and TS build/query/action/denial | PASS HTTPS fixture scope | deployment.json; regression-final.txt | SDK owner | No external registry certification | BLOCKED target |
| Artifact integrity | PASS manifests/schema/digests | PASS deployed download verification and tamper rejection | NOT SUPPORTED individual signatures | deployment.json; closure-tests.txt | SDK/release | Expected digest needs trusted channel; signing unimplemented | BLOCKED signing/target |
| Observability | PASS private bounded API metrics/rules | PASS real local firing/webhook/resolution | NOT RUN production scrape/receiver | alerts.json; alerts-final.txt | Platform | Synthetic scrape target; host/WAL/worker/backup/queue/storage alert coverage missing | BLOCKED production delivery |
| Rate limiting | PASS shared/edge budgets | PASS atomic shared-budget DB tests | NOT RUN representative deployed abuse | regression-final.txt | Platform | Fixed windows and per-host edge; representative abuse exercise required | BLOCKED target |
| Quotas | PASS transactional logical/job accounting | PASS deployed 24 submissions/12 clients, 20 accepted/4 rejected; cancellation releases/reuses slot | PASS one-tenant ingestion admission; NOT RUN byte/cross-tenant saturation | phase-10-closure-2/admission.json; regression.txt | Platform/database | Physical objects/index/WAL/audit/disk not bounded by logical quotas | BLOCKED sizing |
| Worker scheduling | PASS supervision/deadlines | PASS deployed ingestion reclaim and semantic work; process/fencing tests | PASS selected ingestion/semantic; NOT RUN outbox | deployment.json; regression-final.txt | Platform | Hard child limits checked; all queued/executing credential fault cases remain distinct | BLOCKED target |
| Secrets | PASS private files/key ring | PASS deployed session, worker OIDC, internal, DB and local backup-recipient rotations | NOT RUN production custody | deployment.json; production.md | Security/database | Studio public client has no client secret; artifact signing NOT SUPPORTED; do not infer unlisted rotations | BLOCKED custody |
| CI/CD | PASS pinned tests/scans/evidence gate | PASS local negative promotion/tamper tests; NOT RUN hosted execution | NOT RUN hosted reviewers/retention | promotion-negative.txt; closure-tests.txt; release.yaml | Release | Exact-candidate evidence handoff must be configured; no automatic deployment | BLOCKED hosted |
| Supply chain | PASS frozen builds/audits/SBOM | FAIL container high/critical gate | BLOCKED promotion | vulnerability-disposition.json; scans; audits | Security/release | API 60, Studio 59, semantic 60 high; PostgreSQL 92 high/1 critical; Keycloak 3 high/1 critical; ingress 0 high/critical PASS; no exception | BLOCKED security |
| Performance | PASS local load harness | PASS 260 requests/zero errors; latest provisional read p95 FAIL (556.513 ms); earlier scoped targets PASS | NOT RUN representative target capacity | phase-10-closure-2/load-summary.json; earlier deployed-load.json | Platform | Concurrent regressions/scans in latest sample; no saturation, approved SLO or complete continuous resource measurement | BLOCKED capacity |
| Incident response | PASS runbooks | PASS scoped local restore/restart/rollback/revocation | NOT RUN owner-led target exercise | deployment.json; production.md | Incident owner | Named owners, on-call delivery, disaster site and remaining fault scenarios missing | BLOCKED production |

## Separate mandatory certification gates

| Gate | Status | Exact missing prerequisite / scope limit |
|---|---|---|
| Container security | FAIL | Fix retained advisories or obtain explicitly authorized owner dispositions; no exception inferred |
| Complete local acceptance checklist | BLOCKED | Scoped checks pass; unexecuted fault/quota/rotation cases remain itemized in the report |
| Identity broker | PASS local | Production hostname/certificate/key custody and operations still NOT RUN |
| Live Microsoft Entra SSO | NOT RUN | Approved exact organization, application registration, callback, secret, users, subject links and operator authorization |
| Live Google SSO | NOT RUN | Approved OAuth application/consent, callback, test accounts, credentials and subject links |
| Live Workspace SSO | NOT RUN | Approved managed organization/domain, dedicated OAuth client/consent/admin approval and subject links |
| Session durability/revocation | PASS local | No multi-host or mixed-release rolling guarantee |
| Tenant isolation | PASS tested scope | Target memberships/ABAC/RBAC require owner review |
| PostgreSQL recovery | PASS combined PG 17.11 database PITR | Target hardware timing, restored application/broker startup and off-host recovery NOT RUN |
| Off-host disaster recovery | NOT RUN | Encrypted off-host destination, recipients/key custody, retention and recovery host/owner |
| Monitoring/alert delivery | PASS local mechanics | Production receivers and deployed scrape/host/worker/WAL/backup integration NOT RUN |
| Resource isolation | PASS tested cgroups | Hard limits inspected in runtime; no arbitrary-code sandbox or multi-host certification |
| Resource quotas | PASS deployed one-tenant job admission and isolated DB tests | Byte/cross-tenant saturation NOT RUN; physical capacity unbounded |
| Representative load | NOT RUN | Target hardware, sustained representative datasets/workload and approved SLOs |
| Comprehensive failure injection | NOT RUN | Signing/JWKS, outbox/artifact failure and remaining queued/executing/concurrency scenarios not all run in one profile |
| Secret/role lifecycle | PASS scoped checks | See per-check deployment.json; no inference from procedure text |
| SDK integrity | PASS | Individual signatures NOT SUPPORTED; registry/provenance certification separate |
| Hosted release provenance | NOT RUN | Authorized hosted run, attestation verification, retention and enforced reviewer configuration |

Implementation complete, locally accepted, production-like accepted and production certified are
separate decisions. Security and incomplete mandatory operational evidence prevent complete local
acceptance. No open Phase 10 requirement is moved to Phase 11. The final report states exact
commands/results, including intermediate failures and unexecuted scenarios.
