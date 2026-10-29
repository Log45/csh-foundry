# ADR 0015: Signed keyset cursors with anchor revalidation

Status: Accepted for Phase 2

## Decision

Use HMAC-SHA256 opaque tokens bound to principal/tenant/ontology/type/schema, normalized query and
all grants. Bind last sort values by keyed digest and reconstruct them from the authorized unchanged anchor
instead of putting unselected fields into tokens. Include revision; reject changed/deleted/invisible
anchors. Use typed lexicographic keyset predicates with NULLS LAST and identity tie-breakers.
Reject active-schema changes, incompatible context/query/policy and expired tokens (one hour).
Do not promise a cross-request snapshot: non-anchor changes may move rows between pages.
Default process-random key invalidates tokens on restart; optional secret supports shared processes.
Explicit bounded offset mode remains available, including unusually large identities. No cursor DB.

## Consequences

Preserve all Phase 0/1 contracts, tenant boundaries and semantic fixtures.
See docs/api/queries.md and the Phase 2 report for limits and executed evidence.
