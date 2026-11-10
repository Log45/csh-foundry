# Explicit OIDC access-token profiles

This focused compatibility change does not advance a roadmap phase. No database migration,
new dependency, broker, credential rotation, or production deployment is required by the code.

## Findings before this change

Studio `apps/studio/lib/server.ts` (`exchange`) and FastAPI
`services/api/src/ontology_platform/security/oidc.py` (`OIDCVerifier.verify`) both required
`client_id` and RFC 9068 JOSE `typ`. Both rejected a conflicting `azp` but could not accept it
as the sole client identifier. Neither supported configurable token profiles. Studio allowed
RS256/ES256; the API applied each provider's algorithm allowlist. A token could pass Studio but
fail API policy if these lists differed. API routes and workers reuse `OIDCVerifier`; there is
no independent worker verification implementation to change.

The production event proves `client_id` validation failed. It does **not** prove `azp` exists,
its value, the token audience/header, or any other production claim. Success with locally signed
fixtures is not a claim that production login is fixed.

## Contract and architectural decision

The existing trusted provider object gains `access_token_profile`, accepting exactly
`rfc9068` (default) or `keycloak`. Unknown/null values fail configuration validation. Policies
are selected from trusted configuration by issuer; a token can only select an already trusted
issuer, never a profile from its own claims. There is no retry/fallback from strict validation.

| Check | `rfc9068` | `keycloak` |
| --- | --- | --- |
| Client binding | Mandatory nonempty string `client_id` | Nonempty string `client_id` or `azp` required |
| Both claims present | Both must be valid and equal | Both must be valid and equal |
| Client allowlist | API provider clients; Studio exact configured client | Same |
| JOSE header `typ` | `at+jwt` or `application/at+jwt` | Those values, or `JWT` with signed payload `typ=Bearer`/`bearer` |
| Keycloak payload `typ`, if present | Existing RFC behavior | Must be `Bearer`/`bearer`; reject ID/Refresh and malformed values |

A present null, empty, numeric, boolean, array, or object client claim rejects the token, even
when the other claim is valid. A valid `azp` cannot override a wrong `client_id`. The API can
allow both Studio and worker clients; Studio accepts only its own client and rejects worker
substitution. The verified payload is not rewritten to invent a `client_id` claim.

Both profiles retain trusted JWKS signatures, exact issuer, expected API audience, configured
algorithms, required sub/exp/iat/jti, lifetime checks, token-use restrictions and rejection of
untrusted JOSE key URLs. Keycloak mode does not treat a generic signed JWT as proof of access-token
purpose: generic JWT headers need the signed Bearer marker. ID-token audience/nonce verification,
ID/access subject binding, public Code/S256 PKCE, session expiry/cookies, PostgreSQL identity and
tenant authorization are retained. Existing clock-skew policies are unchanged. JTI remains
required; this does not add a replay cache or promise single-use bearer tokens.

The marker/client behavior was checked against [Keycloak 26.2.5 TokenManager source](https://github.com/keycloak/keycloak/blob/26.2.5/services/src/main/java/org/keycloak/protocol/oidc/TokenManager.java)
(`initToken`, `formatTokenType`, `generateIDToken`). The installed production version and actual
issued token shape still need verification. Do not post live tokens to online JWT decoders.

## One trusted configuration for Studio and API

Studio now also reads **`FOUNDRY_OIDC_PROVIDERS`**, the existing API environment variable. It selects
the unique entry matching `STUDIO_OIDC_ISSUER`, requires the entry's audience to equal
`STUDIO_API_AUDIENCE`, and requires `STUDIO_OIDC_CLIENT_ID` in its clients. It derives both the
profile and algorithm allowlist from that entry. No independent `STUDIO_*` profile override exists.
Invalid JSON, duplicate matching issuers, unknown profiles, invalid algorithm lists and mismatches
produce sanitized `503 invalid_oidc_provider_configuration`; production startup checks config.

For backward compatibility, a Studio process without this variable remains strict RFC 9068
with its existing RS256/ES256 list. Enabling compatibility therefore requires exposing the shared
variable to Studio as well as the API. A missing Studio variable cannot enable compatibility.
Both Deployment manifests already use `envFrom: foundry-config`; the base ConfigMap now documents
strict default policy explicitly. Production Compose uses a shared YAML alias for the same policy.
Do not maintain separate provider JSON copies or per-container overrides: separate deployments
cannot detect another process's environment, and stale pods can temporarily retain old settings.
Worker consumers of the same provider policy must also be restarted when it changes.

## OKD4 web-console changes

No production resources were modified. Build reviewed Studio and API images using your existing
build process, including the updated worker image if it packages the verifier separately.

1. In the OpenShift web console, select your project. Open **Workloads → ConfigMaps →
   foundry-config → YAML** (use the actual ConfigMap name referenced by your Deployments).
   Merge this **data entry**, preserving every unrelated field/key:

   ```yaml
   data:
     FOUNDRY_OIDC_PROVIDERS: >-
       [{"id":"keycloak","issuer":"https://sso.csh.rit.edu/auth/realms/csh","audience":"foundry-api","clients":["foundry-studio","foundry-worker"],"algorithms":["RS256"],"access_token_profile":"keycloak"}]
   ```

   Keep the verified Studio issuer, origin, client, audience and state-secret-file settings.
   There is no new secret or client secret. If the JSON has other providers, preserve them and
   their existing strict profiles; change only the intended Keycloak entry.

2. In **Workloads → Deployments → studio/api → YAML**, confirm each container receives that exact
   shared key. The repository's existing shared `envFrom` suffices. If you use explicit environment
   entries instead, merge this entry into each container's existing `env` list, replacing any
   literal `FOUNDRY_OIDC_PROVIDERS` override:

   ```yaml
   env:
     - name: FOUNDRY_OIDC_PROVIDERS
       valueFrom:
         configMapKeyRef:
           name: foundry-config
           key: FOUNDRY_OIDC_PROVIDERS
   ```

   Apply the same source to verifier-using workers. Do not replace the whole env list. Check that
   no explicit env entry overrides the shared envFrom value. Do not put this JSON in a Secret.

3. Update the container `image` fields to the reviewed immutable image references. Coordinate
   rollout of API/workers and Studio so the updated verifier/config is loaded everywhere.
   ConfigMap env changes alone do not update running processes: use each Deployment's
   **Restart rollout** action if the image change did not start a rollout. Watch readiness and
   pod Logs before opening a fresh login. Menu labels may vary by console version.
   Old strict pods reject azp-only tokens during mixed rollout; plan for this interruption.

4. In Keycloak, keep `foundry-studio` public, Standard Flow enabled, S256 required, exact callback
   `https://foundry.csh.rit.edu/auth/callback`, and approved origin. The access token still needs
   audience `foundry-api`; configure an access-token Audience mapper if absent. A hardcoded
   `client_id` mapper or RFC header conversion is no longer necessary in Keycloak profile when
   the token supplies matching `azp` and an accepted access-token type. Do not remove existing
   mappers without checking their effect; a stale conflicting `client_id=studio` will still fail.

To retain strict RFC behavior, omit the profile field or set `rfc9068` in the same shared key,
then reload all consumers. Tokens then must contain `client_id` and the RFC access-token header.

## Verification

Start a fresh login after rollout; never refresh/replay a callback code/state. Confirm:

- Callback returns 303 to Studio, with Secure/HttpOnly `foundry-session` and cleared `foundry-login`.
- `/auth/session` returns 200 and memberships; selecting an authorized tenant permits API reads.
- Existing callback diagnostics remain safe: fixed stage/category/allowlisted claim names only;
  no tokens, cookies, state, codes, verifier, claims payloads, secrets, URLs, stacks or raw errors.
- If callback fails, inspect `studio_auth_callback_failed` in the new Studio pod's Logs. If
  callback succeeds but subsequent requests return `invalid_token`, check all API pod revisions
  and shared config. A 403 or empty memberships after successful token verification requires
  PostgreSQL identity/membership provisioning, not weaker token validation.

Confirm production `azp`, audience and access-token type through an administrator's controlled
local inspection or effective Keycloak configuration. Do not add token payload logging. The
reported missing-client_id event alone is insufficient evidence of an otherwise valid token.

## Validation and changed files

Shared signed-token cases: `fixtures/security/access-token-profiles.json`, exercised by
`apps/studio/tests/auth-callback.test.ts` and `services/api/tests/test_security_oidc.py`.
Each runtime signs JWTs locally and verifies signatures against a local mocked IdP JWKS.
FastAPI tests invoke the real `verified_identity` dependency through HTTP. They exercise token
authentication only; the PostgreSQL integration test below covers tenant authorization separately.

Implementation: `apps/studio/lib/server.ts`, `services/api/src/ontology_platform/security/oidc.py`.
Regression tests: the two files above plus `services/api/tests/test_security_platform.py`, whose
real PostgreSQL signed-token/membership/impersonation test now runs under each profile.
Configuration: `infrastructure/kubernetes/base/configmap.yaml` and
`infrastructure/production/compose.yaml` (strict defaults retained). Documentation: this file,
Studio README and OKD deployment guide. Database migrations: **none**.

Validation results are recorded after execution below. Scope follows `fixtures/VALIDATION.md`:
no claim of full platform validation, release certification, or successful production SSO.

| Check | Result | Evidence |
| --- | --- | --- |
| Backend OIDC regression | PASS | `.venv/bin/python -m pytest services/api/tests/test_security_oidc.py -q`: 127 passed |
| Studio callback/security/routes | PASS | In `apps/studio`, `npm test -- --run tests/auth-callback.test.ts tests/security.test.ts tests/routes.test.ts`: 55 passed; includes 38 shared cases per profile |
| Studio types and formatting | PASS | `npm run typecheck`; Prettier check on changed TS files |
| Backend types and lint | PASS | mypy on `security/oidc.py`; Ruff check and format check on changed Python files |
| Shared deployment config | PASS | PyYAML/JSON parse, strict ConfigMap default, identical Compose API/Studio policy assertions |
| Patch whitespace | PASS | `git diff --check` |
| PostgreSQL membership/tenant integration | NOT RUN | Extended test executed but both profile cases skipped: no `TEST_DATABASE_URL` for a disposable PostgreSQL database |
| Live Keycloak and OKD SSO | NOT RUN | No production access/token used or deployment performed |
| Turtle, CSV identities/FKs, SHACL, OWL, object queries/actions/reconciliation, Polars, semantic engine, Protégé | NOT RUN | Outside this compatibility patch; no corresponding implementation/fixture changes |

The initial sandbox backend run had 125 passes and one failure because binding the existing test's
localhost HTTPS listener was denied. With local-listener permission, the complete suite passed;
after adding provider-isolation coverage the final run passed all 127 tests. Existing Starlette
httpx deprecation warning remains; no dependency was added to suppress it. The PostgreSQL test is
not counted as passing. Full authorization/release validation remains outstanding.

Recommended next step: review the patch, verify the actual production token shape privately, then
roll out both updated services and the shared profile through the web console and confirm SSO/API
behavior. Do not advance another implementation phase as part of this work.

## Studio container build input

Next's production TypeScript check includes `tests/auth-callback.test.ts`, which imports the shared
JSON contract outside `apps/studio`. The Studio Docker build stage must copy
`fixtures/security/access-token-profiles.json` to `/repo/fixtures/security/access-token-profiles.json`
before `npm run build`. Omitting that input causes TS2307 in a clean container even when local
builds pass because the full checkout contains the fixture. `infrastructure/docker/studio.Dockerfile`
now includes that copy; test/type checking remains enabled. The fixture is a build-stage input,
not a credential or a new runtime dependency. No application, authentication policy, or database
change is involved in this packaging correction.

Packaging verification: **PASS** local `npm run build` in `apps/studio`; **PASS** complete local
`docker build -f infrastructure/docker/studio.Dockerfile -t csh-foundry-studio:oidc-build-fix .`,
including production TypeScript checking and final runtime image export; **PASS** `git diff --check`.
Live OpenShift rebuild/deployment: **NOT RUN**. No image was pushed or deployed.
