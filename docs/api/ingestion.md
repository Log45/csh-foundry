# Phase 4 governed ingestion

Ingestion uses the existing operational services and PostgreSQL. REST publishes immutable source
and mapping versions, submits durable jobs and reads their status/diagnostics. A separate bounded
worker performs I/O, Polars transformations and governed materialization. No request accepts file
uploads, paths, connection strings, credentials, SQL or executable expressions.

All endpoints are under `/api/v1/ontologies/{ontology_id}` and use the existing server-derived
trusted local principal. Cross-tenant sharing and production OIDC/policy administration remain
outside this phase.

| Endpoint | Contract |
|---|---|
| POST `/sources` | SourceInput → published SnapshotView |
| GET `/sources?limit=50&offset=0` | Source versions; limit 1–100, offset 0–10,000 |
| GET `/sources/{source_id}?version=1` | Exact immutable source version |
| POST `/mappings` | MappingInput → validated, published SnapshotView |
| POST `/ingestion/runs` | RunInput → durable PENDING RunView |
| GET `/ingestion/runs?limit=50&offset=0` | Bounded run history |
| GET `/ingestion/runs/{run_id}` | RunView including progress, errors and staging purge time |
| GET `/ingestion/runs/{run_id}/diagnostics` | Bounded redacted diagnostics with mapping/version/row where available |
| POST `/ingestion/runs/{run_id}/cancel` | Cooperative cancellation at a transaction boundary |

Publishing a source or mapping checks separate create/publication permissions in one transaction.
Updates create a new explicit positive integer version; published rows reject UPDATE/DELETE through
PostgreSQL triggers. List pages check each returned source/run permission and fail closed on a denied record.
Snapshot responses identify tenant, ontology, kind where applicable, actor,
time, version and published status. They contain logical configuration only. Old runs retain their
original mapping/source/schema references. GET source defaults to version 1, not an implicit latest
mutable configuration. Source identity namespaces cannot change across versions.

## Server-managed registrations

`FOUNDRY_INGESTION_CATALOG_JSON` is a secret server setting containing tenant-owned allowlisted
bindings. It is empty by default. A source API body selects an existing binding key; it cannot
register or inspect a path or database URL. Example server configuration for a local fixture:

```json
[{
  "tenant_id":"00000000-0000-0000-0000-000000000001",
  "key":"factories",
  "revision":"1",
  "kind":"csv",
  "root":"/absolute/server/fixtures",
  "file_name":"factories.csv",
  "source_key_column":"factoryId",
  "columns":[
    {"name":"factoryId","data_type":"string"},
    {"name":"factoryName","data_type":"string"},
    {"name":"location","data_type":"string"}
  ]
}]
```

Bindings are keyed by `(tenant_id,key)` and require source:use_binding permission for that key. Files must resolve inside the registered root; traversal,
escaping symlinks and nonfiles are rejected. Resolved files open with no-follow protection. Root
parents and registrations are operator-managed, not writable by API users. Wildcards/remote file
URLs are not expanded. A source snapshot pins a digest of its registration, including declared
columns, source key, filters, type and location. Changing interpretation requires a new published
source version. PostgreSQL password rotation alone does not change interpretation; connection
identity and role changes do. No connection secret or physical path is returned in source views.

CSV uses explicit string columns, a one-character delimiter, strict CSV parsing and UTF-8 with
optional BOM. Headers must exactly match registered columns with no duplicates. Conversions belong
in mappings, not CSV inference. Malformed quoting/header failures reject extraction; recoverable
row-width/record errors can be quarantined.

JSON supports newline-delimited JSON objects, one record per line. Top-level arrays, multi-line
objects, unknown/missing fields, unsupported nested values and malformed lines are rejected or
quarantined. There is no unbounded top-level document parser. Parquet inspects schema names and
selects registered columns through Polars scan/slice collection. Native values are checked against
registered scalar types and normalized to canonical strings for temporal/decimal/UUID values.

PostgreSQL bindings add secret `url`, `table_schema`, `table` and optional `equals` filters.
Only registered table/view columns can be selected or filtered. SQLAlchemy quotes identifiers and
binds values; clients supply no SQL. Reads run under SELECT-only credentials in a read-only,
REPEATABLE READ transaction, with a three-second connection timeout and five-second statement
budget. Superuser/create-role/create-database roles and write privileges on the registered relation
are rejected. A primary key determines ordering; views without one order by selected scalar columns.
Exact duplicates still produce identity diagnostics. Both table and view reads are supported.

A snapshot read streams bounded server cursor batches, computes a digest over the ordered allowed
values and retains only the requested batch. Each resumed read must match that source version's
observed digest within the run. Thus changes between staging batches fail the run instead of
silently mixing snapshots. Source reads and operational writes never share one atomic transaction.
Rows changed after staging completes cannot change the staged operational proposal. Files use a
whole-file content hash. Raw historical input bytes are not archived; operators must retain input
versions if they need replay after staging retention expires.

All bindings support bounded scalar `equals` predicates. File predicates run through Polars before
mapping; PostgreSQL predicates are parameterized at the source. Values must match registered types;
temporal/decimal/UUID PostgreSQL constants decode to typed bind values. Source positions advance
through filtered-out records, preserving restart safety. Filters are server registration, not
unrestricted execution-request expressions. Invalid source records are diagnosed rather than hidden
by a filter whose fields cannot be parsed.

## Source and mapping publication

```json
{"id":"Factory","version":1,"name":"Factories","binding":"factories",
 "identity_namespace":"manufacturing-factories","owner":"source",
 "reconciliation":"edit_wins","update_policy":"upsert","deletion_policy":"ignore"}
```

Ownership can be source or pipeline; both remain distinct from user/action edits. Only upsert and
ignore-missing-row deletion modes are supported. Unsupported deletion/update modes fail validation;
no missing record or partial snapshot implicitly deletes an object.

```json
{
 "id":"Factory","version":1,"source_id":"Factory","source_version":1,
 "schema_version":"1.0.0","object_type":"Factory","identity_column":"factoryId",
 "properties":[
  {"property":"factoryId","column":"factoryId","conversion":"identity"},
  {"property":"factoryName","column":"factoryName","conversion":"identity"},
  {"property":"location","column":"location","conversion":"identity"}
 ],
 "relationships":[]
}
```

Mappings reference canonical object/property/forward-link IDs and registered columns. Column names
can differ from target property names. Identity must be assigned to the canonical primary key from
the declared identity column. Every required property needs a mapping or a canonical default.
Duplicate assignments, wrong direction/types, unknown columns/targets/links and incompatible
conversions are rejected before publication. Active schema is resolved again at submission and
before each worker step; any activation change fails an existing run with stale_schema.

Conversions: identity, string, integer, float, boolean, decimal, date, timestamp, UUID. Polars uses
explicit source schemas, projections, null normalization, casts and aliases in bounded batches.
Integer text requires canonical signed decimal integer syntax; booleans accept lower-case true/
false; dates require canonical ISO dates; timestamps require offsets; UUIDs are canonical lower-case
strings. Decimal text remains exact and canonical precision/scale validation rejects truncation.
Representation equality follows Phase 3; alternate valid temporal/decimal spellings are not merged
by a new reconciliation algorithm. JSON/array target properties and arbitrary nested extraction,
joins, aggregations, scripts and general expression evaluation are unsupported in this scalar MVP.

Null modes are reject (default), null, default, omit. CSV empty values normalize as missing for
mapping. Native source nulls require nullable registration. Defaults must validate against the target
property. Invalid conversion is always an error, never a reason to apply a default. All outputs then
pass the existing canonical `validate_properties`, including primary-key equality, required fields,
nullability, enums, defaults and numeric rules. Unknown JSONB properties cannot be written.

Relationships map a forward `link` and `target_column`; one target per link per record, at most
eight. For example Machine maps locatedInFactory to factoryId; MaintenanceTask maps taskForMachine
to machineId and assignedEmployee to assignedEmployeeId. Inverse rows are never duplicated.

## Run submission, limits and retention

```json
{
 "idempotency_key":"manufacturing-snapshot-001",
 "mappings":[{"id":"Factory","version":1},{"id":"Machine","version":1},
             {"id":"Employee","version":1},{"id":"MaintenanceTask","version":1}],
 "validation_policy":"reject_run","batch_size":25
}
```

A submission key is hashed and tenant/principal/ontology-scoped. An identical normalized plan,
batch size and validation policy returns the original run. Conflicting reuse returns 409.
Mappings are sorted deterministically and exact source/mapping/schema versions are retained. A run
plan/principal/schema/key cannot be modified by normal application updates or direct SQL UPDATE.
The run table also holds the durable job; no second job database or broker is introduced.

| Bound | Value |
|---|---|
| Raw ingestion body / mapping definition | 64 KiB each |
| Mappings per run | 8 |
| Registered columns / mapped properties | 64 |
| Relationships per row / equality predicates | 8 each |
| Source snapshot file/read bytes | 16 MiB |
| Rows per registered source | 10,000 |
| Canonical row / NDJSON line | 16 KiB |
| Run staging | 10,000 selected records / 16 MiB canonical payload plus bounded identity/row metadata |
| Batch size | 1–100, default 25 |
| Whole-run atomic mode | At most 100 staged records |
| Ingested object/source key | 512 UTF-8 bytes each |
| Config/mapping version | Positive signed 32-bit integer |
| Source extraction / transformation | Five / three seconds, cooperative checks around bounded native work |
| Batch SQL work | 15-second diminishing statement budget |
| Worker lease / recovery limit | 60 seconds / 3 claims |
| One runner invocation | At most 40,000 steps |
| History/diagnostic page | 1–100 items; offset 0–10,000 |

File snapshots buffer at most 16 MiB to avoid a hash/read race; CSV/NDJSON parsing and transformations
are batched, not a claim of fully streaming file I/O. Parquet uses Polars scans/slices with streaming
collection, but compressed row groups/native allocations and a PostgreSQL value before its width
check are not protected by a hard process-memory ceiling. Bounds are admission/row limits, not an
OS resource sandbox. Native decoder, DNS, connection acquisition and commit acknowledgement timing
cannot be promised as hard whole-process deadlines. Production memory/container admission and
source views with bounded columns are still necessary for hostile/high-volume inputs.

Only canonical proposals and redacted codes are staged; invalid raw payloads, credentials and
unrestricted source bodies are not stored. Terminal staging/diagnostics have an explicit minimum
seven-day retention policy and bounded cleanup operation; they are not automatically purged by
request handlers. Operators invoke `--cleanup-days 7` regularly. Cleanup processes at most 100
terminal runs, preserves run/configuration/identity history, and exposes staging_purged_at. Retention
requires maintenance invocation; no background scheduler is implied. Source identity/link state
remains durable so deletion/history cannot silently allow another source to take over an identity.

## Transaction, rejection and relationship semantics

The phases are STAGING → VALIDATING → OBJECTS → LINKS → DONE. All source proposals stage before
operational mutation. Duplicate source/target identities are rejected before applying objects;
source ordering never generates random IDs. Source associations bind immutable source keys and
namespaces to the existing tenant/ontology/type/object identity; unrelated-source collisions or
identity rewrites conflict. Typed property validation is reused, not reimplemented.

Object batches run before relationship batches, allowing endpoints from later object batches.
Missing endpoints, uniqueness/cardinality and revisions are enforced by the existing services in
PostgreSQL. Link state remembers which edges ingestion created and their creation timestamps.
An unchanged repeat creates no duplicate edge. An authorized same-source reference change replaces
only its own unchanged managed edge. User/action edge replacement/deletion is protected by default;
explicit override requires permission. A previously sourced object deleted through governed CRUD
is also protected from automatic recreation; source_wins requires an explicit override.

- reject_run: at most 100 records; all operational objects, links, provenance, identity associations
  and the final checkpoint commit in one transaction. Any error rolls them all back. Staging/job
  diagnostics remain. Larger runs explicitly fail before materialization.
- reject_batch: invalid staging groups are rejected together. Operational batch failure rolls back
  that batch and records diagnostics; completed earlier batches remain. Objects and links are separate
  phases/batches, so a later relationship failure can leave previously committed valid objects.
- quarantine: invalid object records never materialize. Per-record savepoints isolate permitted
  failures inside a batch; the outer batch commits accepted effects and checkpoints together.
  Relationship rejection is explicit LINK_REJECTED with a relationship diagnostic; previously
  committed objects remain. Do not interpret relationship quarantine as undoing earlier object batches.

Authentication/authorization and transient database failures fail/retry the step instead of being
silently treated as bad source data. reject/manual reconciliation can persist Phase 3 property
conflicts in quarantine mode; failed whole-run transactions retain redacted ingestion diagnostics
rather than committed mutation/conflict effects. edit_wins preserves user/action properties and
accepts same-source/pipeline-owned updates. Source version ownership is explicit and stable on
unchanged repeats. source_wins rechecks edit:override. No source refresh silently rewrites identity.

Checkpoint advancement, stage state, counters, operational mutations and provenance commit in the
same transaction, so there is no independent successful-checkpoint write before effects commit.
Retries replay remaining stage states without incrementing unchanged object revisions. New runs
also upsert identically. Cancellation commits between steps, fences the old token and preserves
already committed batches. History counters describe committed effects, not attempted writes.

## Durable worker and authorization

```bash
uv run python -m ontology_platform.ingestion --ontology manufacturing
uv run python -m ontology_platform.ingestion --ontology manufacturing --cleanup-days 7
```

Claims use FOR UPDATE SKIP LOCKED, a random lease token, expiration, attempt count and checkpoints.
Only jobs initiated by the worker's server-configured principal are eligible. Claim and every step
check current permissions; no unrestricted background identity or client-selected delegation exists.
Current source/mapping reads, object/property/link mutation and reconciliation permissions are also
checked at application-service boundaries. Full production identity/delegation is deferred.

Workers renew after successful steps and expose an authorized renewal method. Expired leases can
be reclaimed within a maximum of three total claims; stale tokens and expired owners cannot commit. A stale
prepared batch cannot overwrite an advanced checkpoint. Unexpected process death leaves a leased
RUNNING job for recovery. Transient errors requeue up to the same bound; terminal error codes persist.
The bounded CLI handles one eligible run, then exits. Scheduling, multi-process supervision, retry
backoff and production workload admission are operator concerns, not a distributed orchestrator.

Permissions include source:create/publish/read/use_binding, mapping:create/publish/read, ingestion:execute/
claim/history/diagnostics/cancel/cleanup, edit:initialize_source/reconcile/override, plus existing
object/link/property permissions. The trusted local provider remains a tenant administrator; custom
providers must express consistent policies across CRUD, queries, actions and ingestion. Tenant-safe
FKs and scoped service predicates remain enforced; no RLS/public deployment claim is added.

Errors use existing structured envelopes and sanitized stable codes. Examples: invalid_mapping,
source_header_error/source_parse_error/source_type_error; invalid_conversion/invalid_enum/
invalid_decimal/invalid_date; duplicate_identity; source_identity_collision/source_identity_changed;
source_changed/registration_changed/stale_schema; revision/unique/cardinality conflicts;
reconciliation_conflict/relationship_edit_conflict; lease_lost/checkpoint_changed/lease_exhausted.
Diagnostics retain category, mapping/version and source record number when available; run-wide failures have
no invented row location. Bodies/credentials/source values are not echoed in errors.
