# Phase 0 architecture

The backend is a modular Python monolith. PostgreSQL is the authoritative operational
store. Canonical JSON/Pydantic metadata is independent of RDF/OWL. Open Ontologies is
an external semantic process and never owns operational objects. Protégé is optional
file-based authoring tooling. Next.js/TypeScript, workers, compiler, SDKs, actions,
ingestion and operational object APIs remain reserved boundaries.

The Phase 0 migration creates only `tenants` and Alembic's version table. There is no
public tenant provisioning API. SQLAlchemy sessions have no implicit mutation commit;
governed services will own `transaction(factory)` boundaries. A failed service operation
rolls back the entire PostgreSQL transaction. Phase 1 adds composite tenant-safe keys
and foreign keys, explicit tenant-scoped repositories and rejection tests before exposing
operational APIs. A tenants table alone does not enforce multi-tenant access isolation.

Health probes are public and contain no operational data. Every future domain route must
resolve a principal. The dependency fails closed unless a trusted local identity is
explicitly configured with both tenant and principal. No caller-provided tenant header
is trusted. Authentication/authorization protocols are defined; OIDC/RBAC/ABAC is deferred.

Semantic work runs as offline commands in this phase, and later as durable PostgreSQL
jobs in a separate worker. No reasoning occurs in API request handlers. Open Ontologies
uses disposable private SQLite/in-memory RDF state internally; this is an upstream
implementation detail, never a second authoritative platform datastore.
