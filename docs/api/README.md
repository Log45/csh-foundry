# Phase 0 API

Run `uv run uvicorn ontology_platform.main:create_app --factory --host 127.0.0.1`.

| Endpoint | Behavior |
|---|---|
| GET /health/live | 200 `{"status":"ok"}`; does not contact PostgreSQL |
| GET /health/ready | 200 `{"status":"ready"}` after connectivity and migration check; otherwise 503 |
| GET /api/v1/openapi.json | Versioned OpenAPI document |
| GET /docs | Interactive OpenAPI documentation |

Errors use `{"error":{"code":"...","message":"..."}}`; internal exceptions do not
expose database details or credentials. API mutations and object queries are Phase 1+.
The current readiness revision is `0001_tenants`; update it with future migrations.
