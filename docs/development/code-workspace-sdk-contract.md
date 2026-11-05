# Future Code Workspace integration contract (design only)

Template identity: `foundry-react-next-v1`, Phase 16 template version 0.16.0, path apps/sdk-example.
Dependencies: @foundry/sdk 0.16.0, @foundry/react 0.16.0, React peer, existing pinned Next.js/TypeScript.
The current template imports Studio server routes and requires the monorepo; a future standalone
workspace must supply a reviewed reusable BFF package or a same-origin approved BFF mount before
extracting the app. Copying the browser SDK alone does not supply server authentication.

A future workspace would inject public API path and approved BFF path at build/start, never storage
credentials or service tokens. Use /api/v1 and /bff by default. Authentication remains operator-approved
OIDC -> existing HttpOnly session -> server-only verified API bearer; CSRF/Origin/tenant protections
remain mandatory. Preview URLs require explicit IdP callback configuration and same-origin cookie
routing. Cross-origin Fetch cookies or disabled CSRF are not supported substitutions.

Tenant/Project are explicit launch context hints, never grants. Fetch the current session, select an
authorized tenant, derive principal and rotate session generation, then create an immutable SDK client
with optional projectId for cache scoping. Project permissions remain cumulative server authority.
Tenant/session/Project changes invalidate the old client and private UI. Workspace termination must
cancel reads and revoke session according to the future approved lifecycle policy; no tokens persist
in workspace source, localStorage, exported caches or Git history.

Commands: npm ci; npm run build -w @foundry/sdk; npm run build -w @foundry/react;
npm run dev -w @foundry/sdk-example (loopback 3200); npm run typecheck; npm test;
npm run build; npm run test:consumer. Lockfile and generated contracts are mandatory template inputs.
Preview needs an already configured API, PostgreSQL/ArtifactStore/execution worker and approved BFF
with bounded JSON and streamed binary routes. A future ingress must preserve Origin, forwarded TLS,
HttpOnly cookie security, CSRF and expected tenant semantics. Its implementation is not included.

Future lifecycle assumptions: provisioning, readiness, stop/resume, idle timeout, disk retention,
network isolation, quotas, session invalidation and access revocation need separately approved designs.
The SDK never owns job scheduling and workspace stop cannot imply durable jobs stopped or their
committed materialization batches rolled back. SDK polling remains bounded and explicitly restartable.

Future Git association would refer to an existing governed Project resource and user-approved repository;
repository creation/import, credentials, branch protection and push policy need separate authorization.
Future development-container provisioning would choose pinned runtimes, least privilege, filesystem/
network limits and explicit secret injection; no Dockerfile, orchestration, browser IDE, terminal service,
persistent volume or lifecycle API is created by this design. No GitHub integration is implemented.

Future app deployment is a separate governed resource/publishing/hosting milestone. Building the
example or packing SDKs creates local artifacts only. No preview ingress, deployment controller,
application host or remote repository is implicitly provisioned. Phase 17 remains unimplemented and
Section 23B production readiness remains mandatory and blocked.
