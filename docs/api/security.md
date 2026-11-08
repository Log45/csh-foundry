# Production identity and authorization (Phase 7)

The external provider establishes identity. PostgreSQL bindings, memberships, roles and policies
establish platform authority. No tenant, role, email, group or permission claim grants platform access.
OIDC mode and local/test modes use the same governed services, SQL query compiler and transaction
boundaries. The local provider remains an explicitly insecure development administrator.

## Configuration and supported token profile

Set `FOUNDRY_AUTH_MODE=oidc` and `FOUNDRY_TRUSTED_LOCAL_IDENTITY=false`. Configure
`FOUNDRY_OIDC_PROVIDERS` as a JSON array, at most eight providers:

```json
[{"id":"corporate","issuer":"https://identity.example/realm","audience":"foundry-api",
  "clients":["studio","worker"],"algorithms":["RS256"],"clock_skew":30,"cache_seconds":300}]
```

This supports signed **RFC 9068 JWT API access tokens**, not arbitrary OIDC ID tokens or opaque tokens.
The provider must emit `typ=at+jwt` (or `application/at+jwt`) and nonempty `iss,sub,aud,exp,iat,jti,client_id`.
`exp`/`iat` and optional `nbf` use integer NumericDates; expiration must follow issuance. Issuer,
audience, signature, allowed algorithm, expiry, issuance, not-before, client_id and optional matching
azp are checked. Optional token_use must be `access`. Supported algorithms: RS256 with RSA >=2048
bits, and ES256 with P-256. Configure the provider's API audience separately from browser login.
Client IDs are mandatory allowlists. JWT claim validation applies configured clock skew;
platform authorization retains signed exp as a strict execution deadline, so expiry grace does
not extend operational sessions. Provider-specific tokens requiring another profile are unsupported.
PyJWT 2.15.0 (MIT), cryptography and the already locked httpx implement cryptography and transport.

Provider discovery is fixed at issuer + `/.well-known/openid-configuration`; issuer must match exactly.
JWKS URLs must share the configured HTTPS origin (port 443); cross-origin/CDN JWKS need a separately
reviewed extension. No redirects, proxies, token-supplied jku/x5u/jwk, critical extensions, HTTP URLs,
credentials, fragments or query strings. Metadata/JWKS are limited to 256 KiB each, 32 keys, 3-second
network timeouts and a cooperative 5-second document budget. Provider endpoints are trusted operator
configuration and may point to private infrastructure; token claims cannot select network destinations.

Discovery/JWKS are verified at startup in OIDC mode; failure aborts startup. Keys cache for 30–3600
seconds (default 300). Unknown kids cause at most one refresh per provider per 30 seconds, including
failed refreshes. Publish overlapping keys before rotating; a just-published unknown key may reject
for up to 30 seconds. Cached known keys work during an outage until TTL expires. Expired cache,
unknown key or unavailable verification material fails closed with 401; there is no stale-key fallback.
The cache is per process, bounded by configured providers and key limits. Workers use the same verifier.

`disabled` is the default mode: domain endpoints return 401. Explicit legacy
`TRUSTED_LOCAL_IDENTITY=true` plus both server IDs retains the earlier local workflow in disabled/local
mode; it cannot coexist with OIDC or test mode. `local` additionally requires that opt-in. Keep it on
loopback and never deploy it as production authentication. `test` requires explicit server
`TEST_ISSUER`/`TEST_SUBJECT`, resolves real database memberships and uses PlatformAuthorizer;
it accepts no caller-selected test subject and offers no permission bypass. OIDC forbids test settings.
Deployment configuration must select OIDC explicitly; invalid OIDC never becomes local/test mode.

## Provisioning and tenant selection

Migrate to `0013_security`, then provision the first administrator through a trusted database operator:

```bash
uv run python -m ontology_platform.security.bootstrap \
  --tenant TENANT_UUID --issuer https://identity.example/realm --subject EXTERNAL_SUBJECT \
  --name 'Tenant name'
```

The command requires OIDC configuration and a trusted issuer. It initializes only a tenant with no
memberships and grants the explicitly named subject tenant-administrator. This is an offline operator
trust boundary, never an API startup default or first-login behavior. Existing operational data and
principal attribution are preserved; old local principals are not silently mapped to external users.
The command refuses an initialized tenant. Protect database credentials and backups; this is not an
identity-provider administration API. Disabled global principals require a database operator to restore;
tenant administrators can disable/remove membership without changing another tenant's global identity.

API clients send `Authorization: Bearer ACCESS_TOKEN`. The immutable identity key is `(issuer,sub)`.
Unknown/disabled principals and absent/disabled memberships receive 403 and gain no automatic membership.
One membership selects its tenant automatically. With multiple memberships, send `X-Tenant-ID: UUID`;
it selects an existing enabled membership, never creates authority. Invalid/foreign selections fail.
Membership and principal status are rechecked at every governed transaction. Email is not an identity key.

## RBAC and security administration

Roles are immutable named permission sets **scoped to one tenant**; assignments require composite
membership/role foreign keys. Tenant A administration confers no Tenant B access. Services check existing
colon-separated permission names (`object:query`, `action:invoke`, `schema:publish`, etc.), preserving
Phase 1–6 contracts. The catalog includes only implemented operations. Roles compose: for example,
action-executor still needs the relevant data-reader/data-editor permissions for its object effects.
No role-name branches exist in domain services. Tenant-wide RBAC is the initial scope; resource-specific
object/property boundaries are restrictive ABAC. Per-action/per-ontology RBAC assignment scopes and
global administrator roles are not implemented.

Bootstrap installs tenant-administrator plus data-reader, data-editor, ontology-editor,
schema-publisher, schema-activator, action-executor, ingestion-operator, semantic-analyst,
semantic-reviewer, ontology-importer and security-administrator. They grant nothing until assigned.
Security-administrator can manage policy/membership, but role creation/assignment additionally requires
that every delegated permission be held by the caller. Security policy management explicitly permits
changing restrictive ABAC within that tenant. Membership administration controls trusted attributes.
These are privileged tenant duties; do not assign them to ordinary data users.

All routes start with `/api/v1/security`:

| Method/path | Behavior |
|---|---|
| GET `/me` | Own verified identity, effective tenant permissions and security revision; tenant:read |
| GET `/roles` | Roles and complete permissions; security:read |
| POST `/roles` | `{id,permissions}` creates immutable role; security:role:manage plus delegated permission subset |
| POST / DELETE `/assignments` | `{principal_id,role_id}` assign/revoke; same checks |
| POST `/identities` | `{issuer,subject,principal_type,enabled,attributes}` provisions a tenant membership; security:membership:manage |
| PUT `/memberships/{principal_id}` | `{enabled,attributes}` changes own-tenant membership; same permission |
| GET `/memberships` | Own-tenant members/attributes/assignments; security:membership:manage |
| POST `/policies` | Versioned policy replacement with expected_version; security:policy:manage |
| GET `/policies` | Immutable version history; security:read |
| PUT `/delegations` | Expiring worker/initiator/ontology/job-kind binding; security:delegation:manage |
| GET `/audit` | Redacted tenant decision history; security:audit:read |

GET lists accept limit 1–100 and offset 0–10000. POST/PUT bodies are capped at 64 KiB before parsing.
The local authorizer cannot administer production security through these routes. Cross-tenant bodies
cannot override principal context. Identity provisioning accepts only configured trusted issuers in
OIDC HTTP mode, never rebinds existing identities, and cannot change an established user/service type.

## Restrictive ABAC and precedence

Policies apply to an exact ontology/type and optionally one platform principal ID. All matching
policies intersect. RBAC must first allow an operation. With no matching policy, RBAC supplies the
base allowance. A policy's allow rules OR together; deny rules OR together and are subtracted.
A deny always wins over an allow, including across policies. A deny-only policy starts from the RBAC
set. An empty rules list only restricts properties. No policy grants a missing role permission.

Each rule ANDs at most eight conditions; at most eight rules per policy. Conditions support `eq`
and `in` over an explicit constant or a **platform membership attribute**, with reserved `id` equal
to the principal's stable platform ID. `in` uses 1–16 nonnull values. Null/missing operands never
satisfy allow. A missing/malformed attribute in a deny rule denies the entire type conservatively.
Unknown properties/invalid constants reject administration; runtime type/schema/evaluation errors
fail closed. Policies are declarative data: no Python/SQL/JavaScript or arbitrary expressions.

```json
{"id":"factory-location","expected_version":0,"ontology_id":"manufacturing",
 "object_type":"Factory","principal_id":"PLATFORM_PRINCIPAL_ID",
 "visible_properties":["factoryId","factoryName"],
 "rules":[{"effect":"allow","conditions":[
   {"property":"location","operator":"eq","principal_attribute":"location"}]}]}
```

This permits only matching Factory rows and hides location itself from caller projection/filter/sort/
grouping/aggregations. Trusted policy predicates may use hidden fields. Property allowlists intersect
and also restrict changes; blind writes to hidden properties are intentionally denied. A mutation
needs current-row authority and must keep its proposed row inside the same authorized set. Create
checks defaults and all properties; delete requires permission on every removed property. Link
mutations check both endpoint rows. Restricted absence checks conservatively deny if visibility cannot
be established; unrestricted absence retains ordinary not_found semantics.

Policies compile into existing QueryGrant predicates before SQL filtering, ordering, aggregates,
traversal, counts and pagination. Legacy CRUD gets redact restricted properties; legacy count and
neighbor pages apply SQL row restrictions before counting/paging. The backend may load complete
properties internally for canonical validation/reconciliation; they are never returned without the
matching property authority. Existing query projections continue to select individual SQL JSONB keys.

Policies append immutable versions, activate with compare-and-set expected_version and bump the tenant
security revision. Set enabled=false in a new version to revoke a policy. Membership/assignment/
delegation changes also bump revision through database triggers, including direct SQL changes.
All cursors bind current grant/revision, principal, tenant and query; changes invalidate continuation.
Pages are current reads, not historical snapshots. Effective grant complexity retains existing
64-predicate/8-depth/128-node limits; over-complex combinations fail closed. More than 64 current
policies or 100 assigned roles also fails closed rather than truncating authority.

## Transactions, audit and database trust

Governed operations acquire a tenant security FOR SHARE lock before checking identity and policy.
Administration and database mutation triggers acquire the corresponding exclusive lock. Existing
operations may commit before a waiting revocation; after revocation commits, subsequent operations
observe it. A revocation cannot silently commit between a mutation's checks and commit. Principal
status uses a shared principal-row lock. Existing ontology locks still protect schema/data intervals.
No authorization cache survives a transaction or revocation. Nested services share the same session.

Every centralized permission decision and row/property denial emits a redacted audit event.
Lock-protected transaction snapshots queue at most 256 decisions per independent audit write;
denials flush immediately, and scope exit flushes remaining records before the business commit,
including on exceptions. Denied/rolled-back operations therefore retain evidence without one
commit per permission check. Events carry principal,
worker actor, operation, hashed resource, allow/deny category and security revision. No JWT, claim
body, object value, source credential or raw policy attribute enters audit. An allow decision records
authorization, not proof that the subsequent business transaction committed; action audit remains
the authoritative mutation history. Audit failure fails the caller closed. Audit uses a separate
connection: provision sufficient pool capacity for concurrent operations (default pool overflow is
bounded); exhaustion causes failure, never an unaudited allow. History is indefinite with no purge API.
UPDATE/DELETE triggers protect authorization audit, roles, external bindings and policy versions;
database owners can bypass triggers. PostgreSQL remains authoritative, with tenant-safe service
predicates and FKs. RLS and hostile database-owner isolation are not claimed. Runtime DB credentials
must be confined to the trusted backend; ordinary clients never receive direct SQL access.

## PostgreSQL owner-runtime mode

`FOUNDRY_ALLOW_OWNER_RUNTIME_ROLE=true` permits the existing application database owner to serve
as both migrator and runtime account. API and all service-worker entry points use the same narrow
ownership exception; elevated role flags remain rejected. No Foundry authorization, OIDC/service
identity, tenant boundary, grant, revocation, fencing or database constraint/trigger is bypassed.
Migration and runtime use the same configured URL without runtime table-grant refresh. External
PostgreSQL ingestion-source credentials retain their separate read-only policy. See the
[OKD4 owner-mode instructions](../operations/okd4-deployment.md).

## Background workers

Workers authenticate as provisioned OIDC service principals using client credentials and an
explicit `FOUNDRY_WORKER_TENANT_ID`. `FOUNDRY_WORKER_SUBJECT_ID` has been removed. Authorized job
submission automatically creates a durable, seven-day job execution grant in the same transaction.
No personal tokens or manual per-user worker delegations are needed. Outbox delivery continues
to use service identity and `outbox:deliver` directly.

Each claim resolves the initiating principal from the grant. Every governed transaction checks
current user membership/RBAC/ABAC, worker membership/RBAC/ABAC, grant scope/expiry/revocation,
job lifecycle and the attempt fencing token. Project access must be available to both principals.
The immutable execution context carries job, tenant, initiating and executing principals, grant
and lease token; concurrent attempts share no mutable user identity.

See [dynamic worker execution and rollout](../operations/dynamic-workers.md) for grant lifecycle,
worker provisioning, Alice/Bob examples, scheduled identities, upgrade and failure behavior.
The existing manual `/delegations` API remains for explicit delegated service operations; shared
worker execution requires job grants and does not use those records. Administrators may revoke a
job grant through `DELETE /api/v1/security/job-grants/{id}` (`security:delegation:manage`).
Authorization audit includes both identities, job ID, grant ID and attempt token.


## Phase 8 browser integration

`GET /api/v1/security/tenants?limit=100&offset=0` is the identity-scoped membership discovery
operation. It requires the same verified API access-token credentials, but no selected tenant.
It returns only enabled memberships of that enabled issuer/subject binding as `{id,name}` entries;
limit 1–100 and offset 0–10000. Caller tenant headers cannot select another identity. It grants no
permissions; `/me` and every subsequent domain operation recheck the chosen membership.

Studio performs Code + PKCE on the Next server and retains API access tokens in opaque server-side
sessions. Browser requests carry an HttpOnly cookie, exact Origin and synchronizer CSRF for BFF
operations. See [ADR 0029](../decisions/0029-browser-session-and-studio.md) for cookie/session bounds,
single-process deployment, logout, issuer contracts and future identity-broker integration.

### Operator-configured additional OIDC CA

`FOUNDRY_OIDC_CA_BUNDLE` optionally names a PEM CA bundle readable by the API or worker process.
Its roots are added to HTTPX's normal trusted roots. Hostname verification and certificate-chain
verification remain mandatory, as do trusted HTTPS issuer/endpoint rules. Missing/invalid bundles
fail startup rather than disabling verification. This allows explicitly trusted local/private
issuers without `verify=False` or implicit proxy/environment trust. See
[local Keycloak setup](../development/keycloak-local.md).
