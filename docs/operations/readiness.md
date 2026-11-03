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

## Continuation 3 — 2026-11-02

See the [executed matrix and failures](../architecture/evidence/phase-10-closure-3/README.md).
Implementation is complete; local and production-like acceptance
remain BLOCKED, and production certification is NOT RUN. No named operational owner or approval
is invented. Existing readiness categories above retain their external/target prerequisites.

New evidence: 552 Python passes/one strict xfail/zero skips, 27 frontend tests, five isolated E2E
passes; all six selected image/config/SBOM identities bound; stricter raw release evidence gate;
recovered application startup after PostgreSQL 17.11 PITR; deployed mixed/cross-tenant and logical
byte quota checks; real broker/JWKS/signature/expiry/rotation and SDK interruption; real API scrape
and local alert delivery. PostgreSQL pool exhaustion/rollback/audit semantics remain intact. The
broker maximum is now ten connections, with a documented process/headroom budget.

Security remains FAIL (274 high/two critical package matches; 32 distinct high/critical advisories),
without a supplier-qualified remediation or owner exception. Controlled read p95 is not consistently
below 500 ms: one isolated repetition reaches 528.441 ms. Other isolated/sustained/contention runs
pass, with zero errors; sampled SDK p95 is below two seconds. This does not certify write-heavy or
target capacity. Existing API/ingress spans and later SQL plans do not identify a causal bottleneck
for the historical shared spike; no speculative optimizer/cache/index change was made.

Production delivery, on-call ownership, real provider organizations, approved off-host destination,
key custody, target hardware/data/SLOs and hosted release reviewer/provenance are still required.
Actual outbox delivery and unexecuted deployment-level fault/monitoring cases remain NOT RUN.
Cache maintenance is not evidence deletion: one shared advisory DB cache replaces per-output copies;
12 verified duplicates were removed while all scan/SBOM/recovery results were retained.

| External gate | Result | Required prerequisites / accountable role | Executable validation handoff |
|---|---|---|---|
| Entra ID | NOT RUN | Approved exact tenant/app registration, client secret, callback, consent, test accounts; identity administrator | Render with `scripts/configure_keycloak.py --entra-tenant ... --entra-client ...` into a new private realm file; follow the production runbook's approved-target import, Code/PKCE sign-in, broker access-token profile, explicit identity link, membership and revocation checks |
| Google / Workspace | NOT RUN | Approved OAuth applications, exact callbacks/consent/test users; Workspace hosted domain/admin policy; identity administrator | Render `--google-client ...` / `--workspace-client ... --workspace-domain ...`; run real organization-allowed/denied identities through the same approved-target broker/API flow; dummy provider imports do not certify federation |
| Off-host DR | NOT RUN | Authorized destination/restore host, encrypted base+WAL, independently held keys/config, retention and RPO/RTO; database operator | Execute the production runbook's fresh-cluster physical recovery, then broker/API/Studio startup and tenant/object/history/artifact/authority validation on that destination; record target, elapsed time and hashes |
| Production alerts | NOT RUN | Real API/worker/DB/host/WAL/backup scrape targets, protected credentials, receiver and named acknowledgement owner; platform/DB operators | Validate rules, scrape actual target metrics, inject each approved failure, record receiver firing/acknowledgement/resolution; local API receiver mechanics cover only the stated rule |
| Hosted release/provenance | NOT RUN | Approved repository candidate, completed exact six-image evidence manifest, environment reviewer/protection/retention configuration; security/release reviewer | Dispatch the existing reviewed release workflow at the approved revision; verify CI, SBOM/scan/evidence hashes, archive inventory/digest and hosted attestation subject/identity before the protected approval step; no automatic deployment |
| Target capacity | NOT RUN | Dedicated target architecture/resources, approved business dataset/request mix, concurrency and SLO/RPO/RTO; platform owner and business approver | Repeat warm-up/repetitions/sustained/contention with resource/DB/queue/storage telemetry on that approved target; the fixed 63-object acceptance fixture is a smoke test, not business-capacity certification |
| Real outbox delivery | NOT RUN | Approved egress policy and fixed receiver compatible with the existing destination guard, test credentials and deduplicating receiver; platform/security owner | Configure the existing supervisor's fixed outbox destination on the disposable approved network, perform and observe an actual send/failure/retry, check event-ID deduplication and committed-state integrity; do not bypass private-address guards for a local receiver |

Roles are responsibility placeholders until named humans accept them. No external operation in this
table has been performed or approved by this continuation, and no unexecuted workflow is PASS.

## Acceptance Closure 4 — 2026-11-03

The [Closure 4 matrix](../architecture/evidence/phase-10-closure-4/README.md) supplements, rather than
relabels, historical results above. Implementation PASS; local and production-like acceptance
BLOCKED; production certification NOT RUN. Final validation: 558 Python passes/one strict xfail/zero
skips, 29 frontend tests and five isolated browser tests. Head stays 0017_capacity.

Current final-pool read protocol PASS (3,320 measured requests, zero errors, highest read p95
363.552 ms), but a captured 1,079 ms tail is causally unresolved. Bounded writes PASS (246 timed
requests, final highest operation p95 296.980 ms); async queue/execution/completion are separate.
New publication/outbox/tmpfs faults PASS at their documented scope; physical shared-disk and complete
target fault/capacity certification remain NOT RUN. Recovery/monitoring evidence from Closure 3
remains retained; PostgreSQL/Keycloak image identities are unchanged.

Six-image policy remains FAIL: 274 high/two critical scanner matches, 32 distinct IDs. The broker's
supported system-CA remediation is verified already present; its scanner finding is retained.
PostgreSQL libxml2 remains UNFIXED. No risk exception or named owner is invented. External provider
organizations/registrations, independent off-host recovery/custody, production receivers/owners,
target hardware/workload/SLOs and hosted approval/provenance still require the prerequisites and
operator handoff in the matrix above. No production readiness or Phase 11 authorization is inferred.
