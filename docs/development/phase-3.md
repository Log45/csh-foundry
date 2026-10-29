# Phase 3 checklist — requires separate approval

1. Re-read specifications, validation guide, Phase 2 report and ADRs; run the complete existing
   validation suite and preserve raw pySHACL/profile compatibility results.
2. Define the inert action language precisely: typed parameters, deterministic references,
   create/update/delete object/link operations, validation/preconditions and unsupported diagnostics.
   Do not execute arbitrary Python/SQL from metadata.
3. Add tenant-safe action execution, idempotency, audit, outbox and edit-history persistence through
   Alembic. Tie action/schema versions to execution and approved active metadata.
4. Implement governed action services using existing property validation, object identities,
   revision checks, link cardinality and PostgreSQL transactions. All multi-object mutations,
   audit events and outbox records must commit or roll back together.
5. Recheck authorization and active schema at execution time. Preview must be pure, bounded,
   authorized and never substitute for execution-time checks or cause external side effects.
6. Bind idempotency keys to tenant/principal/action/schema and canonical parameters; retries with
   identical payloads reuse results, conflicting key reuse is rejected, concurrent retries stay atomic.
7. Implement source/edit overlay ownership and deterministic reconciliation contracts without
   introducing the Phase 4 ingestion pipeline or silently overwriting governed edits.
8. Define webhook categories/timeouts and durable outbox delivery/retry boundaries. PostgreSQL
   cannot atomically commit external systems; document compensation/reconciliation where needed.
9. Add action preview/execute/history routes through existing services; avoid separate business logic
   for future MCP/SDKs. Preserve existing CRUD/query/projection/cursor behavior and tenant boundaries.
10. Validate manufacturing ScheduleMaintenance/CompleteMaintenance/UpdateMachineStatus/AssignTask
    against actual vocabulary. Test failed multi-object rollback, duplicate/conflicting idempotency,
    concurrent revisions, authorization, audit/outbox atomicity and webhook failure/retry behavior.
11. Measure lock contention for action/query overlap before changing the retained ontology locking
    boundary. Add durable workers only to the extent explicitly approved by the phase roadmap.
12. Run full PostgreSQL/API/semantic/lint/type/container regressions and applicable fixture checks;
    document migrations/decisions/results, produce Phase 3 report, then stop for Phase 4 approval.

Do not implement production ingestion, semantic materialization, Protégé expansion, OIDC/RBAC
administration, Studio, generated SDKs, Rust or distributed infrastructure during Phase 3.
