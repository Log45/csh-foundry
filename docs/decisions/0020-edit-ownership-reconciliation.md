# ADR 0020: Property ownership and explicit reconciliation

Status: Accepted for Phase 3

Store property-level source/pipeline/user/action ownership separately from resolved JSONB objects.
CRUD edits create user provenance and action edits reference their execution. PostgreSQL objects
remain authoritative; overlays do not create an independent datastore or bypass service mutation.
Legacy values lacking provenance are conservatively user-owned, avoiding silent takeover on upgrade.

Default edit_wins preserves governed values and accepts same-source-owned updates. Explicit
source_wins requires edit:override and transfers ownership. Equal observations preserve ownership.
Reject/manual conflicts persist once per observed schema/revision/value, with no partial property
or ownership changes from a conflicting refresh. Explicit resolution records resolver/time and
rechecks revisions, schema and permissions. Incompatible old overlays require governed rebasing.

Resolved value changes increment ordinary object revisions; source observations that preserve an
edit only update provenance. Keep action history/audit immutable and free of source values. This
foundation exposes governed service calls, not ingestion APIs, connectors, arbitrary merge scripts,
implicit source-row deletion or a full source snapshot system. Phase 4 must compose these contracts.
