# ADR 0023: Source identities, governed edits and staging retention

Status: Accepted for Phase 4

Preserve canonical tenant/ontology/type/object identities. Persist source ID/namespace/key associations
and reject unrelated-source collisions or identity rewrites. Create missing source/pipeline-owned
objects through a small ReconciliationService extension that composes ObjectService atomically;
it cannot adopt existing objects. Existing objects use the existing refresh policies, revisions,
property authorization and conflict model. No parallel reconciliation or mutation engine is added.

Track managed relationship identity/creation time separately from operational forward edges. Source
refreshes replace only unchanged source-managed edges; governed replacements/deletions and previously
sourced object deletion are protected by default. Explicit source_wins checks override permissions.
Missing source records never imply deletion. Only upsert/ignore-missing-row modes are supported.

Keep bounded canonical staging plus redacted diagnostics, never raw invalid payloads/credentials.
Expose mapping/version/record location and stable error codes. Retain terminal staging at least seven
days, then permit explicit bounded cleanup; maintain permanent run/configuration/identity history and
a purge timestamp. Operators must invoke maintenance. Reproduction after cleanup requires retaining
external input versions; content hashes do not create an archive. Production admission, scheduling,
retention automation and complete source snapshot lifecycle remain later operational hardening.
