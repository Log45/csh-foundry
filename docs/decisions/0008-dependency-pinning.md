# ADR 0008: Dependency compatibility and pinning

Status: Accepted for Phase 0

## Context

PLANS.md requires a modular operational platform with verified semantic boundaries.

## Decision

Lock Python runtime/dev dependencies with uv.lock; pin semantic release and checksums, authoring source commits and OWLAPI Maven version. Use pinned source to verify CLI/API contracts, not README claims alone. Record the raw pySHACL string-literal incompatibility and separately test normalized RDF 1.1 terms. Preserve supplied fixtures. Release-image build features are not attested by the binary; optional feature support stays unverified.

## Consequences

Preserve phase boundaries. Add integration tests before introducing persistence or external contracts.
