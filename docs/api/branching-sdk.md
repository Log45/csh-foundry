# Phase 9 branches and generated SDKs

All paths are under `/api/v1/ontologies/{ontology_id}`. Every operation authenticates using the
existing Phase 7 API access-token profile and selected authorized tenant. `schema:read` governs
branch/schema comparison and SDK disclosure; `schema:write` governs branch authoring, merging,
abandonment and draft handoff. These permissions do not confer `schema:publish`, `schema:activate`,
`migration:plan` or `migration:approve`. Existing RBAC, tenant security locks, revocation and audit apply.

## Branch contracts

| Method/path | Request / result |
|---|---|
| POST `/branches` | `{name,base_version?,description?}` → BranchView; omitted base selects current active published version |
| GET `/branches` | Branch metadata, name/UUID order; limit 1–100, offset 0–10,000 |
| GET `/branches/{id}` | Branch lifecycle, immutable base, head revision/hash, creator/updater/timestamps |
| GET `/branches/{id}/head` | Canonical head snapshot, parent, hash, actor, summary, provenance |
| GET `/branches/{id}/revisions` | Immutable snapshots, newest revision first; bounded limit/offset |
| POST `/branches/{id}/edit` | `{expected_revision,definition,summary}` → updated BranchView |
| POST `/branches/{id}/compare` | ComparisonInput → stable-ID changes, values, affected-definition compatibility, source/target hashes |
| POST `/branches/{id}/merge-preview` | MergeInput → proposed canonical schema, conflicts, diagnostics, compatibility and migration/publication implications |
| POST `/branches/{id}/merge` | Same resolved MergeInput plus exact preview_hash → immutable merge record and new target revision |
| POST `/branches/{id}/abandon` | `{expected_revision}` → terminal ABANDONED state; retained history |
| POST `/branches/{id}/draft` | `{expected_revision,version}` → new ordinary governed draft; no replacement of existing versions |
| GET `/merges` | Immutable merge provenance, newest first; bounded limit/offset |

Branch names are labels unique within the tenant/ontology; UUIDs are stable identity. Lifecycle is
ACTIVE → MERGED (source after successful merge) or ACTIVE → ABANDONED. Terminal branches reject
edits/merges. A MERGED snapshot can still be handed off explicitly to a draft; abandoned branches
cannot. There is no delete/reopen/rebase API. Every branch pins one published version and hash;
active-version changes cannot move its base. Branch edits retain the base version string. Select a
new semantic version during draft handoff. Operational objects/relationships are never branched.

Comparison defaults to base versus selected head. Set `source_revision` for an earlier source;
choose exactly one of `target_branch` (optional `target_revision`), `target_version` (published), or
`active:true`. To compare revisions on one branch, set its own UUID as target_branch. Results are
sorted by stable JSON-pointer paths, never display names or JSON insertion order. Each change carries
the stable definition ID, previous/proposed values and classification from the existing compatibility
classifier applied to the affected definition slice. Source/target refs and hashes identify inputs.

## Merge semantics and resolution

The initial merge contract requires two ACTIVE branches with the same immutable published base;
it does not guess ancestry or silently rebase branches with unrelated published bases. It compares
base, target and source, recursively combining independent fields and ID-keyed object/property/link/
action/parameter collections. Existing target order is retained, new IDs append sorted. Ordered
action bindings/operations and ordinary JSON/enum arrays are atomic. Identical concurrent changes
coalesce. Concurrent different edits, remove/modify and incompatible same-ID additions conflict.
Schema reference/type/constraint validation runs on the complete result.

```json
{"source_branch":"SOURCE_UUID","source_revision":2,"target_revision":3,
 "resolutions":[{"conflict":"/object_types/Machine/properties/machineName/name","strategy":"source"}]}
```

A resolution selects `target`, `source`, or `manual` with `value` (and optional `delete:true`). It
must identify an actual conflict; duplicates/unknown conflicts fail. Missing and explicit null values
remain distinguishable through presence flags. Invalid combined cross-definition references produce
`/$schema` with canonical diagnostics. Resolve that explicitly using a complete manually resolved
canonical schema or a complete target/source schema. Manual values cannot bypass validation or change
tenant/ontology/namespace identity. Ordered action arrays must be supplied as complete declarations.

Preview is non-mutating and includes exact revisions/hashes, resolutions, changes, validation,
compatibility, migration requirements and publication implications. Execute resends those inputs and
`preview_hash`. The server recomputes under the ontology write lock and rechecks authority before
commit. Stale revisions return 412 `branch_changed`; stale resolved previews return 412
`stale_preview`; unresolved/invalid results return 409 `merge_conflicts`. Unrelated bases return 409
`unrelated_base`. Conflict count/complexity violations fail explicitly. A preview grants no authority.

Execution atomically appends target revision and merge provenance (base/source/target/result hashes,
revisions, resolution choices, author/time/outcome), and marks source MERGED. Late failure rolls back
all three. Source history stays immutable. Draft handoff uses RegistryService within the same governed
transaction. Breaking changes may be developed/merged into drafts, but publication and activation
still require approved hash/base-bound migration plans. Merge never publishes or activates anything.

## SDK issuance and download

| Method/path | Request / result |
|---|---|
| POST `/sdk/generate` | `{version,language:"python"|"typescript"}` → completed ArtifactView |
| GET `/sdk/artifacts` | Authorized metadata/manifests; bounded limit/offset |
| GET `/sdk/artifacts/{id}` | Current-authority metadata inspection |
| GET `/sdk/artifacts/{id}/download` | `{filename,media_type,archive_base64,sha256}`; base64 deterministic ZIP for existing JSON BFF |
| POST `/sdk/compatibility` | `{previous_version,version}` → existing compatibility analysis, affected symbols, regeneration and migration guidance |

Generation accepts published versions only. Mutable branches, merge previews and ordinary drafts
are not production SDK sources. Completed artifacts are deduplicated by deterministic ZIP hash in
one tenant/ontology. Current schema readers can retrieve them; knowing an artifact ID is insufficient.
Downloads recheck tenant/ontology authority and archive hash. No artifact is public. No generation
implicitly changes a schema or starts a job/activation. Bounded synchronous compilation uses existing
PostgreSQL storage and ontology locking; no new queue or object store exists.

The manifest includes tenant, ontology, published version/hash, actual API contract hash, generator
version, language, source symbols, reproducible epoch and per-file hashes. `artifact_content_hash`
hashes the sorted source-file digest map excluding manifest.json; issuance `content_hash` separately
hashes the complete deterministic ZIP. Manifest cannot hash itself. Actor/time is issuance metadata
outside generated source. Fixed ZIP epoch, permissions and file ordering make regeneration identical.
Changing API contracts, generator code/version or canonical input requires regeneration. No credential
or session value is included. Published schema JSON is included for source/constraint inspection.

## Python package

Unzip and `uv pip install /path/to/package`, or install with pip in an isolated Python >=3.12 venv.
The emitted package pins the tested Pydantic 2.14.1 and httpx 0.28.1 runtimes and imports no backend.

```python
from decimal import Decimal
from ontology_sdk import OntologyClient, SDKError
from ontology_sdk.models import UpdateMachineStatusParameters

async def token_provider() -> str:
    return await credentials.platform_api_access_token()

client = OntologyClient("http://localhost:8000", token_provider, tenant_id)
machine = await client.Machine.get("MCH-005")
query = (client.Machine.query()
         .where(client.Machine.fields.temperatureCelsius.gt(Decimal("80")))
         .where(client.Machine.fields.operationalStatus.eq("CRITICAL"))
         .limit(2))
page = await query.execute()
if page.next_cursor:
    next_page = await query.after(page.next_cursor).execute()
factory_page = await client.Machine.related_locatedInFactory("MCH-005").execute()
parameters = UpdateMachineStatusParameters(
    machineId="MCH-005", newStatus="STOPPED", expectedRevision=machine.version)
preview = await client.actions.UpdateMachineStatus.preview(parameters)
result = await client.actions.UpdateMachineStatus.execute(
    parameters, idempotency_key="my-stable-operation-key")
await client.close()
```

These examples require the published manufacturing action definitions. Other schemas use aliases
from their manifest. Generated read, create, patch and action parameter models preserve canonical
wire aliases; imported names and unsafe/reserved identifiers receive deterministic aliases.
Read properties are optional because projection/ABAC may omit even required stored properties.
Use `model_fields_set` or `model_dump(exclude_unset=True)` to distinguish absence from explicit null.
Dates, aware timestamps, UUIDs and decimals serialize to canonical strings. Decimal floats and naive
timestamps reject. Nullable inputs preserve explicit null; missing create/action fields retain server
default semantics. The backend remains authoritative for every constraint and permission.

`Field.eq/ne`, ordered-field `gt/gte/lt/lte`, text-field matching, null checks and `Expr` `&`, `|`, `~`
emit the existing AST. Immutable Object Sets support order_by/select/limit/after/offset, bounded
traverse and aggregate. Generated related_* methods return the declared target model, including
inverse relationships. Direct repository create/patch/delete use governed object APIs; patch/delete
require expected_version. Business operations use the generated Action wrapper. Action history uses
the existing bounded execution endpoint. No SQL/SPARQL/local filtering or saved-set persistence exists.

## TypeScript package

Unzip, `npm install`, then `npm run build`; import from the resulting independent package.
It uses Fetch and platform runtime APIs and does not import Next.js. The package pins TypeScript
5.9.3 for strict builds and supports Node >=22 with Fetch/structuredClone.

```typescript
import { OntologyClient, SDKError } from "@ontology/generated-sdk";
const client = new OntologyClient({ baseUrl, tenantId, tokenProvider });
const machine = await client.Machine.get("MCH-005");
const query = client.Machine.query()
  .where(client.Machine.fields.temperatureCelsius.gt("80"))
  .where(client.Machine.fields.operationalStatus.eq("CRITICAL"))
  .limit(2);
const page = await query.execute();
if (page.next_cursor) await query.after(page.next_cursor).execute();
await client.Machine.related_locatedInFactory("MCH-005").execute();
const parameters = { machineId: "MCH-005", newStatus: "STOPPED" as const,
                     expectedRevision: machine.version };
await client.actions.UpdateMachineStatus.preview(parameters);
await client.actions.UpdateMachineStatus.execute(parameters, "my-stable-operation-key");
```

Decimal/date/timestamp/UUID values remain strings; no decimal float conversion occurs. Integers use
JavaScript safe integers only: unsafe integer or nonfinite numbers reject on request/response.
This also rejects integer-valued floats outside the safe-integer range. Arrays and JSON retain JSON
structure. Missing read properties are optional; nullable values are explicit null. TypeScript types
are developer aids: actual canonical validation and authorization occur in FastAPI.

## Shared transport behavior

Caller-supplied async token providers return platform API bearer tokens per request. Providers may
change without changing generated SDKs if they issue the documented Phase 7 token profile. Browser
opaque session cookies, external IdP tokens, worker credentials and connector secrets are distinct.
The SDK does not implement OAuth callbacks, broker login or token persistence. Caller-supplied HTTP/
Fetch transports support testing, but never change server security enforcement.

SDKs use query aliases for opaque object IDs (including slash/Unicode), the existing active schema,
30-second HTTP deadlines, no redirects, and a 5 MiB decoded response bound. Responses carrying a
schema_version different from the generated version fail explicitly; old SDKs cannot request
historical operational schemas. SDKError retains status, structured server code/body and response.
No automatic retries, changed idempotency keys, conflict overwrite or cursor restart occurs.
Cursor pages are current reads, not snapshots. Reuse the exact query and explicit next_cursor.
Changing schema/policy/anchor can invalidate continuation; handle the returned error explicitly.

## CLI

Local trusted export workflow uses the real VersionView JSON and exported OpenAPI:

```bash
uv run python scripts/export_openapi.py
uv run python -m ontology_platform.sdk \
  --input published-version.json --openapi apps/studio/lib/openapi.json \
  --tenant TENANT_UUID --ontology manufacturing --version 1.0.0 \
  --language python --output /tmp/manufacturing-sdk
# Repeat with --check to compare without changing generated files.
```

Local files are trusted operator exports; their status/identity/hash is verified, but possession of
files is not API authorization. Remote workflow substitutes `--base-url https://platform.example`
for `--input/--openapi`, sets `FOUNDRY_SDK_ACCESS_TOKEN` in the caller's environment, and retrieves
published inputs through authorized FastAPI. `--token-env` selects another environment variable.
No production DB credential is needed. Output must be empty; `--check` does not overwrite changes.
Both languages use the same generator as API issuance, and print the deterministic manifest.

## Studio and bounds

Ontology Manager's “Schema branches and SDKs” panel uses the existing server-side authenticated BFF.
It supports branch lists/pages, creation/selection, saved-head graph, canonical JSON editing, base/
active comparisons, newest history page, resolved merge preview/confirmation/abort, provenance,
abandonment and explicit new-version draft handoff. Existing Manager controls publish/activate.
SDK controls select published version/language, show completed artifacts/manifests/compatibility and
download private ZIPs. Manufacturing usage examples are explicitly labeled. Tokens remain server-side.
Complex branch edits and manual conflict values use JSON; graph diff highlighting is not implemented.
Comparison of arbitrary versions/earlier revisions and paging deeper history are available through
bounded APIs; the UI exposes the common base/active comparison and newest 50 history records.

| Resource | Bound |
|---|---|
| Branch/SDK HTTP POST body | 64 KiB before JSON parsing |
| Canonical branch/generator schema | 64 KiB UTF-8 canonical JSON |
| Branch count / artifacts per tenant+ontology | 100 each, retained history |
| Branch/history/merge/artifact API pages | 1–100; offset 0–10,000 |
| Three-way traversal | 32 nesting levels, 20,000 visited nodes |
| Conflicts / selected resolutions | 128 each |
| Merge provenance | 64 KiB JSONB text |
| Generated source / stored escaped file JSON | 4 MiB / 8 MiB |
| SDK HTTP response | 5 MiB decoded |
| Concurrent generation | One per ontology via existing PostgreSQL lock |

Raw previews contain bounded inputs/result/conflicts, so their size follows these schema/conflict
bounds; they are not unbounded diagnostic archives. Revision/merge history is immutable and retained;
no automatic retention or aggregate byte quota exists. Database owners remain trusted. Production
admission, backup/restore, distribution signing and live SSO belong to Phase 10, not this feature.
