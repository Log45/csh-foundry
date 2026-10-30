# Phase 10 preparation — production hardening and SSO

Preparation only. Phase 10 requires explicit approval; no items below are implemented by Phase 9.
Retain the existing Phase 7 authorization model and canonical PostgreSQL source of truth.

- [ ] Review production deployment architecture, supported topology and environment boundaries.
- [ ] PostgreSQL backup policy, encrypted backups, point-in-time recovery and restoration drills.
- [ ] Disaster recovery, RPO/RTO, failure-domain and tenant recovery requirements.
- [ ] Observability, monitoring, structured logging, traces, metrics and actionable alerts.
- [ ] Rate limiting, resource quotas, aggregate artifact/history storage and workload admission.
- [ ] Job scheduling, worker supervision/backoff, resource isolation and process deadlines.
- [ ] Secret management, key rotation, credential delivery and least-privilege runtime DB roles.
- [ ] Durable session persistence and horizontal frontend scaling; replace the single-process store.
- [ ] Production HTTPS, trusted reverse proxy configuration, network boundaries and CSP review.
- [ ] Security auditing, threat-model refresh, tenant onboarding and security incident exercises.
- [ ] Live OIDC provider integration and an evaluated replaceable identity broker.
- [ ] Microsoft Entra ID SSO with real provider/profile/audience and organizational policy tests.
- [ ] Google SSO and Google Workspace SSO with real provider and organization tests.
- [ ] Provider key rotation, overlapping keys, outages, logout and session/token revocation.
- [ ] Explicit account linking, enterprise organization-specific IdPs and identity lifecycle rules.
- [ ] Enterprise tenant onboarding and permission/identity administration responsibilities.
- [ ] SDK distribution security, signed provenance, package ownership, registry access and supply chain.
- [ ] CI/CD, deployment approvals, migration rollback/restore playbooks and release artifact integrity.
- [ ] Production readiness testing: representative load, concurrency, recovery, abuse and fault injection.

Validate broker/API access-token profile compatibility without replacing platform RBAC/ABAC with
provider claims. Preserve separate browser sessions, API tokens, service/delegation and connector
credentials. Preserve canonical publication/migration approval/activation and semantic boundaries.
Do not infer live Microsoft/Google testing from controlled local OIDC or signed-token tests.

Phase 9 follow-up review inputs: same-published-base branch merging (no arbitrary rebase DAG),
coarse locks, synchronous bounded SDK compilation, indefinite immutable history, JavaScript safe
integer limits, JSON branch authoring, API-only advanced history comparison and private artifact
retrieval. Review these deliberately before selecting production workloads; do not silently expand
schema/SDK guarantees or introduce a second registry/database/authorization engine.
