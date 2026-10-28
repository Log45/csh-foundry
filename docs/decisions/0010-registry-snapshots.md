# ADR 0010: Versioned registry and published snapshot immutability

Status: Accepted for Phase 1

## Decision

Persist canonical JSON snapshot text and SHA256 hash per tenant/ontology/version. Store version-owned
object/link definition rows as relational FK targets; properties/actions remain nested canonical
metadata, with no action execution. Draft replacement is atomic across both representations.
PostgreSQL triggers protect published version and type snapshots from mutation, including inserts
into published type collections. Type-edit triggers lock the parent version even while it is a
draft, preventing concurrent publication from racing the immutability check. Publication records actor/time and does not activate.
Use one active-version pointer with a status-qualified composite FK to a published version. There
is no active schema before first activation; once activated, the pointer cannot be cleared.
Historical published versions remain immutable/addressable. Stable IDs and namespace cannot change.

## Consequences

Preserve existing canonical identity, semantic adapter and fixture contracts.
Validate persistence on real PostgreSQL. Later phases require separate approval.
