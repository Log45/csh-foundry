# Dataset registry and immutable snapshots (Phase 13)

Datasets are independent DATASET registry resources: no ontology or schema publication is required.
Project membership plus current platform permissions govern every operation. The existing resource
APIs provide listing/search, rename, description, folder movement, sharing/revocation and archive.
Resource identity and owning Project never change. Archived resources/Projects deny version reads.

| Method | `/api/v1` path | Purpose |
| --- | --- | --- |
| POST | `/projects/{project}/datasets` | Create with name, description and optional folder_id |
| GET | `/datasets/{dataset}` | Governed resource metadata |
| GET | `/projects/{project}/resources` | Bounded discovery, including datasets and incoming shares |
| PATCH | `/resources/{dataset}` | Rename, describe, move (expected_revision required) |
| POST | `/resources/{dataset}/archive` | Retain metadata and bytes, end normal access |
| PUT | `/resources/{dataset}/shares` | Existing explicit Project share/revoke protocol |
| POST | `/datasets/{dataset}/uploads` | Reserve version and artifact in one transaction |
| PUT | `/datasets/{dataset}/versions/{version}/content` | Existing streamed artifact transport |
| POST | `/datasets/{dataset}/versions/{version}/finalize` | Verify source, validate and publish |
| GET | `/datasets/{dataset}/versions` | Sequence-descending history, limit 1–100, offset 0–10000 |
| GET | `/datasets/{dataset}/versions/{version}` | Version metadata, schema and validation result |
| GET | `/datasets/{dataset}/versions/{version}/schema` | Ordered schema of a valid committed snapshot |
| GET | `/datasets/{dataset}/versions/{version}/preview?limit=20` | First 1–100 records in source order |
| GET | `/datasets/{dataset}/versions/{version}/content` | Integrity-verified source attachment |
| POST | `/datasets/{dataset}/cleanup` | Owner-only artifact reconciliation, dry_run by default |

Initiation requires `filename`, byte `size`, SHA-256 `checksum`, `format` (`csv`, `json`, `ndjson`,
`parquet`), and optional bounded `source` provenance. Filename does not participate in storage keys.
Explicit format selects the parser; actual content must parse in that format. Extensions and MIME
claims are not trusted. Inputs cannot be file paths, URLs, pickle or user code. Only Parquet's internal
compression is accepted; compressed text containers are unsupported.

The dataset ID equals artifact_id in the version response, and the dataset version ID pins the exact
physical artifact version with that ID. This shared identity prevents cross-Project byte references.
`state` is the dataset lifecycle; `artifact_state` is the independent physical lifecycle. `created_at`,
`created_by`, `filename`, `checksum`, `size`, `sequence`, `provenance` and artifact `committed_at` are
inherited immutable source metadata. `validated_at` records validation completion for success or
failure. `result` contains immutable schema, counts, parser version and validation guarantee, or a
sanitized error code/message. Cached records are returned only by the preview endpoint, not history.

Dataset states: PENDING → COMMITTED or FAILED. Artifact states retain Phase 12 semantics.
Finalization first durably commits verified source bytes, then parses in a spawned process and
rechecks write authority before publishing the result. The parser's result is not visible until the
PostgreSQL transaction commits. A process crash or failed database publication leaves PENDING;
retry finalization resumes from immutable bytes. Concurrent finalizers converge on one terminal row.
Finalization of terminal rows is idempotent. Validation failure returns metadata with state FAILED,
not a valid snapshot; preview/schema return structured 409 errors. Corrected bytes need a new version.
No raw parser exception or source value is reflected in diagnostics. Transport/integrity failures
retain the existing structured artifact errors; request validation uses normal FastAPI 422 errors.

Failed validation retains committed source bytes indefinitely for authorized diagnostics/download.
Owner cleanup only selects old uncommitted physical versions. It retains metadata and marks the
physical version DELETED after exact-key cleanup; dataset PENDING metadata remains diagnostic history
and cannot subsequently publish. There is no prefix cleanup, hard delete, automatic retry job or
purge of committed bytes. Resource archive retains every historical version.

## Validation and schema semantics

- Source ≤8 MiB; decoded Polars frame ≤32 MiB; ≤100000 rows and 256 columns; nesting ≤8 levels.
- Columns have unique, nonempty printable names ≤200 characters. JSON duplicate keys are rejected.
- CSV: strict UTF-8 (optional leading BOM is stripped for parsing), comma, double-quote escaping, mandatory header and exact row widths. Empty
  fields are null. Header-only input is empty data; zero-byte CSV is invalid. Polars infers over the
  entire file with date parsing enabled; mixed numeric/text columns become String. Leading zeros in
  inferred numbers may normalize; upload as JSON strings or Parquet String when identity formatting
  matters. No ignored parse errors, row truncation or sampled schema conformance.
- JSON: a top-level array of nonempty objects. NDJSON: one object per nonblank UTF-8 line. Record keys must
  match (order can differ); nonnull value types must agree recursively. Numbers may widen to float;
  booleans and numbers cannot mix. Missing keys differ from explicit null. Empty arrays/NDJSON have
  no columns. All-null columns are Null; empty lists retain Polars' inferred nested Null type.
- Parquet: PyArrow reads bounded footer metadata with extensions disabled, checks row/column and
  uncompressed row-group size limits, then Polars preserves supported logical types. Arrow source
  schema is also recorded as text. Corrupt/truncated content and unsupported serialization types
  fail. No timezone or decimal conversion is performed beyond parser-native representation.
- Schema is ordered `{name, order, logical_type, nullable}`. Nullability describes observed nulls,
  not a contractual guarantee for later versions. Each committed schema is immutable and may differ
  from earlier versions. Nested logical types are represented by Polars' type expression.
- Full content is parsed and every decoded value is validated before publication. Per-string cells
  ≤64 KiB; preview ≤100 records and 1 MiB serialized JSON. Oversized preview records cause validation
  failure. No sampling claim or general query/filter/join/aggregation API.
- Parser subprocess has a 30-second wall deadline, 20-second CPU limit, and a Linux address-space
  limit of 2 GiB. Local macOS uses a child RSS watchdog (512 MiB, polled every 0.1 seconds) because it does
  not provide that address-space limit; this is a soft development safeguard. Two parsers per API
  process are admitted concurrently; excess finalization returns 503 and remains retryable.
  These are development bounds, not production hostile-input certification. Aggregate capacity across API replicas and larger datasets require separately validated capacity work.

Preview returns `columns`, positional `rows` (preserving schema order), and total `row_count`.
Nulls are JSON null. Dates/times/timestamps use ISO strings; decimals use strings; binary uses
`{"base64":"..."}`; lists and structs use recursive JSON. Nonfinite numbers and unsupported types
fail validation. Records are cached at commit, so preview does not reopen or materialize source data.
Preview uses current dataset governance, with no storage paths or credentials. Source downloads are
separate single-version authorization; generic artifact endpoints reject dataset identities.

Studio uses existing session/CSRF/tenant protections and the fixed binary BFF, with an explicit format
selector, validation progress, failure details, paginated version history and bounded schema/row table.
Rename/move/archive/share controls remain the generic Project controls. No Phase 14 transforms,
ontology mapping, query engine or derived lineage operation is implemented. Provenance identifies
actual uploads only. Production remains blocked under Section 23B.
