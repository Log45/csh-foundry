# Phase 8 implementation checklist and API map

Approved scope: one Next.js application with Ontology Manager and Ontology Studio. No branching,
SDK generation, live Microsoft/Google SSO, external deployment, or second registry/store.

The pasted request ends at “Explicit loading and”. PLANS.md Phase 8 provides the remaining boundary.
Actual Python route/service implementations and generated OpenAPI are the integration authority.

## Baseline

- Git `b77ad7ca589fc8d1ba26e01bc4766087f2c842f7`, initially clean; the old report's uncommitted
  Phase 6/7 work is already included in this revision. No prior work was reset or discarded.
- `uv sync --frozen`: PASS; `uv run alembic current`: `0013_security (head)`.
- Configured full regression: 461 passed, 1 preserved strict xfail, zero skips, 245.45s.
  Evidence: `docs/architecture/evidence/phase-8/baseline-validation.txt`.
- Pinned Python dependencies and semantic engine are unchanged. Node 24 is used for Studio;
  the host's default Node 16 is too old. Frontend exact versions and lockfile are committed inputs.

## Frontend checklist mapped to actual APIs

All domain paths below start `/api/v1/ontologies/{ontology_id}`. Browser calls travel through `/bff`.
Navigation checks effective permission hints; backend services reauthorize every operation.

| Frontend workflow | Actual backend contract | Sequencing / limitations |
|---|---|---|
| Verified identity and permissions | GET `/api/v1/security/me` | Requires selected authorized membership; RBAC hints only, no client ABAC engine |
| Tenant selector | New GET `/api/v1/security/tenants` | Verified identity before tenant selection; own enabled memberships only |
| Ontology list/create | GET/POST `/api/v1/ontologies` | Create writes unpublished canonical draft; namespace/identity immutable |
| Native graph/type/property/link/action editing | GET/POST `/versions`, GET/PUT `/versions/{version}` | Whole canonical draft replacement; backend Pydantic/reference validation; no separate registry |
| Concurrent draft save | PUT `/versions/{version}?expected_hash=...` | New optional hash CAS under ontology write lock, 412 on stale editor |
| Compatibility | POST `/versions/{version}/validate` | Save first; operational additive/breaking analysis, separate semantic checks |
| Publish / activate | POST `/versions/{version}/publish`, `/activate` | Separately authorized; publication freezes, activation validates/migrates atomically |
| Breaking change plans | POST `/versions/{version}/migration-plans`, `/migration-plans/{id}/approve` | Explicit updates and approval, then plan ID in publish/activate |
| Version history | GET `/versions`, GET `/versions/{version}` | Paged; published actor/time/hash; active version shown independently |
| OWL file and mapping review | POST `/interchange/imports` | PREVIEW_ONLY / CREATE_DRAFT; source, explicit mappings and conflict choices; no implicit action/policy import |
| Import provenance/vocabulary/conflicts | GET `/interchange/imports/{id}` and `/original`, `/vocabulary`, `/diagnostics` | Initiating principal private; no import listing API; use returned import ID |
| OWL exports | GET `/interchange/exports/{version}` | Published canonical Turtle plus reimport manifest; originals downloaded separately |
| Object explorer / Object Sets / traversal | POST `/object-sets/query` | Same bounded query AST, signed next cursor; Object Sets are session-local query definitions, no saved-set API exists |
| Query builder | Same query endpoint | Filters, typed operands, projection, sort, traversal; advanced AST allows compound filters |
| Object CRUD/details | Existing GET/POST/PATCH `/objects/{type}/{id}` routes | Stable IDs and expected revision; property/row policies stay server-side |
| Link changes | POST/DELETE `/links` | Both endpoints authorized; inverse traversal uses same canonical edge |
| Aggregates | POST `/aggregate` | Typed SQL aggregates; hidden fields rejected |
| Governed actions | POST `/actions/{id}/preview`, `/execute` | Typed parameters, advisory preview, explicit approval and stable replay key; execution rechecks authority |
| History/audit | GET `/actions/executions`, `/{id}`, `/{id}/audit` | Redacted history; independent permission checks |
| Sources/mappings | GET/POST `/sources`, POST `/mappings` | Publishing is immediate and separately authorized from creation; server registration IDs only |
| Ingestion runs/diagnostics | POST/GET `/ingestion/runs`, GET `/{id}`, `/{id}/diagnostics`, POST `/{id}/cancel` | Asynchronous separately configured worker; explicit refresh; no browser worker credential |
| Semantic compile/export/jobs | POST `/semantic/compile`, `/exports`, `/native-artifacts`, `/jobs`; GET `/jobs` and `/{id}` | Published/active prerequisites; asynchronous separate worker; artifacts stay distinct from operational state |
| Semantic outputs/provenance | GET `/semantic/artifacts/{id}` and `/facts`, `/approval`; POST `/approval` | Freshness and initiating-principal access rechecked; approval never materializes facts |

Complex developer contracts (action definitions, mapping manifests, migration updates, ingestion and
semantic requests) use labeled JSON editors with concrete templates. Native graph, object/property/link
editing, query building, parameter entry and execution review have dedicated controls.
No frontend engine duplicates canonical validation, SQL ABAC, ingestion conversion, or reasoning.

## Verification commands

Use Node >=22 on PATH, uv, the migrated disposable PostgreSQL database, and installed pinned engine.

```
uv run python scripts/export_openapi.py
cd apps/studio
npm ci
npm run generate:api
npm run typecheck
npm test
npm run build
cd ../..
uv run python scripts/test_studio.py
uv run python scripts/validate_phase0.py
```

The E2E runner starts a deterministic local **test-only** TLS provider on 127.0.0.1:8443, API on
127.0.0.1:8001 and Next development server on 127.0.0.1:3000. It creates a short-lived local CA and
RSA signing key under ignored artifacts, trusts only that CA, and uses actual signed RFC 9068 tokens
through the unchanged Phase 7 verifier. It uses disposable PostgreSQL schemas and explicit worker
service memberships/delegations. No test identity bypass is used for browser workflows. Ports must
be free. Test-only Node, Python and browser transports remap the fixed HTTPS issuer socket from
443 to 8443 while preserving issuer identity and real signed-token verification. Production transport
and the backend trusted-URL policy are unchanged. Never expose the deterministic provider publicly. The private test key is removed at exit.
