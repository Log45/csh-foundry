# ADR 0018: Inert actions composing governed mutations

Status: Accepted for Phase 3

Extend the canonical action models in place with strict references, typed identity parameters,
bounded bindings/operations and preconditions. Preserve target-only declarations as inert legacy
metadata. Reject executable expressions and schema/reference mistakes. Derive action definition
versions from canonical content hashes inside immutable published ontology snapshots.

Allow governed services to participate in an explicit caller-owned SQLAlchemy session while
retaining their normal transaction-owning public behavior. The action service composes the existing
ObjectService operations under the existing ontology FOR UPDATE lock. Retain canonical validation,
uniqueness/cardinality and revision checks. Commit operational effects, execution/idempotency,
audit, overlays and outbox together; revalidate authorization and state on every fresh execution.

Use a rolled-back savepoint for exact service-backed preview, without staging durable action
records or external effects. It consumes the same bounded SQL work and lock boundary as execute.
Enforce a diminishing three-second SQL/elapsed budget and a raw 64 KiB action request bound.
This favors validation parity and correctness over contention avoidance. No measured workload
justifies replacing ontology-wide locking. Production identity and ingestion remain separate phases.
