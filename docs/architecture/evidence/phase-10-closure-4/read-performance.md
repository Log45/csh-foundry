# Read performance — all controlled attempts

Nearest-rank percentiles include every measured request. Main rows use the original paced mix and iterations. Read p95 is the highest per-operation p95 among query, Object Set, traversal and preview. SDK generation remains separate. `performance-summary*.json` contains p50/p95/p99/max, throughput, duration, errors and each operation.

| Attempt/run | Clients | Requests | Seconds | req/s | Read p95 ms | SDK p95 ms | Errors |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1/isolated-1 | 1 | 20 | 20.115 | 0.994 | 87.836 | 210.661 | 0 |
| 1/isolated-1 | 4 | 80 | 20.118 | 3.977 | 116.021 | 104.428 | 0 |
| 1/isolated-1 | 8 | 160 | 20.171 | 7.932 | 260.177 | 208.058 | 0 |
| 1/isolated-2 | 1 | 20 | 20.120 | 0.994 | 220.201 | 52.018 | 0 |
| 1/isolated-2 | 4 | 80 | 20.142 | 3.972 | 166.978 | 163.363 | 0 |
| 1/isolated-2 | 8 | 160 | 20.161 | 7.936 | 228.515 | 222.903 | 0 |
| 1/isolated-3 | 1 | 20 | 20.148 | 0.993 | 73.816 | 60.173 | 0 |
| 1/isolated-3 | 4 | 80 | 20.154 | 3.969 | 148.135 | 109.629 | 0 |
| 1/isolated-3 | 8 | 160 | 20.147 | 7.942 | 363.552 | 299.830 | 0 |
| 1/sustained | 8 | 720 | 90.585 | 7.948 | 284.532 | 208.189 | 0 |
| 1/contention | 8 | 160 | 20.136 | 7.946 | 314.191 | 262.053 | 0 |
| 2/isolated-1 | 1 | 20 | 20.067 | 0.997 | 61.691 | 49.000 | 0 |
| 2/isolated-1 | 4 | 80 | 20.085 | 3.983 | 121.634 | 111.567 | 0 |
| 2/isolated-1 | 8 | 160 | 20.097 | 7.961 | 314.341 | 326.075 | 0 |
| 2/isolated-2 | 1 | 20 | 20.067 | 0.997 | 58.859 | 58.766 | 0 |
| 2/isolated-2 | 4 | 80 | 20.091 | 3.982 | 112.247 | 110.607 | 0 |
| 2/isolated-2 | 8 | 160 | 20.096 | 7.962 | 250.623 | 235.170 | 0 |
| 2/isolated-3 | 1 | 20 | 20.068 | 0.997 | 56.440 | 54.071 | 0 |
| 2/isolated-3 | 4 | 80 | 20.090 | 3.982 | 120.361 | 116.821 | 0 |
| 2/isolated-3 | 8 | 160 | 20.097 | 7.961 | 242.648 | 249.796 | 0 |
| 2/sustained | 8 | 720 | 90.411 | 7.964 | 236.410 | 231.143 | 0 |
| 2/contention | 8 | 160 | 20.134 | 7.947 | 354.722 | 251.577 | 0 |

**PASS for the executed Closure 4 protocol:** 3,320 measured mixed requests, including 2,656 reads/preview and 664 SDK generations, zero errors. Highest read p95 363.552 ms. Historical Closure 2/3 failures are unchanged. This does not establish elimination of intermittent stalls: attempt 1 contains a 1,078.535 ms maximum request. Warm-up (130 requests) and overhead probes (240 requests) are reported separately, not discarded.

The paired probes measured overall median/p95 ms: diagnostics disabled 166.125/475.391; diagnostics enabled without sampler 157.610/366.999; diagnostics enabled with sampler 149.658/186.843. Short sequential pairs are noisy and do not establish a causal overhead estimate or an improvement. No workload assertion, pacing, target, authorization or audit was relaxed.
