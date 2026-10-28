# ADR 0004: Operational identity and RDF mapping

Status: Accepted for Phase 0

## Context

PLANS.md requires a modular operational platform with verified semantic boundaries.

## Decision

Use the complete immutable tenant/ontology/type/object tuple and reversible base64url JSON encoding v1. Names and schema versions do not change identity. Keep external-IRI provenance/ambiguity review in a future registry and never interpret owl:sameAs as an operational merge. See canonical-schema.md for exact encoding.

## Consequences

Preserve phase boundaries. Add integration tests before introducing persistence or external contracts.
