# 0052 — Account for worker memory and maintain idle lineage

Scope: corrective work for failures exposed by the existing CI regression suite.

## Memory belongs to the spawned executable

Linux preserves resource-usage high-water statistics across exec. A spawned worker's
`getrusage().ru_maxrss` can therefore include the controller's pre-exec footprint. The
hosted tiny-function failure reported about 290 MB against its 256 MB limit. A Linux
reproduction with a 350 MB parent reproduced a false memory-limit failure for a tiny
function; its actual worker high-water footprint was about 50 MB.

Read Linux worker peak RSS from `/proc/self/status` VmHWM, which describes the current
memory map. Retain the live RSS watchdog and all CPU, address-space, memory, disk, wall,
lease and publication budgets. Missing Linux accounting fails closed. Darwin retains its
existing accounting. Test a small child below a 128 MB limit while its controller holds
300 MB, and preserve real over-budget/no-publication coverage.

## Configure native allocators before native imports

Polars' jemalloc arenas/background threads and Arrow's allocator reservations can exhaust
address space while a Parquet source is tiny. In private Linux children, bound Polars to
two arenas without background allocator threads or retained mappings, select Arrow's
system memory pool, and bound Arrow IO threads. Configuration uses upstream-supported
settings verified against the installed Polars code and Arrow documentation. No resource
budget is increased.

The legacy dataset parser previously imported native libraries while unpickling its
spawn target, before entering the worker function. Move its target into the existing
neutral isolation module. Configure its environment before importing parser/streaming
modules, preserving its 20-second CPU and 2 GiB address-space caps and result/error contract.
The normal execution worker retains its separate governed job budgets. No parsing engine
or transformation semantics are replaced.

## Pending lineage is work even with no queued execution

The shared worker pool previously invoked `run_one()` only for queued execution. Its
indexing tick could stop immediately after the last job published outputs or after a
metadata-only change. A browser exploration could then return an incomplete snapshot
indefinitely.

Discover pending LineagePending generations as a maintenance scope in the existing
controller. Require the existing execution-claim/delegation permissions and enabled service
membership. Use the same bounded projection/sweep implementation and governed control
transaction, tenant by tenant. Preserve explicit disabled memberships during enrollment.
No separate scheduler, service, datastore, public permission, or migration is introduced.
Tests cover idle indexing without queued jobs and prevent indexing after worker membership
revocation. The production controller and browser harness both use this path.

Browser lineage exploration returns a snapshot. The E2E check refreshes that read-only
snapshot while waiting for the asynchronous projection, under its existing five-second
bound. Whole-test retries remain disabled.

## CI prerequisites

Schema export constructs explicit offline settings with an unused loopback database URL
and disabled storage; it requires no .env or running service. Backend shards build the
SDK packages before running tests that import their distribution files. Public schemas
and SDK contracts remain unchanged.
