# ADR 0001: Canonical representation

Status: Accepted for Phase 0

## Context

PLANS.md requires a modular operational platform with verified semantic boundaries.

## Decision

Use format-versioned Pydantic contracts and deterministic JSON independently of SQL and OWL. RDF is a derived semantic representation, not the transactional source of truth. Preserve unsupported imported constructs as diagnostics in later compiler work.

## Consequences

Preserve phase boundaries. Add integration tests before introducing persistence or external contracts.
