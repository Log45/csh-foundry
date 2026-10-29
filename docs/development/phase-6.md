# Phase 6 checklist — requires separate approval

Phase 6 is not implemented. Start only after explicit approval.

1. Read prior phase reports, semantic API/ADRs, fixtures/VALIDATION.md and the pinned authoring
   compatibility findings. Establish a fresh complete configured regression baseline.
2. Reinspect pinned Protégé/WebProtégé/OWLAPI source and documented file interchange contracts.
3. Implement bounded OWL imports as reviewed unpublished canonical drafts; preserve native originals,
   unsupported axioms, explicit vocabulary mapping and imported IRI conflict provenance.
4. Never infer operational actions/access policies from OWL. Never activate imports automatically.
5. Preserve deterministic semantic compilation, principal-private artifacts, tenant-safe identity,
   job fencing, source/edit ownership, existing approval/migration guards and operational authority.
6. Extend supported file round trips and negative/ambiguous import tests on real PostgreSQL.
7. Evaluate optional WebProtégé deployment only with explicit approval; no invented endpoints.
8. Run complete fixture/engine/PostgreSQL/HTTP/Docker/lint/type/migration/authoring checks, report
   exact PASS/FAIL/NOT RUN/NOT SUPPORTED evidence, then stop before Phase 7.
