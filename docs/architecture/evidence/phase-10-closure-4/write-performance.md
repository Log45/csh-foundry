# Bounded write performance

Two executions each measured 123 synchronous HTTP/admission requests across object concurrency 1/4/8 (246 total, zero unexpected errors). The final follow-up preserves role-attributed resources and server job timestamps. Actions, branch/merge and artifact operations are bounded sequential cohorts; separate two-API drills exercise concurrent actions and merges. This is fixture-scale validation, not general saturation capacity.

| Operation | Samples in final follow-up | Highest cohort p95 ms |
|---|---:|---:|
| action_execute | 12 | 57.514 |
| action_preview | 12 | 54.050 |
| action_replay | 12 | 39.492 |
| artifact_sdk | 12 | 296.980 |
| branch_create | 6 | 50.728 |
| branch_revision | 3 | 84.156 |
| ingestion_admission | 3 | 46.200 |
| merge_execute | 3 | 47.134 |
| merge_preview | 3 | 43.889 |
| object_create | 24 | 275.908 |
| object_update | 24 | 200.146 |
| semantic_admission | 3 | 56.574 |
| semantic_artifact | 3 | 45.727 |
| semantic_export | 3 | 60.459 |

**Synchronous/admission write target PASS:** highest operation p95 296.980 ms (<2,000 ms), zero unexpected errors. Expected replica conflicts: one action commit/seven HTTP 409s; one merge/three HTTP 412s; four admissions/four HTTP 409 quota conflicts, with cancellation/replay/recovery. These drill requests are separate from the timed cohort.

| Async kind | Object concurrency | Queue s | Worker s | Server submission-to-completion s | Observed completion s |
|---|---:|---:|---:|---:|---:|
| ingestion | 1 | 0.702808 | 0.217222 | 0.920030 | 1.218196 |
| semantic | 1 | 1.078559 | 0.714152 | 1.792711 | 2.318849 |
| ingestion | 4 | 2.527873 | 0.184123 | 2.711996 | 2.849594 |
| semantic | 4 | 4.879690 | 0.669918 | 5.549608 | 6.109580 |
| ingestion | 8 | 0.629688 | 0.189064 | 0.818752 | 1.242208 |
| semantic | 8 | 4.896953 | 0.758497 | 5.655450 | 6.138097 |

All six final jobs completed. Nearest-rank p95 across three jobs/kind is the maximum: ingestion total 2.711996 s, semantic total 5.655450 s. Admission is not completion. Oldest sampled pending age 4.902163 s. The two-second HTTP write target is not an asynchronous completion guarantee.

During final primary writes: 222 PostgreSQL samples, maximum 22 connections, zero sampled lock waiters, WAL growth 680,628 bytes, allocated database growth 671,744 bytes. Full final run including setup/drills observed 23 connections. Cumulative statistics and allocated size are sampled observations, not exact logical-byte accounting. API resource coverage ends at its intentional recreation for two replicas; expected 404 sampler errors after recreation are retained. The initial seven-container snapshot does not measure replacement API CPU usage.

Ordinary acquisition p95/max: 8.003/73.684 ms; audit acquisition p95/max: 0.529/1.618 ms. Acquisition includes queue wait, connection creation, pre-ping and checkout callbacks; it is not a pure pool wait metric. Live per-pool checked-out counts were not collected; bounded exhaustion/recovery and independent audit behavior passed the full PostgreSQL regression.

Reported throughput is timed writes divided by cohort wall time, which includes polling/pacing; unmeasured setup/polling HTTP calls are not counted as timed writes.
