# Latency investigation — 2026-11-03

**Causal root cause: UNRESOLVED. Component timing localization is materially improved.**
No application performance optimization, authorization cache, pool increase, query/index change,
audit suppression or relaxed workload/target was introduced.

The Closure 3 second isolated repetition remains FAIL (528.441 ms read p95). New measurements use
the final broker maximum ten, initial/minimum two; unchanged ordinary/audit pools, PostgreSQL
maximum 100, one API process/Studio replica during reads and the existing resource/network profile.
Optional API/BFF timing is enabled in the disposable study; production defaults remain disabled.
Images, actual runtime environment selections, commands, CPU/memory bounds and network membership
are in each `final-runtime.json`; the code/defaults are bound by `image-source-binding.json`.
The same request mix, 20 iterations/client, 1/4/8 clients, one-second pacing, TLS verification,
authentication, assertions and 63-object dataset are retained. Both 90-second sustained samples
and separately bounded one-CPU contention samples are retained. No builds/scans/regressions overlap
these measurement windows. Read performance is [reported for every run](read-performance.md).

## Captured stall

Attempt 1 sustained iteration 62 slowed all eight clients across all five operations. The largest
request, trace `bc9fedb8180cc8bfcfe78f01f8cb4403`, took **1,078.535 ms**, despite a passing run p95:

| Stage | Duration ms |
|---|---:|
| Curl request | 1,034.195 |
| Curl process/file overhead inside transport wrapper | 42.054 |
| TCP | 0.311 |
| TLS | 103.869 |
| Curl first-byte wait after request preparation | 929.663 |
| nginx request | 893.000 |
| Studio BFF handler | 740.704 |
| API browser-state request | 90.505 |
| API governed preview request | 631.510 |
| Ordinary SQL-call wall time in governed request (34 statements) | 425.657 |
| Ordinary acquisition in governed request | 25.911 |
| Audit acquisition / SQL in governed request | 0.898 / 1.935 |
| JWT validation in governed request | 0.542 |

Stages are nested/overlapping; do not add every row. SQL-call wall time includes driver/network
and process descheduling, not just PostgreSQL execution. Acquisition includes connection creation,
pre-ping and callbacks, not only queue wait. API duration also includes unseparated fetch,
serialization, thread scheduling and commit time. No SQL parameters or tenant values are retained.
Other simultaneous requests include 1,037.894 ms preview, 819.333 ms SDK and 815.097 ms traversal.
The entire request list, including every failure/slow sample, remains in `correlated-requests.json`.
`slow-resource-index.json` references nearby raw samples by index and SHA-256 without duplicating
large resource payloads. The diagnostic threshold is 250 ms; the acceptance target remains p95 500 ms.

The observer sampled zero PostgreSQL lock waiters around this stall; this cannot exclude shorter
waits. Increased TLS and host curl overhead as well as API/SQL wall time prevent attribution solely
to one SQL statement, API authorization, Keycloak or nginx. No per-statement server execution
trace, GC pause profile or host/VM scheduler trace was collected. These causes cannot be eliminated.

## Resource correction and repeat

The initial Docker stats response omitted `name`; the sampler had not retained the requested
container ID. Those resource rows remain **INCONCLUSIVE for component attribution**, never assigned
to services by guessed ordering/memory. PostgreSQL and aggregate macOS memory-free observations
remain usable. Before API recreation, an additional bounded live collector retained existing
redacted log history; coverage verifies API, BFF and ingress joins for **all 1,660** main requests.

The corrected sampler records immutable container ID plus inspected name, checks HTTP status,
uses a 50,000-row cap, polls containers nominally every 250 ms and PostgreSQL every 100 ms, and
retains container events and aggregate macOS memory-free queries. A complete independent read
protocol then passes all 1,660 requests with all three span types joined. Its slowest request is
405.447 ms; the earlier one-second stall is not reproduced in this corrected resource window.
Seven roles each have 1,281 container observations. Peak memory: API 140,304,384 bytes, Studio
141,111,296, PostgreSQL 232,280,064 and Keycloak 777,003,008. PostgreSQL/Studio/ingress show no new
CPU throttling. API records three throttled periods/81.526 ms; Keycloak two/38.229 ms; the emulated
semantic worker 240/2,295.119 ms over the whole sample. These totals do not establish causality
for a historical stall. Maximum sampled connections are 24; sampled lock waiters are zero.

Resource data are counter observations, not CPU flamegraphs. macOS `memory_pressure -Q` supplies
aggregate free percentage, not per-process pressure or swap/scheduler attribution. The bounded
single-host, ARM64/amd64-emulation workload is not target capacity certification. Per-pool live
checked-out counts, per-stage serialization/commit timing and GC correlation remain unmeasured.

The short instrumentation/sampler probes are retained in attempt 1 and the performance report.
Their median/p95 values vary enough that no reliable causal overhead estimate can be claimed.
No speculative performance patch follows from these observations. Further diagnosis requires
capturing a comparable shared stall with service-attributed resource counters plus GC/off-CPU or
server statement timing, preferably on the authorized target infrastructure.
