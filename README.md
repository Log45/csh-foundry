# CSH Foundry — operational ontology platform

Phase 0 foundation for the modular platform specified in [PLANS.md](PLANS.md).
PostgreSQL owns operational state; canonical metadata is independent of RDF/OWL.
Open Ontologies supplies external semantic checks. Protégé is optional authoring tooling.
Only the Phase 0 scaffold, contracts and compatibility experiments are implemented.

## Local setup

Requirements: uv (tested 0.7.11; CI/container pinned 0.9.5), Python 3.12, Docker with Compose.
For the authoring compatibility check: Java 17+ and Maven. No local Rust toolchain is required.

```bash
uv sync --frozen
cp .env.example .env
# Choose POSTGRES_PASSWORD and set the matching FOUNDRY_DATABASE_URL in .env.
# Use URL-safe password characters or URL-encode them in the SQLAlchemy URL.
docker compose --env-file .env -f infrastructure/compose.yaml up -d --wait postgres
uv run alembic upgrade head
uv run uvicorn ontology_platform.main:create_app --factory --host 127.0.0.1
```

The API serves `/health/live`, `/health/ready`, `/docs` and `/api/v1/openapi.json` on port
8000. Readiness requires the database and current migration. The database binds loopback
port 55432 by default. `.env` is ignored; no database password is committed.
To run the API in Compose instead of on the host:

```bash
docker compose --env-file .env -f infrastructure/compose.yaml --profile api up -d --build
```

This development environment is local-only. There are no operational data endpoints yet.
Future protected routes fail closed by default; a trusted local identity requires explicit
server configuration of tenant and principal IDs. This is not OIDC or production authorization.

## Validation

```bash
uv run python scripts/install_semantic_engine.py
uv run python scripts/validate_phase0.py
uv run python scripts/semantic_smoke.py
mvn -q -f integrations/protege/pom.xml compile exec:java \
  '-Dexec.args=fixtures/manufacturing.ttl artifacts/manufacturing.owl'
```

The installer checks v2.1.0 release bytes against committed SHA256 sums. macOS ARM64/x86_64
and Linux x86_64 downloads are supported. For other hosts build the pinned source with
`cargo build --locked --release` and set `OPEN_ONTOLOGIES_BIN` (required features for the
exercised RDF/SHACL/reasoning commands: none). This builds an upstream dependency, not a
platform Rust accelerator. Source pins and licenses are in `integrations/dependencies.json`.

The validation script requires a migrated disposable PostgreSQL database and the pinned
engine; it uses `.env` by default or `TEST_DATABASE_URL`. Never point migration downgrade
checks at a database with valuable data. `uv run pytest -ra` alone explicitly skips
unconfigured PostgreSQL/engine tests; skips are NOT RUN, never PASS. CI configures both.
The raw pySHACL compatibility test is a strict expected failure, reported separately;
Open Ontologies validates the unchanged fixtures. The normalized pySHACL check and nine
negative cases test RDF 1.1 string-term normalization in memory. See the compatibility report.

`make lint`, `make typecheck`, and `make test` are shortcuts. Application source has strict
mypy checks. API and schema packages are separate uv workspace members. Reserved directories
record later phase boundaries; no Next.js app, worker or native extension is implemented.

## Architecture and next work

- [Architecture](docs/architecture/overview.md) and [canonical contracts](docs/architecture/canonical-schema.md).
- [Dependency/semantic compatibility](docs/architecture/semantic-compatibility.md).
- [Phase 0 report](docs/development/phase-0-report.md).
- [Architecture decisions](docs/decisions/) and [API contract](docs/api/README.md).
- [Phase 1 checklist](docs/development/phase-1.md), requiring separate approval.

Canonical fixtures are preserved. Section 24 of PLANS.md uses conceptual shorthand;
examples/tests use actual `machineId`, `machineName`, `operationalStatus`,
`temperatureCelsius`, `locatedInFactory` and the other supplied vocabulary.
Stop development services with `docker compose --env-file .env -f infrastructure/compose.yaml down`.
This preserves the PostgreSQL named volume.
