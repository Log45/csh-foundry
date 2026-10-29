# CSH Foundry — operational ontology platform

Phase 8 native Ontology Manager and Ontology Studio for the modular platform specified in [PLANS.md](PLANS.md).
PostgreSQL owns operational state; canonical metadata is independent of RDF/OWL.
Open Ontologies supplies external semantic checks. Protégé is optional authoring tooling.
Phases 0–5 provide governed schema publication/activation, tenant-scoped objects/links and a
schema-aware SQL query engine with projection, keyset pagination, traversal, aggregates and internal
Object Sets, transactional actions, previews, durable idempotency/history/audit/outbox, bounded
webhook delivery, property edit reconciliation and durable governed CSV/Parquet/NDJSON/PostgreSQL
ingestion, deterministic RDF/OWL/SHACL compilation, governed RDF exports, durable semantic jobs
and separately approved derived facts. Phase 6 adds explicit Turtle/RDF/XML authoring imports into
unpublished canonical drafts, source preservation, diagnostics, IRI conflicts and deterministic exports.
Phase 7 adds verified OIDC access tokens, platform tenant membership, RBAC, restrictive SQL ABAC,
security administration/audit and delegated service workers. Subsequent roadmap phases are not implemented.

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

This development environment is local-only. Domain endpoints deny access by default. To enable
one explicitly trusted local principal, configure these variables in `.env` or export them for
each host command (use your own tenant UUID if the sample tenant is inappropriate):

```bash
export FOUNDRY_TRUSTED_LOCAL_IDENTITY=true
export FOUNDRY_LOCAL_TENANT_ID=00000000-0000-0000-0000-000000000001
export FOUNDRY_LOCAL_PRINCIPAL_ID=developer
uv run python -m ontology_platform.bootstrap --name "Local manufacturing"
uv run uvicorn ontology_platform.main:create_app --factory --host 127.0.0.1
```

Bootstrap runs once and provisions only that configured tenant. Repeating provisioning returns
an explicit conflict. Every operational request uses the server-configured principal; client
headers cannot select a tenant. Compose forwards the same variables to the API container.
This is a trusted local administration mechanism. For verified production identities use
[the Phase 7 security configuration and API](docs/api/security.md). Keep this instance on loopback. See [the persistence API](docs/api/README.md) for the
create → draft → publish → activate → CRUD workflow and approved migration plans.

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

The existing `validate_phase0.py` command now runs the entire current suite, including Phase 4.
The validation script requires a migrated disposable PostgreSQL database and the pinned
engine; it uses `.env` by default or `TEST_DATABASE_URL`. Never point migration downgrade
checks manually at a database with valuable data. Phase 1 integration tests create and drop
unique PostgreSQL schemas and run upgrade/downgrade checks only inside those test schemas. `uv run pytest -ra` alone explicitly skips
unconfigured PostgreSQL/engine tests; skips are NOT RUN, never PASS. CI configures both.
The raw pySHACL compatibility test is a strict expected failure, reported separately;
Open Ontologies validates the unchanged fixtures. The normalized pySHACL check and nine
negative cases test RDF 1.1 string-term normalization in memory. See the compatibility report.

`make lint`, `make typecheck`, and `make test` are shortcuts. Application source has strict
mypy checks. API and schema packages are separate uv workspace members. Reserved directories
record later phase boundaries; the Next.js app is in `apps/studio`; no native extension is implemented.
A bounded PostgreSQL ingestion worker is available through the API package CLI.
A bounded outbox delivery runner is included; production scheduling is deferred.

## Architecture and next work

- [Architecture](docs/architecture/overview.md) and [canonical contracts](docs/architecture/canonical-schema.md).
- [Dependency/semantic compatibility](docs/architecture/semantic-compatibility.md).
- [Phase 0 report](docs/development/phase-0-report.md).
- [Architecture decisions](docs/decisions/) and [API contract](docs/api/README.md).
- [Phase 1 report](docs/development/phase-1-report.md), [Phase 2 report](docs/development/phase-2-report.md),
  and [query API](docs/api/queries.md).
- [Phase 3 report](docs/development/phase-3-report.md), [action API](docs/api/actions.md),
  [Phase 4 report](docs/development/phase-4-report.md), [ingestion API](docs/api/ingestion.md),
  and [Phase 5 report](docs/development/phase-5-report.md); [Phase 6 report](docs/development/phase-6-report.md) and [interchange API](docs/api/interchange.md).

Canonical fixtures are preserved. Section 24 of PLANS.md uses conceptual shorthand;
examples/tests use actual `machineId`, `machineName`, `operationalStatus`,
`temperatureCelsius`, `locatedInFactory` and the other supplied vocabulary.
Stop development services with `docker compose --env-file .env -f infrastructure/compose.yaml down`.
This preserves the PostgreSQL named volume.

## Query development

Query documentation and manufacturing examples are in [docs/api/queries.md](docs/api/queries.md).
New endpoints live under `/api/v1/ontologies/{ontology}`: `/objects/{type}/query`,
`/object-sets/query`, `/traverse`, `/aggregate`. Existing CRUD routes remain available.
Set optional `FOUNDRY_QUERY_CURSOR_SECRET` to a random secret of at least 32 UTF-8 bytes for
cursor validity across API restarts/processes; otherwise a process-local key is generated.
Never commit a real key. Cursor pagination is not a historical snapshot.

Run `uv run python scripts/benchmark_queries.py` for isolated PostgreSQL measurements. This
creates/drops a random test schema and synthetic data through governed services, records plans
under `docs/architecture/evidence/phase-2/`, and never modifies operational tenant data. It is
a developer benchmark, not an ingestion implementation or production performance guarantee.

## Governed actions and edit ownership

Include the definitions in `ontologies/examples/manufacturing-actions.json` in an approved ontology
draft, then use the registry's publish/activate workflow. The action API supports preview, execute
with required idempotency keys, history and redacted audit. See [actions](docs/api/actions.md) for
contracts, permissions, three-second/64 KiB limits, retry semantics and webhook configuration.
Direct CRUD and action edits record property ownership; future source updates preserve governed
edits by default through ReconciliationService. Bounded ingestion is implemented in Phase 4;
production identity, scheduling and workload admission remain deferred.

`uv run python scripts/benchmark_actions.py` and `uv run python scripts/smoke_actions.py` use
disposable PostgreSQL schemas. `uv run python scripts/smoke_action_container.py` checks the built
`csh-foundry-phase3` image with identity disabled and does not mutate operational data.

## Governed ingestion

Configure tenant-owned server registrations with `FOUNDRY_INGESTION_CATALOG_JSON` (secret server
configuration), publish source/mapping versions and submit durable ingestion runs. No client request
can provide a path, SQL or credentials. Run one eligible job with:

```bash
uv run python -m ontology_platform.ingestion --ontology manufacturing
uv run python -m ontology_platform.ingestion --ontology manufacturing --cleanup-days 7
```

See [ingestion contracts](docs/api/ingestion.md) for connector configuration, null/conversion rules,
atomicity, source/edit ownership, quotas, retries, cancellation and explicit staging maintenance.
Use `scripts/smoke_ingestion.py`, `scripts/benchmark_ingestion.py` and
`scripts/smoke_ingestion_container.py` for reproducible HTTP, private-schema workload and final-image
checks. The canonical fixture workflow produces 63 objects and 70 forward links; unchanged repeats
do not increment revisions. Full production orchestration/security is not claimed.


## Semantic compilation and jobs

See [the semantic API](docs/api/semantic.md) and [Phase 5 report](docs/development/phase-5-report.md).
Compile published metadata, export authorized bounded query selections, then submit validation,
reasoning or native graph-diff jobs. Run a separate worker under the initiating configured principal:

```bash
uv run python -m ontology_platform.semantic --ontology manufacturing
```

Artifacts, reports, proofs and derived facts remain separate from operational state. Reading results
rechecks input permissions and freshness. Set-level approval appends audit history and never updates
objects/relationships or triggers actions. Open Ontologies remains pinned at 2.1.0; certificates are
generated but independent Lean proof checking is NOT RUN on this host. The raw pySHACL mismatch and
base owl-rl fixture limitation remain.

## Optional Protégé file authoring

See [interchange API](docs/api/interchange.md). Select explicit class/property/link IRIs and canonical
constraint definitions, preview the import, then request CREATE_DRAFT. Original semantic axioms stay
private and downloadable; publication and activation use separate existing registry APIs. No Protégé
application or WebProtégé deployment is required. Turtle and RDF/XML are supported; OWL/XML is not.
Run `uv run python scripts/smoke_semantic.py --interchange` for the actual local HTTP import plus
semantic workflow, and `scripts/smoke_semantic_container.py --interchange` for the Phase 6 image smoke.
Phase 7 security is documented in [security.md](docs/api/security.md); Phase 8 browser integration is documented below.


## Production authentication and authorization

Read [the security API and configuration](docs/api/security.md) before exposing domain endpoints.
Set `FOUNDRY_AUTH_MODE=oidc`, configure trusted providers/audience/client allowlists, disable local
identity, migrate to `0013_security`, and explicitly provision the first administrator through
`python -m ontology_platform.security.bootstrap`. Only the documented JWT API access-token profile
is supported. Unknown identities receive no membership or administrator role. Use Authorization
Bearer tokens and, for multi-tenant users, an authorized X-Tenant-ID selection.

RBAC and restrictive ABAC extend the existing governed service and SQL grant interfaces. Security
administration, policy versions, revocation, audit and worker delegation use PostgreSQL. Workers need
service credentials plus current explicit delegation and both identities' permissions. See the
[Phase 7 report](docs/development/phase-7-report.md) for validation and limitations. Phase 8 adds the Studio UI; no
production deployment is included; Phase 10 operational hardening remains separate work.

## Native Ontology Manager and Ontology Studio (Phase 8)

`apps/studio` now contains a single Next.js/React/TypeScript application. Use Node >=22 and follow
[Studio setup](apps/studio/README.md) for the server-side OIDC client, API audience and local runtime.
Configure Phase 7 OIDC and explicit platform memberships first. The browser stores an opaque session
cookie; FastAPI still verifies the API access token and applies current RBAC/ABAC on every operation.
Live Microsoft/Google sign-in remains deferred. Local deterministic OIDC exists only in test tooling.

Manager edits the canonical registry through a native graph, type/property/relationship editors,
action declarations, drafts, compatibility, version history, separate publication/activation and OWL
mapping diagnostics. Studio explores authorized objects and queries, traverses relationships,
previews/executes governed actions and manages ingestion and semantic jobs/results. Workers remain
separate. Complex developer contracts use labeled JSON editors. No Phase 9 SDK or branching is added.

```
cd apps/studio
npm ci
npm run dev
```

For container development use `docker compose --env-file .env -f infrastructure/compose.yaml
--profile studio up --build` (one command). See [the Phase 8 API checklist](docs/development/phase-8.md),
[browser architecture](docs/decisions/0029-browser-session-and-studio.md) and completion report.

The existing local Keycloak connection and certificate configuration are documented in
[local Keycloak setup](docs/development/keycloak-local.md). Its public CA is mounted read-only into
API/Studio through the normal Compose configuration; private keys remain in ignored local artifacts.
