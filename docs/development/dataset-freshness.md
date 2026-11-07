# Dataset freshness policies

`GET /api/v1/datasets/{id}/freshness` requires dataset read authority. `PUT` requires Project write
and records the policy change in the existing audit boundary. Policies contain enabled state, optional
expected interval and optional maximum acceptable age, each bounded from 60 seconds to 365 days. If
both thresholds exist, maximum age determines the status. No policy or a disabled policy is DISABLED;
an enabled policy without a threshold or committed version is UNKNOWN.

FRESH/STALE compares database time to the last successful logical dataset version's finalized timestamp.
A failed validation/run never removes the previous successful version. Dataset reads/queries do not
update freshness. Atomic DAG outputs are observed only after the shared publication transaction.
The status reports the checked time, committed version/timestamp, derived age, policy and reason.
No missing historical timestamp or measurement is invented. See the phase report for scope limitations.

The status also returns the last successful/failed producing run when that pipeline is independently
authorized. The dependency endpoint returns bounded, authorized upstream dataset freshness with
indexing completeness/truncation. Hidden producer identities and upstream sources are omitted.
