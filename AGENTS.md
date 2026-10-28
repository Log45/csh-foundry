# Project Instructions

## Objective

Build an open-source operational ontology platform inspired by Palantir Foundry.

## Technology Stack

- Backend: Python, FastAPI, Pydantic v2, SQLAlchemy 2.x
- Database: PostgreSQL
- Data processing: Polars
- Semantic reasoning: Open Ontologies
- Ontology authoring: Protégé / WebProtégé
- Frontend: Next.js, TypeScript
- Optional native acceleration: Rust through PyO3
- Python package management: uv
- Database migrations: Alembic
- Testing: pytest

## Architectural Constraints

1. PostgreSQL is the authoritative operational datastore.
2. Open Ontologies is a separate semantic reasoning and governance engine.
3. Protégé is an optional ontology authoring tool, not the operational backend.
4. The canonical operational schema must remain independent of RDF/OWL.
5. All operational mutations must pass through governed application services.
6. Use PostgreSQL transactions for multi-object mutations.
7. Use Polars for tabular transformations.
8. Do not introduce Rust unless performance measurements justify it.
9. Do not introduce unnecessary microservices or additional databases.
10. Preserve modular boundaries between metadata, objects, actions, ingestion, security, and semantic reasoning.

## Development Rules

- Follow the implementation roadmap in `PLANS.md`.
- Implement only the currently approved phase.
- Inspect existing code before modifying it.
- Verify external APIs against actual source code or documentation.
- Do not invent Open Ontologies or WebProtégé API endpoints.
- Write unit and integration tests for implemented functionality.
- Run relevant tests before declaring work complete.
- Use type annotations and structured error handling.
- Document important architectural decisions.
- Do not silently introduce breaking schema changes.
- Do not commit credentials or secrets.
- Do not deploy services or modify external resources without approval.

## External Repositories

### Open Ontologies
- Repository: https://github.com/fabio-rovai/open-ontologies
- Purpose: Semantic reasoning, SHACL validation, and ontology governance.
- Integration: Use its documented API or CLI.
- Do not reimplement its reasoning engine.
- Inspect the repository before implementing the adapter.

### Protégé / WebProtégé
- Protégé: https://github.com/protegeproject/protege
- WebProtégé: https://github.com/protegeproject/webprotege
- Purpose: OWL ontology authoring and collaborative editing.
- Integration: Begin with OWL import/export.
- Do not modify or fork Protégé unless explicitly required.

## Completion Requirements

At the end of each implementation phase, report:

- Functionality implemented.
- Files created or modified.
- Database migrations.
- Tests executed and results.
- Known limitations.
- Architectural decisions.
- Recommended next phase.

Stop after completing the approved phase.

Before completing any implementation phase, consult fixtures/VALIDATION.md, execute all applicable validation checks, and report results as PASS, FAIL, NOT RUN, or NOT SUPPORTED. Do not claim successful validation for tests that were not executed.