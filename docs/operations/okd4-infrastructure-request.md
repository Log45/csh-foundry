# CSH Foundry — infrastructure administrator request

We are preparing an application-only OKD4 deployment. No organizational deployment or registry
publication is authorized by this document. Please identify the owners and supply the following
public configuration and operational assurances through approved channels; deliver credentials
and private keys only through the organization’s secrets mechanism.

| Area | Requested information / approval |
|---|---|
| Cluster | Exact OKD/Kubernetes version; namespace/project; allowed SCC (target restricted-v2); namespace UID and supplemental-group/fsGroup ranges; CNI NetworkPolicy behavior and router namespace labels |
| Compute | Node CPU architecture (semantic image currently validated on linux/amd64); schedulable nodes; resource quotas/LimitRanges; storage/ephemeral limits; approved capacity envelope |
| Registry | Approved registry/repository, pull-secret mechanism, image trust/signing/scanning policy, supported architecture and publication authority |
| PostgreSQL | Supported server version (local compatibility uses 17.11); hostname/port, dedicated database/schema, application DML role, separate migration owner role, public TLS CA and certificate hostname, verify-full requirement, connection budget/timeouts, required capabilities and extension policy |
| Database permissions | Existing schema ownership; approved DDL procedure, default privileges for new tables, runtime grants and audit-table restrictions; no runtime superuser, database-owner or schema-owner requirement |
| Identity | Keycloak version/owner, exact HTTPS issuer, discovery/JWKS reachability, signing algorithms, public TLS CA, stable subject lifecycle, RFC 9068 access-token support and API audience |
| Browser client | Public authorization-code client with S256 PKCE, exact `https://STUDIO_HOST/auth/callback`, approved origin and post-logout redirect; disable implicit/password grants and automatic account linking |
| Service client | Confidential service account with fixed client_id and API audience, RFC 9068 `typ=at+jwt`, `sub`, `jti`, `iat`, `exp`, `client_id`, compatible azp; client secret delivery/rotation; separate PostgreSQL platform membership and automatic job-scoped execution grants |
| Exposure | Public Studio hostname, OKD Route access, edge TLS certificate responsibility, HTTP-to-HTTPS redirects/HSTS, internal transport policy (base uses explicit namespace-internal HTTP), ingress controller selectors |
| Egress | DNS services; approved DB and Keycloak destination addresses/CIDRs/ports (including load-balancer/NAT behavior); approved ingestion sources and optional fixed outbox receiver; proxy restrictions |
| Secrets | Secret manager integration, application/session/cursor key custody, rotation and incident procedures, readable volume fsGroup, registry credentials; no credentials in Git |
| Monitoring | Existing log collector, API/worker/DB monitoring ownership, authenticated metrics collector and NetworkPolicy exception, alert routing/acknowledgement and retention |
| Recovery | Managed DB backups/WAL/PITR, encrypted off-host retention and independent key custody, RPO/RTO, restore-test authorization, restore host and application verification responsibility |
| Security | Independent vulnerability disposition/release approval authority, infrastructure patching SLAs, exact external service security/compatibility attestations, operational handoff and deployment approver |

S3 is **optional and not requested for the current deployment**. The source-level storage audit
found no present requirement. If using registered CSV/Parquet files, please provide an existing
shared read-only source claim accessible from API/ingestion pods on eligible nodes. Remote
PostgreSQL ingestion sources need no source claim. Future dataset/media storage is separate scope.

Direct organization Keycloak is preferred when administrators can satisfy the existing token
contract. If those settings cannot be supported, identify the precise incompatibility before
requesting a dedicated approved broker; we will not relax token verification or platform access.
A successful local Keycloak test does not certify the organization’s realm or upstream SSO.

Current security/release acceptance remains BLOCKED. External infrastructure is still subject to
security maintenance and approval even though PostgreSQL and Keycloak images are absent from the
application deployment bill of materials.
