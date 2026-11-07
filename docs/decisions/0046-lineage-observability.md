# ADR 0046: Recoverable governed lineage and execution observability

Date: 2026-11-06. Status: implementation in progress; acceptance requires executed evidence.

PostgreSQL remains authoritative. Existing immutable versions, execution inputs, DAG manifests,
materialization records, application manifests and automation definitions supply provenance. A derived
versioned edge index contains stable identities, never dataset bytes. Design dependencies and observed
execution provenance are distinct. Private drafts are excluded. Index records never grant authority.
Every traversal prunes inaccessible endpoints and supporting resources before expansion or counting.
No placeholder node, redaction count or hidden path is returned. Missing and private roots use 404.

Canonical writes enqueue reconciliation in the same database transaction. Successful multi-output
publication therefore queues all outputs with the same commit. Queries report indexing completeness;
absence of indexed history is never evidence of absence. Bounded idempotent reconciliation reads
canonical rows and records progress. Derived edges are append-only; mutable job state remains in the
existing execution control plane. No second ontology, scheduler, execution engine or audit system.

The actual shared database was already 0026_pipeline_dag at reconnaissance. Keycloak uses container-local
H2 and shares only the existing network with Foundry. Its two protected containers, their persistence
and all configuration are outside rollout targets. Never restart shared PostgreSQL. A private logical
backup and isolated restore rehearsal precede shared changes. Migrations use root alembic.ini with an
explicit target revision; 0027 first requires disposable-schema migration/drift validation. Recovery
means stopping only Foundry writers, preserving evidence and restoring a verified backup into a new
isolated database for operator review; never automatically downgrade or overwrite shared data.

Freshness uses committed version timestamps and database time. No policy means DISABLED. Errors and
operational events expose allowlisted classifications, never raw exception strings, storage keys,
credentials or environment. Existing authorization and current Project membership remain mandatory.
Production remains BLOCKED / NOT PRODUCTION-CERTIFIED under PLANS.md §23B.
