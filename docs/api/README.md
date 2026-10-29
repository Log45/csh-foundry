# Persistence API — Phases 1–2

Run `uv run uvicorn ontology_platform.main:create_app --factory --host 127.0.0.1`.
OpenAPI: `/api/v1/openapi.json`; interactive documentation: `/docs`.
Public `/health/live` returns `{"status":"ok"}`; `/health/ready` returns
`{"status":"ready"}` after PostgreSQL connectivity and revision `0005_query_order` checks.

All endpoints below are under `/api/v1` and require the explicit server-configured local
principal. Missing context returns 401; unauthorized/unprovisioned context returns 403.
There is no trusted client tenant/user header. All reads/writes invoke the authorization
interface. Cross-tenant resources are not found; foreign tenant schema bodies return 403.

| Method / path | Behavior |
|---|---|
| POST /tenant | Provision the configured tenant; body `{"name":"Local manufacturing"}`; 201 |
| GET /tenant | Read the configured provisioned tenant |
| POST /ontologies | Canonical `OntologyDefinition`; creates ontology and first draft; 201 |
| GET /ontologies | Tenant-scoped deterministic ID ordering; `limit` 1–100 and nonnegative `offset` |
| GET /ontologies/{ontology} | Namespace and active-version pointer |
| POST /ontologies/{ontology}/versions | Create another canonical draft; 201 |
| PUT /ontologies/{ontology}/versions/{version} | Replace a draft; published versions return 409; PUT can create a missing draft |
| GET /ontologies/{ontology}/versions | Version history; bounded `limit`/`offset`, lexical version order |
| GET /ontologies/{ontology}/versions/{version} | Canonical snapshot/hash, state, publication actor/time |
| POST /ontologies/{ontology}/versions/{version}/validate | Validate canonical snapshot and compare with active schema; additive/breaking plus reasons |
| POST /ontologies/{ontology}/versions/{version}/publish | Body `{}` or `{"plan_id":"UUID"}`; freezes metadata without activation |
| POST /ontologies/{ontology}/versions/{version}/activate | Explicit transactional activation; body `{}` or approved `plan_id` |
| POST /ontologies/{ontology}/versions/{version}/migration-plans | Create target-hash/base-bound data migration plan; 201 |
| POST /ontologies/{ontology}/migration-plans/{plan}/approve | Explicit local approval; immutable approval data |
| GET /ontologies/{ontology}/object-types | Active canonical object definitions |
| POST /ontologies/{ontology}/objects/{type} | Body `{"object_id":"FAC-001","properties":{...}}`; 201 |
| GET /ontologies/{ontology}/objects/{type}/{object} | Fetch one schema-aware object |
| PATCH /ontologies/{ontology}/objects/{type}/{object} | Body `{"expected_version":1,"properties":{"location":"New"}}`; property merge; 200 |
| DELETE /ontologies/{ontology}/objects/{type}/{object}?expected_version=2 | Delete at current revision; 204; existing edges return 409 |
| POST /ontologies/{ontology}/links | Typed forward-edge identity; 201; endpoint existence and cardinality checked |
| DELETE /ontologies/{ontology}/links | Same edge identity body; 204 |
| GET /ontologies/{ontology}/objects/{type}/{object}/links/{link} | Bounded direct neighbors; forward ID or inverse alias; `direction=forward|inverse`, `limit`/`offset` |

Single-object GET/PATCH/DELETE also accept `/objects/{type}?object_id=...` so opaque IDs
containing slashes/Unicode/reserved characters are transportable without changing identity.
Navigation has the equivalent `/objects/{type}/links/{link}?object_id=...` alias. These are
single-object lookups, not a filtering/query language. Unknown fields (including tenant overrides)
are rejected. Request property values remain strict JSON values; decimal/date/timestamp/UUID values
use the Phase 0 canonical string representations. The object primary-key value must match `object_id`.

## Manufacturing quick start

After configuring a local principal and provisioning its tenant as described in README:

```bash
curl --fail -H 'Content-Type: application/json' \
  --data-binary @ontologies/examples/manufacturing.json \
  http://127.0.0.1:8000/api/v1/ontologies
curl --fail -H 'Content-Type: application/json' -d '{}' \
  http://127.0.0.1:8000/api/v1/ontologies/manufacturing/versions/1.0.0/publish
curl --fail -H 'Content-Type: application/json' -d '{}' \
  http://127.0.0.1:8000/api/v1/ontologies/manufacturing/versions/1.0.0/activate
curl --fail -H 'Content-Type: application/json' \
  -d '{"object_id":"FAC-001","properties":{"factoryId":"FAC-001","factoryName":"North Assembly","location":"Rochester, NY"}}' \
  http://127.0.0.1:8000/api/v1/ontologies/manufacturing/objects/Factory
```

The supplied proposal has tenant UUID `00000000-0000-0000-0000-000000000001`.
For another configured tenant, copy the proposal and set its tenant ID; do not edit fixtures.

A forward-edge request is:

```json
{"link_type_id":"locatedInFactory","source_object_type_id":"Machine",
 "source_object_id":"MCH-001","target_object_type_id":"Factory","target_object_id":"FAC-001"}
```

After both endpoints exist, create this edge once. Navigate it from a factory with
`/objects/Factory/FAC-001/links/containsMachine`, or with `locatedInFactory?direction=inverse`.

## Migration workflow

Optional property/type/link additions are additive. Removals, primary-key/type/constraint
changes and existing link/action changes conservatively require a migration plan. Even constraint
relaxations are currently classified as breaking. Ontology identity/namespace changes are rejected.
A plan body is:

```json
{"updates":[{"object_type_id":"Factory","object_id":"FAC-001","expected_version":1,
             "properties":{"factoryId":"FAC-001","factoryName":"North Assembly",
                           "location":"Rochester, NY","newRequiredCode":"NORTH"}}]}
```

Plans use full replacement properties, not executable expressions. Create a plan for the target,
explicitly approve it, and pass its ID to publication and activation. Empty approved plans permit
structural breaking changes only if all current data validates unchanged. Approval is bound to
current active version and target content hash; editing a draft or changing active version invalidates
that binding. Each migrated row also checks its expected revision. Approval and execution are
separate requests; the trusted local administrator can approve their own plan in Phase 1.

Activation validates **all** current objects, unique properties, endpoints and link cardinalities.
It increments object revisions and validation schema versions, records actor/time, and switches the
active pointer only if the entire transaction succeeds. Failure leaves the previous pointer, rows,
revisions and link versions untouched. Older published snapshots remain inspectable.

Errors use `{"error":{"code":"...","message":"..."}}`. In particular: `invalid_properties`
(422), `identity_mismatch` (422), `revision_conflict` (409), `cardinality_conflict` (409),
`unique_conflict` (409), `migration_required` / `invalid_plan` (409), and `activation_too_large` (409).
No database details or credentials are exposed. Phase 1 activation is capped at 1,000 objects and
5,000 links; larger jobs are deferred. Full authorization, advanced queries, actions and ingestion
are not implemented by this API.

Phase 2 query/traversal/aggregation endpoints and internal Object Sets are documented in [queries.md](queries.md).

## Governed actions

Phase 3 adds active-schema action preview/execute/history/audit endpoints. See
[the action API](actions.md) for strict definition references, idempotency, authorization,
transactional outbox delivery and edit reconciliation contracts.

## Governed ingestion

Phase 4 adds immutable source/mapping publication, durable run submission/history/diagnostics and
cooperative cancellation. See [ingestion](ingestion.md) for registered connector security, staging,
worker claims, source/edit policies and bounded atomicity. Existing routes remain available.


Phase 5 adds principal-private semantic artifacts, compiled RDF/OWL/SHACL, governed exports,
fenced jobs and separately approved derived facts. See [semantic API](semantic.md) and ADRs 0024–0026.
Migrations `0010_semantic` and `0011_semantic_history` add four semantic tables and bounded
claim/error history; downgrade removes semantic history while preserving operational objects.
