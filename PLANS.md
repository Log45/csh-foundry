# Open-Source Operational Ontology Platform

## Architecture, Implementation Roadmap, and Coding Agent Specification

**Project status:** Phases 0–9 implemented within documented completion-report boundaries; Phase 10 requires separate approval

**Document version:** 1.2 (Codex-ready; provider-independent SSO roadmap)

**Primary language:** Python

**Optional performance language:** Rust

**Primary database:** PostgreSQL

**Semantic engine:** Open Ontologies

**Ontology authoring:** Native Ontology Manager; optional Protégé / WebProtégé interoperability

**API framework:** FastAPI

**Data processing:** Polars

**Frontend:** Next.js / TypeScript

---

# 1. Project Objective

Build an open-source, ontology-driven data and application platform inspired by Palantir Foundry.

The platform must allow developers to:

1. Define operational object types, properties, and relationships.

2. Connect external datasets to those object types.

3. Materialize source data into queryable operational objects.

4. Query, filter, aggregate, and traverse objects through typed APIs.

5. Define and execute governed actions that modify operational state.

6. Enforce ontology-level, object-level, property-level, and action-level permissions.

7. Maintain ontology versions and safely evolve schemas.

8. Use semantic reasoning to derive knowledge and validate ontology changes.

9. Import and export RDF/OWL ontologies created with Protégé.

10. Generate typed Python and TypeScript SDKs.

11. Support applications, workflows, and AI agents that interact with the ontology.

12. Scale independently where performance measurements justify additional infrastructure.

The project must prioritize correctness, maintainability, extensibility, and developer experience over premature optimization.

## 1.1 Architectural principles

- PostgreSQL is the authoritative operational datastore.

- The canonical operational schema is maintained independently of OWL.

- RDF/OWL is a semantic representation, not the authoritative transactional database.

- Open Ontologies is an external semantic engine, not the operational object backend.

- Protégé is an optional advanced ontology authoring environment.

- All operational mutations pass through governed APIs.

- Business actions must execute atomically when modifying data within PostgreSQL.

- External side effects must use durable, retryable workflows.

- Authorization must be enforced in the backend, never only in the frontend.

- Authentication must be provider-independent: external OIDC sign-in establishes identity; PostgreSQL-backed tenant membership, RBAC, and ABAC remain authoritative for platform access.

- Browser sessions and external identity-provider tokens must never weaken FastAPI access-token verification. Microsoft/Google SSO is a planned integration, not a prerequisite for Phase 8.

- Expensive ingestion and reasoning tasks must run outside request handlers.

- Rust is introduced only for workloads where it offers a demonstrated benefit.

- Each major subsystem must expose stable interfaces and have automated tests.

- The initial deployment should be runnable locally through Docker Compose.

## 1.2 Non-goals for the initial release

Do not attempt to implement:

- A new relational or graph database.

- A general-purpose OWL reasoner.

- A replacement for Protégé.

- A distributed SQL query engine.

- A full visual data pipeline builder.

- A general-purpose distributed workflow orchestrator.

- Arbitrary Python execution inside the API server.

- Real-time collaborative ontology editing.

- Full compatibility with Palantir Foundry APIs.

- A complete multi-region distributed architecture.

These may be evaluated in later releases.

---

## 1.3 Required reference files and authoritative naming

The following repository files are canonical integration-test inputs and must be preserved:
```text
AGENTS.md
PLANS.md
fixtures/
  VALIDATION.md
  manufacturing.ttl
  manufacturing-shapes.ttl
  manufacturing-data.ttl
  factories.csv
  machines.csv
  employees.csv
  maintenance_tasks.csv
```

`fixtures/manufacturing.ttl` is the authoritative reference for **sample ontology vocabulary**, not for the platform's general internal naming conventions. In particular, its `Machine` properties are `machineId`, `machineName`, `operationalStatus`, and `temperatureCelsius`. The example CSV columns use the same names. Do not silently replace them with `id`, `name`, `status`, or `temperature` in fixture-specific mappings. The `Machine`→`Factory` relationship is `locatedInFactory`, with inverse `containsMachine`.

The plan's conceptual diagrams may use shortened names, but executable fixtures, mapping configurations, and integration tests must use the actual vocabulary. If an example conflicts with a fixture, correct the example and record the discrepancy rather than altering a valid fixture to fit it.

---

# 2. Technology Stack

## 2.1 Required technologies

\| Layer | Technology | Responsibility |

\|---|---|---|

\| Frontend | Next.js, TypeScript | Ontology Studio and object exploration |

\| Backend | Python, FastAPI | Application APIs and orchestration |

\| Database | PostgreSQL | Operational objects, metadata, transactions |

\| ORM / SQL | SQLAlchemy 2.x, Alembic | Database access and migrations |

\| Validation | Pydantic v2 | API and schema validation |

\| Dataframes | Polars | Data ingestion and transformations |

\| Semantic engine | Open Ontologies | Reasoning, SHACL, semantic governance |

\| OWL authoring | Protégé / WebProtégé | Advanced semantic modeling |

\| Background jobs | PostgreSQL-backed jobs initially | Ingestion, validation, reconciliation |

\| Authentication | OpenID Connect; provider-independent browser sessions | Verified user identity, future Microsoft/Google SSO |

\| Testing | pytest, pytest-asyncio | Python automated testing |

\| Integration testing | Testcontainers or Docker Compose | Real database and service testing |

\| API documentation | OpenAPI | Machine-readable API contracts |

\| Packaging | uv | Python dependencies and environments |

\| Containerization | Docker Compose | Local development and deployment |

## 2.2 Recommended additional technologies

These are recommendations, not mandatory dependencies for the first milestone.

\| Technology | Purpose | Adoption stage |

\|---|---|---|

\| Keycloak or equivalent OIDC broker | Optional replaceable identity broker for Microsoft, Google, and enterprise SSO | Phase 10 integration; evaluate in Phase 8 |

\| OPA | Centralized authorization policy evaluation | Security milestone |

\| Redis | Caching, coordination, rate limiting | Only when justified |

\| MinIO / S3 | Raw datasets, artifacts, exports | Ingestion milestone |

\| DuckDB | Local analytical SQL over files | Optional ingestion enhancement |

\| PyArrow | Arrow interoperability | When required by connectors |

\| OpenTelemetry | Tracing and metrics | Production hardening |

\| Prometheus / Grafana | Monitoring | Production hardening |

\| PyO3 / Maturin | Rust extensions for Python | Performance milestone |

\| Ruff | Python linting and formatting | Initial setup |

\| mypy or Pyright | Static type checking | Initial setup |

\| GitHub Actions | Continuous integration | Initial setup |

Do not introduce Kafka, Kubernetes, Elasticsearch, Neo4j, or a distributed task queue until there is a demonstrated requirement.

---

# 3. High-Level Architecture
```text
                          USERS / DEVELOPERS
                                  |
                                  v
                     +------------------------+
                     \|     Next.js Studio     |
                     \|                        |
                     \| Ontology Manager       |
                     \| Object Explorer        |
                     \| Action Builder         |
                     \| Data Source Manager    |
                     \| SDK / API Explorer     |
                     +-----------+------------+
                                 |
                                 v
                     +------------------------+
                     \|      FastAPI API       |
                     \|                        |
                     \| Authentication         |
                     \| Authorization          |
                     \| Schema Registry        |
                     \| Object Query API       |
                     \| Action Engine          |
                     \| Data Source APIs       |
                     \| Semantic API           |
                     +-----------+------------+
                                 |
               +-----------------+-----------------+
               \|                 |                 |
               v                 v                 v
       +---------------+ +---------------+ +----------------+
       \| PostgreSQL    | | Job Workers   | | Semantic       |
       \|               | |               | | Adapter        |
       \| Metadata      | | Polars        | |                |
       \| Objects       | | Ingestion     | | Open Ontologies|
       \| Links         | | Validation    | | RDF / OWL      |
       \| Edits         | | Reconciliation| | SHACL          |
       \| Audit         | | Exports       | | Reasoning      |
       +---------------+ +---------------+ +----------------+
               ^                                  ^
               \|                                  |
               \|                           +------+-------+
               \|                           |  WebProtégé  |
               \|                           |  OWL Author  |
               \|                           +--------------+
               |
       +------------------+
       \| Optional Rust    |
       \|                  |
       \| PyO3 extensions  |
       \| Materialization  |
       \| Graph processing |
       +------------------+
```

## 3.1 Service boundaries

Implement the initial system as a modular Python application.

The following modules must have explicit interfaces:

1. Ontology metadata.

2. Operational object storage.

3. Object query service.

4. Action execution.

5. Authorization.

6. Data ingestion.

7. Semantic engine integration.

8. Ontology versioning.

9. SDK generation.

10. Background job execution.

Modules must not directly access each other's private persistence implementation.

Use service interfaces and dependency injection where appropriate.

Avoid splitting the application into many independently deployed microservices during the initial release.

---

# 4. Repository Structure

Create the following monorepo:
```text
ontology-platform/
|
├── apps/
│   └── studio/
│       ├── app/
│       ├── components/
│       ├── features/
│       ├── lib/
│       └── tests/
│
├── services/
│   ├── api/
│   │   ├── pyproject.toml
│   │   ├── src/
│   │   │   └── ontology_platform/
│   │   │       ├── main.py
│   │   │       ├── config.py
│   │   │       ├── dependencies.py
│   │   │       ├── api/
│   │   │       │   └── v1/
│   │   │       ├── auth/
│   │   │       ├── metadata/
│   │   │       ├── objects/
│   │   │       ├── queries/
│   │   │       ├── actions/
│   │   │       ├── edits/
│   │   │       ├── security/
│   │   │       ├── ingestion/
│   │   │       ├── semantic/
│   │   │       ├── branching/
│   │   │       ├── sdk/
│   │   │       ├── jobs/
│   │   │       ├── audit/
│   │   │       └── db/
│   │   ├── migrations/
│   │   └── tests/
│   │
│   └── worker/
│       ├── src/
│       └── tests/
│
├── packages/
│   ├── ontology-schema/
│   ├── ontology-compiler/
│   ├── python-sdk/
│   ├── typescript-sdk/
│   └── sdk-generator/
│
├── rust/
│   └── ontology-accelerators/
│       ├── Cargo.toml
│       └── src/
│
├── integrations/
│   ├── open-ontologies/
│   ├── protege/
│   └── connectors/
│
├── ontologies/
│   ├── examples/
│   └── schemas/
│
├── infrastructure/
│   ├── docker/
│   ├── compose.yaml
│   └── monitoring/
│
├── docs/
│   ├── architecture/
│   ├── api/
│   ├── decisions/
│   └── development/
│
├── scripts/
├── .github/workflows/
├── Makefile
└── README.md
```

The coding agent may refine internal paths, but should preserve the separation of responsibilities.

---

# 5. Canonical Ontology Schema

## 5.1 Objective

Create a canonical operational ontology representation that is independent of both PostgreSQL and RDF/OWL.

This representation must be the contract between:

- The schema registry.

- Operational object storage.

- API generation.

- SDK generation.

- The semantic compiler.

- The frontend Ontology Studio.

## 5.2 Required ontology concepts

Implement the following definitions:
```python
class OntologyDefinition:
    id: str
    name: str
    namespace: str
    version: str
    object_types: list["ObjectTypeDefinition"]
    link_types: list["LinkTypeDefinition"]
    action_types: list["ActionTypeDefinition"]
```
```python
class ObjectTypeDefinition:
    id: str
    name: str
    description: str | None
    properties: list["PropertyDefinition"]
    primary_key: str
```
```python
class PropertyDefinition:
    id: str
    name: str
    data_type: str
    required: bool
    nullable: bool
    indexed: bool
    default: object | None
```
```python
class LinkTypeDefinition:
    id: str
    name: str
    source_type: str
    target_type: str
    cardinality: str
    inverse_name: str | None
```
```python
class ActionTypeDefinition:
    id: str
    name: str
    parameters: list["ParameterDefinition"]
    operations: list["ActionOperation"]
```

These examples describe the required concepts, not the final complete Pydantic implementation.

The final models must include validation and explicit versioning.

## 5.3 Supported property types

Initially support:

- String.

- Integer.

- Float.

- Boolean.

- Date.

- Timestamp.

- UUID.

- Decimal.

- JSON.

- Arrays of supported scalar types.

Define explicit rules for:

- Nullability.

- Default values.

- Numeric precision.

- Time zones.

- String lengths.

- Enumerated values.

- Uniqueness.

- Indexing.

- Type compatibility.

Do not silently coerce invalid values.

## 5.4 Identity

Each operational object must have:

- A stable object type identifier.

- A stable primary key.

- An ontology identifier.

- A version number.

- Creation and update timestamps.

Object identity must remain stable across ingestion runs.

## 5.5 Schema compilation

Implement a compiler that produces:

1. Operational schema metadata.

2. RDF/OWL class and property definitions.

3. SHACL validation shapes.

4. Python SDK models.

5. TypeScript SDK models.

6. JSON Schema or OpenAPI-compatible representations.

The compiler must clearly distinguish between:

- Concepts that can be represented in OWL.

- Operational concepts that cannot be represented in OWL.

- Semantic concepts imported from OWL that cannot be represented operationally.

Unsupported constructs must generate diagnostics rather than being silently discarded.

## 5.6 Acceptance criteria

- An ontology can be defined in JSON or YAML.

- Definitions are validated using Pydantic.

- Invalid references between types are rejected.

- Duplicate identifiers are rejected.

- An ontology can be compiled into RDF/OWL.

- The same ontology can be compiled into SHACL.

- Generated output is deterministic.

- Round-trip serialization preserves supported definitions.

---

## 5.7 Operational identity and RDF IRI mapping

Define a deterministic, versioned mapping between operational object identities and RDF individual IRIs **before** implementing the semantic compiler.

- Operational identity is `(tenant_id, ontology_id, object_type_id, object_id)`; identifiers are immutable and never derived from mutable display labels.
- Each ontology has a stable namespace/base IRI. Generate RDF individual IRIs by a documented, collision-resistant encoding of the complete operational identity. Percent-encode or otherwise safely encode reserved characters; never concatenate raw user input into an IRI.
- Maintain a mapping registry for imported external IRIs, including the original IRI, canonical operational identity, source/provenance, and conflict status.
- Define how imported individuals with duplicate IRIs, duplicate business keys, or conflicting classes are rejected or reviewed. Do not silently merge unrelated individuals.
- Export the same operational object to the same IRI across repeated exports, schema versions, and ingestion runs, unless an explicit migration changes identity.
- Distinguish RDF class/property IRIs from individual IRIs. Keep `owl:sameAs` assertions separate from operational identity merges; never treat an `owl:sameAs` statement as authorization to merge database records.
- Treat tenant isolation as an identity and export boundary. A semantic export must not include other tenants' data.
- Record IRI mapping version, namespace, and provenance in exported artifacts.

**Acceptance criteria:** Deterministic operational→IRI→operational round trips; no collisions for differing tenants/types/IDs; preservation of imported IRIs where configured; stable export after schema publication; and explicit diagnostics for ambiguous mappings.

---

# 6. PostgreSQL Data Model

## 6.1 Objective

Implement a flexible operational object backend using PostgreSQL.

Use JSONB for dynamic object properties and relational tables for identity, relationships, transactions, and governance metadata.

## 6.2 Initial tables

Create tables for:

### Ontology metadata
```text
ontologies
ontology_versions
ontology_branches
object_type_definitions
property_definitions
link_type_definitions
action_type_definitions
schema_migrations
```

### Operational objects
```text
objects
object_links
object_edits
object_edit_history
```

### Ingestion
```text
data_sources
data_source_versions
data_mappings
ingestion_runs
ingestion_errors
source_object_state
```

### Actions and audit
```text
action_executions
audit_events
outbox_events
```

### Security
```text
principals
groups
group_memberships
policy_definitions
policy_bindings
```

### Background jobs
```text
jobs
job_attempts
```

Not every table needs to be implemented in the first milestone.

## 6.3 Object storage

Use a logical schema equivalent to:
```sql
CREATE TABLE objects (
    tenant_id UUID NOT NULL,
    ontology_id UUID NOT NULL,
    object_type_id UUID NOT NULL,
    object_id TEXT NOT NULL,
    properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    version BIGINT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (
        tenant_id,
        ontology_id,
        object_type_id,
        object_id
    )
);
```

Additional foreign keys and indexes must be defined in the actual migration.

The object ID must not be generated from a mutable display name.

## 6.4 Relationships

Create an `object_links` table containing:
```text
tenant_id
ontology_id
link_type_id
source_object_type_id
source_object_id
target_object_type_id
target_object_id
created_at
updated_at
```

Enforce endpoint existence and cardinality in the transactional service layer, with database constraints wherever feasible.

Use composite foreign keys or a suitable identity registry to preserve referential integrity.

## 6.5 Indexing strategy

Initially use:

- B-tree indexes for object identity.

- B-tree indexes for link traversal.

- GIN indexes for selected JSONB query patterns.

- Expression indexes for frequently queried properties.

Do not create a GIN index on every JSONB column automatically.

Introduce an index registry so property definitions can request indexes.

Support safe index creation and removal as background schema operations.

## 6.6 Concurrency

Use optimistic concurrency for object updates.

Each mutation must verify the expected object version.

On a version mismatch, return a structured conflict response.

Use PostgreSQL transactions for multi-object actions.

## 6.7 Acceptance criteria

- Objects can be created, retrieved, updated, and deleted.

- Object properties are validated against published schemas.

- Relationships cannot reference nonexistent objects.

- Object versions increase after successful mutations.

- Conflicting updates are rejected.

- Multi-object transactions roll back completely on failure.

- Indexes can be created for selected properties.

- Database migrations run successfully from a clean installation.

---

## 6.8 Tenant-aware persistence from the first migration

Tenant isolation is a **Phase 1 persistence requirement**, not a Phase 7 retrofit.

- Create a `tenants` table and associate each ontology, schema version, operational object, link, source mapping, job, and audit event with its owning tenant (directly or via enforceable relational ownership).
- Include `tenant_id` in object identity and appropriate unique keys, foreign keys, and indexes. The example schema above is a logical starting point; actual migrations must define composite tenant-safe foreign keys and consistent ontology ownership.
- Explicitly resolve tenant context for every service operation. No API, background job, query, action, or semantic export may fall back to an unrestricted cross-tenant context.
- Reject cross-tenant links and writes. Cross-tenant sharing is out of scope for the MVP.
- Provide a single-tenant local-development bootstrap **without** removing tenant boundaries from persistence.
- Introduce authentication/authorization service interfaces in Phase 0. Full OIDC and fine-grained RBAC/ABAC remain Phase 7 deliverables; until then, only explicitly configured trusted local-development identities may access the service. Do not deploy an unauthenticated multi-tenant instance.
- Test cross-tenant reads, writes, joins, link traversal, counts, and background jobs starting in Phase 1.

---

# 7. Ontology Metadata Service

## 7.1 Objective

Provide APIs for creating, validating, publishing, and evolving ontology definitions.

## 7.2 Required capabilities

Implement:

- Create ontology.

- List ontologies.

- Retrieve ontology.

- Create object type.

- Update object type.

- Delete object type.

- Define properties.

- Define link types.

- Define action types.

- Validate schema.

- Publish schema version.

- Compare schema versions.

- Retrieve schema history.

## 7.3 Draft and published schemas

A schema must have a lifecycle:
```text
DRAFT
  |
  v
VALIDATING
  |
  v
PUBLISHED
  |
  v
DEPRECATED
```

Published schema versions must be immutable.

Changes to a published schema must create a new draft version.

## 7.4 Schema migrations

Implement schema-change classification:

**Additive changes**

Examples:

- Add optional property.

- Add object type.

- Add link type.

**Potentially breaking changes**

Examples:

- Remove property.

- Change property type.

- Change primary key.

- Tighten required constraints.

- Remove object type.

Breaking changes must require a migration plan.

Do not automatically delete operational data when a schema definition is removed.

## 7.5 Acceptance criteria

- Published schemas cannot be modified in place.

- Schema changes are classified.

- Breaking changes cannot be published without an approved migration plan.

- Schema versions can be compared.

- Existing objects remain valid or are explicitly migrated.

---

## 7.6 Active schema and publication semantics

For the MVP, each `(tenant_id, ontology_id)` has **exactly one active published schema version** at a time. Older published versions remain immutable and addressable for history and compatibility checks.

- Drafting or validating a version does not change the active operational schema.
- Publication records an immutable version. Activation is a separate explicit operation, or an explicitly documented atomic publish-and-activate transaction.
- Before activation, classify changes as additive or breaking, validate existing objects against the proposed schema, and require an approved migration plan for breaking changes.
- Execute required data migrations with a documented failure/rollback strategy; never activate a version whose required migration failed. Record activation timestamp and actor.
- Record the schema version used by each ingestion run, validation report, semantic export, and generated SDK. Existing objects are interpreted under the active version unless an explicitly versioned historical read is supported.
- Preserve stable object identities across schema activation; never rewrite primary keys merely because a display name or class label changes.
- For the MVP, do not promise concurrent multi-version object storage, automatic data branching, or automatic backward compatibility. Report incompatible clients and require migration or SDK regeneration.

**Acceptance criteria:** Draft publication does not change live objects; failed migrations leave the previously active version intact; breaking changes cannot activate without approval; old versions remain inspectable; and ingestion/SDK artifacts identify the schema version they use.

---

# 8. Operational Object API

## 8.1 Objective

Expose operational ontology objects through FastAPI.

All object operations must be schema-aware and authorization-aware.

## 8.2 Required endpoints

Implement versioned endpoints:
```http
POST   /api/v1/ontologies
GET    /api/v1/ontologies
GET    /api/v1/ontologies/{ontology_id}
POST   /api/v1/ontologies/{ontology_id}/publish
GET    /api/v1/object-types
GET    /api/v1/object-types/{type_id}
POST   /api/v1/objects/{type_id}
GET    /api/v1/objects/{type_id}/{object_id}
PATCH  /api/v1/objects/{type_id}/{object_id}
DELETE /api/v1/objects/{type_id}/{object_id}
POST   /api/v1/objects/{type_id}/query
GET    /api/v1/objects/{type_id}/{object_id}/links
POST   /api/v1/objects/{type_id}/{object_id}/links
```

Every request must resolve its ontology and tenant context explicitly.

## 8.3 Query abstraction

Create a structured query representation.

Example:
```json
{
  "object_type": "Machine",
  "filter": {
    "and": [
      {
        "property": "operationalStatus",
        "operator": "eq",
        "value": "RUNNING"
      },
      {
        "property": "temperatureCelsius",
        "operator": "gt",
        "value": 80
      }
    ]
  },
  "order_by": [
    {
      "property": "temperatureCelsius",
      "direction": "desc"
    }
  ],
  "limit": 100
}
```

The backend must compile the query into parameterized SQL.

Never concatenate untrusted property names or values directly into SQL.

Property names must be resolved against published schema metadata.

## 8.4 Supported query operations

Initial support:

- Equality.

- Inequality.

- Numeric comparisons.

- Boolean combinations.

- Null checks.

- String matching.

- Sorting.

- Pagination.

- Property projection.

- Link traversal.

- Basic aggregations.

Add cursor pagination for large result sets.

Do not return unbounded object collections.

## 8.5 Object Set API

Implement a composable object-set representation.

For example:
```python
machines = (
    client.objects("Machine")
    .filter(operationalStatus="RUNNING")
    .filter(temperatureCelsius__gt=80)
    .limit(100)
    .execute()
)
```

The SDK should compile this expression into the structured query API.

Avoid fetching all objects and filtering them in Python.

## 8.6 Acceptance criteria

- Queries are validated against schema definitions.

- Invalid property names are rejected.

- Queries use parameterized SQL.

- Pagination is deterministic.

- Link traversal returns valid authorized objects.

- Query execution does not expose unauthorized properties.

- Query plans can be inspected during development.

---

# 9. Action Engine

## 9.1 Objective

Implement Foundry-inspired Action Types.

Actions represent governed business operations that modify operational state.

## 9.2 Initial action operations

Support:
```text
CREATE_OBJECT
UPDATE_OBJECT
DELETE_OBJECT
CREATE_LINK
DELETE_LINK
```

Actions must be declaratively defined in ontology metadata.

Example:
```yaml
name: ScheduleMaintenance
parameters:
  machine_id:
    type: string
    required: true
  scheduled_date:
    type: date
    required: true
operations:
  - type: CREATE_OBJECT
    object_type: MaintenanceTask
  - type: CREATE_LINK
    link_type: hasMaintenanceTask
```

The actual action language must define deterministic parameter references and object references.

Do not use unrestricted `eval` or execute arbitrary code embedded in ontology metadata.

## 9.3 Execution pipeline

Every action must follow:
```text
Receive Request
      |
      v
Authenticate User
      |
      v
Authorize Action
      |
      v
Validate Parameters
      |
      v
Validate Business Preconditions
      |
      v
Start Database Transaction
      |
      v
Apply Object / Link Changes
      |
      v
Record Audit Event
      |
      v
Insert Outbox Events
      |
      v
Commit Transaction
      |
      v
Process External Side Effects
```

## 9.4 Idempotency

Support idempotency keys for action execution.

Repeated requests with the same key and identical parameters must not duplicate effects.

Conflicting reuse of an idempotency key must be rejected.

## 9.5 External webhooks

Support two distinct categories:

**Pre-commit validation**

- Used for checks that must pass before applying an action.

- Must have a timeout.

- Must fail closed when configured as mandatory.

- Must not be assumed to be free of side effects.

**Post-commit notifications**

- Delivered through a transactional outbox.

- Must support retries.

- Must include stable event identifiers.

- Must tolerate duplicate delivery.

Do not claim that PostgreSQL transactions can atomically commit changes in external systems.

For workflows that require external writes, implement explicit retry, compensation, and reconciliation behavior.

## 9.6 Action previews

Implement:
```http
POST /api/v1/actions/{action_type}/preview
POST /api/v1/actions/{action_type}/execute
```

Preview must:

- Validate parameters.

- Check permissions.

- Evaluate preconditions.

- Describe proposed changes.

- Avoid mutations and external side effects.

Preview results must not be treated as authorization to execute later without revalidation.

## 9.7 Acceptance criteria

- Valid actions modify objects.

- Invalid actions leave the database unchanged.

- Multi-object operations are atomic.

- Concurrent conflicting actions are handled correctly.

- Idempotency prevents duplicate effects.

- Every execution produces an audit record.

- Webhook failures do not corrupt committed operational state.

- Unauthorized actions are rejected.

---

# 10. Source Data, Edits, and Reconciliation

## 10.1 Objective

Separate externally sourced data from user-authored operational changes.

This is necessary because Foundry-like objects may be populated by data pipelines while also being editable through applications.

## 10.2 Data layers

Implement three conceptual layers:
```text
SOURCE STATE
    |
    v
USER EDIT OVERLAY
    |
    v
RESOLVED OPERATIONAL OBJECT
```

**Source state**

Contains the latest accepted values from ingestion.

**Edit overlay**

Contains user-authored changes made through actions.

**Resolved object**

Contains the values applications currently observe.

## 10.3 Conflict strategies

Support configurable property-level policies:

- Source wins.

- User edit wins.

- Reject conflicting update.

- Require manual reconciliation.

Choose a deterministic default and document it.

For the initial MVP, use explicit property ownership where possible rather than attempting sophisticated automatic merges.

## 10.4 Source identity

Each data mapping must define:

- Source system.

- Source dataset.

- Source primary key.

- Target ontology.

- Target object type.

- Object ID mapping.

- Property mappings.

- Update strategy.

- Deletion strategy.

A source record must map deterministically to the same operational object across runs.

## 10.5 Deletion behavior

Support:

- Ignore missing source rows.

- Soft-delete missing objects.

- Hard-delete only when explicitly authorized.

Do not delete operational objects simply because a partial ingestion batch omitted them.

## 10.6 Acceptance criteria

- Re-ingesting unchanged data does not create duplicate objects.

- User edits survive source refreshes when configured to do so.

- Conflicts are recorded.

- Deletion behavior is explicit.

- Failed ingestion batches do not leave partially committed logical snapshots.

---

# 11. Data Ingestion with Polars

## 11.1 Objective

Implement an ingestion pipeline that converts external data into validated operational objects.

Use Polars for dataframe manipulation and transformations.

## 11.2 Initial supported sources

Implement:

1. CSV.

2. Parquet.

3. JSON.

4. PostgreSQL tables or queries.

Add other connectors later.

## 11.3 Pipeline
```text
External Data
     |
     v
Connector
     |
     v
Polars LazyFrame / DataFrame
     |
     v
Mapping and Transformation
     |
     v
Schema Validation
     |
     v
Staging Tables
     |
     v
Diff / Reconciliation
     |
     v
Transactional Materialization
     |
     v
Operational Objects
```

Prefer Polars lazy execution for file-based transformations where applicable.

Use batch processing rather than converting every row into a large Python object graph.

## 11.4 Mapping configuration

Example:
```yaml
source:
  type: csv
  path: fixtures/machines.csv
target:
  ontology: manufacturing
  object_type: Machine
identity:
  source_column: machineId
  target_property: machineId
properties:
  machineId:
    column: machineId
  machineName:
    column: machineName
  temperatureCelsius:
    column: temperatureCelsius
  operationalStatus:
    column: operationalStatus
```

The mapping language must support:

- Column renaming.

- Type conversion.

- Default values.

- Null handling.

- Simple expressions.

- Relationship mappings.

- Row filtering.

Avoid arbitrary Python code execution inside untrusted mapping definitions.

## 11.5 Batch execution

Each ingestion run must track:
```text
run_id
source_id
started_at
completed_at
status
rows_read
rows_valid
rows_rejected
objects_created
objects_updated
objects_deleted
error_summary
```

Persist rejected records or diagnostic references for troubleshooting.

## 11.6 Incremental ingestion

Initial implementation:

- Full snapshot ingestion.

- Deterministic upserts.

- Change detection using hashes or source version markers.

Later:

- Incremental source cursors.

- Change data capture.

- Event-driven ingestion.

- Streaming updates.

## 11.7 Acceptance criteria

- CSV and Parquet ingestion work.

- Polars transformations are tested.

- Mapping errors are reported clearly.

- Invalid rows can be quarantined.

- Repeated ingestion is idempotent.

- Large datasets are processed in bounded batches.

- Ingestion jobs can be retried safely.

- Operational objects remain queryable during ingestion.

---

# 12. Open Ontologies Integration

## 12.1 Objective

Integrate Open Ontologies as an external semantic reasoning and governance service.

Do not duplicate its reasoning functionality in Python.

## 12.2 Integration strategy

Create a `SemanticEngine` interface.
```python
from typing import Protocol
class SemanticEngine(Protocol):
    async def validate_ontology(
        self,
        ontology_artifact: bytes,
    ) -> object:
        ...
    async def validate_shapes(
        self,
        ontology_artifact: bytes,
        data_artifact: bytes,
    ) -> object:
        ...
    async def reason(
        self,
        ontology_artifact: bytes,
        data_artifact: bytes,
    ) -> object:
        ...
    async def analyze_change(
        self,
        previous_artifact: bytes,
        proposed_artifact: bytes,
    ) -> object:
        ...
```

Use typed request and response models in the actual implementation.

Implement an `OpenOntologiesAdapter` behind this interface.

## 12.3 Integration discovery

Before implementing the adapter, inspect the pinned Open Ontologies version and document:

- Available CLI commands.

- REST endpoints.

- MCP tools.

- Required build features.

- Input and output formats.

- Error handling.

- Persistent storage behavior.

- Supported reasoning profiles.

- SHACL support.

- Proof certificate generation.

- Proof verification requirements.

Do not invent endpoint contracts.

Prefer a documented HTTP integration for a long-running service.

Use a subprocess adapter if it is simpler or more reliable for batch operations.

## 12.4 Semantic artifacts

Store versioned semantic artifacts:
```text
ontology.owl
ontology.ttl
shapes.ttl
mapping.json
validation-report.json
reasoning-report.json
change-plan.json
```

Artifacts must be associated with:

- Ontology ID.

- Ontology version.

- Generation timestamp.

- Compiler version.

- Semantic engine version.

- Content hash.

## 12.5 Reasoning lifecycle

Semantic reasoning must run asynchronously.
```text
Published Ontology
       |
       v
Export RDF / OWL
       |
       v
Export Selected Operational Facts
       |
       v
Open Ontologies
       |
       v
Reasoning / Validation
       |
       v
Store Results
       |
       v
Publish Approved Derived Facts
```

Do not run full ontology reasoning on every object query.

## 12.6 Derived facts

Store inferred facts separately from asserted operational state.

Track:

- Inference rule or explanation.

- Input artifact version.

- Reasoning engine version.

- Timestamp.

- Provenance.

- Verification status.

Do not automatically write inferred facts into authoritative source properties.

## 12.7 Security of reasoning

Semantic reasoning must not become a path around object-level security.

For the initial release:

- Restrict semantic jobs to authorized datasets.

- Do not expose unrestricted global SPARQL to ordinary users.

- Apply authorization to returned inferred facts.

- Track provenance so inferred facts can be associated with their supporting inputs.

- Treat derived facts as potentially sensitive.

## 12.8 Proof verification

Where Open Ontologies supports proof certificates:

- Generate certificates for supported reasoning modes.

- Verify them using the documented checker.

- Store verification results.

- Expose verification status through the API.

A valid proof establishes entailment under the relevant logical assumptions. It does not establish that the input data is factually correct.

## 12.9 Acceptance criteria

- Ontology definitions can be exported to RDF/OWL.

- Open Ontologies can validate the exported artifacts.

- SHACL violations are returned as structured diagnostics.

- Supported reasoning tasks produce results.

- Semantic jobs are asynchronous.

- Semantic failures do not corrupt operational objects.

- Engine upgrades are covered by compatibility tests.

---

## 12.10 Integration capability matrix and fallback policy

During Phase 0, produce `docs/architecture/semantic-compatibility.md` for the **pinned** Open Ontologies build and its enabled features. Include the command/API actually exercised, fixture used, result (`PASS`, `FAIL`, `NOT RUN`, `NOT SUPPORTED`), and evidence/log reference for each capability:

| Capability | MVP expectation | Verification |
|---|---|---|
| Turtle parsing | Required | Parse `manufacturing.ttl` and `manufacturing-data.ttl` |
| OWL class and property interpretation | Required for supported subset | Inspect imported fixture definitions |
| SHACL validation | Required | Validate `manufacturing-data.ttl` against `manufacturing-shapes.ttl` |
| `CriticalMachine` inference | Required **if supported by the selected reasoning profile** | Verify expected classifications and document any profile limitation |
| Semantic change analysis | Later | Inspect documented feature and smoke-test if available |
| Proof certificates | Optional | Inspect documented feature and test if available |
| WebProtégé interoperability | Optional for MVP | Test file-based OWL import/export |

If Open Ontologies lacks an MVP-required operation, **do not invent an API or implement a custom reasoner**. Report the gap and propose a narrowly scoped, established adapter/library or a change in MVP scope for explicit approval. Record license compatibility, build flags, supported reasoning profile, command/API version, and pin/commit hash. SHACL validation and OWL inference are separate checks; parsing success alone is not evidence of either.

---

# 13. Protégé and WebProtégé Integration

## 13.1 Objective

Support Protégé as an advanced semantic authoring environment.

The platform must not require Protégé for normal operational ontology management.

## 13.2 Initial integration

Implement file-based integration first.

Support:
```text
Protégé
   |
   v
OWL / RDF Export
   |
   v
Ontology Import API
   |
   v
Semantic Validation
   |
   v
Schema Translation
   |
   v
Operational Schema Draft
```

Supported initial formats:

- Turtle.

- RDF/XML.

- OWL/XML where supported by the selected parser.

Use established RDF/OWL libraries.

## 13.3 Import behavior

Importing an OWL ontology must:

1. Parse the artifact.

2. Identify classes.

3. Identify datatype properties.

4. Identify object properties.

5. Identify supported subclass relationships.

6. Translate supported constructs.

7. Preserve original semantic artifacts.

8. Report unsupported constructs.

9. Generate a proposed operational schema.

10. Require review before publication.

Do not silently interpret OWL cardinality axioms as database constraints without an explicit mapping policy.

## 13.4 WebProtégé deployment

Treat WebProtégé as an optional service.

Before implementation:

- Evaluate the maintained deployment architecture.

- Verify its license and dependencies.

- Determine supported export and integration mechanisms.

- Pin a specific tested version.

- Document resource requirements.

Do not assume WebProtégé exposes a stable API for every operation.

## 13.5 Synchronization

Initial synchronization is one-directional:
```text
Protégé → Operational Schema Draft
```

Later support:
```text
Operational Schema → OWL Export
```

Do not implement unrestricted bidirectional live synchronization in the MVP.

## 13.6 Acceptance criteria

- An OWL ontology exported from Protégé can be imported.

- Supported classes and properties become operational schema drafts.

- Unsupported constructs generate warnings.

- Original OWL artifacts are preserved.

- No imported schema becomes active without validation and publication.

- The operational platform works when WebProtégé is unavailable.

---

# 14. Authorization and Multi-Tenancy

## 14.1 Objective

Implement secure access to ontology metadata, objects, relationships, and actions.

## 14.2 Authentication

Use OIDC-compatible authentication.

Use a replaceable, standards-based OIDC issuer; Keycloak is an optional self-hosted identity broker, not a mandatory provider. Phase 7 establishes verified backend identities and authorization. Phase 8 establishes browser login/session contracts with a local deterministic OIDC provider. Phase 10 integrates and tests live Microsoft Entra ID and Google sign-in through a selected broker or explicitly reviewed direct-provider architecture.

FastAPI must validate:

- Token signature.

- Issuer.

- Audience.

- Expiration.

- Required claims.

Do not trust arbitrary client-supplied user identifiers.

### 14.2.1 External SSO and API-token boundaries

- Support future Microsoft Entra ID organizational SSO, Google account sign-in, and Google Workspace; consider consumer Microsoft accounts separately during provider configuration. Additional organization-specific OIDC providers should be pluggable.
- Prefer a replaceable OIDC identity broker that federates external providers and issues platform-audience access tokens conforming to the backend's documented supported profile (currently RFC 9068). A direct-provider design requires explicit token-profile and audience review.
- Never send Google or Microsoft ID tokens directly to FastAPI as bearer API access tokens; never accept Microsoft Graph or Google API access tokens as platform API credentials. Do not relax issuer, audience, token-type, signature, or algorithm checks for compatibility.
- Bind external identities by trusted issuer and immutable subject, not email address alone. Account linking, organization onboarding, tenant selection, and just-in-time provisioning must be explicitly governed; email domains or token roles do not automatically grant tenant access.
- Keep PostgreSQL-managed principals, tenant memberships, RBAC, ABAC, policy versions, and revocation authoritative regardless of identity provider.
- Use Authorization Code Flow with PKCE for interactive sign-in. Prefer server-managed sessions and a backend-for-frontend boundary with Secure, HttpOnly, appropriately scoped SameSite cookies, CSRF defenses, validated state/nonce, session rotation/expiry, and logout. Keep long-lived tokens out of browser JavaScript.
- Treat external IdP integration, organizational SSO enforcement, provider outage handling, key rotation, logout semantics, and identity lifecycle as Phase 10 acceptance items; optional SCIM/group sync belongs to Phase 11.

## 14.3 Authorization levels

Support:

1. Tenant.

2. Ontology.

3. Object type.

4. Object instance.

5. Property.

6. Link type.

7. Action type.

## 14.4 Authorization model

Start with RBAC for coarse-grained permissions.

Add ABAC for object- and property-level restrictions.

Example:
```text
A maintenance technician may:
READ Machine objects
READ MaintenanceTask objects
EXECUTE CompleteMaintenance
But may only modify tasks assigned to them.
```

Policies must be enforced during query compilation and action execution.

## 14.5 Data isolation

Every operational query must be scoped to the authenticated tenant.

Do not rely solely on frontend filtering.

Use database constraints and consider PostgreSQL row-level security as an additional defense-in-depth mechanism.

If using row-level security, document the interaction between application connection pooling, transaction-scoped identity, and database roles.

## 14.6 Link traversal security

Traversing a link must not expose an unauthorized target object.

Aggregations must not disclose restricted data through counts or other derived outputs.

## 14.7 Acceptance criteria

- Cross-tenant reads and writes are rejected.

- Object-level policies are enforced.

- Restricted properties are omitted or rejected consistently.

- Unauthorized actions fail before mutation.

- Link traversal respects authorization.

- Security behavior is tested against direct API calls, not only the UI.

---

# 15. Ontology Branching and Versioning

## 15.1 Objective

Support safe ontology development without changing production schemas.

## 15.2 Initial branch model

Implement:
```text
main
  |
  +-- feature/add-maintenance-properties
  |
  +-- feature/new-machine-links
```

Branches contain schema definitions, not automatically duplicated operational datasets.

## 15.3 Branch operations

Support:

- Create branch.

- Read branch.

- Modify draft definitions.

- Compare branches.

- Validate branch.

- Generate migration plan.

- Merge compatible changes.

- Publish release.

## 15.4 Merge behavior

Detect conflicts such as:

- Same property modified incompatibly.

- Object type deleted on one branch and modified on another.

- Incompatible type changes.

- Conflicting action definitions.

Do not automatically merge incompatible schemas.

## 15.5 Data isolation

Initially, production operational data remains separate from schema development.

A development branch may use:

- Synthetic test data.

- A separate development tenant.

- An explicitly created snapshot.

Do not automatically expose production data to development branches.

## 15.6 Acceptance criteria

- Schema branches are isolated.

- Branch differences are inspectable.

- Conflicts are detected.

- Published versions are immutable.

- Merge operations preserve history.

- Production schemas are not modified by unmerged branches.

---

# 16. Python and TypeScript SDKs

## 16.1 Objective

Generate typed clients from published ontology schemas.

## 16.2 Python SDK

Desired usage:
```python
client = OntologyClient(
    base_url="http://localhost:8000",
    token=token,
)
machine = await client.objects.Machine.get("MACHINE-001")
machines = await (
    client.objects.Machine
    .where(operationalStatus="RUNNING")
    .limit(100)
    .execute()
)
```

Generated action methods should expose typed parameters.

## 16.3 TypeScript SDK

Desired usage:
```typescript
const machine = await client.objects.Machine.get(
  "MACHINE-001"
);
await client.actions.ScheduleMaintenance.execute({
  machineId: "MACHINE-001",
  scheduledDate: "2026-11-01"
});
```

These examples describe the desired SDK experience; the coding agent must define and implement the actual client contract.

## 16.4 SDK versioning

Each generated SDK must identify:

- Ontology ID.

- Published ontology version.

- API compatibility version.

- Generation timestamp.

SDKs must not silently change behavior when a schema branch is modified.

## 16.5 Acceptance criteria

- SDKs can be generated from a published schema.

- Generated models are type checked.

- Generated clients can query objects.

- Generated clients can execute actions.

- SDK generation is deterministic.

- Incompatible schema changes produce appropriate compatibility diagnostics.

---

# 17. Frontend Ontology Studio

## 17.1 Objective

Build a minimal developer-facing UI using Next.js.

Do not attempt to reproduce all of Foundry's visual applications.

## 17.2 Required initial pages

### Ontology overview

Display:

- Ontology name.

- Version.

- Status.

- Object types.

- Link types.

- Action types.

### Object type editor

Allow developers to:

- Create object types.

- Add properties.

- Configure property types.

- Define primary keys.

- Configure links.

- Validate definitions.

### Object explorer

Allow users to:

- Browse object types.

- Search objects.

- Filter objects.

- Inspect properties.

- Traverse relationships.

- View edit history.

### Action explorer

Allow users to:

- View action definitions.

- Enter parameters.

- Preview actions.

- Execute authorized actions.

- Inspect execution history.

### Data source manager

Display:

- Configured sources.

- Data mappings.

- Ingestion status.

- Validation failures.

- Last successful synchronization.

### Semantic validation

Display:

- OWL import results.

- SHACL violations.

- Semantic change analysis.

- Reasoning results.

- Proof verification status.

## 17.3 Frontend requirements

- TypeScript strict mode.

- Typed API client.

- Server-side authorization enforcement.

- Accessible forms and navigation.

- Structured loading and error states.

- No direct database access.

- No privileged semantic-engine access from the browser.

## 17.4 Acceptance criteria

A developer can create a simple ontology, ingest data, query objects, and execute an action through the UI.

---

# 18. Background Jobs

## 18.1 Objective

Run long-running operations outside the FastAPI request lifecycle.

## 18.2 Required job types

- Data ingestion.

- Schema compilation.

- Semantic validation.

- Reasoning.

- Derived-fact materialization.

- SDK generation.

- Index creation.

- Source reconciliation.

- Outbox delivery.

## 18.3 Initial implementation

Use PostgreSQL-backed jobs with separate Python worker processes.

Workers should:

- Claim jobs safely.

- Record attempts.

- Renew leases or heartbeats.

- Retry transient failures.

- Respect retry limits.

- Detect abandoned jobs.

- Support cancellation where safe.

Use PostgreSQL locking patterns appropriate for concurrent workers, such as `FOR UPDATE SKIP LOCKED`.

Do not use FastAPI `BackgroundTasks` as the sole mechanism for durable production jobs.

## 18.4 Future evolution

Evaluate a dedicated task queue or workflow engine when:

- Job volume becomes substantial.

- Complex dependencies are required.

- Scheduling becomes sophisticated.

- Cross-service workflows become common.

---

# 19. Optional Rust Components

## 19.1 Objective

Use Rust selectively to accelerate expensive operations without rewriting the Python application.

## 19.2 Initial rule

Do not implement Rust accelerators before establishing Python baselines.

## 19.3 Candidate components

Evaluate Rust for:

- Large-scale object materialization.

- Graph traversal.

- Relationship resolution.

- Bulk validation.

- Custom indexing.

- CPU-intensive transformations.

## 19.4 PyO3 architecture
```text
FastAPI
   |
   v
Python Domain Services
   |
   v
PyO3 Binding
   |
   v
Rust Library
```

Use Maturin to build the extension.

## 19.5 Interface requirements

Rust extensions must:

- Expose stable typed interfaces.

- Return structured errors.

- Avoid unnecessary Python/Rust data copies.

- Release the GIL during suitable long-running native operations.

- Be tested against the Python implementation.

- Support the deployment platforms selected for the project.

Prefer Arrow-compatible memory representations when transferring large tabular datasets.

## 19.6 Performance criteria

Introduce Rust only when benchmarks show a meaningful improvement in:

- Throughput.

- p95 latency.

- Memory usage.

- CPU utilization.

- Cost per processed record.

Maintain equivalent behavior between Python and Rust implementations.

---

# 20. AI Agent Integration

## 20.1 Objective

Allow AI agents to inspect and operate on ontology data through controlled interfaces.

## 20.2 Initial tools

Expose tools equivalent to:
```text
ontology_list_types
ontology_describe_type
ontology_query_objects
ontology_get_object
ontology_traverse_links
ontology_validate_schema
ontology_reason
ontology_preview_action
ontology_execute_action
```

## 20.3 Security

AI agents must use the same authorization system as other clients.

Do not give agents unrestricted SQL access.

Do not give agents unrestricted SPARQL access to sensitive graphs.

Mutating actions must require explicit authorization and, where appropriate, human approval.

## 20.4 MCP

Implement an optional MCP adapter around the existing application services.

Do not create separate business logic for MCP.

The MCP adapter should call the same query and action services used by FastAPI.

---

# 21. Observability and Reliability

## 21.1 Structured logging

Every request and background job should include:
```text
request_id
trace_id
tenant_id
principal_id
operation
duration
status
```

Do not log authentication tokens or sensitive object properties.

## 21.2 Metrics

Track:

- API request latency.

- API error rates.

- Database query latency.

- Object query throughput.

- Action success/failure rates.

- Ingestion throughput.

- Ingestion failure rates.

- Background job queue depth.

- Semantic validation duration.

- Reasoning duration.

- Worker resource utilization.

## 21.3 Health endpoints

Implement:
```http
GET /health/live
GET /health/ready
```

Readiness should reflect dependencies required to serve operational requests.

Semantic-engine unavailability should not necessarily make ordinary object queries unavailable.

## 21.4 Recovery

Document and test:

- PostgreSQL backup and restoration.

- Object storage backup.

- Schema artifact recovery.

- Worker restart behavior.

- Outbox replay.

- Failed ingestion recovery.

---

# 22. Testing Strategy

## 22.1 Unit tests

Test:

- Schema validation.

- Type conversion.

- Query compilation.

- Action parameter validation.

- Authorization decisions.

- Schema migration classification.

- RDF/OWL compilation.

- SDK generation.

## 22.2 Integration tests

Use real PostgreSQL instances.

Test:

- Database transactions.

- Optimistic concurrency.

- Object relationships.

- JSONB queries.

- Ingestion staging.

- Outbox processing.

- Tenant isolation.

## 22.3 Semantic integration tests

Use pinned Open Ontologies artifacts.

Test:

- RDF/OWL import.

- SHACL validation.

- Supported inference.

- Semantic change detection.

- Error handling.

- Proof verification where supported.

## 22.4 Protégé compatibility tests

Maintain sample OWL files created in Protégé.

Verify that supported constructs import correctly.

Verify that unsupported constructs produce diagnostics.

## 22.5 End-to-end tests

The reference application must demonstrate:

1. Define ontology.

2. Publish schema.

3. Import source data.

4. Query operational objects.

5. Traverse relationships.

6. Execute an action.

7. Verify persistence.

8. Refresh source data.

9. Verify edit reconciliation.

10. Run semantic reasoning.

11. Validate authorization.

12. Generate and use an SDK.

## 22.6 Performance tests

Establish benchmark datasets containing:

- 10,000 objects.

- 100,000 objects.

- 1,000,000 objects.

Benchmark:

- Primary-key lookups.

- Filtered queries.

- Link traversal.

- Bulk ingestion.

- Concurrent updates.

- Action execution.

Record hardware, dataset characteristics, query plans, and latency distributions.

Do not define production performance claims from synthetic benchmarks alone.

---

## 22.7 Canonical fixture validation and reporting

Before completing **any** implementation phase, read `fixtures/VALIDATION.md`, run all checks applicable to that phase, and report each check as `PASS`, `FAIL`, `NOT RUN`, or `NOT SUPPORTED`. Do not claim successful validation for unexecuted checks. Preserve original fixture inputs as regression baselines; add separate negative fixtures rather than corrupting the canonical examples.

The progressive end-to-end acceptance path is:
```text
CSV → Polars → PostgreSQL operational objects → FastAPI queries
    → authorized RDF export → SHACL validation / supported OWL inference
```

Verify deterministic IDs and IRIs, property types, correct Factory/Machine/Employee/MaintenanceTask links, idempotent ingestion, no unauthorized cross-tenant exports, and consistent results between operational objects and exported RDF. Run Turtle parsing, CSV integrity, and direct semantic compatibility tests in Phase 0; complete the entire path as the required subsystems arrive in Phases 1–6. Any unsupported reasoning profile must be documented, not represented as a successful inference test.

---

# 23. Implementation Roadmap

The project must be implemented incrementally.

Do not attempt all features simultaneously.

## Phase 0 — Architecture and integration verification

**Priority: Critical**

Tasks:

1. Initialize the repository.

2. Establish coding standards.

3. Set up uv and Python tooling.

4. Create Docker Compose configuration.

5. Deploy PostgreSQL.

6. Evaluate Open Ontologies integration.

7. Evaluate Protégé import/export.

8. Document architecture decisions.

9. Define the canonical ontology schema.

10. Establish CI.

Deliverables:

- Running development environment.

- Architecture documentation.

- Semantic-engine compatibility report.

- Initial schema specification.

- Passing CI pipeline.

**Exit criteria:** The application starts locally and all external integration assumptions have been verified or explicitly deferred.

---

## Phase 1 — Ontology metadata and object storage

**Priority: Critical**

Tasks:

1. Implement ontology metadata models.

2. Implement schema registry.

3. Implement PostgreSQL migrations.

4. Implement object persistence.

5. Implement relationship persistence.

6. Implement property validation.

7. Implement optimistic concurrency.

8. Implement initial object CRUD APIs.
9. Create tenant-aware keys, foreign keys, indexes, and tenant-scoped service queries.
10. Test cross-tenant access rejection and tenant-safe link integrity.
11. Implement one-active-schema-version activation rules and migration guards.

Deliverables:

- Ontology definitions.

- Object type definitions.

- Object persistence.

- Relationship persistence.

- REST APIs.

- Automated tests.

**Exit criteria:** Developers can define object types and persist linked operational objects.

---

## Phase 2 — Object queries

**Priority: Critical**

Tasks:

1. Implement query AST.

2. Implement SQL query compiler.

3. Implement filters.

4. Implement sorting.

5. Implement pagination.

6. Implement link traversal.

7. Implement aggregations.

8. Add query tests and benchmarks.

Deliverables:

- Object query API.

- Structured query language.

- SQL compiler.

- Query integration tests.

**Exit criteria:** Applications can query and traverse operational objects without writing SQL.

---

## Phase 3 — Actions and object edits

**Priority: Critical**

Tasks:

1. Implement action definitions.

2. Implement action validation.

3. Implement transactional execution.

4. Implement action previews.

5. Implement idempotency.

6. Implement audit events.

7. Implement transactional outbox.

8. Implement edit overlays.

9. Implement source/edit reconciliation.

Deliverables:

- Action engine.

- Object edit history.

- Transactional outbox.

- Reconciliation framework.

**Exit criteria:** Governed actions can atomically modify multiple objects and links.

---

## Phase 4 — Data ingestion

**Priority: High**

Tasks:

1. Implement Polars ingestion framework.

2. Implement CSV connector.

3. Implement Parquet connector.

4. Implement JSON connector.

5. Implement PostgreSQL connector.

6. Implement mapping definitions.

7. Implement staging and validation.

8. Implement deterministic upserts.

9. Implement ingestion history.

10. Implement durable background workers.

Deliverables:

- Data ingestion API.

- Connector interfaces.

- Mapping system.

- Background job infrastructure.

**Exit criteria:** External datasets can be materialized and refreshed without losing governed user edits.

---

## Phase 5 — Semantic integration

**Priority: High**

Tasks:

1. Implement RDF/OWL compiler.

2. Implement SHACL compiler.

3. Implement Open Ontologies adapter.

4. Implement semantic validation jobs.

5. Implement reasoning jobs.

6. Implement semantic artifact storage.

7. Implement inferred-fact provenance.

8. Implement change analysis.

9. Add proof verification integration where supported.

Deliverables:

- Semantic API.

- RDF/OWL export.

- SHACL validation.

- Reasoning integration.

- Semantic governance reports.

**Exit criteria:** Operational ontology definitions can be semantically validated and used for supported inference workflows.

---

## Phase 6 — Protégé integration

**Priority: High**

Tasks:

1. Implement OWL import.

2. Implement supported construct mapping.

3. Implement import diagnostics.

4. Implement ontology draft generation.

5. Implement OWL export.

6. Add Protégé-generated test fixtures.

7. Evaluate optional WebProtégé deployment.

Deliverables:

- Protégé import/export.

- Compatibility documentation.

- Optional WebProtégé deployment.

**Exit criteria:** A supported ontology created in Protégé can become an operational schema draft.

---

## Phase 7 — Authentication and authorization

**Priority: Critical before public deployment**

Tasks:

1. Integrate OIDC authentication.

2. Implement tenant isolation.

3. Implement RBAC.

4. Implement object-level authorization.

5. Implement property-level authorization.

6. Implement action permissions.

7. Implement link traversal security.

8. Implement authorization integration tests.

Security interfaces should be designed in earlier phases, even if the full implementation is completed here.

Do not publicly deploy the system before this phase is complete.

**Exit criteria:** All operational APIs enforce authorization consistently.

---

## Phase 8 — Native Ontology Manager and Ontology Studio

**Priority: High**

Tasks:

1. Implement ontology overview.

2. Implement object type editor.

3. Implement relationship editor.

4. Implement object explorer.

5. Implement action explorer.

6. Implement ingestion dashboard.

7. Implement semantic validation dashboard.

8. Implement a **single Next.js application with two workspaces**: native Ontology Manager (schema graph, object/property/link/action types, drafts, publication/activation, version history, OWL import/export and mapping diagnostics) and Ontology Studio (objects, Object Sets, queries, links, governed actions, ingestion, semantic results).

9. Implement provider-independent frontend authentication/session contracts, using OIDC Authorization Code + PKCE, a server-managed session / backend-for-frontend approach where appropriate, secure cookies, CSRF/state/nonce protection, expiry and logout. Use a deterministic local OIDC provider for tests.

10. Integrate Phase 7 verified identity, tenant selection, RBAC/ABAC, and permission-aware navigation. FastAPI remains the enforcement boundary; never forward external ID tokens or unrelated-provider API tokens as platform bearer credentials.

11. Document an interchangeable identity-broker contract for future Microsoft Entra ID and Google sign-in, including issuer/audience/token profile and principal mapping. Do **not** implement live provider integration or weaken RFC 9068 verification in Phase 8.

Deliverables:

- One Next.js application with native Ontology Manager and Ontology Studio workspaces.

- Secure, provider-independent browser login/session foundation validated against a local OIDC test provider.

- Object explorer.

- Schema editor.

- Action execution interface.

**Exit criteria:** A developer can complete the reference workflow without directly invoking REST endpoints, using verified frontend sessions and authorization-aware workflows; live Microsoft/Google sign-in is deferred to Phase 10.

---

## Phase 9 — Branching and SDK generation

**Priority: Medium**

Tasks:

1. Implement schema branches.

2. Implement schema diffs.

3. Implement merge conflict detection.

4. Implement migration planning.

5. Implement Python SDK generation.

6. Implement TypeScript SDK generation.

7. Implement SDK compatibility tests.

Deliverables:

- Branching API.

- Migration planning.

- Generated SDKs.

**Exit criteria:** Developers can evolve ontologies without modifying published schemas and can generate typed clients.

---

## Phase 10 — Production hardening

**Priority: High before production release**

Tasks:

1. Add observability.

2. Add structured logging.

3. Add performance benchmarks.

4. Add backup and recovery procedures.

5. Add rate limiting.

6. Add resource limits.

7. Add deployment documentation.

8. Add dependency vulnerability scanning.

9. Add audit retention policies.

10. Add operational runbooks.

11. Select and deploy a replaceable OIDC broker (or document and approve a direct-provider alternative) and integrate **Microsoft Entra ID organizational SSO** and **Google account / Google Workspace sign-in** with the Phase 8 browser session layer. Do not assume external tokens match the platform API token profile.

12. Validate provider-specific issuer, audience, authorized client, JWKS rotation, logout, session renewal/expiry, IdP outage behavior, secret handling, and platform-audience access-token issuance. Do not use ID tokens or third-party API tokens as platform API credentials.

13. Test stable issuer+subject identity binding, account-linking safety, tenant selection, role/membership revocation, optional organization-level allowed providers, and organization onboarding. Never grant membership from email domain alone.

14. Run actual integration tests against configured Microsoft and Google environments and clearly distinguish PASS, FAIL, NOT RUN, and NOT SUPPORTED; mock-provider tests alone are insufficient to claim live SSO support.

**Exit criteria:** The platform can be deployed, monitored, backed up, restored, and upgraded reliably; Microsoft Entra ID and Google sign-in have been validated in configured integration environments, or are explicitly marked NOT RUN and remain an open release gate for the intended SSO-enabled product.

---

## Phase 11 — Optional advanced capabilities

Implement only after the MVP is stable.

Potential additions:

- PyO3 Rust accelerators.

- Incremental semantic reasoning.

- Change data capture.

- Streaming ingestion.

- Advanced graph analytics.

- Visual pipeline builder.

- Application builder.

- MCP agent integration.

- Full-text search.

- Vector search.

- Advanced lineage visualization.

- Distributed materialization.

- Cross-ontology federation.

- Enterprise identity lifecycle: SCIM provisioning/deprovisioning, governed group synchronization, organization-specific mandatory SSO and advanced login policies.

- Fine-grained schema branching environments.

---

# 24. Reference Application

Implement a manufacturing maintenance application to validate the entire architecture.

## 24.1 Object types

### Factory
```text
id
name
location
```

### Machine
```text
id
name
status
temperature
factory_id
```

### Employee
```text
id
name
department
```

### MaintenanceTask
```text
id
machine_id
assigned_employee_id
scheduled_date
status
```

## 24.2 Relationships
```text
Factory
   |
   +-- contains --> Machine
Machine
   |
   +-- hasTask --> MaintenanceTask
Employee
   |
   +-- assignedTo --> MaintenanceTask
```

## 24.3 Actions

Implement:
```text
ScheduleMaintenance
CompleteMaintenance
UpdateMachineStatus
AssignMaintenanceTask
```

## 24.4 Semantic rules

Create a semantic classification for critical machines.

For example:
```text
CriticalMachine ⊑ Machine
Machine ⊓ (operationalStatus value "CRITICAL") ≡ CriticalMachine
```

Add supported inference rules or logical definitions that classify selected machines based on explicit conditions.

Keep the semantic classification separate from operational status mutations.

## 24.5 Required demonstration

The final demonstration must:

1. Import a manufacturing ontology from Protégé.

2. Publish the operational schema.

3. Ingest machine data from CSV.

4. Query machines using FastAPI.

5. Traverse machine-to-factory relationships.

6. Schedule maintenance through an action.

7. Verify transactionally created objects and links.

8. Refresh source data.

9. Verify preservation of configured user edits.

10. Run Open Ontologies reasoning.

11. Display semantic results.

12. Demonstrate unauthorized access rejection.

13. Generate and use a typed SDK.

This reference application is the primary end-to-end acceptance test for the project.

---

# 25. Coding Agent Execution Instructions

The coding agent must follow these rules.

## 25.0 Required repository inputs

Read `AGENTS.md`, this `PLANS.md`, and `fixtures/VALIDATION.md` before making architectural changes. Inspect the exact fixture vocabulary and pin external repository versions before implementing integrations. If a referenced file is missing, report that as a blocker rather than silently substituting invented test data. Document assumptions in architecture decision records and stop after the currently approved phase.

## 25.1 Implementation discipline

1. Work on one implementation phase at a time.

2. Do not implement future phases without explicit authorization.

3. Before writing code, inspect the current repository state.

4. Identify existing functionality before adding new abstractions.

5. Prefer established libraries over custom infrastructure.

6. Keep modules cohesive and interfaces explicit.

7. Avoid premature microservice decomposition.

8. Avoid unnecessary dependencies.

9. Write tests alongside implementations.

10. Run relevant tests before declaring a task complete.

## 25.2 External dependencies

Before integrating an external project:

1. Inspect its current documentation.

2. Inspect its license.

3. Pin a compatible version.

4. Verify required APIs and build features.

5. Create a minimal integration test.

6. Document known limitations.

Do not assume that an external tool supports an API merely because a similar tool does.

## 25.3 Database requirements

- All schema changes must use Alembic migrations.

- Do not modify production database schemas manually.

- Use parameterized queries.

- Use explicit transaction boundaries.

- Maintain referential integrity.

- Test rollback behavior.

- Avoid unbounded database queries.

## 25.4 Python requirements

- Use Python type annotations.

- Use Pydantic for API contracts.

- Use SQLAlchemy for database persistence.

- Use Polars for tabular transformations.

- Prefer asynchronous I/O where useful.

- Do not perform CPU-intensive work on the API event loop.

- Avoid unnecessary global mutable state.

## 25.5 Rust requirements

- Do not introduce Rust unless a task explicitly requires it.

- Prefer PyO3 for in-process acceleration.

- Keep Rust interfaces narrow.

- Provide equivalent Python tests.

- Benchmark against the Python implementation.

## 25.6 Documentation requirements

For each completed phase, update:
```text
README.md
docs/architecture/
docs/api/
docs/decisions/
```

Document:

- New functionality.

- Public interfaces.

- Database changes.

- Configuration.

- Tests.

- Known limitations.

## 25.7 Completion report

At the end of each phase, provide:
```text
PHASE:
STATUS:
IMPLEMENTED:
- ...
FILES CREATED:
- ...
FILES MODIFIED:
- ...
DATABASE MIGRATIONS:
- ...
TESTS RUN:
- ...
TEST RESULTS:
- ...
KNOWN LIMITATIONS:
- ...
NEXT RECOMMENDED PHASE:
- ...
```

Do not claim tests passed unless they were actually executed.

---

# 26. Definition of MVP Completion

The MVP is complete when the following capabilities work together:

- [ ] PostgreSQL stores operational objects and links.

- [ ] FastAPI exposes schema-aware object APIs.

- [ ] Developers can define and publish ontology schemas.

- [ ] Objects can be queried through structured filters.

- [ ] Relationships can be traversed.

- [ ] Actions can modify multiple objects transactionally.

- [ ] Object changes are audited.

- [ ] Source data can be ingested using Polars.

- [ ] Source refreshes follow explicit reconciliation policies.

- [ ] Open Ontologies validates semantic artifacts.

- [ ] Protégé OWL files can be imported.

- [ ] Authentication and authorization are enforced.

- [ ] Provider-independent frontend login/session foundation is validated; live Microsoft/Google SSO is a Phase 10 product milestone rather than a prerequisite for the initial Phase 8 UI.

- [ ] A basic Next.js Ontology Studio is functional.

- [ ] Python and TypeScript SDKs can be generated.

- [ ] The manufacturing reference application passes end-to-end tests.

- [ ] The system runs through Docker Compose.

- [ ] The project has reproducible builds and automated tests.

---

# 27. Immediate First Task for the Coding Agent

Begin with **Phase 0: Architecture and Integration Verification**.

Do not implement the full platform yet.

The first deliverable should include:

1. A functioning monorepo scaffold.

2. A FastAPI application with health endpoints.

3. A PostgreSQL container and verified connection.

4. SQLAlchemy and Alembic configuration.

5. A basic Python test suite.

6. A pinned Open Ontologies integration with a working smoke test.

7. A sample Protégé-compatible OWL artifact.

8. A proposed canonical ontology schema.

9. An architecture decision record describing the source-of-truth boundaries.

10. A detailed task breakdown for Phase 1.

**Stop after completing Phase 0 and report results before proceeding.**

The implementation must establish a reliable foundation before adding object storage, actions, ingestion, or semantic reasoning workflows.
