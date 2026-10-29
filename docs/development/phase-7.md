# Phase 7 implementation and threat checklist

Approved scope: production identity and authorization only. The supplied request ends at
`Pres` in section 14; preceding requirements and PLANS Phase 7 define this implementation.
Existing uncommitted Phase 6 work is the baseline and must be preserved.

## Threat model before implementation

- [x] Forged/unsigned/wrong-profile JWTs; issuer/audience/client/algorithm confusion;
  untrusted token key URLs; oversized discovery/JWKS; redirects; key rotation/outage.
- [x] Identity collisions across issuers, arbitrary email/role/tenant claims; unknown,
  disabled identities and removed membership; multi-tenant selection spoofing.
- [x] Privilege escalation via role, policy, membership and attribute administration.
- [x] Revocation racing transactions, stale grants/cursors, rollback losing denial audit.
- [x] Full-document CRUD, counts, endpoint checks and proposed writes bypassing SQL grants.
- [x] Hidden filter/sort/aggregate/traversal fields, anchor/cursor disclosure.
- [x] Actions/activation/reconciliation applying unauthorized proposed state or properties.
- [x] Job principal reconstruction and service worker confused-deputy delegation;
  revocation between external work and commit; outbox identity.
- [x] Private semantic artifacts/facts/approvals/import originals and draft/publication separation.
- [x] Database ownership/FKs, direct SQL policy updates, immutable audit/version history.
- [x] Local/test configuration accidentally enabling production impersonation.

Entry points inspected: get_principal, Settings, LocalAuthorizer, Principal, TenantService,
GovernedService, RegistryService/activation, ObjectService/links/counts, QueryCompiler/QueryService/
CursorCodec/ObjectSet, actions/preview/replay/overlays, ReconciliationService, source catalog/
IngestionService/Worker/CLI, SemanticService/Worker/CLI, interchange services, WebhookRunner/CLI,
bootstrap. Existing workers filter jobs by initiating principal; production delegation must preserve
that attribution and intersect worker and initiating-principal authority.

Design: external identity binding with explicit provisioning, tenant-scoped RBAC, restrictive
ABAC compiled into existing QueryGrant, deny precedence, fail closed. No role/tenant claims are
imported from tokens. Transaction-scoped shared security locks serialize with exclusive security
administration. Every decision emits redacted durable audit. No RLS claim for owner connections.

Implementation and final validation evidence are recorded in [the Phase 7 report](phase-7-report.md).
Checked items mean the bounded implementation and relevant tests were reviewed; optional external
provider deployment, GUI and independent proof verification remain explicit NOT RUN items there.

Final result: **461 passed, one preserved strict expected failure, zero skips**; full runner lint,
format, strict mypy and migration drift PASS. Phase 7 stops here. Phase 8 requires separate approval.
