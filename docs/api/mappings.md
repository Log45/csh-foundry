# Governed dataset mappings

A MAPPING is a normal Project resource. Generic resource APIs provide discovery, search, rename,
description, folder moves, archive and read-only shares. Stable IDs survive moves and renames.
Production remains blocked; Phase 16 is excluded.

All endpoints use `/api/v1`, existing authentication, tenant selection, Project membership and schema/
object/property/link authorization. Source dataset, mapping and target ontology access are cumulative.
A share never grants mutation or access to its private dependencies.

| Operation | Endpoint |
| --- | --- |
| Create | `POST /projects/{project}/mappings` (CreateArtifact contract) |
| Read | `GET /mappings/{mapping}` |
| Structural target validation | `POST /mappings/{mapping}/validate` (MappingSpec) |
| Immutable publication/history/read | `POST/GET /mappings/{mapping}/definitions`, `GET /mappings/{mapping}/definitions/{definition}` |
| Bounded read-only sample | `POST /mappings/{mapping}/preview` (MappingRun or draft MappingPreview) |
| Materialize/full-source validation | `POST /mappings/{mapping}/runs` (MappingRun; mode materialize/full_validation) |
| History | `GET /mappings/{mapping}/runs?limit=50&offset=0` |
| Status/cancel/retry | Existing `/execution/jobs/{run}`, `.../cancel`, `.../retry` |
| Provenance | `GET /materialization/runs/{run}/provenance?limit=50&offset=0` |
| Source runs | `GET /datasets/{dataset}/versions/{version}/materializations` |
| Object source runs | `GET /ontologies/{ontology}/objects/{type}/{id}/materializations` |
| Link source runs | `GET /ontologies/{ontology}/links/{link}/materializations?source_type=...&source_id=...&target_type=...&target_id=...` |

Pagination is deterministic and bounded (existing 1–100 limit, bounded offsets). A source or target
lineage page can be short after access filtering; inaccessible dependencies are never expanded.

Example definition for the canonical manufacturing schema:

```json
{
  "target_resource_id": "<registered ONTOLOGY_VERSION resource UUID>",
  "ontology_id": "manufacturing",
  "schema_version": "1.0.0",
  "columns": {"factoryId": "String", "name": "String"},
  "objects": [{
    "object_type": "Factory",
    "identity": {"components": [{"column": "factoryId", "conversion": "string"}]},
    "properties": {
      "factoryName": {"column": "name", "conversion": "string"},
      "location": {"constant": "Unknown", "conversion": "string"}
    }
  }],
  "relationships": [],
  "write_policy": "upsert_owned",
  "duplicates": "reject",
  "max_objects": 100000,
  "max_links": 100000
}
```

Run body:

```json
{
  "definition_id": "<immutable definition UUID>",
  "dataset_id": "<dataset UUID>",
  "version_id": "<committed dataset version UUID>",
  "mode": "materialize"
}
```

`mode: full_validation` scans every row and checks ownership/endpoint availability without changing
objects, links or provenance. It remains a point-in-time preflight; mutations recheck all live domain
invariants. Sample preview reads only the dataset's cached first rows (at most twenty mapped targets)
and explicitly reports `sample-only`; it cannot establish full-source validity or duplicate absence.

Identity exclusively supplies the primary-key property. A single component must match the canonical
primary-key type; composite keys require a string primary key and use a versioned typed JSON hash.
Unicode is NFC; decimals normalize equivalent numeric representations; timezone timestamps normalize
to UTC. Null/invalid keys fail. Duplicate object keys reject unless `coalesce_identical` is explicitly
selected; conflicting values always reject. Duplicate edges coalesce.

Property values select a column or explicit constant and declare a conversion. Null policy is reject,
allow (only nullable properties), or default (explicit nonnull default). Strict scalar conversions cover
string, signed 64-bit integer, float, boolean, date, timestamp, UUID and decimal (up to 38 digits).
Decimal-to-float coercion, nested/binary/array values, nanosecond timestamp truncation, arbitrary scripts
and unrestricted expressions are unsupported. Perform supported tabular transformations in Phase 14.
Required properties, enum values, precision/scale and canonical key consistency use existing validators.

Relationships name an existing link type and source/target object type plus identity components.
Objects from the same run are available before the link pass. Missing endpoints or cardinality conflicts
fail. Existing links are observed; no existing link is deleted, replaced or claimed as action-independent
ownership. Replays create no duplicate canonical edges.

Only objects created by the same stable mapping may be refreshed. Different mapping ownership and
unrelated existing identities fail closed. Refresh uses edit_wins overlays, preserving action/user edits.
Insert-only permits identical replay but rejects changed mapped values. Ownership is not automatically
transferred or released; archive stops future mutation and retains history. Missing-source deletion,
replacement and ownership-transfer workflows are excluded.

Publication uses visible transactional batches of 100 targets. Full-source conversion precedes writes;
a later live constraint failure, cancellation or revocation can leave earlier committed batches visible.
Each batch commits provenance and progress with the domain writes. Status identifies the incomplete
run; it never calls it successful. Retry replays the exact pinned contract and skips its committed
provenance. New runs reconcile without duplicate objects/links. No cross-transaction atomicity is claimed.

Provenance contains source record ordinal in the immutable checksum-pinned snapshot, mapping/definition,
run, dataset/artifact version, target ontology/version, canonical object/link identity, operation, actor
and timestamp. It does not return source rows or property values. Reading it requires current access to
mapping, source, target registry reference and canonical endpoints. Histories and private-source filters
preserve the existing pipeline lineage APIs.

Previously observed materialized links that have been removed through governed mutations are not
silently recreated. Immutable provenance detects the missing edge and the run fails with a conflict;
existing replacement edges and action-managed values remain authoritative.
