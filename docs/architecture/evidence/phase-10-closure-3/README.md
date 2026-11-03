# Phase 10 acceptance continuation 3 — 2026-11-02

Phase 10 remains **BLOCKED**. Phase 11 is not approved. This directory preserves successful
checks, failed harness attempts, a reproducible isolated latency miss and unexecuted work.
It is not a release approval manifest. No risk exception is authorized.

Source baseline: `86bf658eb8cca52b1e9c6a5cc82f98dc5961c618`, initially clean (`baseline.txt`).
Earlier continuation work was already present in that revision; no changes were discarded.
Migration remains `0017_capacity`; no migration, canonical fixture or application domain service
was changed. `source-files.json` binds the final edited source/document files; `SHA256SUMS` binds
public evidence. Private credentials, detailed diagnostics, dumps and WAL are excluded from Git.

## Decisions

| Assessment | Result | Meaning |
|---|---|---|
| Implementation complete | PASS | Required platform functionality and continuation tooling delivered; acceptance and certification remain separate |
| Local acceptance | BLOCKED | Container high/critical gate FAIL; repeated isolated read target FAIL; remaining fault/target checks unverified |
| Production-like acceptance | BLOCKED | Local ARM64 fixture-scale evidence is insufficient; representative target capacity and remaining operational faults are unverified |
| Production certification | NOT RUN | Live external IdPs, off-host recovery, production alert owner/receiver, target hardware, hosted approval/provenance absent |

## Executed validation

| Check | Result | Evidence |
|---|---|---|
| Full configured Python validation | PASS | `regression.txt`, `checks-full.json`: Ruff, format, strict mypy, Alembic drift and **552 passed / 1 strict xfail / 0 skipped**; 389.59 seconds |
| Focused PostgreSQL/security/capacity suite | PASS | `focused-capacity.txt`: 34 passed; two tenants, mixed admission at 2/8/12 clients, logical-byte races/abort/retry, staging rollback/cancel/retention cleanup, pool exhaustion/recovery/shutdown, existing audit semantics |
| Supply-chain/recovery guard regressions | PASS | `targeted-final.txt`: 24 passed, including unsigned self-exception rejection, six-image raw findings/SBOM identity checks, immutable export and owned internal recovery network guards |
| Frontend format/typecheck/tests/build | PASS | `frontend.txt`: 27 tests; production build succeeds |
| Isolated durable browser E2E | PASS | `browser.txt`, `checks-browser.json`: five tests; Studio 13000/13001, API 18001, local test IdP 8443; developer port 3000 untouched |
| Manufacturing fixture hashes | PASS | `fixture-sha256.json` equals earlier closure hashes; full fixture/negative/RDF/CSV tests execute in regression |
| Raw pySHACL conformance | NOT SUPPORTED | Preserved strict expected failure for RDFLib simple/xsd:string mismatch; not converted into raw conformance PASS |
| Normalized SHACL and semantic workflows | PASS | Full semantic regression plus deployed validation/reasoning assertions in `combined-final/deployment.json` |
| Base owl-rl CriticalMachine rule | NOT SUPPORTED | Existing profile limitation retained; owl-rl-ext coverage is distinct |
| Protégé/OWLAPI roundtrip | PASS | `protege.txt`: OWLAPI 4.5.29; expected xsd:date declaration addition, no removed axioms; no interactive GUI claim |
| Selected six-image scans | FAIL | `scans.txt`, `vulnerability-disposition.json`: 274 high and 2 critical matches; 32 distinct high/critical advisory IDs across images |
| Selected six-image SBOMs | PASS | Both initial and final `raw-scans-sboms*.tar.gz` / hash inventories retained; `images.json` verifies real selected index/config/SBOM manifest bindings |
| Production Dockerfile build verification | PASS | `builds.json`, `build-*.txt`: API ARM64/amd64, Studio, semantic amd64 and ingress; verification tags are explicitly unselected and not promoted |
| Alternative distributions | NOT RUN | No unqualified libc/collation/vendor distribution replacement selected |
| Production Compose core/manufacturing/SDK/semantic/rollback/session/ingress | PASS | `combined-final/deployment.json`: final integrated run passes |
| Extended combined deployment | PASS | `combined-final/deployment.json`: **58 PASS assertions / 50 distinct checks**, zero FAIL; earlier 43-PASS/one-FAIL root attempt retained |
| Ingestion-only deployed admission | PASS | `admission.json`: 24 submissions, 20 admitted/four rejected, cancel/reuse and zero final usage |
| Mixed deployed job admission | PASS | `mixed-admission.json`: 28 submissions at 2/8/12 clients, each 20 admitted/eight HTTP 409/four semantic admissions, repeated cancel, zero final active jobs |
| Cross-tenant mixed admission | PASS | PostgreSQL/ASGI tests at 2/8/12 clients and deployed two-tenant test in `combined-final/deployment.json`: four admitted/four rejected per tenant, replay/cancel and failed-auth isolation |
| Logical-byte saturation/staging | PASS at governed-service/PostgreSQL scope | Capacity tests cover concurrent native artifacts, aborted/malformed uploads, independent tenants, retry, staging transaction rollback and reconnect accounting; cancellation retains staging until governed retention cleanup |
| Deployed logical-byte/cross-tenant extension | PASS | `combined-final/deployment.json`: valid 1,117,708-byte quota, one accepted/seven 409 uploads for saturated primary; eight independent secondary uploads, no double charge on retry, invalid upload rollback and unauthorized no-charge checks |
| Ordinary/audit pools | PASS scoped | Capacity/security tests verify bounded ordinary=1 and audit=2 exhaustion, recovery/dispose, rollback audit and audit failure abort; real two-API-replica shared accounting/rollback audit also PASS in final deployment |
| PITR plus restored application startup | PASS | `combined-final/physical-recovery.json`, `combined-final/deployment.json`: PostgreSQL 17.11, 46 Foundry/101 Keycloak table hashes, before/target retained, after excluded; recovered Keycloak/API/Studio login, metadata, object, history, SDK and unauthorized denial |
| JWKS-only outage | PASS | Final combined deployment: discovery remains available, cert endpoint 503, fresh verifier denies, restore succeeds |
| Broker outage / invalid key / expired signed token | PASS | Final combined deployment: login unavailable, fresh verifier denied, bounded known-key cache preserved, wrong signature denied, actual one-second broker token expired and denied |
| Actual signing-key rotation | PASS | `combined-final/deployment.json`: actual new RSA kid, old/new verification overlap, bounded unknown-key refresh and final API success |
| Interrupted SDK publication/concurrent generation | PASS | `combined-final/deployment.json`: observed SQL wait, actual API SIGKILL, no incomplete artifact, retry and eight concurrent replay requests share one ID; tamper/cross-tenant/missing artifact rejection |
| Worker crash/revocation/checkpoint recovery | PASS scoped | Final combined deployment: actual SIGKILL/lease/checkpoint reclaim, revoked old client secret, queued delegation revocation and idempotent continuation; broader fault matrix remains unverified |
| Governance races and execution-time revocation | PASS scoped | Regression plus two real API replicas: eight creates, one action commit/seven 409 conflicts and replay; one branch merge/three stale 412 conflicts; rollback audit preserved; remaining worker fault matrix unverified |
| Real API monitoring firing/delivery/resolution | PASS local | `combined-final/real-api-alerts.json`: authenticated real API scrape, unchanged two-minute rule, local Alertmanager firing/webhook/resolution; production receiver NOT RUN |
| Query-path profiling / EXPLAIN | PASS diagnostic | `combined-final/query-profile.json`: forty governed queries, ordinary SQL timing, idle pool checkout and real redacted EXPLAIN ANALYZE/BUFFERS; not historical-spike attribution |
| Off-host DR / live Entra/Google/Workspace / hosted release | NOT RUN | No authorized destination, credentials, organizations, owners or approval/provenance execution |
| Final Docker control / leftover project cleanup | PASS | `developer-preservation-final.json`, `disposable-cleanup.json`, `cleanup-race-smoke-final.json`: original developer containers/data retained; all fifteen own acceptance projects absent; cleanup race fixed and actual removal retested |

The final full Python rerun includes broker cap, shared-cache and cleanup guard regressions.
Later Docker-control error classification also passes focused guard checks and actual cleanup smoke.
The final integrated run exercises corrected quota, artifact, monitoring and replica paths. Historical
failed attempts remain failed; successful final evidence does not change their recorded outcomes.

## Controlled performance

`attempt-1/` preserves the complete original request mix and all samples. Scans finished before
measurements; no builds, full regression or frontend build ran during them. Each client performs
one paced request/second, cycling query, Object Set, traversal, action preview and Python SDK
creation. Warm-up executes 65 requests; measured runs execute **1,660 requests with zero errors**.

| Run | Clients | Highest read/preview/traversal p95 | SDK p95 | Read <500 ms |
|---|---|---|---|---|
| Isolated repeat 1 | 1/4/8 | 391.657 ms | 364.044 ms | PASS |
| Isolated repeat 2 | 1/4/8 | 528.441 ms | 299.642 ms | FAIL |
| Isolated repeat 3 | 1/4/8 | 283.601 ms | 276.242 ms | PASS |
| Sustained 90 seconds | 8 | 336.732 ms | 345.661 ms | PASS |
| Separate one-CPU competitor, 20 seconds | 8 | 384.885 ms | 314.188 ms | PASS |

The prior 260-request/556.513 ms sample remains unchanged in closure-2. Repeat 2 shows a shared
spike across all eight clients in iteration 15. Existing API spans and ingress durations also
increase, so curl overhead alone does not explain it. No component-specific causal bottleneck
was established. No speculative index, cache, authorization, audit or pool enlargement was made.
The 500 ms target is **not consistently met**. The sampled SDK p95 stays below two seconds;
write-heavy action/ingestion p95 and general production write capacity are NOT RUN.

Host: Apple M1 Pro, ARM64, 16 GiB host RAM; Docker 10 CPUs/about 7.65 GiB, one API process/Studio
replica during samples; amd64 semantic engine under emulation. API ordinary pool 5+5 plus separate
2 audit connections. PostgreSQL max_connections=100, reserved=3, shared_buffers=128 MiB,
work_mem=4 MiB. Runtime CPU/memory limits and exact image identities are in `attempt-1/runtime.json`.
Dataset: canonical 63 objects/70 links before later recovery markers and admission fixtures.
These are provisional engineering targets, not production SLOs or capacity certification.

Resource snapshots show no ending lock waiters/deadlocks/temp spill. Twelve coarse samples begin
at UTC epoch 1793655022.724 during the sustained run, not at the earlier spike. The raw sampler
header incorrectly says repeat 2; preserve it as a harness annotation error, not coverage of that
spike. Observed Foundry connections peak at 11 in those samples. WAL increases from 25,021,940
to 36,244,805 bytes across sustained/contention and later operations; this is not isolated per-request
WAL cost or a whole-run resource distribution. CPU/memory, queue status/age and logical bytes are
retained; no target worker-throughput or physical storage bound is established.

Keycloak's pool was still supplier-default during these load samples. The later template cap of
10 (initial/minimum 2) was exercised by subsequent startup/login/recovery assertions, not by a new
complete controlled latency sample. Retained-load checks compare image IDs and CPU/memory limits;
they do not certify equivalence of every runtime setting.

## Failed and interrupted attempts

- Initial migration runner selected local auth without opt-in; corrected to disabled auth on the
  disposable test cluster. `migrate-initial-failed.txt` retained.
- First capacity test expected HTTP 202 instead of the existing 200 contract, then incorrectly
  expected the other tenant's legitimate active jobs to disappear. Both test errors were corrected;
  both failed logs remain; the final 34-test run and full suite pass.
- Attempt 1: unchanged ingress burst was exhausted between quota batches; refill/pacing added
  between batches without changing concurrent submission count or production limits.
- Attempt 2: Docker forbids attaching a `none` network container to an application network.
  Restore now optionally starts on the exact owned internal project data network, with guard tests.
- Attempt 3: temporary runtime secret replacement needed owner write permission; restore now
  changes its own file to 0600 for replacement and restores 0440. No developer secret is touched.
- Attempt 4: new stdin-based fault injection exposed missing keyword forwarding in `dc`; fixed.
- Attempt 5: deployed quota fixture selected less than the one-MiB configuration minimum; startup
  correctly rejected it. The application minimum was not weakened.
- Root final extended attempt: a large padding upload returned 413 before quota saturation.
  Fixture changed to bounded 60,000-character uploads; later deployed byte checks pass.
- `operations.txt` and `operations/deployment.json` retain an explicitly interrupted setup while
  the correction was being prepared. Cleanup was initially unverifiable while Docker was unavailable;
  the later exact-project audit verifies this and all fourteen other own projects are absent.

No Docker control-plane failure is attributed to a cause without evidence. After the user freed
storage and explicitly authorized developer service restarts, Docker Desktop was restarted and
the original five developer container IDs restored. Studio/API return 200, trusted loopback Keycloak
discovery returns 200, and a read-only check retains one manufacturing object and migration
0017_capacity (`developer-preservation-final.json`). No Docker reset, broad prune, existing backup
or credential deletion, external deployment, developer realm edit or risk approval occurred.

Fifteen Grype DB files were hashed: three versions, twelve byte-identical duplicates. Shared locked
cache reuse is now tested across output directories; duplicate removal reclaimed 40,573,624,320
bytes without deleting scan/SBOM evidence. `cache-deduplication.json` records retained copies and
actual freed-space measurements. Final six-image scans use the shared cache and reproduce the
same blocking findings. Historical initial scans and failures remain retained.

Additional fixture corrections: source-root changes need a new governed registration version;
reusing the host-path fingerprint correctly returned registration_changed. The corrected second
fixture publishes source/mapping v2. SDK wait observation needs the disposable administrator's
visibility into pg_stat_activity; runtime privileges were not broadened. Failed observations remain
in `operations-resumed`, `operations-final` and `operations-observed` evidence.


The final integrated acceptance passed before the post-run cleanup audit exposed six unreferenced
restore volumes: asynchronous `--rm` removal raced volume deletion. Only those exact own volumes
were removed. The helper now validates disposable ownership, waits for removal, reports failures,
and distinguishes Docker control errors from absent resources. Three guard tests and an actual
container/volume cleanup smoke pass; `disposable-cleanup-initial-failed.json` remains unchanged.
Two Studio replicas also pass restart, shared session/logout and store-outage checks. The final
application recovery takes 82.967 seconds on this host, without a production RTO claim.

`acceptance-assessment.json` records the actual gates and raw-file hashes; `release-gate.txt`
records the verifier's expected BLOCKED result. It is an assessment, not a promotable release.
