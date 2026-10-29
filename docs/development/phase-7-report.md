# Phase 7 report — Production authentication and authorization

PHASE: **7 only**. Date: 2026-10-29, America/New_York.
Base Git revision: `07d28eb621486060357e80f07335c1135aedf722`.
The reviewed Phase 6 implementation was already uncommitted on arrival and was preserved.
STATUS: **Implemented and validated within the documented Phase 7 scope and supported profile.**
All Phase 7 work remains uncommitted. No Phase 8 implementation, push or deployment was performed.

## Functionality implemented

- Explicit disabled/local/test/OIDC authentication modes with no OIDC-to-development fallback.
  Production settings require trusted providers and reject local/test identity settings. Default
  disabled mode denies protected requests; the earlier explicit local opt-in remains compatible.
- Bounded trusted OIDC discovery/JWKS cache, startup verification, key rotation and refresh throttling;
  actual asymmetric JWT signature/issuer/audience/time/client/profile verification using pinned PyJWT.
  Only the documented RFC 9068 API access-token profile is supported; ID tokens are rejected.
- Immutable issuer/subject identity bindings, explicit user/service principals and enabled tenant
  memberships. First login grants nothing. X-Tenant-ID selects and verifies existing membership;
  token tenant/role/email/attribute claims never establish platform authorization.
- Offline explicit first-administrator provisioning; twelve tenant-owned role definitions at bootstrap,
  immutable role creation, assignment/revocation, effective permission inspection and membership APIs.
  Grant/assignment requires administrative permission and a subset of the caller's own permissions.
- Declarative restrictive ABAC with equality/membership against platform attributes, explicit deny
  precedence, conservative missing-attribute behavior, intersected property visibility and policy versions.
  Existing QueryGrant/SQL compiler handles row restrictions, traversals, aggregates, filters and sorting.
- Direct CRUD/legacy count/neighbor integration, both-endpoint link checks and proposed-state SQL policy
  evaluation. Hidden properties cannot be written blindly or returned from CRUD. Schema activation
  checks row/property authority before validating/mutating all affected data. Existing canonical
  validation, SQL transactions, optimistic concurrency, action replay and audit/outbox remain.
- Shared tenant security locks, exclusive administration/revision triggers and principal status locks
  coordinate revocation through commit. Transaction-local snapshots reuse only lock-protected identity,
  roles and grants. No authorization cache survives the governed boundary. Cursors bind current revision,
  principal/tenant/query and worker actor; authorization changes invalidate reuse.
- Durable redacted authorization decision audit, including denials after rollback, plus committed
  administration markers. Mutation history remains in existing action audit. Audit failure fails closed.
- Verified service worker credentials, explicit expiring worker/initiator/ontology/job-kind delegation,
  role and SQL-grant intersection, current membership/expiry checks and original job ownership.
  Engine/extraction work stays outside transactions and authorization is rechecked before fenced commit.
  Outbox uses its own verified service identity. Existing leases/checkpoints/retries are retained.
- Security administration/self-introspection OpenAPI with Bearer authentication, production configuration,
  API reference, threat checklist, architecture decision and reproducible final-image smoke script.

## Files created or modified

Paths below distinguish this phase from the preexisting Phase 6 changes.

| Area | Phase 7 files |
|---|---|
| New security implementation | `services/api/src/ontology_platform/security/{contracts,oidc,identity,service,admin,routes,bootstrap,workers}.py` |
| Extended existing security contracts | `services/api/src/ontology_platform/security/{interfaces,query}.py` |
| Authentication/application | `services/api/src/ontology_platform/{config,dependencies,main}.py` |
| Persistence and transaction integration | `services/api/src/ontology_platform/db/{models,governance}.py` |
| Existing domain integration | `services/api/src/ontology_platform/{objects/service,metadata/service,queries/service,queries/compiler}.py` |
| Existing worker entry points | `services/api/src/ontology_platform/{ingestion/__main__,semantic/__main__,jobs/webhooks}.py` |
| New migration | `services/api/migrations/versions/0013_security_production_security.py` |
| New tests | `services/api/tests/test_security_{oidc,platform,workflows}.py` |
| Dependencies/configuration | `services/api/pyproject.toml`, `uv.lock`, `.env.example`, `infrastructure/compose.yaml` |
| New smoke tooling | `scripts/smoke_security_container.py` |
| New documentation | `docs/api/security.md`, `docs/decisions/0028-production-identity-and-policy.md`, `docs/development/phase-7.md`, this report |
| Updated documentation | Root README; API README/queries/actions/ingestion/semantic/interchange; architecture overview/migrations |
| Evidence | `docs/architecture/evidence/phase-7/` baseline, regression, final-image, OWLAPI and integrity results |

No existing test was weakened or deleted. Canonical schema models, fixtures, PLANS.md, AGENTS.md,
Open Ontologies/OWLAPI pins, source/edit conflict semantics and approved phase boundaries are preserved.
Preexisting Phase 6 parser/import/migration changes remain in place.

## Database migrations

`0013_security` adds ten tables: principals, external_identities, security_state, tenant_memberships,
security_roles, role_assignments, security_policy_versions, security_policy_bindings, worker_delegations,
and authorization_audit. Composite tenant membership/role/policy/delegation FKs prevent cross-tenant
assignments. External bindings, role definitions, policy versions and authorization history reject
UPDATE/DELETE. Security changes increment a tenant revision under the same lock held by operations.
Existing tenants receive empty security-state anchors; no identity, membership or privilege is inferred.

Local development PostgreSQL is at **0013_security**. DDL uses two-second lock and 30-second statement
budgets. Clean upgrades, downgrade/re-upgrade, ORM drift and preservation of existing operational rows
are tested in disposable schemas. Downgrade removes Phase 7 identities/security history only and leaves
operational objects and Phase 6 imports intact. An OIDC application cannot use the downgraded security
schema; configuration and backup planning remain an operator responsibility.

## Baseline

Git status showed the uncommitted Phase 6 files; no baseline changes were discarded. Alembic current
reported **0012_ontology_imports** and `uv sync --frozen` passed. The complete configured regression
runner passed **401 tests, one preserved strict expected failure, zero skips**, **208.40 seconds**.
This includes existing authorization, actions/reconciliation/outbox, ingestion, queries, semantic and
ontology import suites. Lint, formatting, strict mypy and Alembic drift checks passed.
Evidence: `baseline-validation.txt`.

Actual host environment: Python **3.12.0**, PostgreSQL **17.6**, RDFLib **7.1.4**, pySHACL **0.30.1**,
Polars **1.44.2**, Open Ontologies **2.1.0** and OWLAPI **4.5.29**. New runtime pin: PyJWT **2.15.0**
with cryptography **50.0.2**. Existing httpx **0.28.1** is now declared as a runtime dependency too.
Exact versions and fixture/instruction hashes are in `integrity.json`. The image uses Python 3.12.12.

## Validation results

Final configured regression: **461 passed, one preserved strict expected failure, zero skips**,
462 collected, **276.99 seconds**. This adds 60 new security cases to the verified 401-test baseline.
Evidence: `validation-final.txt`. Ruff lint/format, strict mypy (83 modules) and Alembic drift passed;
135 Python files are formatted. The rebuilt final image smoke and OWLAPI harness also passed.
An earlier complete pass is retained in `validation.txt`: **458 passed, one strict expected failure,
zero skips**, 459 collected, **254.19 seconds**. That run preceded final activation/cursor/header/
administration-audit review changes. The first final rerun (`validation-before-audit-batching.txt`)
caught an intermittent ingestion deadline failure: 457 passed, 1 failed, 1 xfailed. Bounded
independent audit batches corrected repeated commit overhead without increasing deadlines;
`validation-final.txt` verifies the final implementation together.

| Check | Result | Evidence / limits |
|---|---|---|
| Reviewed Phase 6 baseline | PASS | `baseline-validation.txt`: 401 passed, 1 xfailed, no skips |
| Complete Phase 7 regression | PASS | `validation-final.txt`: 461 passed, 1 preserved xfailed, zero skips; 276.99s |
| Ruff lint/format and strict mypy | PASS | Final runner preamble; 83 application/schema modules; new smoke script separately checked |
| Alembic upgrade/downgrade/re-upgrade/drift | PASS | Real PostgreSQL regression; revision 0013; `alembic check` reports no drift |
| Actual JWT signature/profile/claims threats | PASS | RSA/EC cryptography, alg=none/HMAC confusion, malformed/missing claims, wrong issuer/audience/client, expiration/nbf/iat |
| Trusted discovery/JWKS/rotation/outage | PASS | Bounded HTTP transport fixture, issuer/origin/redirect/body limits, unknown kid refresh throttle and rotation |
| Actual OIDC FastAPI dependency | PASS | Signed tokens through TestClient and real PostgreSQL; forged roles/tenant/identity headers and disabled identity denied |
| Membership/RBAC/escalation/tenant isolation | PASS | Same external subject across tenants/providers, role revocation, membership disable, tenant selection and forbidden administration |
| ABAC SQL rows/property restrictions | PASS | CRUD, query/filter/sort/group/count, proposed writes, missing attributes, allow/deny precedence and property restrictions |
| Links/traversal/endpoint visibility | PASS | Real PostgreSQL SQL target filtering before paging, both endpoints checked; retained Phase 1/2 suites |
| Current policy versions/cursors | PASS | Immutable versions, expected-version conflict, disable, cursor invalidation and revocation |
| Transaction/revocation coordination | PASS | Concurrent readers/revocation, principal/membership checks, tenant-bound transaction snapshot |
| Actions/idempotency/import/private results | PASS | Verified platform identity preview/execute/replay/revocation and private import originals, plus retained complete suites |
| Delegated ingestion | PASS | Original 63-object/70-forward-link manufacturing workflow under service/initiator intersection; job-kind and membership revocation |
| Delegated semantic execution | PASS | Actual pinned engine; positive delegated completion/owner read and verified engine-work-before-revocation probe; revocation prevents all output commits; RUNNING lease remains for authorized recovery |
| Authorization audit | PASS | Durable denial audit, immutable history, verified initiator/worker attribution and committed administration markers |
| Final Docker build and HTTP probes | PASS | `docker-build.txt`, `docker-smoke.txt`: liveness/readiness/OpenAPI/Bearer schema, spoof denial and fail-closed OIDC startup |
| Turtle/CSV identity/FK/RDF consistency | PASS | Complete retained fixture suite and unchanged input hashes |
| Raw pySHACL conformance | FAIL | Preserved strict expected failure: simple/xsd:string sh:in mismatch; never counted as raw PASS |
| Normalized SHACL and negative fixtures | PASS | Retained independent in-memory compatibility harness and nine negative cases |
| Open Ontologies raw SHACL and owl-rl-ext | PASS | Actual pinned engine in configured fixture/semantic and worker suites |
| CriticalMachine with base owl-rl | NOT SUPPORTED | Existing executed profile limitation unchanged |
| Independent Lean proof checking | NOT RUN | No independent checker invoked; generated certificates remain unverified |
| OWLAPI/Protégé file compatibility | PASS | `protege.txt`: OWLAPI 4.5.29 source/RDFXML round trip; recorded xsd:date declaration delta retained |
| Protégé GUI / deployed WebProtégé | NOT RUN | Optional applications/deployment not invoked; no GUI validation claim |
| Live external OIDC provider / public deployment | NOT RUN | No external provider configured or deployment authorized; crypto/metadata behavior tested with local controlled transport |
| Remote CI | NOT RUN | No push/remote workflow requested; configured equivalent local checks executed |
| Fixture/instruction/upstream pin preservation | PASS | `integrity.json` and Git diff; existing regression tests unchanged |

Intermediate development failures were corrected without weakening earlier tests: new-test imports,
a helper method name, and repeated authorization SQL overhead that initially exceeded the existing
15-second ingestion deadline. Lock-protected transaction snapshots, unrestricted-row predicate shortcuts and bounded independent
audit batches restored the manufacturing run with that original deadline unchanged. The independent
audit batching tests verify complete evidence after business rollback, 256-event bounds, immediate
denial handling and fail-closed rollback on audit failure. All regression logs retain their actual results; incomplete/intermediate probes are not called final
passes. `validation-interrupted-for-worker-review.txt` records an intentionally interrupted run while
the worker regression was strengthened to assert actual external work and a successful delegated
completion/result read. The final configured run includes those stronger tests and has no unexpected
failure. Raw pySHACL remains the separately reported FAIL, not a passing raw validation.

All disposable test schemas and final-image smoke containers were cleaned up; a read-only PostgreSQL
check confirmed zero remaining `test_phase1_*` schemas. Development PostgreSQL remains running at
0013_security. No first administrator was silently provisioned in the development database; the
operator must configure a real trusted issuer/subject before using the documented bootstrap.

## Architectural decisions and known limitations

ADR **0028** documents the identity-provider/platform authority split, extension of existing
Authorizer/QueryGrant contracts, restrictive SQL ABAC, transactional security locking, redacted audit
and expiring intersected worker delegation. PostgreSQL remains authoritative and no competing policy
engine, additional database, microservice or executable policy language was introduced.

1. Only the documented RFC 9068 token profile, RS256/ES256 and same-origin HTTPS JWKS are supported.
   Generic ID-token/opaque-token compatibility and arbitrary provider custom profiles are not claimed.
   Key rotation has a bounded 30-second refresh throttle and cached keys expire; IdP outages fail closed.
2. RBAC assignment scope is tenant-wide. Exact ontology/type/principal ABAC supplies object/property
   restrictions. Per-action/per-ontology RBAC assignment scopes, global administrators, external role
   synchronization and a frontend identity-management/login experience are not implemented.
3. Disabled global principals require operator restoration; tenant membership can be disabled through
   governed APIs. New external identities need explicit provisioning; no self-service signup is exposed.
4. Query/ABAC complexity, activation bounds, ontology locks and existing workload deadlines remain.
   Tenant security locking intentionally serializes administration with in-flight work. A waiting
   revocation follows already-started operations; it does not retroactively cancel a committed mutation.
5. Audit is durable application evidence, not tamper-proof storage. Database owners can bypass triggers.
   Runtime database credentials remain trusted/backend-only; no RLS or hostile SQL-owner isolation is claimed.
   Independent audit writes require connection-pool capacity and fail callers closed on failure.
6. Worker credentials are refreshed by operators between bounded invocations. Revocation during external
   work prevents checkpoint/output commit, but an already-sent external notification cannot be undone.
   Revoked workers cannot retain permission solely to mark jobs failed; authorized lease recovery is required.
7. Tenant-wide security revision changes conservatively invalidate existing semantic export policy
   hashes; provision workers/delegations before exports and re-export after security changes.
   Artifacts/imports remain initiating-principal private; roles do not automatically grant cross-principal
   sharing/review of another owner's semantic data. Derived facts still never mutate operational state.
8. Existing raw pySHACL failure, base owl-rl limitation, unverified certificates, GUI validation gap,
   source resource bounds and indefinite history retention remain explicit. Phase 10 hardening, workload
   admission, deployment/backup/monitoring and a production readiness certification are not claimed.

## Next recommended phase

Stop after **Phase 7**. **Phase 8 — Ontology Studio** is next only after review and separate approval.
Future UI clients should use the OIDC/Bearer, membership-selection and security APIs documented here.
