# ADR 0037: Governed immutable artifact storage

Status: accepted for authorized Phase 12. Recorded before substantial implementation.

PostgreSQL owns artifact identities, authorization, lifecycle and version metadata. An ARTIFACT
registry resource uses the existing owning Project, folders, sharing, archive and tenant locks.
Ontology authority columns become nullable only for this new type; historical ontology references
and their trigger validation remain mandatory. No dataset service or second ACL is introduced.

Artifact versions reserve opaque tenant/artifact/version keys and monotonically increasing sequences
under the existing tenant lock. States are PENDING, COMMITTED, FAILED and DELETED. A committed
row and its bytes are never overwritten or automatically purged. Resource archive retains history.
An additive forward-only migration enforces tenant FKs and committed-row immutability.

Transfers are server mediated, size bounded, spooled to disk and streamed to/from a replaceable
ArtifactStore. The S3 adapter uses bounded SDK retries/timeouts, conditional immutable writes,
multipart abort on failure, read-back SHA-256 verification and explicit provider errors. Filenames
never participate in keys. Content is always downloaded as an attachment with nosniff; generic
bytes are not parsed, executed or rendered. Client MIME types are ignored (application/octet-stream).

The upload protocol has separate durable initiation, transfer, and finalization transactions. Transfer
and finalization serialize with governance; interrupted transfers cannot commit metadata. If storage
succeeds and PostgreSQL rolls back, a retry verifies the same immutable object. Finalization rechecks
bytes and is idempotent. Explicit owner maintenance expires abandoned uploads after a configured
age, records failure before deletion, and only deletes FAILED versions with no committed consumer.
No prefix deletion, committed purge or automatic bucket lifecycle rule is allowed. Future consumers
must reference committed version rows; deletion of those rows is prohibited.

Storage is disabled by default. Local MinIO is an opt-in profile with persistent storage and separate
bootstrap/application credentials. Externally managed S3 is configured by operators, never clients.
TLS verification cannot be disabled; development HTTP must be explicitly enabled. Presigned GET
is optional only when operators explicitly declare the configured endpoint client reachable; short
single-object capabilities can survive revocation until expiry. The default transfer reauthorizes
requests. No organizational deployment or production certification is authorized.
