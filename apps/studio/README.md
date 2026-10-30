# Foundry Studio — Phase 8

One Next.js application for native Ontology Manager and operational Ontology Studio.
The canonical registry, data, authorization and jobs remain in the existing FastAPI/PostgreSQL backend.

Use **Node 22 or newer** (verified Node 24), npm and the Phase 7 API. From this directory:

```
npm ci
npm run dev
```

Set these server-side environment variables before starting Next:

```
STUDIO_ORIGIN=http://127.0.0.1:3000
STUDIO_API_ORIGIN=http://127.0.0.1:8000
STUDIO_OIDC_ISSUER=https://YOUR-TRUSTED-BROKER/realm
STUDIO_OIDC_CLIENT_ID=studio
STUDIO_API_AUDIENCE=foundry-api
```

The browser client must support Authorization Code + PKCE S256 and `openid` scope, with redirect URI
`STUDIO_ORIGIN/auth/callback`. Token exchange uses `client_id` and PKCE (a registered public client,
no client secret). The broker must mint RFC 9068 API JWT access tokens with the API audience,
`client_id=studio` and the documented Phase 7 claims. API configuration must trust that issuer and
allow the studio client. Browser ID tokens and API access tokens have separate audiences. Provision
issuer/subject platform memberships through Phase 7 tooling; login grants nothing automatically.

The server keeps access tokens in a bounded process-local session store. Browser cookies contain
opaque random IDs, HttpOnly, SameSite=Lax, Path=/ and Secure for HTTPS origins. Production origins
must use HTTPS; HTTP is accepted only on explicit loopback origins for local development. Sessions
expire at access-token expiry or one hour, whichever comes first. No refresh tokens are requested
or persisted. Sign out invalidates the local session; broker-wide single logout is not implemented.
Restart clears sessions. Run **one Next process/replica**; horizontal session persistence is deferred.
Never expose development mode or the deterministic test provider publicly.

Select a tenant, then an ontology. Manager provides a native graph, object/property/relationship forms,
action-definition editor, drafts/history, compatibility, separate publication/activation and OWL
mapping review. Studio provides typed queries, session-local Object Sets, traversal, action previews
and approved execution, ingestion requests/history and semantic artifacts/jobs/facts/provenance.
Complex developer contracts use JSON editors. Backend errors appear as stable sanitized codes.
Workers remain separate; submit does not synchronously complete ingestion or reasoning.

```
npm run typecheck
npm test
npm run build
# From repository root, with disposable PostgreSQL and pinned semantic engine:
uv run python scripts/test_studio.py
```

To regenerate contracts from actual source, run `uv run python scripts/export_openapi.py` at repository
root, then `npm run generate:api` here. This generates application contract types, not Phase 9 SDKs.

Docker development: configure `.env` and Phase 7 OIDC, then run from repository root:

```
docker compose --env-file .env -f infrastructure/compose.yaml --profile studio up --build
```

Compose publishes Studio on loopback 3000 and API on loopback 8000. Its explicit internal HTTP flag
permits BFF-to-API traffic on the private Docker network. Use HTTPS and appropriate network controls
for any future external deployment. This phase does not deploy or configure an external broker.

See [Phase 8 checklist](../../docs/development/phase-8.md) and
[browser session architecture](../../docs/decisions/0029-browser-session-and-studio.md).

## Phase 9 development workflows

Manager includes Schema branches and SDKs through the existing authenticated BFF. Branches have
explicit published bases, revision guards, canonical JSON editing, saved schema graphs, comparisons,
resolved merge previews/confirmation, history and draft handoff. Published-only SDK generation displays
private manifests and downloads deterministic Python/TypeScript ZIPs without browser bearer tokens.
See [contracts and documented UI limits](../../docs/api/branching-sdk.md).
