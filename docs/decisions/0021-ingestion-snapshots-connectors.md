# ADR 0021: Immutable ingestion configuration and registered connectors

Status: Accepted for Phase 4

Publish immutable tenant/ontology-scoped source and mapping version rows. Keep physical paths,
connection identities and credentials in a server-owned tenant binding catalog; REST selects
registered keys only. Pin a registration digest, exact source/mapping versions, active canonical
schema and input fingerprints to each run. Changing registration interpretation requires a new
source version. Password rotation alone does not change interpretation.

Use existing Polars and Python/SQLAlchemy dependencies: bounded local CSV/NDJSON snapshots, Polars
Parquet scan/slice, read-only allowlisted PostgreSQL tables/views with bound scalar predicates.
File predicates use bounded Polars expressions; mappings select/rename columns and explicitly
convert scalars before the existing canonical validator. No executable expressions, arbitrary SQL,
filesystem paths, uploads, remote URLs, new analytical engine or extra operational database.

Buffer at most 16 MiB of local input to hash the same bytes being parsed; do not describe this as
fully streaming file I/O. PostgreSQL uses a bounded server cursor and read-only repeatable-read
snapshot, rechecking a fingerprint on resumed batches. Native Parquet row groups/individual source
values and OS/native timing are not a hard process memory/deadline sandbox. Preserve and document
these limitations instead of inventing streaming guarantees. Old raw input is not archived.
