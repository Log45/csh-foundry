# Initial canonical contract (format version 1)

`packages/ontology-schema/src/ontology_schema/models.py` defines ontologies, object types,
properties, links, actions, versions, activation records, tenant/object identities and RDF
mappings. JSON is the Phase 0 interchange format; YAML, RDF/SHACL compilers and generated
SDKs are deferred to their roadmap phases. Generate JSON Schema with
`OntologyDefinition.model_json_schema()`; `ontologies/schemas/ontology.schema.json` is its
checked-in representation. `ontologies/examples/manufacturing.json` preserves fixture
vocabulary and is an unpublished proposal, not a semantic-to-operational import result.

Unknown fields and duplicate definition IDs are rejected. Primary keys reference required,
nonnullable scalar string/UUID/integer properties. Links and action targets must resolve.
Actions are inert typed declarations; parameter binding and operation execution are deferred.

Property values are validated explicitly without coercion: signed 64-bit integers, finite
binary floats (JSON integers are not silently floats), booleans, strings with optional length,
ISO dates, offset-aware ISO timestamps, canonical lowercase UUID strings, decimal strings
with explicit precision/scale, JSON and scalar arrays. Arrays cannot contain null elements;
nullable applies to the whole value. Enums apply to scalars. Decimal limits reject excess
scale rather than rounding. Unique properties require indexing; enforcement is Phase 1.
Required means presence, nullable means a supplied null is legal. `has_default=true`
distinguishes an explicit null default from no default; nonnull defaults also imply presence.
A null default is rejected for a nonnullable property when `has_default=true`.
No implicit property-type widening is promised; changes in type require compatibility review.

`canonical_json()` sorts JSON object keys, preserves definition array order, emits compact
UTF-8 JSON and rejects nonfinite values. Definition ordering is meaningful; reordering arrays
can change the serialized snapshot. Supported model JSON round trips preserve definitions.
Published version contracts hold canonical snapshot text, a timestamp and matching identity.
That snapshot is immutable in the contract. Database immutability, approved migration state
and exactly one active published version are Phase 1 invariants, not implemented services.
Activation records require an actor, aware timestamp and a migration-plan reference for breaking
changes; existence/approval and data validation must be checked transactionally in Phase 1.

## Identity / IRI mapping v1

The identity tuple is `(tenant_id, ontology_id, object_type_id, object_id)`. Encode its four
strings as compact UTF-8 JSON and unpadded base64url; append to
`{namespace}individual/v1/{payload}`. Namespace is stable HTTP(S), ending in `/` or `#`.
The entire tuple is encoded, including tenant; slashes, percent characters, fragments and
Unicode cannot collide by delimiter ambiguity. UUID tenant IDs serialize canonically.
Decoding rejects foreign namespaces, unknown versions and noncanonical encodings. Schema
version, object revision, names and labels never enter the IRI. Export provenance must
record namespace, mapping version and input version. Future class/property IRIs must use
separate term prefixes; they must not use the `individual/v1/` path.

Imported external IRIs are preserved through `ImportedIRIMapping` proposals including
provenance and review status. Persistent registry uniqueness and conflict detection are
Phase 6 work: reject ambiguous duplicate IRIs/business keys/classes or require review;
never silently merge. `owl:sameAs` is a semantic assertion and cannot authorize a merge.
No external-IRI preservation service or cross-tenant export is implemented yet.


Phase 6 adds [governed ontology file interchange](../api/interchange.md).
Explicit mappings reuse canonical definitions and registry drafts. PostgreSQL remains authoritative;
Protégé/WebProtégé are optional. Original semantic axioms remain archived separately from operational
definitions. See ADR 0027 for bounds, preservation and publication/activation boundaries.

Phase 9 uses these same models for immutable branch snapshots and SDK compilation. Branch heads
are development state, not active schemas; SDK issuance selects only published immutable versions.
See [branch/SDK contracts](../api/branching-sdk.md) and ADRs 0030–0031.
