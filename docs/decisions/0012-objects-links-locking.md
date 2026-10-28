# ADR 0012: JSONB objects, forward relationships and coarse concurrency

Status: Accepted for Phase 1

## Decision

Use the stable Phase 0 composite identity for JSONB objects. Validate canonical property types,
required/null/default/enum rules without coercion and require primary-key equality with object ID.
Enforce unique properties under an ontology transaction lock; compare decimal/timestamp values
semantically and other supported values by JSONB equality. Multiple null/missing values are allowed.
Store only forward edges with tenant-safe endpoint and versioned link-definition FKs. Derive inverse
navigation via joins. Maximum fan-in/fan-out enforces declared cardinality; minimum edge counts are
not defined by the canonical contract. Endpoint deletion is restricted until links are removed.
Writers use ontology FOR UPDATE, consistent readers FOR SHARE; PATCH also uses expected revision
in UPDATE ... RETURNING. This deliberately limits write concurrency per ontology to establish correct
uniqueness/cardinality/activation behavior. Schema activation and mutations cannot race through
services. Revisit locking/indexes with measured query workloads in later phases. Property indexed
flags are persisted requests; physical property-index jobs are deferred. No blanket JSONB GIN index.

## Consequences

Preserve existing canonical identity, semantic adapter and fixture contracts.
Validate persistence on real PostgreSQL. Later phases require separate approval.
