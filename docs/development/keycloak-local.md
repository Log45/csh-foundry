# Existing local Keycloak connection

The running `foundry-keycloak` 26.8.1 instance is connected to the Foundry Docker network.
Its existing `foundry` realm, `studio` public client, and `dev` user are preserved.

- Browser Studio: http://127.0.0.1:3000
- Issuer: https://keycloak.localhost/realms/foundry
- Admin console remains accessible through http://localhost:8080.
- Local TLS proxy: `foundry-keycloak-tls`, nginx 1.28.3-alpine, host loopback port 443 only.
- Keycloak realm `frontendUrl`: https://keycloak.localhost
- Client: code flow, S256 PKCE, RS256, RFC 9068 header, API audience foundry-api and client_id=studio.
- Existing Keycloak user `dev` has an explicit administrator membership in the existing local
  Foundry tenant. Existing objects/ontologies were not rewritten.

The ignored `.env` contains issuer/client settings. Private backups, TLS/signing material and logs
are in ignored `artifacts/keycloak-local/`. Do not commit that directory or share its private keys.
The TLS proxy mounts only its server certificate/key and nginx configuration, never the CA key.

Restart the app containers with the normal Compose file:

```bash
docker compose --env-file .env \
  -f infrastructure/compose.yaml \
  --profile studio up -d --build api studio
```

The normal Compose configuration mounts the configured public CA directory read-only. FastAPI uses the additive
`FOUNDRY_OIDC_CA_BUNDLE` configuration; Next uses `NODE_EXTRA_CA_CERTS`. HTTPS hostname and
certificate verification remain enabled. Invalid/missing configured CA bundles fail closed.
Workers use the same API CA configuration. Default public certificate authorities remain trusted.

Browser trust is separate. The public certificate to trust is
`artifacts/keycloak-local/ca.pem` (Foundry Local Development CA), never `ca-key.pem`.
On macOS the user login keychain can trust it using:

```bash
security add-trusted-cert -r trustRoot \
  -k "$HOME/Library/Keychains/login.keychain-db" \
  /Users/log/Documents/code/csh-foundry/artifacts/keycloak-local/ca.pem
```

This establishes trust in this local CA; it does not disable TLS verification. Browser processes may
need to restart to observe changed trust settings. Do not bypass a browser certificate warning.
The browser resolves *.localhost to loopback; Docker resolves keycloak.localhost to the TLS proxy.
Host Python/curl may need a hosts entry (`127.0.0.1 keycloak.localhost`) or curl `--resolve` when
using the issuer outside Docker; the Docker application does not need that hosts entry.

The original Keycloak container has no persistent volume. Do not remove/recreate it without a
proper export/backup of its realm and users. Existing configuration snapshots are saved privately,
but they are not a full credential/database backup. The TLS proxy has restart policy unless-stopped;
its certificates last 90 days and the local CA lasts one year. This is local development, not a
production deployment or live Microsoft/Google SSO integration.

Stop the proxy explicitly with `docker stop foundry-keycloak-tls` when no longer needed. The ignored .env supplies FOUNDRY_OIDC_CA_DIRECTORY, FOUNDRY_DOCKER_OIDC_CA_BUNDLE and
STUDIO_NODE_EXTRA_CA_CERTS so the normal Compose command preserves certificate trust.

## Verified connection

The local CA has been installed in this user's macOS login keychain, and the in-app browser
successfully completed the Keycloak `dev` login, callback and tenant selection. Studio displayed
the existing published/active manufacturing ontology. The user's password was not changed.

A pending login expires in five minutes and is lost when Studio restarts. If a callback reports
`invalid_login_state` after restarting containers, open http://127.0.0.1:3000 and start a new sign-in.
Do not reload or reuse the old callback URL. Existing Keycloak SSO may complete the new flow without
another password prompt.

The CA tests exercise an actual TLS listener: explicit trust succeeds, absent trust and a wrong
hostname fail, and malformed/missing CA bundles fail closed. The worker verifier test fixture now
accepts the additional CA configuration argument while retaining all delegation/revocation checks.
Expected security-test database errors (immutable audit/role/policy mutations) are deliberate
negative checks in disposable schemas, not failures in the signed-in user's tenant.

Final validation: **PASS** configured regression (`scripts/validate_phase0.py`): **466 passed,
1 preserved strict expected failure, zero skips**, 209.08 seconds. This includes the new TLS checks
and unchanged worker delegation/revocation checks. Ruff lint/format, strict mypy and Alembic drift:
**PASS**. Live container readiness, trusted discovery, required PKCE rejection, and signed-in browser
callback/tenant/ontology view: **PASS**. Raw pySHACL remains **FAIL** under its documented strict xfail;
no successful raw conformance is claimed. No database migration or production/live external SSO
integration was performed. The earlier interrupted regression is not counted as passing.
Local evidence is retained in ignored `artifacts/keycloak-local/`.

## Restored local UX environment — 2026-11-02

The original Keycloak container and TLS proxy were absent. The retained backup
`artifacts/keycloak-backups/20261029T181035Z/container.tar` was checksum-verified and imported as
`foundry-keycloak-recovered:20261029`, with UID 1000 restored explicitly. This is a filesystem export,
so use `docker import`, not `docker load`. It includes the original embedded H2 database, realm,
users and signing keys. Keep this recovery image local; it contains the backed-up identity data.

The running recovery containers are `foundry-keycloak` and `foundry-keycloak-tls`, attached to
`csh-foundry_default`. The TLS proxy has the `keycloak.localhost` network alias. Only the issuer
certificate/key are mounted, not the CA private key. Its configuration lives in the new private
`artifacts/keycloak-recovered-20261102/nginx.conf`; the original configuration and backup are intact.
The proxy uses the reviewed ingress image, resolves the restored backend dynamically, and omits
request/query logging. Keycloak trusts only the proxy's actual bridge address for forwarded headers.

For normal starts/restarts from the repository root:

```bash
uv run python scripts/start_local_studio.py
# Add --build after changing API/Studio source or Dockerfiles.
```

The helper starts the existing Keycloak/TLS containers, waits for verified HTTPS discovery with
the expected issuer, then starts API/Studio using the existing `.env`. This ordering avoids API
OIDC startup failure while Keycloak is still booting. It does not restore or reset data/credentials.
Use `docker start` for these identity containers; do not delete/recreate them for ordinary restarts.
Their H2 data currently remains in the restored container's writable layer, not a named volume.
Take a new consistent backup before removing that container or replacing it.

URLs and identity contract:

- Studio: `http://127.0.0.1:3000`.
- Keycloak console: `https://keycloak.localhost/admin/` (loopback HTTP admin port 8080 also exists).
- Issuer: `https://keycloak.localhost/realms/foundry`.
- Public client: `studio`; callback `http://127.0.0.1:3000/auth/callback`.
- Required S256 PKCE, RFC 9068 API token, audience `foundry-api`, `client_id=studio`.
- Sign in as `dev` using its password from the October 29 backup. No password was changed/reset.
- The restored subject still has its existing enabled Foundry membership in **Phase 1 local smoke**.
  Select that tenant and the active `manufacturing` ontology (1.0.0) after signing in.

The existing manufacturing ontology currently contains **one operational object**; no full sample
load was performed and no existing object/membership was rewritten. A 63-object manufacturing demo
would be a separate governed ingestion into an explicitly selected tenant.

Checks executed: backup SHA256; issuer certificate validity and macOS trust; actual HTTPS discovery;
restored `dev` account and Studio client/mappers; existing platform subject/membership; actual login
form through TLS; API readiness; Studio HTTP 200. Private diagnostics/inventory are retained beneath
`artifacts/keycloak-recovered-20261102/`. Browser password entry and post-login UX are left to the user.
Start a fresh sign-in after an app restart; do not reuse a stale callback URL.

For another recovery when these container names are absent, import the same verified archive:

```bash
docker import --change 'USER 1000' --change 'WORKDIR /' \
  artifacts/keycloak-backups/20261029T181035Z/container.tar \
  foundry-keycloak-recovered:20261029
```

Run the TLS proxy on the Foundry network first. Reuse the saved public cert/key and prepared proxy
configuration, set alias `keycloak.localhost`, and publish only `127.0.0.1:443:443`. Then run:

```bash
docker run -d --name foundry-keycloak --restart unless-stopped \
  --network csh-foundry_default \
  --env-file artifacts/keycloak-backups/20261029T181035Z/restore.env \
  -e KC_HOSTNAME=https://keycloak.localhost \
  -e KC_PROXY_HEADERS=xforwarded \
  -e KC_PROXY_TRUSTED_ADDRESSES=REPLACE_WITH_TLS_PROXY_IP/32 \
  -p 127.0.0.1:8080:8080 \
  --entrypoint /opt/keycloak/bin/kc.sh foundry-keycloak-recovered:20261029 start-dev
```

Obtain the proxy address with `docker inspect foundry-keycloak-tls --format
'{{(index .NetworkSettings.Networks "csh-foundry_default").IPAddress}}'`. The existing private
`restore.env` supplies the saved bootstrap environment without printing credentials; importing
an existing realm/database does not reset its users. This is a local UX recovery, not the production
Compose profile or production certification.
