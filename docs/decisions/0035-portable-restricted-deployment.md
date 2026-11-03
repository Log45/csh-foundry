# 0035 — Portable restricted deployment with external infrastructure

Status: accepted for Phase 10 engineering; production approval remains separate.

Use Kustomize for a common application-only Kubernetes base, an OKD Route overlay and a portable
self-hosted overlay. Keep the same modular application code/images and governed PostgreSQL services
across hosting profiles. PostgreSQL and Keycloak are externally owned dependencies in the OKD BOM;
version, TLS, security maintenance, compatibility and operational assurances remain mandatory.
Do not introduce a second identity broker unless the external realm cannot meet the existing
RFC9068/PKCE/issuer/audience/client/identity-binding contract. Platform authorization remains in DB.

Keep Next.js standalone/BFF behind a Route; it cannot be replaced with static nginx. The API service
remains private because it hosts internal session/metrics endpoints. The optional Compose nginx
uses a pinned maintained unprivileged image, supported package minimization and 8080/8443 listeners.
A configured Compose backchannel may change only the OIDC socket port for a trusted issuer origin.
The public issuer, discovery/JWKS origin, audience/signature and CA/hostname verification do not
change. The OKD profile needs no such override and introduces no extra proxy.

Let OKD assign the UID/fsGroup; do not depend on group0 or anyuid/privileged SCCs. Images have
numeric non-root defaults, immutable application roots, explicit temporary storage and no root
startup initialization. Portable Kubernetes may set an allowed fsGroup for projected Secrets;
cluster admission and actual group injection remain target checks.

Retain PostgreSQL-backed durable artifacts, sessions, jobs and outbox. Engine files/cache/heartbeat
are disposable. Registered file ingestion requires shared read-only sources; expose an optional
component mounting an existing claim. Current bounded workloads do not justify S3. The future
project/dataset/media/Spark roadmap remains separately unapproved.

Use a dedicated migration Job and separate owner credentials in a maintenance release. PostgreSQL
advisory locks prevent concurrent migration commands; explicit orchestration stops applications,
waits for migration/drift success, then applies workloads. Kubernetes YAML ordering is insufficient.
Operators must serialize rollout commands; a database lock cannot coordinate Kubernetes Job deletion.
A failed migration leaves workloads stopped for reviewed repair rather than automatic downgrade.
No schema migration was introduced; current head stays0017_capacity.

Release verification selects explicit profiles: six images for Compose, three application images
plus mandatory hashed external-service assessments and deployment/configuration identities for
OKD/self-hosted Kubernetes. Required images/services cannot disappear by changing profiles.
Raw high/critical findings and incomplete gates still block release; no new trust root, independent
risk authorizer or self-approved advisory exception is introduced. Successful local Docker tests
are not SCC admission, external-service certification or production release approval.
