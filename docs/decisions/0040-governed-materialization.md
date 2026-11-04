# ADR 0040: Governed dataset materialization

Status: Phase 15 design recorded before implementation. Acceptance is tracked separately.

MAPPING uses the existing Project resource registry, folder, sharing and archive services. Definition
versions are append-only, sequence-numbered, closed JSON contracts. They reference a canonical
ONTOLOGY_VERSION resource and an exact published version. Execution requires that same version to
remain active; even additive activation requires explicit republication. No display name resolves a
schema. Dataset/artifact UUID, checksum and schema are pinned in execution input/request metadata.

Identity uses the canonical ontology primary key. A single key is normalized to its declared scalar
type and rendered as the canonical primary-key string. Composite keys require a string primary key
and use SHA-256 of a typed, NFC-normalized JSON tuple (versioned algorithm). Tenant, ontology and type
scope the canonical object table key. Decimal numeric equivalents normalize; booleans remain distinct
from numbers; null/nonfinite keys are rejected. Conflicting duplicate object identities fail full-source
validation; identical rows may coalesce explicitly. Relationships use the same identity algorithm.

Direct columns and explicit constants support strict scalar conversion, explicit null/default policy,
and existing required/enum/precision validators. Nested/binary/array values and arbitrary expressions
are rejected in this initial subset. Temporal conversion must not truncate precision. Rejected
alternatives: user Python, implicit stringification of arbitrary objects, permissive casts and silently
resolving newer schema versions.

Full-source conversion runs in the Phase 14 isolated child with its existing limits and Polars batches.
A local disposable SQLite staging index bounds duplicate state in memory; it is temporary processing
state, never an authoritative database or queue. It stores one object/link per canonical identity and
bounded samples. Source plus staging must fit the existing temporary budget. Source remains 1 GiB;
object count has an independent explicit per-run budget. No per-cell provenance is introduced.

Materialization reuses execution_jobs admission, leases, heartbeat, retries, cancellation and fencing.
Objects are processed before links, in bounded short transactions; every batch rechecks mapping write,
source read, target Project access, active schema and current principal permissions. Object writes pass
through ReconciliationService.create_from_source/refresh -> ObjectService. Links use
ObjectService.create_link, including endpoint, type, cardinality and mutation authorization. No worker
SQL inserts canonical objects or links. Stale tokens and elapsed leases prevent further batch commits.

An append-only object ownership association prevents adopting unrelated or differently mapped objects.
Property overlays use source='mapping:<stable UUID>', owner=pipeline, edit_wins; action/user values
remain protected. Insert-only rejects existing owned records whose mapped values differ. Ownership
transfer/revocation and source deletion are excluded: archive prevents future writes, but retains
ownership/history. Link insertion is idempotent; existing edges are observed, never deleted/replaced.
This avoids seizing action-managed link ownership. Missing endpoints and cardinality fail safely.

Publication is explicitly transactional batches with visible partial state, not cross-transaction
atomicity. Each successful batch commits mutation, provenance and metrics together. Failure/cancellation
preserves prior batches and their run ID; retries replay pinned inputs and skip committed provenance.
Success is recorded only after both passes finish. No successful-run visibility claim is made during
execution. Rejected alternatives: one transaction for 1 GiB, parallel object store/generation graph,
destructive replacement, and direct worker writes bypassing domain services.

Provenance is one immutable record per run/target, with source reference, operation and timestamp;
run input and immutable definition supply checksum, schema, actor and target version. Counts/retention
are bounded by per-run object/link limits and existing queue admission. Lineage retrieval requires
mapping, dataset and ontology authorization and object/link visibility. No private source payload is
returned in diagnostics or provenance. Schema validation is operational; semantic reasoning remains
in the existing independent Open Ontologies service. No new external semantic API is introduced.

Production remains blocked under Section 23B; no Phase 16 feature is authorized.

Implementation refinements: ownership uses an ontology-qualified tombstone rather than an object FK,
so existing governed action deletion remains possible; refresh refuses to resurrect that identity.
CSV columns declared String are parsed as String before per-batch inference, preserving leading zeros
and preventing row-order/batch-boundary-dependent identities. Existing dataset validation retains its
original inference because the streaming override is opt-in. Preview also accepts a draft specification
with dataset/version pins, so users can inspect samples before publishing an immutable definition.

Previously observed materialized links that have been removed through governed mutations are not
silently recreated. Immutable provenance detects the missing edge and the run fails with a conflict;
existing replacement edges and action-managed values remain authoritative.
