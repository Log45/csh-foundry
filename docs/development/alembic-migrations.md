# Database migrations

The repository-root `alembic.ini` defines `script_location = services/api/migrations` and
`prepend_sys_path = services/api/src`. `services/api/migrations/env.py` obtains the configured
database URL from Settings and supports an explicitly supplied SQLAlchemy connection for
isolated-schema tests. API startup checks readiness; it does not apply migrations.

The current source head and required readiness revision are **`0030_directory_shares`**.
From the repository root, inspect the configured database and repository head:

```sh
uv run alembic -c alembic.ini current
uv run alembic -c alembic.ini heads
```

For a new disposable local database only:

```sh
uv run alembic -c alembic.ini upgrade head
uv run alembic -c alembic.ini check
```

For an existing shared database, verify the exact host/database/user/schema and current
revision, create a backup and rehearse an isolated restore before applying an explicitly
reviewed target revision. Follow [the shared rollout procedure](shared-dev-rollout.md) and
[the current Phase 22 migration/worker runbook](../operations/phase-22-okd4.md). Never run an
unqualified shared `upgrade head` or downgrade against valuable data. Several migrations are
forward-only; recovery uses a verified restore and reviewed connection cutover, with a matching
artifact checkpoint where storage is enabled.

The recent forward path is:

```text
0024_pipeline_graphs → 0025_applications → 0026_pipeline_dag
→ 0027_lineage_observability → 0028_job_execution_grants
→ 0029_personal_tenants → 0030_directory_shares
```

Revision 0027 adds lineage, freshness and operational events. Revision 0028 adds immutable
worker job grants; 0029 adds personal tenant ownership and resource shares; 0030 extends
shares for directory invitations. These references describe source migrations, not confirmation
that any particular deployment has applied them. Check `current` on the intended target.

If using another working directory, change to the repository root before invoking this relative
configuration. A “No script_location key” error indicates the canonical configuration was not
loaded; do not create another `alembic.ini` to hide it. Production release remains blocked
under PLANS.md §23B.
