# Background workers

Workers run inside the modular API package against the same governed PostgreSQL services.
The current database readiness revision is `0030_directory_shares`. Configure the database,
OIDC service identity, storage and source catalog before starting the appropriate worker.
From the repository root:

```bash
# Each command processes one eligible job and exits.
uv run python -m ontology_platform.ingestion
uv run python -m ontology_platform.semantic
# Continuous execution controller, automation dispatch and lineage maintenance.
uv run python scripts/run_execution_worker.py
```

Ingestion and semantic runners accept an optional `--ontology manufacturing` queue filter.
Ingestion also supports explicit staging cleanup with `--cleanup-days 7` (7–3650 days).
The semantic runner needs the pinned Open Ontologies executable, installed with
`uv run python scripts/install_semantic_engine.py` or selected by `OPEN_ONTOLOGIES_BIN`.
The execution controller needs the same ArtifactStore configuration as the API for
storage-backed jobs; see [execution setup and limits](../../docs/development/execution-workers.md).

OIDC workers authenticate as their own verified service principal. The pool discovers the
owning tenant and resolves the initiating principal from each immutable job grant; startup
no longer requires a tenant or ontology. Automatic enrollment is bounded by existing worker
roles and respects disabled identities/memberships and restricted Project access. Every
protected operation rechecks both user and service authority. Outbox delivery instead
requires explicit tenant-scoped `outbox:deliver` service authority.

Multiple processes use PostgreSQL leases, attempt fencing and retained ontology locks.
The execution controller performs bounded pending-lineage maintenance even when no execution
job is queued. Supervision remains operator-managed; the development Compose `worker` profile
runs the execution controller only. No additional broker or datastore is introduced.

See [ingestion](../../docs/api/ingestion.md), [semantics](../../docs/api/semantic.md),
[dynamic worker authorization](../../docs/operations/dynamic-workers.md) and the
[current worker rollout settings](../../docs/operations/phase-22-okd4.md). Production deployment
and certification remain subject to PLANS.md §23B.
