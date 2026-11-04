# ADR 0038: Independent governed dataset snapshots

Status: accepted for authorized Phase 13; recorded before implementation.

A DATASET registry resource owns immutable artifact versions using its own stable resource ID.
Artifact transport is reused through a dataset-specific service adapter; generic artifact endpoints
continue to reject DATASET IDs. Sharing grants access only to that dataset's versions. Project
membership, tenant locks, resource lifecycle, audit and canonical ontology authority remain intact.

Dataset versions extend a reserved artifact version with a declared format, immutable schema,
provenance, validation result and bounded preview. PostgreSQL composite foreign keys and triggers
require the artifact and dataset to have the same tenant and resource identity; publication requires
a committed artifact. Tenant transaction locks serialize sequence allocation and publication.
PENDING becomes COMMITTED or FAILED. Retry after a crash can resume PENDING validation against
committed bytes. Terminal dataset rows cannot change. Failed parsing retains committed source bytes
for diagnostics; abandoned uncommitted uploads use existing artifact reconciliation. No automatic
purge of committed bytes is introduced.

Initial validation is deliberately restricted to 8 MiB source bytes, 100,000 rows, 256 columns,
8 nested levels and 100 preview rows. Full parsing validates every record, never sampled conformance.
CSV is strict UTF-8, comma separated with a mandatory unique nonempty header and exact row widths;
empty CSV requires a header. JSON is an array of objects; NDJSON is one object per nonblank line.
JSON duplicate keys and inconsistent record keys/types are errors. Empty JSON arrays have no columns.
Nulls are allowed; CSV empty fields are null. CSV inference scans all rows with Polars; JSON values
must have consistent types (numeric widening allowed by Polars). Parquet retains Polars source types.
Compression is supported only inside Parquet. Schema nullability describes observed nulls, not a
future constraint. Historical schemas are never rewritten.

Parsing runs in an isolated spawned process with a deadline; Parquet metadata expansion, decoded
cell sizes and schema nesting are bounded before publication. Preview is stored with the validated
snapshot so reading it never re-parses or materializes large files. Values use JSON null, ISO temporal
strings, decimal strings, base64 binary and recursive JSON collections; nonfinite numbers are rejected.
No user code, query engine, transformations, ontology mapping or derived lineage is implemented.
Production remains blocked under Section 23B.
