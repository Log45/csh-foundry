# Phase 22 LDAP recipient search validation

Local implementation and validation used the working tree based on revision 9ef6ebd, Python
3.12, Node 24, PostgreSQL 18.3 in a disposable local cluster, a loopback LDAP StartTLS fixture,
Chromium with the local OIDC fixture, and a disposable pinned Keycloak 26.8.1 container.

## Implementation and migration

Studio can browse and search the configured directories in one combobox. LDAP uses verified
anonymous StartTLS and bounded one-level RFC 2696 pages. The API holds the connection behind
a short-lived cursor scoped to the actor, tenant and query. A missing cursor restarts at the
first page. The LDAP selection signature is derived from the shared API cursor key so
issuance can proceed on a different replica. The existing Keycloak search route retains its
principal ID and label contract. Manual principal and tenant invitations are available in all
directory modes.

LDAP selections create pending shares with a digest of the 24-hour claim secret. The claim
checks the signed Keycloak issuer, subject binding and exact username, the active acting
membership, and current authority to share the resource in its owning tenant. Claim and
revocation serialize on the share row. Acceptance binds the share to the Foundry principal
and clears the pending data. Studio holds the link fragment in tab-local storage through
OIDC and workspace naming. An already-available Keycloak profile scope can be requested
with the Studio setting in the runbook.

Forward-only Alembic revision 0030_directory_shares extends tenant_shares. Validation covered
a clean migration and an upgrade from 0029 with existing pending principal invitations
and accepted tenant shares. See the [API contract](../api/tenant-sharing.md) and
[OKD4 runbook](../operations/phase-22-okd4.md).

## Validation

| Check | Result | Evidence |
| --- | --- | --- |
| LDAP protocol and bounds | PASS | Loopback wire fixture verified anonymous StartTLS, certificate and hostname failure, one-level scope, escaped UID/name prefix filters, repeated cookies on one connection, bounded results and cursor cleanup. |
| FastAPI and PostgreSQL sharing | PASS | Authorization, source configuration, mixed failures, first-sign-in claim, missing username, wrong account and secret, expiry, revoke, replay, concurrent claim/revoke, cross-tenant isolation and upgrade tests passed. |
| Broader backend regression | PASS | 966 passed, 139 skipped, one expected failure with the artifact backend disabled. Four PostgreSQL connector tests passed separately with the disposable setup role. The final focused regression had 297 passes and the same expected failure. |
| Studio and SDK | PASS | Studio typecheck and production build, 110 Studio tests, three Playwright cases, generated-contract drift check, SDK typecheck and 64 SDK tests. |
| Keycloak profile scope | PASS | The disposable pinned Keycloak fixture with an available profile scope issued a verified Studio access token with preferred_username and sub. The existing directory-to-principal search also passed. |
| Turtle parsing, CSV keys/FKs and RDF consistency | PASS | The fixture tests parsed all Turtle graphs and matched 63 explicitly typed RDF instances and relationships to CSV identities. |
| SHACL and negative fixtures | PASS | Open Ontologies and RDF 1.1-normalized pySHACL checks passed, including invalid fixtures. Unnormalized raw pySHACL retained its expected string-term mismatch. |
| OWL reasoning | PASS | The owl-rl-ext profile inferred the expected three CriticalMachine instances. |
| CriticalMachine with base owl-rl | NOT SUPPORTED | The tested Open Ontologies executable lacks the required inference in this profile. |
| FastAPI object queries, actions and reconciliation, Polars ingestion | PASS | Local PostgreSQL regression exercised the canonical data, object queries, governed actions and ingestion. |
| Static checks | PASS | Ruff, mypy and git diff --check. |
| MinIO-dependent cases | NOT RUN | The broad regression used the disabled artifact backend. The LDAP follow-up does not touch artifact storage. |
| Protégé desktop and WebProtégé | NOT RUN | Interactive applications were outside this sharing follow-up. |
| Target OKD4 and current Keycloak realm | NOT RUN | Target rollout, TCP 389 policy, three API pod LDAP pages, actual Studio access-token username, and target first-sign-in claim require separately approved verification. |

The semantic tests used the local Open Ontologies executable with SHA-256
493f6db51550112528d19f3ca88caf133b46c2a9054a195a98bc588b57ba07b6.

To reproduce the targeted checks, configure a disposable TEST_DATABASE_URL and run pytest
for test_ldap_directory.py, test_directory.py, test_directory_shares.py, test_phase22.py,
test_security_oidc.py, test_fixtures.py, test_semantic.py, test_phase1.py, test_api.py,
test_actions.py and test_ingestion.py. Set OPEN_ONTOLOGIES_BIN to the pinned executable.
Run scripts/test_keycloak.py --phase22 --directory-profile against the disposable database.
Build Studio, then run scripts/test_studio.py directory-sharing.spec.ts with
STUDIO_E2E_DURABLE=true and STUDIO_E2E_LDAP=true, and run personal-tenant.spec.ts with the
LDAP fixture disabled.

## Files

- API implementation under services/api/src/ontology_platform includes config.py,
  dependencies.py, main.py, db/governance.py, db/models.py, and security/directory.py,
  security/interfaces.py, security/ldap_directory.py, security/recipient_directory.py,
  security/routes.py and security/sharing.py.
- Dependencies and migration include services/api/pyproject.toml, uv.lock and
  services/api/migrations/versions/0030_directory_shares.py.
- Studio implementation includes app/style.css, components/workspace.tsx,
  features/sharing.tsx, features/recipient-picker.tsx, features/share-claim.tsx and
  lib/server.ts, all under apps/studio.
- Generated contracts include apps/studio/lib/openapi.json, apps/studio/lib/api-schema.ts,
  packages/typescript-sdk/src/endpoints.ts, packages/typescript-sdk/src/schema.ts and
  packages/react-sdk/src/hooks.ts. scripts/generate_platform_sdk.py declares the new methods.
- Backend tests include test_directory.py, test_ldap_directory.py, test_directory_shares.py,
  test_phase22.py and the head-revision checks in test_applications.py, test_mappings.py,
  test_media_functions_automations.py, test_owner_runtime_postgres.py and
  test_pipeline_graphs.py, all under services/api/tests. scripts/test_keycloak.py exercises
  the optional profile scope in the disposable broker.
- Studio tests include tests/security.test.ts, tests/sharing.test.tsx,
  tests/workspace-consistency.test.tsx, tests/e2e_backend.py, tests/e2e/login.ts and
  tests/e2e/directory-sharing.spec.ts, all under apps/studio.
- Documentation includes docs/api/tenant-sharing.md, docs/operations/phase-22-okd4.md and this
  report.

## Remaining target checks

The configured LDAP realm needs a unique UID that matches the signed Studio username.
LDAP bind is anonymous. Page continuation needs affinity to the live API process.
The proposed next phase is a separately approved OKD4 rehearsal of the migration,
directory egress and trust, API routing, actual Studio username claim, and private invitation
flow with a new eligible user.
