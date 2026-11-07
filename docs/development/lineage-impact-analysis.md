# Impact analysis semantics

`POST /api/v1/lineage/impact` forces bounded downstream traversal and returns deterministic paths with
supporting authoritative records. EXACT_VERSION is an immutable publication pin; RESOURCE is a
registry-level relation; POTENTIAL is a declared schema/query/output-target dependency; HISTORICAL is
an actual past execution relationship. Membership is not proof of value contribution. A historical
consumer is not necessarily affected by a future schema/version change.

Potential paths require compatibility review before a change. Application query bindings describe
schema/type dependence, never permanent provenance for every returned object. Definitions and
outputs retain exact immutable identities. Shared DAG ancestors are deduplicated; resource cycles
cannot cause unbounded recursion. Only authorized paths are returned; no hidden placeholder or count
is included. Traversal limits and incomplete indexing are explicit. A shortest deterministic witness
path is retained for each reached identity, capped at 100 targets; it is not an exhaustive path export.

See [lineage/column contracts](lineage-observability.md) and [operator limits](phase-21-limits.md).
