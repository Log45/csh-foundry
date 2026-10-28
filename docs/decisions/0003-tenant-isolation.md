# ADR 0003: Tenant isolation

Status: Accepted for Phase 0

## Context

PLANS.md requires a modular operational platform with verified semantic boundaries.

## Decision

Every domain operation requires explicit authenticated tenant context. Include tenant in composite keys/FKs and repository predicates from Phase 1. Trusted local identity is opt-in, configured on the server, fails closed by default. Health probes are public. Full OIDC and policy enforcement remain Phase 7 and block public deployment. RLS is deferred pending role/pool design; no isolation claim is made for a tenant table alone.

## Consequences

Preserve phase boundaries. Add integration tests before introducing persistence or external contracts.
