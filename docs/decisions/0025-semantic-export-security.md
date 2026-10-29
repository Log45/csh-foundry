# ADR 0025: Principal-private semantic snapshots under governed query locks

Status: Accepted for Phase 5

Expose bounded root-query selections and explicit forward link IDs. Compose QueryService in a
caller-owned service transaction; SQL grants restrict rows and selected JSONB keys. Recheck
object/property require permissions and separately authorize schema, export and links. Export only
edges whose two endpoints belong to authorized selections; emit their declared inverse RDF edges
without storing duplicate operational relationships. No unrestricted SPARQL or direct DB export path.

The existing shared ontology lock prevents governed operational writers/activation during the
bounded export. This is a consistent governed mutation interval with a bounded query selection, not
historical reconstruction or an external-source snapshot transaction. Persist selected identities,
revisions, edge boundary, query/policy hashes, source versions and available retained staging run
associations. Staging associations are explicitly not exact historical revision attribution.

All artifacts, reports, facts and proofs are private to their creating principal within the tenant.
Reading a result rechecks BOTH input artifacts and recreates the authorized asserted selection.
Policy changes or an originally selected identity falling out of the current selection deny payload
access. Changed values/revisions/edges/provenance mark same-identity results STALE; unchanged input
is CURRENT. A changed active schema denies historical payload with stale_schema rather than trying
to apply incompatible new grants. Immutable provenance and job identifier-only history remain.
Approval applies to an entire immutable derived set, requires fresh authorized inputs and appends
actor/time/state audit events. Approval never grants wider data access or writes operational state.
Production sharing/delegation, OIDC and policy administration remain later phases.
