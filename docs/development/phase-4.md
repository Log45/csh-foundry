# Phase 4 checklist — requires separate approval

Phase 4 is not implemented. Begin only after Phase 3 review and explicit approval.

1. Read AGENTS.md, PLANS.md, fixtures/VALIDATION.md, the Phase 3 report, action API and ADRs.
   Run the complete configured regression suite; retain raw pySHACL/profile compatibility findings.
2. Define bounded typed source/mapping/job contracts, tenant ownership, source identity, active-schema
   binding, explicit update/delete/quarantine policies and server-owned property reconciliation rules.
3. Add the smallest Alembic schema for source versions, mappings, staging, run history, diagnostics
   and resumable PostgreSQL jobs. Test fresh/upgrade/downgrade/data preservation/drift in private schemas.
4. Implement CSV/Parquet/JSON connectors and narrowly authorized PostgreSQL reads. Verify external
   library APIs. Prevent arbitrary paths, SQL, network credentials or executable expressions in mappings.
5. Use explicit Polars schemas and lazy/batched transformations, canonical fixture column names,
   bounded staging, reproducible validation, strict conversion errors and reject/quarantine reporting.
6. Implement deterministic identity mapping/upserts, forward relationship materialization and partial
   batch safeguards through governed services. Establish transactional batch/snapshot boundaries and
   explicit crash/retry behavior without extending Phase 1 activation bounds silently.
7. Integrate ReconciliationService ownership/overrides/conflicts. Source refreshes must preserve
   governed edits by default, revalidate schema/revisions and never infer deletion from omitted rows.
8. Add durable PostgreSQL worker claims/leases/retries/cancellation and restart recovery. Reuse the
   outbox's at-least-once constraints where relevant; do not add a broker or distributed orchestrator.
9. Expose typed versioned source/mapping/run/diagnostic APIs with server-derived tenant/principal;
   preserve existing registry, CRUD, action, history and query behavior.
10. Materialize the canonical 6 factories, 20 machines, 12 employees, 25 tasks and expected forward
    edges; repeat with identical inputs and confirm idempotency. Test changed sources, protected edits,
    explicit conflicts/resolutions, malformed rows, FKs, partial batches and interrupted jobs.
11. Measure representative batch sizes/memory/throughput and action/query/ingestion lock contention.
    Retain ontology locking unless correctness-preserving redesign is justified by measurements.
12. Run applicable fixture/static/semantic/PostgreSQL/HTTP/Docker/lint/format/type/migration checks;
    report PASS/FAIL/NOT RUN/NOT SUPPORTED with evidence. Write Phase 4 completion report and Phase 5
    checklist, then stop. Do not implement semantic materialization, Studio, SDKs, production OIDC,
    additional databases, distributed infrastructure or Rust in the ingestion phase.
