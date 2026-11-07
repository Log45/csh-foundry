# Shared development rollout

Phase 21 protects `foundry-keycloak`, `foundry-keycloak-tls`, their mounts, network membership,
container-local H2 persistence, configuration and authentication. Do not target either container,
restart shared PostgreSQL, delete volumes, reset data or use broad Compose teardown/recreation.

The live preflight found Foundry at **0026_pipeline_dag**, already beyond the historical Phase 20
report's 0024 observation. Foundry is database `foundry`, schema `public`, user `foundry`, host
`localhost:55432` from the host / `postgres:5432` from the application network. Keycloak shares the
network but has a separate container-local H2 database. Its lack of an external mount is an existing
persistence limitation: preserving the container is mandatory. No Keycloak changes are part of rollout.

1. Inspect container identities/start times/mounts/networks and non-secret database topology. Capture
   protected state privately. Inspect current revision and active jobs; verify disk space and reads.
2. Create a timestamped `pg_dump -Fc` of the actual Foundry database with mode 0600. Run `pg_restore
   --list`, restore into a newly named disposable database, verify preserved revision/rows, then remove
   only that owned rehearsal database. Never overwrite shared data to test recovery.
3. Review exact pending migrations, including short lock/statement timeouts. Test fresh/upgrade/drift
   in disposable schemas and preserve the test results. Do not infer approval from `head`.
4. `uv run python scripts/phase21_shared_dev.py prepare` captures existing runtime/authentication
   settings and creates private development storage credentials in ignored artifacts (0600). Reuse
   that configuration on subsequent calls. It is not a production configuration mechanism.
5. Run its `build` and `storage` modes. Storage uses the existing persistent Compose volume and
   initializes buckets/policy twice to verify idempotence. API and worker share one ArtifactStore.
6. Stop **only** Foundry writers. `uv run python scripts/migrate_shared_phase21.py` is a controlled
   preflight wrapper around the existing root Alembic configuration, targeting exactly 0027. It checks
   the backup-rehearsal evidence, exact target/revision, absence of active jobs and canonical data
   fingerprints; migration and drift checks run in one transaction. It refuses an unexpected target.
7. Run `uv run python scripts/phase21_shared_dev.py deploy`. It requires 0027 and uses targeted
   `up -d --no-deps --no-build api worker studio`; PostgreSQL and Keycloak are not lifecycle targets.
8. Verify readiness, existing authentication, preserved records and authenticated legacy/DAG/two-output
   workflows. Recompare protected IDs/start times/mounts/networks, treating mount enumeration as an
   unordered set. Container health alone is insufficient acceptance.

## Recovery

Migration errors roll back the transaction; retain logs and the original backup. Stop only Foundry
writers, verify Keycloak availability, and diagnose locks/schema/target before any retry. If data
recovery is necessary, restore the verified backup into a **new isolated database**, validate it, and
obtain operator approval for a connection cutover. Never automatically downgrade or overwrite the
shared database. Retain old application images until new authenticated workflows pass. The previous
runtime expects revision 0026; it must not be claimed ready against 0027.

Private evidence is in `artifacts/phase21/`; it includes a logical backup and connection configuration
and must not be committed. The phase report distinguishes executed evidence from planned checks.
Production remains BLOCKED under PLANS.md §23B.
