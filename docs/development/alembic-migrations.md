# Canonical Alembic invocation

The repository root `alembic.ini` defines `script_location = services/api/migrations` and
`prepend_sys_path = services/api/src`. `services/api/migrations/env.py` obtains the configured database
URL from Settings and supports an explicitly supplied SQLAlchemy connection for isolated-schema tests.
There is no API-startup migration service or separate migration configuration.

From the repository root:

```sh
uv run alembic -c alembic.ini current
uv run alembic -c alembic.ini heads
uv run alembic -c alembic.ini upgrade 0027_lineage_observability
uv run alembic -c alembic.ini check
```

For shared development, first follow [the controlled rollout](shared-dev-rollout.md). Never run
unqualified `upgrade head`; verify the exact database/schema and pending revisions first. If using
another working directory, change to the repository root before invoking this relative configuration.
The previous “No script_location key” failure comes from invoking without the repository configuration.
Do not create another alembic.ini to hide it. The forward path is 0024_pipeline_graphs →
0025_applications → 0026_pipeline_dag → 0027_lineage_observability. Production is separately blocked.
