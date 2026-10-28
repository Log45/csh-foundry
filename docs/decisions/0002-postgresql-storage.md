# ADR 0002: PostgreSQL operational storage

Status: Accepted for Phase 0

## Context

PLANS.md requires a modular operational platform with verified semantic boundaries.

## Decision

PostgreSQL owns operational metadata, object identities, JSONB properties, forward links, governance and transactions. Phase 0 creates only a tenant anchor. Phase 1 adds relational identities/FKs plus JSONB; no additional platform database. Service operations own explicit SQLAlchemy transactions.

## Consequences

Preserve phase boundaries. Add integration tests before introducing persistence or external contracts.
