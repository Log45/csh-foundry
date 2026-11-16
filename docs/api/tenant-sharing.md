# Tenant onboarding and resource sharing API

Use a verified access token on every request. Discovery is read-only and works before tenant
selection. Use `X-Tenant-ID` to select an enabled membership on all scoped operations.

| Request | Contract |
| --- | --- |
| `POST /api/v1/security/personal-tenant` | Uses the bearer token and server eligibility policy. Accepts no identity or tenant arguments. Returns `personal_tenant_id` for an eligible human, including on repeat sign-ins. Returns null for an already provisioned human outside the onboarding policy. Unprovisioned ineligible accounts, disabled identities and service accounts receive 403. |
| `GET /api/v1/security/tenants` | Lists enabled memberships with personal ownership first, then stable tenant IDs. |
| `POST /api/v1/shares` | Supply one of `project_id` or `ontology_id`, one of `recipient_principal_id` or `recipient_tenant_id`, and `access` of `viewer` or `collaborator`. Creates a pending invitation in the resource's owning tenant. |
| `GET /api/v1/shares?direction=incoming\|outgoing` | Lists received invitations and grants, or grants on resources the acting user manages. Supports `limit` and `offset`. |
| `POST /api/v1/shares/{id}/accept` | The recipient or recipient tenant's membership manager accepts the invitation. Repeating acceptance returns the accepted grant. |
| `DELETE /api/v1/shares/{id}` | The resource manager permanently revokes the grant. History remains available. |

Project owners need Project management permission to issue or revoke invitations. Ontology
sharing requires membership management and read authority in the owning tenant. Responses
identify `owner_tenant_id` and the canonical Project or Ontology ID. A share never grants
ownership or tenant administration.

To use the grant, send the accepted ID in `X-Resource-Share` on an operation that declares
that header in OpenAPI. Keep `X-Tenant-ID` set to your acting tenant. The server derives
the owner from the share and checks that the route addresses its resource. The Viewer role
can read permitted ontology schema and objects, query, traverse, aggregate, and browse Project
folders. A Collaborator can also edit Project metadata and folders, author or validate
ontology drafts, and create or update permitted objects and create links. Publishing,
activation, actions, job submissions, semantic and OWL exports, child-resource metadata
and downloads, deletion and ownership transfer are outside share authority. Independent
membership and Project checks still apply on the ordinary tenant routes.

The platform TypeScript SDK exposes `shares.list`, `invite`, `accept`, and `revoke` and the
React SDK exposes matching hooks. Create a separate SDK client with `resourceShare` for
shared operations. Its `tenantId` is the acting tenant. Generated ontology TypeScript clients
also accept `resourceShare`. Generated Python clients accept `resource_share` with the same
meaning. API operations still decide whether a method may use the grant.
