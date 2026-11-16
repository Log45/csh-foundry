# Codex implementation prompt for Phase 22

I approve implementation of Phase 22 as defined in the current `PLANS.md`, including first-sign-in personal tenant provisioning and one shared worker pool across eligible tenants. This approval covers repository changes and local validation. Production deployment and external resource changes require separate approval. Stop after Phase 22.

Read `AGENTS.md`, the Phase 22 section of `PLANS.md`, `fixtures/VALIDATION.md`, and any scoped instructions. Inspect the Studio sign-in and tenant selection flows, PostgreSQL identity and membership models, authorization and Project governance, resource ownership, migrations, job grants, all worker entry points, API and SDK contracts, and OKD manifests before editing. Record the authorization model and migration decisions, then implement and validate the phase.

## Personal tenant onboarding

- On the first successful Studio sign-in, call a governed FastAPI onboarding operation for eligible human Keycloak accounts. Define eligibility explicitly using trusted server configuration and verified identity. Derive the identity from the verified access token’s exact `(issuer, sub)`. Deny disabled identities and service accounts.
- In one PostgreSQL transaction, resolve or create the Foundry principal, create its personal tenant, and establish ownership, enabled membership, and required tenant roles. Enforce one personal tenant per principal in the database. Concurrent first sign-ins and retries must converge without duplicating tenants, leaving partial state, or escalating privileges in any other tenant.
- Provision a personal tenant for eligible existing users on their next sign-in if they lack one, including users who already belong to shared tenants. Preserve existing IDs, memberships, and ownership. Handle onboarding failure explicitly in Studio. Keep `GET /api/v1/security/tenants` read-only.

## Membership, sharing, and ownership

- Support many-to-many membership and tenant-scoped roles for owners, administrators, editors or members, and viewers. Keep the authenticated principal, acting tenant, and resource’s authoritative owning tenant distinct. Resolve ownership server-side.
- Implement governed direct-principal and recipient-tenant sharing for Projects and Ontologies, with Viewer and Collaborator access. Define invitation and acceptance, revocation, audit, discovery, and recipient membership behavior. Allow authorized access through a resource share without requiring membership in the owning tenant. Preserve applicable RBAC/ABAC and independent checks for linked or referenced resources. A resource share cannot grant tenant administration or transfer rights.
- Add Studio tenant selection, shared-with-me and shared-by-me views, share management, and owning-tenant attribution. Update API contracts and regenerate affected SDKs.
- Treat ownership transfer as optional under the roadmap. If delivered, require source authorization and destination acceptance, and validate dependencies, quotas, active jobs, existing shares, artifact ownership, and audit provenance before any atomic transfer. If deferred, document the limitation and keep transfer disabled.

## Shared worker pool

- Keep the existing Keycloak worker client and shared worker architecture. Workers must start and idle successfully on an empty database. The same replicas must process authorized work for multiple eligible tenants, including a personal tenant created after the workers start, without a configuration edit or a per-tenant deployment.
- Replace startup tenant selection with claim-time tenant scoping based on the persisted job or delivery record. For scheduled or maintenance work, derive scope from eligible persisted records. Define how the worker service receives narrowly scoped authority in new personal tenants and how existing tenants retain or obtain worker eligibility. Keep this policy server-controlled. Review ingestion, semantic, execution, automation, outbox/webhook, and maintenance entry points for fixed tenant and ontology assumptions.
- Keep claim and lease acquisition atomic and prevent a busy, denied, or stalled tenant from blocking other eligible tenants. Preserve job-grant scope, initiator and service actor attribution, Project and tenant authorization, ABAC, expiry, revocation, quotas, fencing, retries, and audit. Outbox/webhook work continues to require tenant-scoped service permission. A claim or tenant ID by itself confers no access.
- For shared-resource submissions, check the initiator’s access to the requested operation and resource in the owning tenant before issuing a job grant. Recheck current authority at claim and execution. Document and deny any unsupported shared-resource job paths.
- Remove the need for `FOUNDRY_WORKER_TENANT_ID` across supported worker paths and remove it from shipped deployment configuration. Verify that rollout preserves existing authorized jobs and fails closed for jobs without valid authority. Document how to migrate existing tenants and queued jobs and how to roll back application and worker versions safely.

## Verification and delivery

- Use a forward-only Alembic migration where needed and test both a clean database and an upgrade with existing tenants, users, shares where applicable, and queued work. Document backup, rollout, rollback, and recovery assumptions.
- Exercise first sign-in, repeat and concurrent sign-in, existing memberships, disabled and service identities, and tenant selection in API and Studio tests. Test two-way cross-tenant isolation, Viewer and Collaborator permissions, direct and tenant shares, revocation, inherited access boundaries, and leakage through search, traversal, aggregates, exports, and SDKs. Test transfer races if transfer is delivered.
- With real PostgreSQL, verify a worker idles with zero tenants, claims concurrently without duplicate execution, and processes authorized work for two tenants, including one created after startup. Exercise denied and revoked authority, tenant/grant mismatches, lease recovery and fencing, tenant queue progress, and tenant-scoped delivery. Run existing security and worker regressions and applicable checks from `fixtures/VALIDATION.md`.
- Include an OKD4 rollout and verification runbook using the web console and pod terminals only. Report functionality, changed files, migrations, architectural decisions, limitations, validation results as PASS, FAIL, NOT RUN, or NOT SUPPORTED, and the recommended next phase.
