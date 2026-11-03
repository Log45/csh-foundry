# Phase 10 Acceptance Closure 4 — 2026-11-03

**Implementation PASS; local acceptance BLOCKED; production-like acceptance BLOCKED;
production certification NOT RUN. Phase 11 remains unapproved.** No risk exception is authorized.

Starting revision `86bf658eb8cca52b1e9c6a5cc82f98dc5961c618` had substantial existing uncommitted
Closure 3 changes. `baseline.json` records the starting status; existing work and all previous
evidence were preserved. Historical checksums verify 109/36/151 files in closures 1/2/3.
No migration was added; head remains `0017_capacity`. Canonical fixtures are unchanged.

## Changes and security decision

Optional request-scoped SQL/acquisition/JWT timing and BFF session/backend timing preserve W3C
trace IDs across the browser-state and governed API calls. No SQL text/parameters, tokens,
cookies, raw paths or tenant values are exported by these diagnostics. API/Studio flags default
to false. No new collector platform, database, Rust component, authorization authority, cache,
query/index optimization or pool-size change was introduced. Diagnostic API/Studio images were
built, scanned, started and exercised; the other four selected images remain unchanged.

All 32 distinct advisories were reviewed against supplier sources. Current PostgreSQL/trixie
package upgrade simulation offers only tzdata, not a supported fix for retained vulnerabilities.
No stable/unstable package mixture, libc/collation-family change, essential-package force purge or
vendor JAR substitution was performed. The maintained broker remains 26.8.1 at the same digest.
See [advisory inventory](advisory-inventory.md), [full disposition](vulnerability-disposition.json),
[distinct review dossiers](distinct-advisories.json) and [critical dispositions](critical-dispositions.json).

| Critical finding | Technical disposition | Evidence / remaining gate |
|---|---|---|
| CVE-2026-6653, PostgreSQL libxml2 | UNFIXED | Debian still lists selected trixie package vulnerable; no supported stable fix. No-DSA is not risk acceptance |
| CVE-2026-91403, Keycloak/OpenJDK trust | REMEDIATED, already present before Closure 4 | Actual default Java store links to system trust; installed CA package matches Red Hat RHSA-2026:88459; both implicated roots absent. No new package fix was applied here. Scanner's Java-version critical match remains blocking pending reviewed disposition |

[Red Hat's OpenJDK determination](https://access.redhat.com/security/cve/CVE-2026-91403) directs
RHEL installations to the [corrective CA package](https://access.redhat.com/security/cve/CVE-2026-114406).
The [Debian libxml2 tracker](https://security-tracker.debian.org/tracker/CVE-2026-6653) remains the
selected distribution authority. Raw vendor snapshots, exact 118 trust-anchor subjects/fingerprints
and supplier manifest identities are retained. Guava 33.7.2 fixes GHSA-xxph-c9ww-hj94 upstream, but
is not bundled in the selected supported broker. SQLite CLI/source-package applicability is
recorded without a waiver; vendor review is required, not inferred from absent runtime commands.

**New package vulnerabilities patched: zero.** Scanner findings remain **274 high / two critical
matches, 32 distinct high/critical IDs**. Technical review identifies 31 unresolved advisories and
one already-corrected CA-store finding with a scanner/package-detection discrepancy. Neither that
review nor the supplier's no-fix classifications changes the raw scanner counts or release policy.
API/Studio/semantic: 60/59/60 high; PostgreSQL: 92 high/one critical; Keycloak: three high/one critical;
ingress: zero high/critical. All six CycloneDX SBOMs PASS. **Container security gate FAIL.**
Grype 0.121.0 uses the shared cache; v6.1.10 DB built 2026-11-03T06:20:47Z, archive checksum
`ab581eb337614de4e5f2f1f944ae78992d98242387632c235b406a51dd4d9cd1`. No identical scan was repeated.
Raw scan/SBOM bytes remain in ignored `artifacts/phase10-closure-4/scan/`, bound by hashes.

## Performance and fault evidence

[Every controlled read run](read-performance.md), [bounded writes](write-performance.md) and the
[root-cause investigation](root-cause-analysis.md) retain quantiles, throughput, durations, errors,
trace IDs, stage times, runtime configuration and resource observations.

- Read/SDK protocol: **3,320 measured requests, zero errors**, six 1/4/8-client repetitions,
  two 90-second sustained and two separate one-CPU contention samples. Highest read p95
  **363.552 ms**; executed protocol target PASS. Historical latency failures remain FAIL.
- A shared one-second tail stall was captured in attempt 1. Its maximum was **1,078.535 ms**;
  passing p95 does not erase it. Additional latency is localized across TLS/BFF/API and SQL-call
  wall time, but **causal root cause remains UNRESOLVED**. No speculative performance patch.
- Attempt 1's missing Docker stats identity prevents component attribution. The corrected complete
  read run has service-attributed counters and all 1,660 trace joins; its slowest request is
  405.447 ms. It does not reproduce the one-second stall. GC/off-CPU and per-statement server
  timing remain unmeasured, so PostgreSQL/Keycloak/nginx/host causality is not asserted.
- Writes: **246 timed requests across two bounded executions**, zero unexpected errors.
  Final 1/4/8 cohorts have highest operation p95 **296.980 / 97.016 / 275.908 ms**; HTTP target PASS.
  Fourteen operations cover creation/update, preview/execute/replay, artifacts, branch revisions,
  merge preview/execute and asynchronous admissions. Separate two-API races verify correct conflicts.
- Six final asynchronous jobs complete: ingestion server queue/worker/total maxima
  **2.527873 / 0.217222 / 2.711996 s**; semantic **4.896953 / 0.758497 / 5.655450 s**.
  Sampled queue age peaks at 4.902163 s. Admission is not full job completion.
- Final primary writes observe at most 22 database connections, zero sampled lock waiters,
  680,628 WAL bytes and 671,744 allocated database bytes of growth. The full write/drill window
  peaks at 23 connections; corrected reads peak at 24. Per-pool live checked-out counts are not
  collected; regression verifies bounded pool exhaustion/recovery and audit rollback behavior.

Connection budget remains ordinary 5+5 plus audit two per API process; broker initial/minimum two,
maximum ten; PostgreSQL maximum 100. Conservative totals including reservations/operator allowances:
one API/two workers 52, two APIs/two workers 64, optional outbox 74; corresponding headroom 48/36/26.
One API/Studio serves read measurements. The governance drill runs two API replicas. CPU/memory and
network membership are inspected; no connection-pool capacity was enlarged to mask contention.

[Fault coverage](fault-coverage.md) includes new concurrent schema publication, a real receiver and
actual child-process exit after an external outbox effect but before checkpoint, lease/retry with
stable-ID consumer deduplication, and bounded 16-MiB tmpfs failures/recovery. Existing security,
lease/fencing, quota and audit tests run in the full regression. Prior PITR/restored applications,
identity/SDK faults and local alerts are retained without unnecessary full-drill repetition.

## Validation and retained failures

| Check | Result | Executed evidence |
|---|---|---|
| Final configured Python validation | PASS | final-validation/regression-full.txt: **558 passed / one strict xfail / zero skips**, 293.74 s; Ruff, format, strict mypy, Alembic drift |
| Initial configured validation | PASS | regression-full.txt: 554 passed/one xfail/zero skips, before four additional harness tests |
| Final focused diagnostics/release/scanner guards | PASS | static-final.txt: 18 passed; strict mypy 98 source files; 197 Python files formatted |
| Frontend tests/typecheck/format/production build | PASS | 29 tests; frontend-*.txt; explicit formatting covers new diagnostics module |
| Isolated durable browser E2E | PASS | browser.txt: five tests; ports 13000/13001/18001, developer services untouched |
| Turtle/CSV/RDF/FK/normalized SHACL/negative fixtures | PASS | Full configured fixture tests; unchanged fixture hashes |
| Raw pySHACL conformance | FAIL, strict expected failure preserved | simple-string/xsd:string mismatch remains explicitly xfail |
| Pinned engine validation/extended reasoning | PASS | Full configured semantic integrations; engine 2.1.0 retained |
| Base owl-rl CriticalMachine inference | NOT SUPPORTED | Existing documented upstream profile limit preserved |
| OWLAPI file roundtrip | PASS | owlapi-roundtrip.txt: 4.5.29, explicit xsd:date declaration addition; no axiom removal |
| Protégé GUI / independent proof verification | NOT RUN | No GUI or independent proof-verifier run claimed |
| API/Studio production image builds/startup | PASS | build-*.txt, runtime/deployment evidence, actual API image-source SHA binding |
| Six SBOMs and raw identity/hash binding | PASS | images.json, vulnerability-disposition.json, supply-chain-binding.json |
| Six-image high/critical policy | FAIL | 274 high/two critical; no suppression/exception |
| Exact-candidate release verifier | BLOCKED | release-gate-result.json; mandatory incomplete/non-PASS gates retained; no promotable archive |
| Developer environment preservation | PASS | same IDs/images/start times/mounts, HTTP/TLS 200, same one object/head 0017_capacity |
| Exact own-resource cleanup | PASS | disposable-cleanup.json; no unrelated resources pruned |

Attempt 1 remains **FAIL** at its original cold-cache tmpfs assertion: Python reported no usable
temporary directory instead of the assumed ENOSPC. Both corrected cold/warm cases then PASS with
actual engine recovery. Its 40 PASS / six COMPLETED / one FAIL raw records are unchanged: the six
COMPLETED records are successful terminal-state assertions emitted using the reserved status
keyword; subsequent code uses job_status and the final six-job evidence is standard PASS.
Attempt 2 has 19 PASS records; final write follow-up has 24 PASS records. These are scoped follow-ups,
not a retroactive relabeling of the original failed all-scenarios invocation.

The initial resource attribution defect and a container-log recreation gap are retained and
corrected. The first run's log history was collected before recreation; later capture starts with
the sampler. Span joins deduplicate snapshot/live records. Final write sampling retains expected
HTTP 404s after intentional API recreation; primary write resources precede that recreation.

## Remaining acceptance dependencies

Local acceptance remains BLOCKED by the unchanged security policy failure and incomplete mandatory
fault/causal-diagnosis evidence; no residual vulnerability is accepted. Physical host/database disk
failure is NOT RUN because shared storage must not be filled. Complete target fault, representative
capacity and approved business SLOs remain unvalidated. Live per-pool utilization, GC/off-CPU and
server-statement timing are explicit diagnostic limits.

Production certification additionally requires approved Entra/Google/Workspace registrations,
organizations, callbacks, consent, test accounts/subject links and operator credentials; an
independent off-host recovery destination/host with encryption/key custody/retention and RPO/RTO;
production scrape targets/receiver plus named acknowledgement/on-call owners; actual target hardware,
data/workload and business SLO approvals; and an authorized hosted release with enforced reviewers,
retention and independently verified provenance. Existing operator handoff procedures remain in
`docs/operations/production.md` and readiness.md. No external resource was modified or certified.

Reproduce with reviewed API/Studio `phase10-closure4` images and existing selected semantic/ingress/
PostgreSQL/Keycloak images: `scripts/accept_phase10_closure4.py --scope all|reads|writes --output NEW_DIR`.
Use one disposable project at a time for the fixed acceptance subnets. Main runs clean up only their
own project/volumes; private credentials, WAL and detailed logs remain ignored. Do not publish them.
`files.txt` inventories Closure 4 files; `source-files.json`, the starting/final working-tree records
and `SHA256SUMS` bind reviewed source/evidence. No deployment, migration or Phase 11 work is approved.
