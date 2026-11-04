# Local execution workers and limits

Production remains blocked under Section 23B. These are development execution controls, not production
certification or a hostile-code sandbox. No service is automatically started or shared schema migrated.

Provision PostgreSQL and the existing opt-in MinIO configuration, explicitly migrate a selected database
to `0021_execution`, then run `uv run python scripts/run_execution_worker.py` in a separate process.
Use the same database schema, artifact endpoint/bucket and identity configuration as the API. Storage
credentials stay in the controller; the declarative child receives only resolved temporary paths and
specifications. Do not expose a worker HTTP endpoint. The worker does not migrate a database.

`FOUNDRY_EXECUTION_` administrator settings (integers, bytes unless noted):

| Setting | Default | Meaning |
| --- | --- | --- |
| SOURCE_BYTES | 1073741824 | Individual source/upload acceptance ceiling; may be lowered |
| DECODED_BYTES | 17179869184 | Total decoded frame bytes, independent from source compression |
| BATCH_BYTES | 8388608 | Target text batch; decoded batch maximum four times this value |
| RECORD_BYTES | 1048576 | Text record/physical CSV line limit; cells retain 64 KiB bound |
| ROW_GROUP_BYTES | 268435456 | Maximum declared Parquet uncompressed row-group size |
| ROWS / COLUMNS | 100000000 / 256 | Independent row and schema-width policy |
| MEMORY_BYTES | 2147483648 | Child RSS watchdog budget |
| ADDRESS_BYTES | 8589934592 | Linux RLIMIT_AS; address space differs from resident memory |
| TEMPORARY_BYTES | 4294967296 | Sum of resolved inputs and generated files per attempt |
| WALL_SECONDS / CPU_SECONDS | 1800 / 1200 | Child deadline / OS CPU limit |
| CONCURRENT_JOBS | 2 | Active jobs per control-plane schema across worker replicas |
| TENANT_JOBS / PROJECT_JOBS | 2 / 1 | Active admission limits |
| QUEUE_JOBS | 100 | Total queued/active admission bound |
| LEASE_SECONDS / ATTEMPTS | 60 / 3 | Lease duration / maximum claim count |

Artifact settings independently bound source transport: `FOUNDRY_ARTIFACT_MAX_BYTES` defaults to 1 GiB,
`CONCURRENT_UPLOADS` 2, `TENANT_UPLOADS` 1, `TRANSFER_SECONDS` 1800. Session advisory transfer slots
release on disconnect; an explicit idle API connection is held, with no business transaction. Provision
at least concurrent_uploads × max_bytes API temporary disk, plus concurrent_jobs × temporary_bytes
worker disk. Artifacts and datasets share the existing S3 bucket; PostgreSQL contains no source frames.

Linux CPU/address-space/per-file-size limits are kernel enforced. Aggregate directory size, RSS and
wall/cancellation are monitored by the controller; macOS RSS monitoring is a soft safeguard. A Linux
container/cgroup with memory/CPU/pid limits, a size-limited temp volume, non-root UID and restricted
egress is required for hard deployment isolation. RLIMIT_AS is not a cgroup, and the macOS watchdog
is not equivalent. This phase's local measurements do not certify a multi-tenant hostile-code service.

Repeat local acceptance with `scripts/validate_phase14.py`, `--large`, `--full`, and `--browser`.
These runners start only disposable MinIO volumes and randomly named PostgreSQL schemas. The large
suite generates exact 8/100/500/1024 MiB sources, verifies whole-source SHA-256/row counts/previews,
prints upload throughput and child peak RSS/temp use, and executes a 1 GiB CSV transformation. Parquet
fixtures are uncompressed, with bounded row groups and deterministic footer padding to exact byte size;
no giant fixtures are committed. Small/large parser conformance tests do not substitute for Linux
cgroup, crash-at-every-instruction or external object-store certification.

Polars scratch paths are pinned to the owned job directory using the verified POLARS_TEMP_DIR contract;
Python temporary files use the same directory. Declarative children retain only required locale/import
environment variables, not controller credentials. For a smaller scale rerun, use
`--large --large-selection 1073741824` to execute all four maximum cases and the CSV transformation.
The synchronous <=8 MiB compatibility path retains Phase 13 process admission/isolation bounds; the
explicit `/validate` endpoint always uses durable worker admission and the settings above.

Derived output reservations are worker owned: user dataset upload/finalize/validation endpoints reject
them. Both artifact and dataset commit guards require a live lease and the transaction-local execution
token. Pipeline Project write permission, all input read permissions and output write permission are
rechecked before publication. Operators must not bypass these guards to repair an interrupted run;
use bounded retry with its original immutable reservation.

`--browser-only` runs the browser workflows without repeating Python acceptance, including a generated
1 GiB CSV upload through Studio/BFF/API. The binary BFF bypasses Next Proxy's cloning buffer while
retaining route-level session, CSRF and tenant checks. The maximum browser test disables trace capture
and removes the login-only interception before streaming to avoid test-driver buffering.

Phase 15 extends this same controller with MATERIALIZATION jobs. A deliberately selected disposable/
development schema must be at `0022_materialization` for current code. The worker CLI is unchanged.
Mapping source conversion uses the existing child limits and an attempt-local disk index; target
mutations use short, fenced batches of 100 through canonical application services. Default target
budgets are 100,000 objects / 100,000 links (each at most one million). Counts and immutable provenance
commit with each batch; partial failures/cancellations retain visible progress. Restart/retry does not
adopt unrelated objects or overwrite action edits. No destructive source deletion, ownership transfer
or automatic provenance purge is supported. See the Phase 15 API/report for contracts and measurements.
