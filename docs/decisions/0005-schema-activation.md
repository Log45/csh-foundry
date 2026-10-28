# ADR 0005: Schema versioning and activation

Status: Accepted for Phase 0

## Context

PLANS.md requires a modular operational platform with verified semantic boundaries.

## Decision

Published canonical snapshots are immutable. Publication and activation are separate; drafting never changes active state. Phase 1 will enforce one active published version per tenant/ontology, actor/time, compatibility analysis, existing-data validation and approved breaking migration plans in a transaction. Failed migrations leave the old version active. Phase 0 defines contracts only.

## Consequences

Preserve phase boundaries. Add integration tests before introducing persistence or external contracts.
