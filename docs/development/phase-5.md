# Phase 5 checklist — implemented within documented bounds

Phase 5 was explicitly approved and implemented. See [the completion report](phase-5-report.md)
for executed evidence, scope and limitations. The original checklist is retained below.

1. Read AGENTS.md, PLANS.md, fixtures/VALIDATION.md, Phase 4 report/API/ADRs and the semantic
   compatibility report. Run the complete configured Phase 0–4 baseline, preserving the raw pySHACL
   expected failure and base owl-rl profile limitation.
2. Reinspect the pinned Open Ontologies source/CLI contracts, features/licenses and engine pins.
   Do not invent endpoints, reimplement reasoning or change dependencies speculatively.
3. Define typed, versioned semantic artifact/job/result contracts with tenant/principal ownership,
   schema version, source/run references, input hashes, engine/compiler version and provenance.
4. Implement deterministic canonical-schema → supported RDF/OWL and SHACL compilation, reusing the
   established stable operational identity/IRI mapping. Report unsupported constructs explicitly.
5. Export authorized operational datasets with property/row restrictions through governed interfaces.
   Do not expose unrestricted global SPARQL or make semantic outputs an authorization bypass.
6. Add the smallest tenant-safe Alembic schema for artifact manifests, validation/reasoning jobs,
   reports and separately stored derived facts. Test upgrades/downgrades/drift/data preservation.
7. Run reasoning/SHACL through the replaceable pinned adapter in durable PostgreSQL jobs, reusing
   appropriate fencing/retry/cancellation/checkpoint patterns. Keep expensive work outside handlers.
8. Exercise parsing, raw SHACL, negative diagnostics and owl-rl-ext CriticalMachine inference
   independently; preserve unsupported-profile findings and sanitized timeout/unavailability handling.
9. Store asserted and inferred facts separately with input/engine/rule provenance and approval state.
   Never silently overwrite authoritative operational source/user/action properties with inference.
10. Add semantic change analysis and proof generation/verification only where the pinned engine
    actually supports the required workflow; report NOT SUPPORTED/NOT RUN precisely where applicable.
11. Expose typed governed artifact/job/report APIs and test cross-tenant/property/inference boundaries,
    stale schemas, restart recovery, partial failures, reproducibility and stable export graph equality.
12. Measure bounded export/reasoning workloads, resource use and query/action/ingestion contention.
    Retain existing operational invariants and locking unless measurements justify a reviewed change.
13. Execute all applicable fixture/PostgreSQL/semantic/HTTP/Docker/lint/type/migration/Protégé
    regressions. Produce the Phase 5 report and Phase 6 checklist, then stop for approval.

Do not expand Protégé/WebProtégé authoring, implement production OIDC/RBAC/ABAC, Studio, generated
SDKs, Rust acceleration, extra operational databases, a broker or distributed infrastructure here.
