# 0049 Personal tenants, resource shares and shared work

A verified Keycloak access token can onboard only through an operator-selected Studio client.
The operator can require a signed realm role assigned to human accounts or explicitly allow all
users who can sign in to that client. In the all-users mode, Studio collects a workspace name
before Foundry creates any tenant or identity records. The client uses authorization code with
PKCE and has service accounts and direct grants disabled. Foundry keys identities by exact issuer and
subject. Onboarding serializes creation of that binding and locks the existing principal before
creating its tenant. A composite ownership foreign key requires an owner membership, and a
unique principal key limits personal ownership to one tenant. Existing memberships and roles
stay intact. The additive, forward-only migration performs no inferred ownership or grant backfill.

A share has an owning tenant and a foreign key to exactly one Project or Ontology. The owner
issues a pending invitation to a principal or tenant. A principal accepts for themselves in
their selected tenant. Recipient tenant administrators accept on behalf of their tenant, and
enabled human members can use the accepted grant while acting in that tenant. The issuing
side can revoke it permanently. The resource transaction rechecks the grant, identity and
acting membership and uses the owning tenant for storage and policy. Shared access confers
only the explicit API operation allowlist. Project access includes the Project and folders.
Independent child resources and same-tenant ResourceShare grants keep their existing checks.
Ontology shares use the normal schema and object services and owner ABAC. Attributes from
the acting tenant do not satisfy owner policy. Share requests cannot submit background jobs,
export data, manage security, or transfer ownership.

Worker authentication verifies the operator-configured OIDC worker client before queue selection.
With the default `FOUNDRY_WORKER_AUTO_PROVISION=true`, the pool registers the verified issuer and
subject as a service principal without a manually configured subject. Bounded discovery of due work
enrolls missing tenant memberships with the immutable `system-worker-v1` role. This role contains
worker execution and delivery operations and excludes security administration, schema publication,
and ownership management. Active execution grants determine which Projects receive missing worker
editor memberships. Due automations use the Project of their persisted definition.

Enrollment is transactional, serialized with tenant security administration, and audited. Existing
memberships and role assignments remain authoritative. A disabled principal or membership stays
disabled, and an existing Project viewer membership is not promoted. Automatic mode treats an
absent Project membership as work awaiting enrollment; to deny a Project explicitly, retain a viewer
membership, or disable the tenant's worker membership to suspend all its queues. Operators needing
fully manual enrollment can set `FOUNDRY_WORKER_AUTO_PROVISION=false`.

The existing claim transaction still rechecks capability, job grants, current initiator authority,
Project and resource permissions, ABAC, expiry, revocation, and fencing. Worker enrollment grants
no permissions to users. No migration, new database, or Keycloak configuration change is required.
