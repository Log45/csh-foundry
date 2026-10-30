# Phase 9 implementation checklist

Approved scope: governed schema branches/merges, published-schema Python/TypeScript SDKs and
integration in the existing Studio. No Phase 10 implementation.

## Audit and baseline

- [x] Record clean checkout revision: 2aac02783bb71b1b71a4fe1463e7e2aa646a1440.
- [x] Inspect roadmap, reports, decisions, canonical models and actual registry/query/action/security contracts.
- [x] Verify PostgreSQL migration 0013_security (database initially stopped; start existing local service).
- [x] Record configured Python, frontend, browser/security/semantic/import baseline evidence.

## Implementation order

- [x] Tenant-owned branches, immutable base/head history, bounded queries and optimistic concurrency.
- [x] Deterministic ID-based comparison and three-way merge, explicit resolutions, stale preview protection.
- [x] Atomic merge provenance and draft handoff; retain existing migration/publication/activation guards.
- [x] Migration constraints/triggers, real PostgreSQL concurrency/governance/security tests.
- [x] Deterministic canonical-to-language compilation, safe aliases, published inputs and manifest hashes.
- [x] Independently usable async Python and TypeScript clients for actual HTTP/AST/action contracts.
- [x] Authorized artifact APIs/downloads and shared reproducible CLI.
- [x] Existing Manager branch/merge and SDK controls through the authenticated BFF.
- [x] Generated-package manufacturing acceptance, browser tests and measured bounded workloads.
- [x] Full validation matrix, architecture/API/usage docs, Phase 9 report and Phase 10 preparation.

## Chosen extension points

RegistryService composes with a caller-owned session. GovernedService.operation holds Phase 7
security context; ontology(write=True) serializes mutations. Reuse schema:read/schema:write for
branch metadata and authoring, schema:read for SDK generation/retrieval (schema disclosure).
Existing publication/activation permissions remain separate. compare() is the sole compatibility
classifier. Existing canonical hashing preserves definition-list order; merge output preserves existing target definition
order, appends new IDs sorted and retains action binding/operation order. Operational objects are never branched.

Final validation: 498 Python passes, one preserved strict xfail, zero skips; 24 frontend tests,
4 browser tests, strict typing/lint/format, migrations, independent SDK packages, both Docker images
and smoke checks. See phase-9-report.md for the complete PASS/FAIL/NOT RUN/NOT SUPPORTED matrix
and documented boundaries. Phase 10 preparation is documentation only.
