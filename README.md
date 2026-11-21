# CSH Foundry

An open-source operational ontology platform inspired by Palantir Foundry. CSH Foundry
connects governed data, typed objects, transactional actions, pipelines and applications
in one tenant-aware platform.

The current source includes Phases 0–22, directory-based sharing, shared worker execution
and subsequent CI and worker fixes. PostgreSQL is the authoritative operational datastore;
canonical metadata stays independent of RDF/OWL. Open Ontologies is a separate semantic
engine, and Protégé is optional authoring tooling.

**Status:** implemented capabilities have local validation evidence, with limitations recorded
in the phase reports. Production release remains **BLOCKED / NOT PRODUCTION-CERTIFIED** under
[PLANS.md §23B](PLANS.md). Historical test counts and image scans describe their recorded
candidates, not certification of the current checkout.

## Current capabilities

| Area | Implemented functionality | Documentation |
| --- | --- | --- |
| Ontology management | Canonical types, properties, relationships and actions; drafts, immutable publication, separate activation, governed migrations, branches and three-way merges | [Registry API](docs/api/README.md), [branches and generated SDKs](docs/api/branching-sdk.md) |
| Operational data | Tenant-scoped objects and links, schema-aware queries, signed cursor pagination, traversal, aggregation and Object Sets | [Query API](docs/api/queries.md) |
| Governed actions | Preview, transactional execution, idempotency, history, audit, outbox delivery and property edit reconciliation | [Action API](docs/api/actions.md) |
| Ingestion and semantics | Registered CSV/Parquet/NDJSON/PostgreSQL sources, durable ingestion, RDF/OWL/SHACL compilation, exports, semantic jobs and separately approved derived facts | [Ingestion](docs/api/ingestion.md), [semantics](docs/api/semantic.md), [OWL interchange](docs/api/interchange.md) |
| Projects and data assets | Projects, folders and resource governance; immutable artifacts; versioned datasets with validation, schema history and previews | [Projects](docs/api/projects.md), [artifacts](docs/api/artifacts.md), [datasets](docs/api/datasets.md) |
| Pipelines and materialization | Visual pipeline authoring, versioned DAGs, Polars execution, pinned inputs, multiple atomically published outputs and dataset-to-ontology mapping | [Pipelines](docs/api/pipelines.md), [mappings](docs/api/mappings.md) |
| Applications and automation | Published declarative visual applications, Media Sets, trusted typed functions and durable manual/scheduled/event automations | [Applications](docs/api/applications.md), [media, functions and automations](docs/api/media-functions-automations.md) |
| Lineage and operations | Governed resource and column lineage, impact analysis, freshness policies, execution details and operational events | [Lineage](docs/development/lineage-observability.md), [observability](docs/development/execution-observability.md) |
| Identity and collaboration | OIDC/Keycloak, memberships, RBAC and restrictive ABAC, personal workspaces, explicit Project/Ontology invitations, Keycloak/LDAP recipient discovery | [Security](docs/api/security.md), [tenant sharing](docs/api/tenant-sharing.md) |
| Developer tooling | Generated ontology-specific Python/TypeScript packages, platform TypeScript SDK, React hooks and a starter application | [TypeScript SDK](packages/typescript-sdk/README.md), [React SDK](packages/react-sdk/README.md), [starter](apps/sdk-example/README.md) |

Studio is the Next.js application for Ontology Manager, object exploration, Projects,
data workflows, visual builders, lineage and sharing. All operations use the governed
FastAPI application services and current authorization checks.

## Local API quick start

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), Docker with Compose.
Studio and SDK development also require Node.js 22 or newer and npm; CI uses Node 24.
Java 17+ and Maven are needed only for the OWLAPI authoring compatibility check.
No platform Rust toolchain is required.

Run from the repository root, using a **new disposable local database**:

```bash
uv sync --frozen
cp .env.example .env
```

Edit `.env`: choose `POSTGRES_PASSWORD` and set the matching `FOUNDRY_DATABASE_URL`.
Use URL-safe password characters or URL-encode the password in the database URL. To enable
one trusted local developer, set:

```dotenv
FOUNDRY_AUTH_MODE=local
FOUNDRY_TRUSTED_LOCAL_IDENTITY=true
FOUNDRY_LOCAL_TENANT_ID=00000000-0000-0000-0000-000000000001
FOUNDRY_LOCAL_PRINCIPAL_ID=developer
```

Then initialize and run:

```bash
docker compose --env-file .env -f infrastructure/compose.yaml up -d --wait postgres
uv run alembic -c alembic.ini upgrade head
uv run python -m ontology_platform.bootstrap --name "Local manufacturing"
uv run uvicorn ontology_platform.main:create_app --factory --host 127.0.0.1
```

The API is at [localhost:8000](http://127.0.0.1:8000), with interactive docs at
[/docs](http://127.0.0.1:8000/docs) and OpenAPI at
[/api/v1/openapi.json](http://127.0.0.1:8000/api/v1/openapi.json).
`/health/live` checks liveness; `/health/ready` checks PostgreSQL and the required migration.
The current migration head is **`0030_directory_shares`**. PostgreSQL binds loopback port
55432 by default. Bootstrap provisions the configured tenant once; repeating it returns a conflict.
The default disabled authentication mode denies domain access.

Use the [manufacturing API walkthrough](docs/api/README.md#manufacturing-quick-start) to
create a draft, publish, activate and create an object. Its sample tenant UUID matches the
configuration above. The fixtures model 63 objects and 70 forward links; vocabulary includes
`machineId`, `machineName`, `operationalStatus`, `temperatureCelsius` and `locatedInFactory`.

The trusted local profile is for loopback development. For an existing or shared database,
inspect the target, back up and follow the [migration guide](docs/development/alembic-migrations.md)
and [rollout runbook](docs/operations/phase-22-okd4.md) before upgrading. Several migrations
are forward-only. API startup does not run migrations.

To run the API in a container after database initialization:

```bash
docker compose --env-file .env -f infrastructure/compose.yaml --profile api up -d --build
```

For this disposable local stack, `docker compose --env-file .env -f infrastructure/compose.yaml down`
stops services while preserving named volumes. Shared environments require targeted rollout operations.

## Studio and authenticated workspaces

Studio uses OIDC Authorization Code with PKCE and an opaque browser session cookie. Configure
a trusted broker, API token audience/client policy and platform access before using it;
the local API principal above does not provide browser login. Eligible Keycloak users can
receive a personal workspace through explicitly configured onboarding. Other identities require
provisioned access. Project and Ontology shares preserve owning-tenant authorization and
have a bounded scope; share-only authority cannot submit background jobs.

Follow [Studio setup](apps/studio/README.md), [OIDC token profiles](docs/development/oidc-token-profiles.md)
and [local Keycloak setup](docs/development/keycloak-local.md). Build the local SDK dependency
before starting Studio:

```bash
npm ci
npm run build -w @foundry/sdk
npm ci --prefix apps/studio
npm run dev --prefix apps/studio
```

Studio serves [localhost:3000](http://127.0.0.1:3000). Its server-side configuration includes
`STUDIO_ORIGIN`, `STUDIO_API_ORIGIN`, `STUDIO_OIDC_ISSUER`, `STUDIO_OIDC_CLIENT_ID` and
`STUDIO_API_AUDIENCE`. These must be supplied to the Next.js process; the repository-root
`.env` is not automatically loaded by a host Studio process.

Development can use process-local sessions. Production requires encrypted PostgreSQL-backed
browser state through the internal API, with shared secrets and encryption keys configured
as described in the [production runbook](docs/operations/production.md). Durable sessions
support multiple Studio replicas and restart continuity. API tokens remain server-side;
refresh tokens are not persisted.

## Storage and workers

Ontology-only development can leave artifact storage disabled. Artifacts, datasets, media
and pipeline outputs use the existing S3-compatible ArtifactStore. The optional development
MinIO profile uses a persistent volume and a source-built pinned image. Configure server-side
storage credentials and matching API/worker settings using the
[artifact setup guide](docs/development/artifact-storage.md) and
[development storage guide](docs/development/development-object-storage.md).

Submitting a job does not execute it in the API request. With the database, storage, source
catalog and worker authentication configured, the existing entry points are:

```bash
# Process one eligible ingestion or semantic job, respectively.
uv run python -m ontology_platform.ingestion
uv run python -m ontology_platform.semantic
# Run the execution controller, automation dispatch and idle lineage maintenance.
uv run python scripts/run_execution_worker.py
```

Ingestion and semantic commands accept an optional `--ontology` queue filter. OIDC workers
use their own verified service identity and immutable job-scoped grants; they resolve the
initiating user and owning tenant per job. They recheck both identities' current authority.
No startup tenant or ontology is required. Outbox delivery uses explicit service permissions.
See [worker entry points](services/worker/README.md),
[dynamic worker authorization](docs/operations/dynamic-workers.md) and
[execution limits](docs/development/execution-workers.md).

The semantic worker needs the pinned Open Ontologies 2.1.0 executable:

```bash
uv run python scripts/install_semantic_engine.py
uv run python scripts/semantic_smoke.py
```

The installer verifies committed SHA-256 checksums for supported macOS and Linux downloads.
Other platforms need a build of the pinned upstream source and `OPEN_ONTOLOGIES_BIN`.
See [dependency compatibility](docs/architecture/semantic-compatibility.md) and
`integrations/dependencies.json`. Semantic results and derived facts remain separate from
operational objects; approval does not mutate objects or execute actions.

## Development and validation

```bash
make lint
make typecheck
# Fixture checks without a database:
uv run pytest services/api/tests/test_fixtures.py -ra
# Python suite; configure disposable integrations for full coverage:
make test
# Platform SDKs:
npm ci
npm run build
npm run typecheck
npm test
# Studio (after SDK build and Studio dependency installation):
npm run typecheck --prefix apps/studio
npm test --prefix apps/studio
npm run build --prefix apps/studio
```

Consult [fixtures/VALIDATION.md](fixtures/VALIDATION.md) for acceptance criteria and
[the CI guide](docs/development/ci.md) for the current regression, browser, owner-role,
real PostgreSQL/MinIO/semantic-engine and extended scale profiles. The historical
`scripts/validate_phase0.py` name runs lint, types, migration drift and the current Python
suite, not just Phase 0. It uses configured database settings unless `TEST_DATABASE_URL`
is supplied; use a disposable database and prepare Node dependencies as documented in CI.

Unconfigured integration tests may skip locally: report them as **NOT RUN**, never PASS.
Raw pySHACL has a preserved strict expected failure for RDFLib string-term identity;
normalized SHACL and Open Ontologies checks are separate. The pinned base `owl-rl` profile
does not infer the fixture's CriticalMachines; `owl-rl-ext` does. Interactive Protégé and
external identity/cluster acceptance require their own executed evidence.

## Architecture, operations and roadmap

- [Architecture overview](docs/architecture/overview.md), [canonical schema](docs/architecture/canonical-schema.md) and [architectural decisions](docs/decisions/).
- [API reference index](docs/api/README.md) and [migration instructions](docs/development/alembic-migrations.md).
- [Phase 21 lineage and rollout report](docs/development/phase-21-report.md), [Phase 22 report](docs/development/phase-22-report.md) and [directory-sharing follow-up](docs/development/phase-22-ldap-recipient-search-report.md).
- [Production operations](docs/operations/production.md), [readiness gates](docs/operations/readiness.md), [OKD4 deployment](docs/operations/okd4-deployment.md) and [current sharing rollout](docs/operations/phase-22-okd4.md).
- [Roadmap and authorization history](PLANS.md). Dated reports preserve their original evidence and scope; later implementation supersedes their historical “not implemented” statements.

The backend remains a modular FastAPI/Pydantic/SQLAlchemy application, with Polars for tabular
transformations. PostgreSQL owns governance and operational transactions; optional S3 storage
holds immutable binary content. No Rust accelerator, Spark engine, arbitrary user-code execution,
Code Workspace/IDE hosting or ownership-transfer API is implemented. Target OKD4, live
organizational identity and production release gates still require separate acceptance.
