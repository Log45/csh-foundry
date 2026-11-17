# Tenant onboarding and resource sharing API

Use a verified access token on every request. Discovery is read-only and works before tenant
selection. Use `X-Tenant-ID` to select an enabled membership on all scoped operations.

| Request | Contract |
| --- | --- |
| `POST /api/v1/security/personal-tenant` | Uses the bearer token and server eligibility policy. Accepts an optional `{"name":"My workspace"}` body and derives identity from the token. In all-users mode, an eligible user's first request without a name returns `{"personal_tenant_id":null,"name_required":true}` without creating records. A valid name creates the workspace, and repeat requests return its ID. Returns a null ID for an already provisioned human outside the onboarding policy. Unprovisioned ineligible accounts, disabled identities and service accounts receive 403. |
| `GET /api/v1/security/tenants` | Lists enabled memberships with personal ownership first, then stable tenant IDs. |
| `GET /api/v1/shares/targets/{kind}?search=...` | Finds up to 25 shareable resources in the selected tenant. Use `project` to search active Projects you own by name or ID, or `ontology` to search by ontology ID. |
| `GET /api/v1/shares/recipients?search=...` | Searches the configured Keycloak realm as an authorized share issuer. Returns usernames and corresponding Foundry principal IDs for enabled human accounts already registered in Foundry. Provide at least two letters or digits. |
| `POST /api/v1/shares` | Supply one of `project_id` or `ontology_id`, one of `recipient_principal_id` or `recipient_tenant_id`, and `access` of `viewer` or `collaborator`. Creates a pending invitation in the resource's owning tenant. |
| `GET /api/v1/shares?direction=incoming\|outgoing` | Lists received invitations and grants, or grants on resources the acting user manages. Supports `limit` and `offset`. |
| `POST /api/v1/shares/{id}/accept` | The recipient or recipient tenant's membership manager accepts the invitation. Repeating acceptance returns the accepted grant. |
| `DELETE /api/v1/shares/{id}` | The resource manager permanently revokes the grant. History remains available. |

Project owners need Project management permission to issue or revoke invitations. Ontology
sharing requires membership management and read authority in the owning tenant. Responses
identify `owner_tenant_id` and the canonical Project or Ontology ID. A share never grants
ownership or tenant administration.

A recipient principal ID identifies a person's Foundry account. In Studio, users can copy
their own ID from **Sharing**. The invitation form can look up a recipient by username or
accept the ID directly. Eligible Keycloak users register automatically when they first sign in
to Foundry. The [deployment guide](../operations/phase-22-okd4.md#optional-keycloak-user-search)
describes how to enable the username directory.

To use the grant, send the accepted ID in `X-Resource-Share` on an operation that declares
that header in OpenAPI. Keep `X-Tenant-ID` set to your acting tenant. The server derives
the owner from the share and checks that the route addresses its resource. The Viewer role
can read permitted ontology schema and objects, query, traverse, aggregate, and browse Project
folders. A Collaborator can also edit Project metadata and folders, author or validate
ontology drafts, and create or update permitted objects and create links. Publishing,
activation, actions, job submissions, semantic and OWL exports, child-resource metadata
and downloads, deletion and ownership transfer are outside share authority. Independent
membership and Project checks still apply on the ordinary tenant routes.

The platform TypeScript SDK exposes `shares.list`, `targets`, `recipients`, `invite`, `accept`,
and `revoke` and the
React SDK exposes matching hooks. Create a separate SDK client with `resourceShare` for
shared operations. Its `tenantId` is the acting tenant. Generated ontology TypeScript clients
also accept `resourceShare`. Generated Python clients accept `resource_share` with the same
meaning. API operations still decide whether a method may use the grant.


## Recipient lookup and private invitations

`GET /api/v1/shares/recipient-directory?search=` lists available recipients for share managers
in the acting tenant. The page contains `results`, `next_cursor`, and `unavailable_sources`.
Each result has a `source`, a selectable `id`, a `username` and a `display_name`. A blank query
browses LDAP. Send the same `search` and the returned `cursor` to load more LDAP entries.
`DELETE /api/v1/shares/recipient-directory?cursor=…` releases a page held by the caller.
On `directory_restart` discard the cursor and start the search again. Keycloak results
continue to use ordinary principal invitations. The legacy `GET /api/v1/shares/recipients`
keeps its Keycloak response and behavior.

For an LDAP result, send its selection ID as `selection` to
`POST /api/v1/shares/directory-invitations` along with the resource and access level.
Selections are signed for the caller, issuer/subject and acting tenant, and expire after
10 minutes. The response returns a pending share and a 24-hour, single-use `claim_secret`.
Studio places the secret in a private link fragment and removes it from the address bar
before OIDC sign-in. It keeps the claim in tab-local storage through the callback and
personal workspace naming. An SDK client must pass the secret privately and submit it only
in the JSON body to `POST /api/v1/shares/{share_id}/claim`.

LDAP visibility never provisions a principal. The configured directory exposes a UID but
no trusted immutable realm subject, so every LDAP selection uses the claim flow. The
recipient must already have resolved their membership through an authenticated Foundry
principal. A claim checks the unexpired secret digest, exact verified Keycloak issuer and
username, immutable subject binding, current recipient membership, and the original
sender's current permission on the owning resource. The accepted share references the
verified Foundry principal. Acceptance clears the digest and pending directory data.
Revocation and acceptance lock the same PostgreSQL row. A recipient without a signed
username receives `invitation_username_unavailable` and can try again after signing in
with the intended account. Neither a directory selection nor a pending claim grants access.
