# ADR 0048: existing PostgreSQL owner as runtime account

Status: implemented for the explicit owner-runtime task, 2026-11-08.

The OKD4 environment permanently supplies one existing application database owner account and
cannot provision another runtime role. API, workers and migrations must work with that account.
`FOUNDRY_ALLOW_OWNER_RUNTIME_ROLE` already existed, but the API skipped the entire catalog check
while workers unconditionally rejected owners. This inconsistency prevented shared-worker startup.

The common `require_runtime_role` accepts an explicit, default-false ownership exception. API and
all service worker startup/refresh paths pass their configured value, including ingestion, semantic,
outbox and the execution controller. Role flags SUPERUSER/CREATEDB/CREATEROLE/REPLICATION are still
rejected regardless of the ownership setting. No Foundry authorization operation reads this flag.
The external PostgreSQL connector's independent read-only credential policy is unchanged.

Owner mode uses the same existing database URL for migration and runtime. Migrations remain a
separate serialized maintenance process with the advisory lock and Alembic drift check, now
explicitly selecting the configured application schema. Migration 0028 is unchanged and retains
all FK/uniqueness/check constraints, immutable grant scope, irreversible revocation and audit guards.
No new migration or grant backfill is needed. Owners already have privileges on their tables;
separate runtime table grants and post-migration grant refresh are not part of owner-mode rollout.

The provisioning utility has a verification-only owner path: no role/database creation, no grants
or revokes, no administrator URL, and no migration side effect. Existing non-owner deployments
retain their existing procedure. The optional load validator also reuses its configured account in
owner mode instead of creating another runtime login. Historical fixed-target migration assertions
identify specific development installations; they do not enforce role separation.

Database ownership is trusted backend capability. The application does not disable triggers or
relax job grants, authentication, service validation, tenant/resource policies, revocation or fencing.
The test harness initializes an isolated PostgreSQL cluster and one unprivileged application owner;
all tested migrations and runtime connections use that owner. Its bootstrap account is only a
local test setup mechanism, not an extra account required in the target deployment.
