# ADR 0028: Verified OIDC identity and transactional platform authorization

Status: Accepted for Phase 7.

Use explicitly configured OIDC issuers and a narrowly supported RFC 9068 API access-token profile.
PyJWT 2.15.0 with cryptography verifies asymmetric signatures; existing httpx supplies bounded
nonredirecting discovery/JWKS retrieval. Never dynamically trust token issuers/key locations or treat
ID tokens as API credentials. Platform-owned immutable issuer/subject bindings and enabled tenant
memberships determine identity context. First login grants no authority; offline explicit first-admin
bootstrap and governed tenant administration provision identities. Service accounts are explicit types.

Extend the existing Authorizer/QueryGrant contracts instead of adding an independent authorization
engine or OPA service. Tenant-owned immutable RBAC roles grant implemented permission names;
restrictive declarative ABAC intersects their authority through the existing SQL compiler. Match
resource properties to platform-owned principal attributes with bounded equality/membership rules;
explicit deny takes precedence, missing attributes never allow, and proposed writes stay in scope.
Legacy counts/neighbors apply the same SQL grants, CRUD returns visible properties, and actions,
activation, reconciliation and semantic jobs compose these same governed checks.

Hold a tenant security shared lock throughout every governed transaction and an exclusive lock
through administration. Database security-change triggers bump revisions and coordinate direct SQL
changes too. Lock principal status for the transaction. Transaction-local snapshots may reuse only
state protected by these locks; never cache authority between transactions. Recheck live expiry and
delegation expiry even inside the snapshot. Already-started operations may finish ahead of a waiting
revocation; once revocation commits, old authority cannot commit later. Existing ontology locks and
SQL query grants/cursor binding remain. This is deliberately coarse, favoring correctness.

Keep append-only redacted decision audit in bounded independent batches of at most 256 events.
Flush on denial and on transaction-scope exit (including exceptions), before business commit, so
evidence survives denied/rolled-back business requests without one audit commit per permission. Separate authorization evidence from existing committed action audit. Audit
failure fails the request closed. Do not claim owner-proof storage or database RLS; PostgreSQL tenant
FKs, scoped queries and backend-only DB credentials remain the persistence trust model.

Workers authenticate service access tokens, require explicit expiring tenant/ontology/kind/initiator
delegations and intersect both identities' current roles/ABAC. Original job ownership and private
artifacts remain attributed to the initiator; audit records the worker actor. External work stays
outside locks; current authority is checked again at fenced commit. Revoked workers cannot persist
outputs or silently retain elevated failure-reporting authority. Outbox uses its own current service
identity and retains at-least-once external effects.

No frontend login, identity-provider management, new database/microservice, RLS, arbitrary policy code,
production scheduler or later-phase observability/deployment work is introduced. See
[security API](../api/security.md) for exact limits, unsupported profiles, scopes and operational caveats.
