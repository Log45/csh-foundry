# ADR 0039: Bounded ingestion and governed pipeline execution

Status: Phase 14 design; implementation and acceptance tracked separately in the phase report.

PostgreSQL remains the control plane and metadata authority. Dataset ingestion, immutable pipeline
specifications, and execution are separate modules. ArtifactStore remains the only byte transport.
No Spark, arbitrary Python, ontology mapping, distributed queue, or additional database is introduced.

## Contracts and processing

A portable JSON specification describes named input contracts, a typed expression tree and ordered
relational operations. An engine interface accepts resolved local immutable files and returns a
validated output manifest; persisted definitions never contain Polars expressions or executable code.
The Polars adapter plans lazy scans and writes Parquet. Select/filter/project can stream; sort, joins,
grouping and deduplication can require state. Admission is based on bounded worker resources, not a
promise that every operation fits every dataset. Strict casts reject overflow. Null predicates exclude
unknown rows; division by zero is an error, never an implicit nonfinite result.

Source size defaults to 1 GiB and can be lowered. Independent operator settings bound decoded bytes,
record bytes, rows, columns, batch bytes, memory, CPU, temporary disk, wall time and concurrency.
Text validation reads incremental records and batches; JSON arrays preserve duplicate-key rejection.
CSV validates every record, and schema reconciliation covers the complete file. Parquet metadata and
batches are bounded before decoding. Only schema, counts, provenance and first-100 preview enter SQL.
Historical snapshots keep their original parser semantics. No whole-file source buffer is required.

## Durability and authority

Validation jobs and runs use PostgreSQL leases, clock_timestamp, SKIP LOCKED, heartbeat and random
attempt fencing tokens. A short admission transaction applies global/tenant/Project queue and active
limits. No tenant lock spans parsing or artifact transfer. Workers recheck the initiating principal's
current permissions before input resolution and publication. Revocation prevents publication. Pipeline
sharing confers no input or output permissions. Private/missing IDs use existing non-enumeration rules.

Each run pins definition UUID, dataset/version UUIDs, SHA-256, parameters and engine version before
queueing. Published definitions and lineage are append-only with composite tenant-qualified FKs.
Output reservation is deterministic per run, and only one fenced attempt can publish it. Execution
writes private temporary files; verified immutable artifact bytes commit before one SQL transaction
publishes dataset metadata, lineage and success. A crash leaves unreferenced/pending bytes, never a
successful partial dataset; a resumed attempt verifies the reserved bytes or abandons its staging
reservation. PostgreSQL and S3 are explicitly not one transaction.

Cancellation invalidates publication and terminates only the attempt child; expired leases can retry
with a new token. Permanent data/specification failures are distinct from retryable storage/database
failures, with bounded retries. Terminal completion is idempotent. Durable work never depends on an
HTTP background task, and repeated finalization returns existing validation status.

## Isolation and limitations

Workers execute trusted declarative adapters in spawned processes with CPU/address-space/file-size
limits and bounded temporary directories. Linux deployment requires container memory/CPU/pid/disk and
egress restrictions for hard isolation. macOS RSS monitoring is a development safeguard, not a cgroup
or hostile-code sandbox. Definitions cannot specify paths, URLs, storage keys, imports or callbacks.
Errors expose fixed categories, not parser contents, filesystem paths or credentials. Capacity is
rejected when required limits cannot be provided. No production certification is implied.

Lineage is produced only by successful real runs and pins both physical and logical versions. Retrieval
checks output access and filters each input independently; inaccessible identities and definitions are
omitted. Bounded pagination prevents graph expansion. Studio uses existing session/CSRF/tenant BFF
protections, bounded checksum chunks and streamed transfer, with explicit queued validation states.

Mandatory acceptance includes real PostgreSQL/MinIO tests and deterministic 8/100/500/1024 MiB sources
for all four formats, peak memory/disk measurements, a 1 GiB transformation, failure/restart/fencing and
existing regressions. Missing evidence is NOT RUN, never acceptance. Section 23B remains blocked.

Implementation refinements: the existing small-source finalize endpoint remains a synchronous
compatibility path, now using the bounded parser. Sources over 8 MiB always enqueue; `/validate`
explicitly queues any source size. API transfer slots use connection-owned PostgreSQL advisory locks,
released on disconnect, independently of job leases. Short reauthorization transactions surround S3 I/O.
A durable admission stores authenticated identity attributes, never a bearer token; the trusted worker
reconstructs a bounded internal actor for an attempt and checks current identity bindings/membership.
OIDC bearer expiry does not silently cancel admitted work; identity/membership revocation does.
CSV uses its completely reconciled schema for lazy execution, avoiding whole-source inference in the
executor. JSON normalization casts bounded pieces to the reconciled schema before lazy scanning.
Reserved derived versions reject user upload/finalize/validation. Physical and logical publication
guards require the live job lease and transaction-local attempt token, so another governed endpoint
cannot publish staging output. Run initiation and publication require pipeline Project write permission
as well as current input read and output write authority. Input schemas/counts are checked against
immutable snapshots, and materialized output schemas must match the planned schema.
