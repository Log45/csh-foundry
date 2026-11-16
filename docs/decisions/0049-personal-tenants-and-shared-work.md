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

Worker authentication verifies the existing service identity before any queue selection.
Tenant eligibility comes from existing enabled service memberships and bounded roles.
Candidate discovery uses due persisted rows and the applicable role. The existing claim
transaction rechecks capability, job grants, current initiator authority and fencing. A
server-configured worker binding can receive ingestion, semantic and execution capabilities atomically
in a new personal tenant. Automation and webhook delivery require separate
tenant permissions. Execution and automation retain explicit Project access. No new
service, queue, or database is required.
