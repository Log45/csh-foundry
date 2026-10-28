# ADR 0007: Protégé and WebProtégé integration

Status: Accepted for Phase 0

## Context

PLANS.md requires a modular operational platform with verified semantic boundaries.

## Decision

Use file-based Turtle/RDF/XML interchange. Verify using Protégé 5.6.9-compatible OWLAPI 4.5.29; do not claim a desktop GUI test. The round trip adds an explicit xsd:date declaration and removes no axioms. Imported OWL becomes a reviewed unpublished operational draft in Phase 6. WebProtégé 4.0.2 is source-inspected only; its MongoDB/servlet deployment is outside the operational stack and is not deployed.

## Consequences

Preserve phase boundaries. Add integration tests before introducing persistence or external contracts.
