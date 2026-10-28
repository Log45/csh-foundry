# ADR 0006: Open Ontologies integration

Status: Accepted for Phase 0

## Context

PLANS.md requires a modular operational platform with verified semantic boundaries.

## Decision

Use pinned v2.1.0 batch subprocess commands in disposable state directories, with typed results, no shell, timeout and sanitized failures. Keep SemanticEngine replaceable. Use owl-rl-ext for the fixture hasValue/intersection inference; base owl-rl cannot derive it. No custom reasoner or HTTP deployment is introduced. Workers and persisted provenance are Phase 5.

## Consequences

Preserve phase boundaries. Add integration tests before introducing persistence or external contracts.
