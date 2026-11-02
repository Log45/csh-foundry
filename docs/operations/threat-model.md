# Phase 10 threat-model refresh

Trust boundaries: browser ↔ TLS ingress ↔ Next BFF ↔ FastAPI services ↔ PostgreSQL; API ↔ broker;
broker ↔ external organization; workers ↔ sources/semantic subprocess/outbox; build ↔ artifact
consumer; database ↔ backups/operator. PostgreSQL/root/identity administrators remain trusted.
Evidence names refer to Phase 10 evidence or the full regression. A control listed here is not
certification of a deployed environment; unexecuted operational exercises remain NOT RUN.

| Scenario / boundary | Existing and new controls | Residual risk / required mitigation | Executed evidence |
|---|---|---|---|
| Token substitution / API | Signature/issuer/audience/client/typ/expiry checks; ID tokens rejected | Trusted issuer configuration/operator key custody | OIDC regressions; actual Keycloak tokens |
| OAuth callback/redirect injection / browser | Fixed configured origin, state/nonce/S256, exact Origin | Compromised approved broker remains trusted identity source | Browser/auth tests; nginx Host test |
| Login CSRF or session fixation | Cookie-bound single-use state, new random session/CSRF, old-handle deletion | Host/browser compromise | State races/browser tests |
| Session theft / persistence | HttpOnly/Secure/SameSite cookies; encrypted rows, hashed handles | Compromised Next/internal credential can read sessions; isolate network/secrets | Ciphertext/outage/replica tests |
| Cross-replica logout or stale updates | Shared delete/CAS, no deleted-row resurrection | In-flight already-authorized transactions can finish under existing locking contract | Store races/replica restart/logout |
| Email linking takeover / broker | Deny unlinked identities; operator-verified immutable external links | Administrative verification is operational; no self-service linking | Configuration contract; live linking exercise NOT RUN |
| External role/domain/tenant escalation | Platform principals/membership/RBAC/ABAC authoritative | Compromised platform administrator | Existing security/cross-tenant regressions |
| Provider/JWKS outage or rotation | Bounded refresh/cache, overlap policy, expired material denied | Availability loss; up to 30s unknown-key rejection | OIDC rotation/outage tests |
| Untrusted forwarded hosts | Fixed origin/hostname; ingress overwrites; API proxy headers disabled | Docker host/network owner trusted | Actual nginx Host/private-path checks |
| Browser XSS / malicious object text | React escaping, nonce scripts, no raw HTML/token serialization | Inline styles retained for graph coordinates; no arbitrary script exceptions | Built browser tests; CSP header/image smoke |
| SQL/query/ontology injection | Bound SQL/query AST; canonical validation; isolated no-network OWL parser | DB owner may bypass application; untrusted native parser resource use | Query/interchange/security regressions |
| Action partial write / replay | Governed transaction/idempotency/audit/outbox | External delivery at-least-once; recipients deduplicate | Action rollback/idempotency/outbox tests |
| Branch merge race / authorization bypass | Exact revisions/preview hashes/security/ontology locks | Coarse contention; same-base scope only | Branch concurrency/security regressions |
| SDK tampering / distribution | Determinism, immutable metadata, independent digest/inventory/schema verification | Expected hash requires trusted channel; no individual SDK signatures | Package tests and archive tampering rejection |
| Ingestion source credential/data exposure | Server-owned catalog, SELECT-only source checks, redacted errors | Source/host administrator trusted; protect input snapshots | Ingestion/connector/security tests |
| Worker credential compromise | Separate service client; current platform role and initiating delegation intersection | Compromised authorized worker can perform its delegated operations | Delegation/revocation/client-credential tests |
| Crash/duplicate job execution | DB leases/tokens/checkpoints/fenced commits | Retry exhaustion requires operator diagnosis | Actual worker process termination/recovery regressions |
| Semantic import/engine exhaustion | Existing input/process deadlines, separate memory/CPU/tmpfs container, supervised kill | Large valid jobs may fail; no completeness/independent proof guarantee | Engine timeout tests; bounded container execution |
| Admission/resource abuse | Edge identity/address limits, shared budgets, tenant job/logical-byte quotas | Physical audit/object/index/WAL growth excluded; monitor capacity | Atomic budget/admission/quota rollback tests |
| Secret disclosure / logs | File-backed secrets; no URI/body/token request logging; private metrics | Root/DB owners trusted; collectors must preserve redaction | Structured HTTP/load logs and internal denial tests |
| Audit destruction / database | Immutable triggers, runtime audit-mutation revocation, security decisions fail closed | Owner-proof off-host archive NOT implemented | Existing audit immutability/security regressions |
| Backup exposure / disaster | Encrypted streaming dump, physical backup/WAL drill, off-host custody runbook | Off-host destination/custody/RPO/RTO exercise NOT RUN | Local encrypted backup and WAL recovery evidence |
| Supply-chain compromise | Locked dependencies, action/scanner digests, audits/SBOMs, release gate/provenance workflow | Remaining app high and PostgreSQL/Keycloak critical findings block promotion; hosted provenance NOT RUN | Actual audit/SBOM/scan outputs; no exceptions hidden |

Nginx access logging records status/duration only on all server blocks, including HTTP redirects
and rejected hosts. A callback-sentinel regression verifies query values are absent. Operators
must ensure error/collector logging preserves this boundary; public ingress logs remain URI-free. Security audit
is intentionally separate from request telemetry and survives denied/rolled-back business requests.
Target-environment incident/alert delivery and disaster recovery exercises remain required gates.

Closure evidence is in `docs/architecture/evidence/phase-10-closure/`. The final maintained stable
ingress image scans without high/critical findings. Retained PostgreSQL libxml2 parsing exposure
and Keycloak Java CA trust/Guava/native-library findings remain blocking: network/role boundaries
and local tests do not approve residual risk. See `vulnerability-disposition.md` for supplier fixes,
reachability limits, exact package/image identities and required owner decisions. No exception is
approved. Live-provider TLS and off-host/owner-led incident exercises remain NOT RUN.

Concurrent acceptance exposed a connection-starvation availability defect: ordinary lock waiters
could consume the connection needed for independent authorization audit. API audit writes now use
a separate pool capped at two connections, with no overflow and the same restricted role. Audit
failure still aborts business mutations; durable audit on business rollback is preserved. This
reserves progress under ordinary-pool contention, not capacity against arbitrary load. Count both
pools in connection sizing and retain target load/abuse validation. Continuation evidence is in
`docs/architecture/evidence/phase-10-closure-2/`.
