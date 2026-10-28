# ADR 0009: Governed local tenancy and service transactions

Status: Accepted for Phase 1

## Decision

Every domain operation invokes the authorization interface and uses the configured local
principal with explicit tenant context. The local administrator can provision only their configured
tenant. A missing/blank/mismatched identity is denied; tenant resolution is required for subsequent
operations. No client header chooses tenant identity. Domain requests never access ORM persistence
directly. Shared application contracts and unit-of-work helpers are public module interfaces.
Composite tenant keys/FKs provide ownership and endpoint integrity; scoped service predicates provide
read isolation. RLS/OIDC/fine-grained policies remain later work. Keep local instances on loopback.

## Consequences

Preserve existing canonical identity, semantic adapter and fixture contracts.
Validate persistence on real PostgreSQL. Later phases require separate approval.
