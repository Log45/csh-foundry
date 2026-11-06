# Atomic multi-output publication protocol

The visibility transaction belongs to PostgreSQL. S3/MinIO is outside that transaction.

1. Admission authorizes exact committed input pins and every output target. PostgreSQL stores one
   parent execution job, immutable plan/digest, node records and output reservations. New target UUIDs
   and output version UUIDs are allocated once, without visible placeholder resources or versions.
2. Fenced workers execute/verify every ancestor and serialize each output under existing child
   limits. Full-content/schema validation, SHA-256, size and row-count verification precede staging.
3. Output bytes are uploaded to final immutable ObjectKeys and verified using ArtifactStore. There
   is no metadata or download capability for these objects during preparation. A private durable
   manifest records the target/version identities, checksum, schema/result and PREPARED state. No
   later copy/move is required to make a successful commit usable.
4. After every output is PREPARED, publication takes the existing security/tenant governed lock,
   parent job row lock and sorted target resource locks. It rechecks live DB-clock lease/token,
   cancellation, engine/input/target authority, all immutable object checksums and output contracts.
   Concurrent writes to existing targets append immutable versions under those serialized locks.
   Duplicate targets inside one run are rejected. There is no silent last-writer-wins replacement.
5. Inside one SQLAlchemy/PostgreSQL transaction, DatasetService creates all new resources and all
   artifact/dataset versions at their preallocated identities, associates provenance, commits each
   physical/logical version, commits every manifest row, records a commit UUID, and marks the parent
   SUCCEEDED. Audit belongs to the same transaction. A final DB-clock fence precedes success.
6. PostgreSQL commits once. Any error rolls back every metadata/resource/visibility change. Deferred
   artifact/dataset constraint triggers additionally reject an individual DAG version becoming visible
   in a separate transaction without its committed parent manifest and successful parent job.

Cancellation and commit serialize on the parent/security/tenant lock domain. If cancellation wins,
fencing rejects publication, no outputs appear, and the parent becomes CANCELLED. If commit wins,
all outputs appear and subsequent cancel preserves SUCCEEDED. A failed or pre-commit-cancelled run
never exposes the subset of outputs whose preparation happened to succeed.

Recovery reads PostgreSQL. A COMMITTED manifest and SUCCEEDED parent are authoritative even if a
worker acknowledgement was lost. Terminal parent immutability prevents duplicate success/publication.
If the transaction rolled back, manifests remain PREPARED and all version identities remain reusable.
An expired token cannot mutate node/manifest records or publish. The replacement token must reverify
plan/inputs and private bytes before reuse. Missing private bytes are recomputed; checksum mismatches
are not reused. Storage's immutable put/verify handles a crash after upload but before manifest update.
Outputs with incompatible recomputed checksums fail rather than replacing immutable staged bytes.

Private intermediate cleanup and uncommitted output cleanup only run after terminal parent state.
The sweep takes the parent lock; a manual retry waits until cleanup finishes, then regenerates missing
bytes at the existing reservations. Cleanup never deletes COMMITTED output keys and is idempotent.
A cleanup timestamp bounds routine rescanning; manifests are rechecked daily for late stale-worker uploads. A crash
mid-cleanup leaves it unset so the next bounded worker sweep retries. Storage errors may temporarily
retain private orphan bytes, but cannot expose partial datasets. Local scratch after abrupt host
termination remains an operator filesystem-maintenance concern.

Manifest state is EXECUTING, PREPARING, PREPARED, COMMITTED, or ABANDONED. Recovery can restart a
nonterminal attempt from EXECUTING using verified node results. Terminal failure/cancellation cleanup
marks ABANDONED. Node states and parent attempts are real persisted events, without invented progress.
No mutable manifest is a user-visible dataset catalog, alternate artifact store or authorization grant.

Migration: forward-only `0026_pipeline_dag` follows `0025_applications`. It adds dag_runs, dag_nodes,
dag_outputs, tenant-qualified parent FKs, stable unique reservations, state/commit constraints, live
fencing/immutability triggers, success guards and deferred visibility guards. It permits v2 parent
jobs without a legacy primary output field. Historical definitions/jobs/versions remain untouched.
Use owned disposable schemas to test fresh install, prior-head upgrade and Alembic drift. Never run
this migration against the shared developer database without separate explicit authorization.

Production remains BLOCKED under PLANS.md §23B. This protocol does not certify object-store durability,
operator recovery, target-cluster isolation or distributed ACID across PostgreSQL and S3.
