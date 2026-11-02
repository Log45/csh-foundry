# ADR 0032 — Keycloak as the replaceable authentication broker

Accepted for Phase 10 at the user's direction. Keycloak 26.8.1 is the selected broker;
application requests continue to use OIDC discovery, Code + S256 PKCE and RFC 9068 tokens.
Keycloak administration is isolated in `security/broker.py` and an offline realm renderer.
No runtime application code calls the Keycloak Admin API. A different issuer can replace it
by satisfying the existing issuer/audience/signature/claims/client contract and explicitly
migrating verified identities. Broker subject changes never silently rebind principals.

Keycloak provides established federation, Google/Workspace integration, generic OIDC for
tenant-specific Entra, asymmetric signing/JWKS rotation and standard logout. Its existing local
deployment reduces integration risk. The tradeoff is a separately maintained Java service,
database ownership, backups, key rotation and security upgrades. Apache-2.0 licensing permits
open-source distribution. Direct Entra/Google integration would require different token profiles
and offers no common platform-audience issuer. Managed brokers add an external operator and
commercial dependency. These alternatives were considered; no competing broker was deployed.

Realm configuration disables password grants, implicit flow, browser refresh tokens, offline
access and full role scopes. It sets `access.token.header.type.rfc9068=true`, explicit API
audience and client_id mappers. A separate confidential worker client uses client credentials.
Roles, groups, email, Workspace domains and Entra tenants grant no platform membership.

Organization isolation initially uses a dedicated realm and Studio deployment per organization,
plus explicit platform memberships. API providers remain bounded to eight configured issuers;
one Studio serves one configured issuer. No shared-realm domain-based tenant routing is claimed.
Entra uses an exact organization tenant UUID, excluding common/organizations/consumer issuers.
Google consumer and managed Workspace clients remain separate; Workspace checks one exact signed
hosted domain at the broker. Upstream credentials are secret-file inputs, never generated secrets.

Unlinked external identities are denied by a first-broker-login deny flow. Operators must verify
external issuer/subject ownership and explicitly prelink broker identities. Automatic email
merging and self-service account linking are unsupported. Platform identity binding remains the
governed Phase 7 workflow. Existing identities require an approved migration, never email matching.

Source-reviewed contracts:

- [OIDC endpoints](https://www.keycloak.org/securing-apps/oidc-layers).
- [Hostname/proxy boundaries](https://www.keycloak.org/server/hostname).
- [Import limitations](https://www.keycloak.org/server/importExport): exports are not full backups.
- Pinned [advanced OIDC configuration](https://github.com/keycloak/keycloak/blob/26.8.1/services/src/main/java/org/keycloak/protocol/oidc/OIDCAdvancedConfigWrapper.java),
  [OIDC provider configuration](https://github.com/keycloak/keycloak/blob/26.8.1/services/src/main/java/org/keycloak/broker/oidc/OIDCIdentityProviderConfig.java),
  [Google hosted-domain enforcement](https://github.com/keycloak/keycloak/blob/26.8.1/services/src/main/java/org/keycloak/social/google/GoogleIdentityProvider.java).

The disposable actual-Keycloak contract test verifies Code/PKCE, nonce, issuer, audience,
signature, RFC 9068, ID-token rejection and code replay rejection. Its loopback transport is a
test seam; it is not evidence of production TLS or live upstream federation. Live Microsoft,
Google and Workspace certification requires separate real-provider execution.
