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

## Projects (Phase 11)

The Projects tab uses the same BFF, selected tenant and opaque authenticated session. It appears
with `project:read`; creating a Project also requires `project:create`. Owner/editor/viewer roles
further restrict the caller's platform permissions. Owners manage membership/shares/Project lifecycle;
editors organize folders and resources; viewers browse. Schema permission is additionally required
for ontology resource discovery. No Project role grants object, property or action access.

Create/select a Project, navigate direct folder children using the breadcrumb, and register a page
of assets from a published ontology ID/version. Resources open the canonical ontology in Manager.
Move assets using a stable destination folder ID (blank means root). Membership uses platform
principal IDs; sharing uses an accessible target Project ID. Explicitly load share pages and select
`Show resources shared with this Project` to browse incoming references. All lists paginate.
Archived Projects remain selectable but read-only; archive does not delete canonical definitions.
Refresh after 412 conflicts, revocation or membership changes. The backend rechecks all operations.
See [contracts and limits](../../docs/api/projects.md).

Project resources now support generic artifacts: create a logical artifact, upload a file up to
64 MiB, inspect version history/checksums, download verified versions, archive and share through
the existing resource controls. Binary transfers use `/bff/artifacts`, with session, CSRF and
expected-tenant checks. Storage credentials stay in FastAPI. Storage setup is documented in
[artifact operations](../../docs/development/artifact-storage.md); unavailable storage fails visibly.

Phase 13 adds independent, Project-governed datasets with immutable source versions, full-content
CSV/JSON/NDJSON/Parquet validation, schema history and bounded previews. See the
[dataset API and validation contract](../../docs/api/datasets.md). Studio supports dataset creation, upload,
validation errors, source download, version history, schema and preview in Project folders.
Production remains blocked; Phase 14 is not implemented.


Phase 14 adds a structured JSON pipeline editor, immutable definition publication, pinned run inputs,
run monitoring/cancellation/retry and authorized lineage. Dataset checksums use 1 MiB slices, and
the fixed binary BFF streams up to 1 GiB. Large validation is queued; a separately operated durable
worker processes it. Refresh validation/history to recover after navigation. See
[execution limits](../../docs/development/execution-workers.md). Production remains blocked.

Phase 15 Project resources include MAPPING. The mapping panel accepts a closed JSON definition with
canonical ontology resource/version, identity columns, property conversions and relationship endpoints;
users supply explicit dataset/version UUIDs. It offers structural validation, immutable publication,
sample preview, durable full-source validation, materialization, run refresh/cancel/retry, reconciliation
counts, canonical object inspection and access-controlled provenance. Samples are labeled separately
from full validation. Partial transactional batch visibility is shown explicitly. Existing BFF session,
CSRF and tenant-context rules apply; no storage/worker credentials enter the browser.
