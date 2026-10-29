# ADR 0014: SQL-enforced query grants

Status: Accepted for Phase 2

## Decision

Retain require for governed operations and add a separate QueryAuthorizer protocol returning a
complete server-owned QueryGrant per type. Grants define SQL row predicates/allowed identities,
visible properties and a revision. Refuse new query access for legacy providers lacking a grant.
Apply grants in SQL before filters, sorting, paging, traversal and aggregation; reject every client
reference to a hidden field, including intermediate-step filters. Refresh/copy grants each request.
No Python post-filtering or pagination/count inference from unauthorized rows. Policy providers
must coordinate set grants with require for legacy CRUD; full production policy administration
remains Phase 7. The default trusted local principal remains an own-tenant administrator.

## Consequences

Preserve all Phase 0/1 contracts, tenant boundaries and semantic fixtures.
See docs/api/queries.md and the Phase 2 report for limits and executed evidence.
