# Personal tenants and cross-tenant resource access

PostgreSQL holds Foundry identities, many-to-many memberships and roles. A personal tenant is
an ordinary tenant with an additional ownership record that references the owner's membership.
Its database key limits a principal to one personal tenant. The original administrator of a
shared tenant keeps the existing tenant ID, assignments and ownership arrangements. The migration
does not infer personal ownership from any legacy records.

New tenants receive tenant owner, administrator, editor and viewer roles alongside the existing
capability roles. Project membership remains a separate governance check. A security
administrator can provision a principal or add an existing principal to multiple tenants
through the existing security API. A principal who has two enabled memberships explicitly
selects an acting tenant in Studio or uses `X-Tenant-ID` with the API.

A cross-tenant share has one authoritative owning tenant taken from the stored Project or
Ontology record. A direct invitation is addressed to the Foundry principal ID. That user accepts
in any enabled acting tenant and can use the share from any such tenant. An invitation to a
tenant requires acceptance by a member with `security:membership:manage` in that tenant.
Acceptance grants access to the tenant's current and future enabled human members while acting
in that tenant. Removal or disabling of membership cuts off access from that tenant. The owning
side can permanently revoke either kind of grant. Invitations have no automatic expiry. The
owner can renew access or change its level by issuing a new invitation and revoking the old one.

A Project share applies to its description and folder tree. Project contents such as datasets,
functions, pipelines, media and ontology references use their independent owner-tenant access
paths. A share has no effect on the older same-tenant Project resource catalog shares.
Ontology shares use the same operational query, traversal, aggregate, link and object services,
including the owning tenant's row/property policies. A recipient without an owning membership
has no owning-tenant membership attributes. Studio and the API retain separate acting-tenant
and owning-tenant IDs. Query cursors bind the acting tenant and grant when used through a share.

A shared request rechecks the grant and recipient in the resource transaction. The share and
recipient membership are held with PostgreSQL row locks until it completes. Revocation takes
effect for subsequent requests, including those using an already open Studio view. Audit records
correlate the invitation lifecycle and shared operations with the grant ID, actor principal,
acting tenant, and owning tenant.

Workers authenticate as the configured Keycloak service before discovering queues. Candidate
scopes come from due jobs, due deliveries, enabled nonmanual automations and retained ingestion
staging. A scan considers up to 16 scopes, with one scope per tenant per pass before considering
another ontology from that tenant. Tenant order is randomized on each scan. Bounded scans,
row locks with SKIP LOCKED, per-tenant lease handling, and worker lock timeouts let other
tenants make progress when one queue is busy or denied. The candidate query confers no
authority. Each claim, attempt and commit rechecks the existing grant, actor, initiator and
policy constraints. See [ADR 0049](../decisions/0049-personal-tenants-and-shared-work.md).
