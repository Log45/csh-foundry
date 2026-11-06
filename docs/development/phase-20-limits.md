# Phase 20 operator limits

Closed contracts hard-cap 16 inputs, 100 transformations, 16 outputs, 216 dependency/output edges,
16 consumers per upstream result, depth 64, and ready-layer width 32. Graph documents permit 118
nodes (sources/transforms/outputs) and 216 edges; canonical definitions independently enforce their
limits. Use fewer transformations/outputs when the visual graph's total-node ceiling is reached.
Semantic JSON is at most 256 KiB, visual node configurations 16 KiB, expression nesting 16 levels,
and columns 256. HTTP and BFF pipeline envelopes are at most 512 KiB; other families retain 64 KiB.
No caller can override worker budgets in a run request.

ExecutionSettings environment prefix is `FOUNDRY_EXECUTION_`:

| Setting | Default | Maximum override |
| --- | ---: | ---: |
| dag_nodes | 100 | 100 |
| dag_outputs | 16 | 16 |
| retained_nodes (per tenant, historical records) | 100,000 | 1,000,000 |
| intermediate_bytes (cumulative private materializations) | 2 GiB | 4 GiB |
| staged_bytes (all outputs) | 2 GiB | 4 GiB |
| cumulative_output_rows | 100,000,000 | 100,000,000 |
| manifest_bytes (node/output metadata) | 16 MiB | 32 MiB |
| node_seconds | 600 | 1800 |
| Concurrent active nodes per run | 1 | 1 |

Existing source ceiling is 1 GiB per dataset, including each serialized output. Existing aggregate
local temporary disk is 4 GiB by default, including source downloads, normalized text, scratch,
materialized nodes and output serialization. Existing memory is 2 GiB, address space 8 GiB, CPU1200s,
parent wall1800s, and jobs2 global/2 tenant/1 Project. Existing operator settings retain their prior
validation ranges; DAG settings cannot raise source/memory/process ceilings through a payload.

Each child uses remaining wall time and node deadline; the parent live-lease/deadline check also
fences final commit. Sequential children do not imply arbitrary joins fit memory: sorts, grouping,
deduplication and explosive joins may exceed budgets and fail. Per-child RSS and aggregate run-disk
watchdogs preserve development limits; macOS watchdogs are soft, while Linux additionally applies
address/CPU/per-file rlimits. No new hostile-code or production-kernel isolation claim is made.

Intermediate sizes, cumulative outputs/rows and serialized metadata are checked before durable
publication. Full-content output validation and per-output 1 GiB limits remain. Intermediate preview
rows are omitted; output previews retain the existing 100-row/1 MiB cap. Run metrics expose measured
peak child RSS, measured peak temporary disk, intermediate/staged bytes, output rows and wall time.
Filesystem watchdog sampling can miss short-lived scratch peaks; this remains a documented
measurement limit rather than a claim of continuous kernel accounting.

Admission rejects a tenant that would exceed retained-node history; immutable history is not silently
purged. Operators must plan retention/export before raising caps. Cleanup sweeps at most ten terminal
run manifests per worker tick, never active runs or committed output objects. Existing queue limits
bound admitted work independently of history retention. See the Phase 20 report for executed evidence.
