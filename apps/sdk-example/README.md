# Foundry React SDK example (template foundry-react-next-v1)

Working React/TypeScript Next.js application consuming @foundry/sdk and @foundry/react.
It reuses Studio's actual auth, JSON BFF and binary BFF route implementations, imported server-side;
there is no copied authentication implementation or browser bearer token.

From repository root, use a supported Node (26.7 tested) and synced uv environment:

```sh
npm ci
npm run build -w @foundry/sdk
npm run build -w @foundry/react
npm run dev -w @foundry/sdk-example
```

Configure the process environment using the same values documented in apps/studio/README.md:
STUDIO_ORIGIN=http://127.0.0.1:3200, STUDIO_API_ORIGIN=http://127.0.0.1:8000,
STUDIO_OIDC_ISSUER, STUDIO_OIDC_CLIENT_ID, STUDIO_API_AUDIENCE. Register this exact origin's
/auth/callback with your approved development identity provider; use your existing authorized
provider setup. Do not provision external resources through this template. All these variables are
server-only. HTTPS is required outside explicitly permitted loopback/internal development settings.
Existing durable browser state additionally uses STUDIO_STATE_SECRET with the API's configured state
keys/secret; never place these in NEXT_PUBLIC variables. No secrets are included in this example.
NEXT_PUBLIC_FOUNDRY_API_BASE optionally selects the BFF's API path (default /api/v1); the existing BFF
accepts /api/v1 only. It is build-time public configuration, never a secret/API origin/token.

The backend, PostgreSQL, configured ArtifactStore and execution worker must already run in your local
development environment. Do not automatically migrate the shared developer database. Use the existing
platform administration/Studio to prepare authorized resources. Sign in, select your tenant and query
an active ontology/type. Query results use explicit cursor pagination (ten rows per page). Enter exact
dataset and immutable version UUIDs to inspect schema and ten preview rows; enter pipeline/materialization
job UUIDs for bounded monitoring, and mapping UUID for metadata. Jobs are started through governed APIs
or Studio; the example does not schedule work. Materialization metrics and partial-commit warning remain
visible even after cancellation/failure. Errors display categories/codes; session expiry discards the
client/private UI and restores sign-in. Tenant switching invalidates old client before selection.

`npm run build -w @foundry/sdk-example`, `npm run typecheck -w @foundry/sdk-example`.
For isolated real OIDC/PostgreSQL browser acceptance:

```sh
STUDIO_E2E_APP=apps/sdk-example STUDIO_E2E_PORT=3200 \
  uv run python scripts/test_studio.py
```

The test runner owns disposable schemas and a loopback test IdP; it does not use production identity.
Full data/worker validation uses scripts/validate_phase15.py with a private MinIO project. The SDK
integration tests use actual API/service transactions; browser acceptance covers the real BFF.
No deployment is performed. Production remains blocked under PLANS.md Section 23B.
