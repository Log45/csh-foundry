# ADR 0029: Native Studio and provider-independent browser sessions

Status: accepted for approved Phase 8 implementation.

Next.js is one application with two workspaces over the existing canonical registry. It adds no
operational datastore, authorization engine, RDF store, reasoning implementation or persistent
Object Set service. React native graph and forms edit canonical JSON; backend Pydantic validation
and governed services remain authoritative. Complex declarative developer contracts have labeled
JSON editors, preserving unsupported-feature diagnostics rather than inventing endpoints.

The browser authenticates using Authorization Code + PKCE S256 through a configured public OIDC
client. Discovery issuer and authorization/token/JWKS origins must match trusted configuration;
redirects are rejected. Code exchange, signature/issuer/audience/expiry checks, state, nonce and API
token-profile checks occur on the Next server. Only the API access token is retained. It is never
serialized into HTML, React props, localStorage, sessionStorage, URLs or browser-accessible cookies.
The configured broker must support separate login/API audiences and the Phase 7 RFC 9068 profile.
Identity remains issuer/subject. Email, group, provider tenant and role claims never establish
platform authority. Microsoft Entra ID and Google sign-in remain Phase 10 work through this contract;
external provider API tokens must not be forwarded unchanged unless they meet the approved profile.
Keycloak is an optional interchangeable broker, not a new required service.

Browser cookies contain 256-bit random opaque IDs; server maps store only SHA256 keys. Login
transactions are bound to a separate HttpOnly cookie, expire in five minutes and consume once.
Session cookies are HttpOnly, SameSite=Lax, host-only, Path=/ and Secure on HTTPS. HTTP is accepted
only on loopback origins for local development. Session lifetime is bounded by signed API token
expiry and one hour; no silent refresh or offline token storage. Logout removes server state.
Session state is bounded to 1,000 concurrent sessions and 1,000 pending logins; expired entries are
pruned at admission. Process restart invalidates sessions; one Next process/replica is supported.
Horizontal encrypted persistence and broker-wide logout are explicit later deployment decisions.
No backend credential or database access is given to Next.

Every browser POST requires exact configured Origin. Tenant selection, logout and BFF also require
per-session synchronizer CSRF tokens. Read-only session bootstrap has no mutation. Auth and BFF
responses are no-store. Login starts with a same-origin fetch and navigates to the returned trusted
URL; a CSP-restricted native form redirect is not required. Referrer policy on auth responses avoids
callback-code referrers. Script/style policy permits Next bootstrap inline scripts/styles; unsafe-eval
is allowed only in development for React debugging. React text rendering escapes data; no raw HTML
rendering is used. A per-request nonce CSP can further harden a future public deployment.

The BFF accepts only methods/routes present in the checked-in generated OpenAPI contract, rejects
encoded separators/dot segments and unknown query keys, and uses a fixed operator API origin.
No browser-provided authorization, cookies, tenant headers, arbitrary upstream URLs or redirects
are forwarded. Payload and response sizes and network waits are bounded. Only sanitized backend
error codes cross this boundary. All domain requests carry a server-selected tenant and the actual
API bearer credential. FastAPI independently verifies it and rechecks memberships, RBAC, SQL ABAC,
revocation, schema lifecycle and transaction rules. The BFF is not an authorization cache.

Membership discovery is a narrowly scoped new identity-service read before tenant selection. It
lists only the verified subject's enabled memberships with bounded pages. Selecting a tenant calls
existing `/security/me` with that selection before updating the server session. Browser navigation
is an affordance based on effective permissions; manually calling a hidden operation never grants
backend authority. Unsaved/cached operational views are discarded on tenant changes/logout/expiry.

Draft saves optionally pass expected_hash. RegistryService compares it to the current canonical
hash while holding the existing ontology write lock, returning 412 before mutation on mismatch.
The parameter is backward compatible; published immutability and separate publish/activate checks
remain. It provides editor collision protection without Phase 9 branching or collaboration.
