# Studio OIDC callback investigation

Scope: targeted authentication investigation and diagnostics; no roadmap phase advancement,
production deployment, schema migration, or authentication-policy change.

## Finding

**Production root cause remains unconfirmed. Probable cause: an issued-token contract mismatch,
particularly missing `client_id` or missing `foundry-api` audience.** Both reproduce the exact
`401 {"error":{"code":"authentication_failed"}}` with real signed JWTs in local tests.
Signature/key errors, expired tokens, and issuer mismatch also reproduce it. No production token,
callback trace, Keycloak version, or deployed image revision was available to distinguish them.
This diagnosis assumes the deployed image matches the checked-out code.

Confirmed defect: the callback catches non-BoundaryError exceptions and hides their cause without
logging. The patch adds safe diagnostics while preserving existing client responses and checks.
It does not itself correct a provider token profile.

## Exact path and flow (line numbers after diagnostic patch)

| Step | Source | Behavior |
| --- | --- | --- |
| Route | `apps/studio/app/auth/[operation]/route.ts:33` | `handle`, exported through `protectedHandle` as GET/POST at lines 136–137; callback branch at line 49 |
| Start | Same route, line 41 | POST `/auth/login`, exact Origin check, `beginBrowserLogin`, `authorization`; opaque `foundry-login` cookie, 300 seconds, HttpOnly/SameSite=Lax/Secure on HTTPS |
| Random inputs | `apps/studio/lib/server.ts:81`, `:195` | Independent 32-byte random ID, state, nonce, verifier; SHA-256/base64url PKCE challenge |
| Persistence | Same server, lines 160, 195 | With state credential, PUT login data to `/internal/browser-state/login/<SHA256(id)>`; cookie contains only ID, not state/verifier |
| Authorization | Same server, line 397 | Discovery checks exact issuer and same-origin endpoints, S256 support; redirect URI is configured origin plus `/auth/callback`; scope `openid` |
| Consume | Same server, line 215 | DELETE login record atomically; compare returned state and expiry; single use |
| Exchange | Same server, line 414 | Rediscover; POST form with authorization code, client ID, exact same redirect URI, saved PKCE verifier; no client secret or Basic authentication |
| Token envelope/JWKS | Same server, lines 436, 445 | Require Bearer, string ID/access tokens with size limits; bounded same-origin JWKS |
| ID JWT | Same server, lines 455, 461 | Verify signature (RS256/ES256), exact issuer, Studio audience, sub/iat/exp/nonce; verify nonce and azp binding |
| API JWT | Same server, lines 471, 477 | Independently verify signature, issuer, API audience, sub/exp/iat/jti/client_id; require RFC 9068 header, subject/client binding, NumericDates and lifetime |
| Session | Same server, lines 223, 498 | Persist only API access token and CSRF value server-side; expiry capped below one hour in durable mode |
| Response | Route, lines 62–69 | Revoke prior browser session, set opaque `foundry-session`, clear login cookie, 303 to Studio origin |
| Subsequent access | Route, lines 71–92 | `/auth/session` lists tenants and optionally calls `/api/v1/security/me`; platform membership/roles enforced by API |

Production uses PostgreSQL browser state through FastAPI, encrypted by
`services/api/src/ontology_platform/security/browser.py:42` (`BrowserStore`); it does not use
process-local sessions. Development without `STUDIO_STATE_SECRET` uses memory. No API bearer-token
verification or membership establishment happens during callback: internal state calls authenticate
with the shared service secret. Domain API token verification happens later in
`services/api/src/ontology_platform/security/oidc.py:144` (`OIDCVerifier.verify`).
Realm roles/email are not callback prerequisites and do not grant platform membership.
`FOUNDRY_AUTH_MODE` is backend configuration; Studio independently requires its OIDC settings.

## Failure paths

There is one fallback construction of `authentication_failed`: route lines 114–123. It handles
any non-BoundaryError thrown inside the handler's try block, including other auth operations.
For callback, sources include:

- `jwtVerify` / JWKS processing: missing claims, issuer/audience mismatch, expiry, invalid signature,
  unsupported keys/algorithms, malformed JWTs.
- Discovery/token/JWKS fetch rejection or timeout, stream read failure, JSON parsing or malformed
  provider document producing a native TypeError. Discovery success does not prove JWKS reachability.
- Internal browser-state JSON parsing/shape errors, unexpected cookie/state data (including native
  timing-safe comparison errors), or unexpected session/response exceptions.

Cookie loading and route parameter resolution precede the try; failures there do not use this fallback.

Expected policy failures preserve their own sanitized codes:

| Condition | Response |
| --- | --- |
| Expired/missing local login or mismatched state | 401 `invalid_login_state` (durable missing state: `session_expired`) |
| Token HTTP error, including invalid_client or invalid_grant from PKCE/code/redirect failure | 502 `identity_provider_unavailable` |
| Invalid discovery/issuer metadata | 502 `invalid_discovery` |
| Missing/oversize code | 401 `invalid_code` |
| Invalid token envelope/JWKS count | 401 `invalid_token_response` / `invalid_jwks` |
| Nonce or ID azp mismatch | 401 `invalid_nonce` |
| Valid JWT with wrong typ, wrong existing client_id/azp or subject binding | 401 `invalid_access_token` |
| State service transport/HTTP failure | 503 `session_store_unavailable` (401 maps to `session_expired`; 409 retains status) |
| Missing/short production state credential | 503 configuration error |

Thus missing audience/client_id fits the reported response; a valid JWT with only `typ=JWT`
does not. Multiple provider defects can coexist: fixing audience/client_id may expose typ next.
An invalid-code token test does not establish successful exchange, but makes absent client
authentication less compelling; code itself explicitly expects a public client.

## Minimal fix and Keycloak settings

Keep verification intact. First deploy diagnostic code and initiate a fresh login. Example:

```json
{"event":"studio_auth_callback_failed","stage":"access_token","category":"ERR_JWT_CLAIM_VALIDATION_FAILED","claim":"client_id","status":401}
```

Only fixed stage/category, allowlisted claim name and numeric status are logged. No raw exceptions,
stacks, JWT payloads, URLs, provider response bodies, codes, cookies, state, verifier or secrets.
Diagnostics are always on for failed callbacks and require no timing/debug flag.

Compare the `foundry-studio` client's effective settings to the existing tested reference in
`services/api/src/ontology_platform/security/broker.py:135` (do not import its entire realm):

- Public client / Client authentication OFF; Standard flow ON; S256 required; implicit/password
  grants OFF. No Studio client secret is supported or required. Worker remains confidential.
- Exact redirect URI `https://foundry.csh.rit.edu/auth/callback`; web origin
  `https://foundry.csh.rit.edu`; RS256 signing.
- Dedicated client scope or a default assigned scope with an Audience mapper: Included Custom
  Audience `foundry-api`, Add to access token ON, Add to ID token OFF. An `audience` authorization
  query parameter alone is not evidence that the issued JWT contains the audience.
- Hardcoded claim mapper: Token Claim Name `client_id`, Claim value `foundry-studio`, JSON type
  String, Add to access token ON, ID/userinfo OFF. Do not retain the reference value `studio`.
- RFC 9068 access-token header enabled (`access.token.header.type.rfc9068: "true"`), full JWT
  access tokens (`client.use.lightweight.access.token.enabled: "false"`), standard sub/iat/exp/jti
  claims. Header `typ` is distinct from a payload claim named `typ`.

Official references: [Keycloak administration: client scopes/audiences/mappers](https://www.keycloak.org/docs/26.2.5/server_admin/)
and [Keycloak source: RFC 9068 attribute](https://github.com/keycloak/keycloak/blob/main/server-spi-private/src/main/java/org/keycloak/protocol/oidc/OIDCConfigAttributes.java).
Live Keycloak version/support remains unknown. If it cannot mint this profile, document the
limitation and use the repository's separately approved broker integration process, without relaxing
Studio or backend validation. Do not add a second broker as part of this debugging task.

## OKD4 web-console procedure

No cluster changes have been made. Use the project's supported build process to build an image
containing the diagnostic patch, then in the OpenShift console:

1. Select the Foundry project. Open **Workloads → Deployments → Studio deployment → YAML** and
   update only the Studio container `image` to the newly built immutable image reference. Save and
   watch the rollout and pod readiness. Menu names can vary by console version/perspective.
2. In **Workloads → ConfigMaps**, inspect the ConfigMap actually referenced by Studio's Deployment
   (`envFrom` / `env`). The verified Studio origin, API origin, issuer, audience and
   `STUDIO_OIDC_CLIENT_ID=foundry-studio` need no further changes. Confirm the API's effective
   `FOUNDRY_OIDC_PROVIDERS` includes `foundry-studio` and `foundry-api`, as already reported.
3. Inspect Deployment `command`/`args`, `volumeMounts` and `volumes`. The standard image starts
   `node studio-entry.mjs`; `infrastructure/docker/studio-entry.mjs:1` reads and trims
   `STUDIO_STATE_SECRET_FILE` into `STUDIO_STATE_SECRET`. Directly starting `server.js` bypasses
   that loader. File existence alone does not confirm loading, length (at least 43), matching API
   credential, or API encryption-key availability. Do not print secret values. In **Workloads →
   Secrets**, check key names and mounted references only. No secret rotation/new secret is
   indicated by current evidence. Successful production login initiation already exercises state PUT.
4. Open the new Studio pod's **Logs** tab, initiate a fresh login and find
   `studio_auth_callback_failed`. Inspect all replicas if needed. Do not refresh/replay callback:
   login state and authorization code are single use. If the event never appears, verify image
   revision, target pod and route destination before drawing conclusions.
5. Apply only the Keycloak client corrections indicated by the event and effective client scope.
   Use Keycloak's admin console for those changes. No OpenShift environment variable supplies a
   missing token audience/claim/header; those are issuer settings. If a ConfigMap does need an
   edit, use its YAML editor, then the Deployment's **Restart rollout** action to reload env values.

Information needed to confirm: new event stage/category/claim, deployed revision, Keycloak version,
and effective mapper/header configuration. Share those diagnostic fields, not tokens or secrets.

## Verification and validation

- PASS: `npm test -- --run tests/auth-callback.test.ts tests/security.test.ts tests/routes.test.ts`
  in `apps/studio`: 43 tests across 3 files. New signed-JWT callback regressions cover successful
  Code/PKCE public-client flow, audience, missing client_id, issuer, signature, expiry, header type,
  nonce, state/cookie, grant errors, discovery transport and JWKS JSON failures, and log redaction.
  Existing security tests cover durable-store outage failure without memory fallback.
- PASS: `npm run typecheck` in `apps/studio`.
- PASS: Prettier check on all four changed/new TypeScript files; `git diff --check`.
- FAIL (environment): initial root `npm test` could not start under Node 16 (unsupported;
  `stripVTControlCharacters` import unavailable). Retried with the installed supported Node 25.9.0;
  PASS: root workspace retry, 63 tests across 3 files. Focused Studio tests above also ran on Node 25.9.0.
- Consulted `fixtures/VALIDATION.md`: callback authentication and secret-log checks exercised as
  above. No claim of full platform authorization/release certification.
- NOT RUN: live OKD/Keycloak login, real PostgreSQL session integration, full tenant-isolation and
  backend regression suites; no production access or running integration environment established.
- NOT RUN (outside this patch): Turtle/CSV/SHACL/OWL, object queries/actions/reconciliation, Polars,
  semantic engine and Protégé checks; their implementations/fixtures were not changed.

After applying the confirmed issuer fix, a fresh browser login must produce callback **303** to
Studio with Secure/HttpOnly `foundry-session` and cleared `foundry-login`; `/auth/session` must return
200 with memberships and tenant selection must permit authorized queries. A later empty tenant
list/403 is a separate PostgreSQL membership/authorization issue, not proof that callback failed.

Changed files: auth route and `lib/server.ts`; new `lib/auth-diagnostics.ts`,
`tests/auth-callback.test.ts` and this report. Existing uncommitted `keycloak-local.md` edits were
preserved. Database migrations: none. Architectural decision: preserve public Code/PKCE and the
existing dual ID/API JWT verification; add bounded server-side diagnostic metadata only.
Next step: confirm the failing production stage and correct the issuer configuration; no new
implementation phase is authorized or started.
