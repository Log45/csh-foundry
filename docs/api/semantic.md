# Phase 5 semantic API

Routes below are under `/api/v1/ontologies/{ontology_id}/semantic`. All use the server-configured
principal/tenant, existing service authorization and structured error envelope. There is no engine
invocation in an API handler. Run `uv run python -m ontology_platform.semantic --ontology manufacturing`
separately, with `OPEN_ONTOLOGIES_BIN` pointing to the checksum-verified 2.1.0 release binary.

| Method/path | Contract |
|---|---|
| POST `/compile` | `{schema_version}` → ontology/shapes artifact UUIDs |
| POST `/native-artifacts` | `{schema_version,kind:ontology\|shapes,content}` → UUID; explicit semantic:publish |
| POST `/exports` | ExportInput → immutable asserted artifact UUID |
| GET `/artifacts/{id}` | Immutable manifest, content and evaluated freshness |
| POST `/jobs` | JobInput → durable PENDING JobView (or original identical job) |
| GET `/jobs`, `/jobs/{id}` | Principal-private status/history/output UUIDs; limit 1–100, offset 0–10000 |
| POST `/jobs/{id}/cancel` | Fence outstanding work; terminal states unchanged |
| GET `/artifacts/{id}/facts` | Bounded FactView page from derived set, with provenance/approval/freshness |
| GET `/artifacts/{id}/approval` | Bounded immutable approval audit events |
| POST `/artifacts/{id}/approval` | `{state:APPROVED\|REJECTED}`; fresh derived set only |

Export example:

```json
{"schema_version":"1.0.0",
 "selections":[{"object_type":"Factory","limit":200},
               {"object_type":"Machine","select":["machineId","operationalStatus"],"limit":200}],
 "links":["locatedInFactory"]}
```

Each selection uses the existing validated root query/filter/projection/order contract. It selects
one bounded page (up to 200); it does not silently fetch the entire type. Unique root types only;
no traversal/cursor/offset. At most eight selections, 1,000 total objects, 16 requested link types,
5,000 forward edges, 20,000 RDF statements, 4 MiB output and a cooperative 10-second export budget.
The query engine retains its own property/predicate/SQL bounds. Both endpoints must be selected
and readable; otherwise the edge is omitted. Inverse RDF edges use the same authorization boundary.
Projections can intentionally omit required fields, so validating a partial export against full
shapes may report violations. It is not evidence that authoritative objects violate their schema.

Job example (primary is asserted data; secondary is shapes for validation or ontology for reasoning):

```json
{"operation":"reasoning","primary_artifact":"<asserted UUID>",
 "secondary_artifact":"<ontology UUID>","profile":"owl-rl-ext"}
```

Validation preserves three-valued conforms: true/false/null (undetermined when unsupported or no
focus nodes). SHACL violations complete the job with a semantic result, not an infrastructure
failure. Reports include hashes, job/input references, engine/profile, duration, violation count,
at most 100 violation details, truncation and skipped/unmatched constraints. Reasoning returns
separate derived/proof/report artifacts. Base owl-rl and owl-rl-ext remain distinct. Canonical v1
has no CriticalMachine rule definition; explicitly published native semantic rules can supply it
without altering operational metadata. Change jobs take two ontology artifacts (different published
versions allowed) and return the native diff report, not an operational migration authorization.

Manifests include version 1, tenant/ontology/schema, compiler 1.0.0, engine 2.1.0/commit, actor/time,
category, COMPLETED status, exact input/output hashes, diagnostics and provenance. Source references
are current accepted source versions plus bounded available staging run associations, which may
expire with Phase 4 staging cleanup. The asserted artifact itself retains exact exported bytes,
object revisions and edge boundary. No historical source reconstruction is claimed. Generated
schema/shape RDF is byte deterministic sorted full-IRI Turtle, with named list/shape nodes. Identity
mapping remains v1; vocabulary uses separate schema/v1 category/tuple IRIs. String/enum values are
explicit xsd:string; null means absent triple. JSON/arrays reject selected nonnull export values;
other lossy mappings produce structured compiler diagnostics. The unchanged raw pySHACL fixture
failure remains a separate compatibility finding.

Semantic outputs are sensitive. Artifacts are principal-private with no sharing endpoint. Reading
reports/facts/proofs reauthorizes original inputs, current SQL grants and property/object/link/source
permissions. Changed grants or no-longer-selected identities deny payload access. Same identities
with changed values/revisions/edges/provenance return STALE; activation returns stale_schema. Execution-version changes mark old results STALE. Approval
requires CURRENT inputs and appends an immutable set-level event (PENDING is the absence of an event).
Approval does not copy facts into operational objects or trigger actions. Job history stores only
status, sanitized error categories, times, attempt counts and opaque input/output identifiers.

Claims use a 60-second lease, at most three total claims and SKIP LOCKED. Explicit renewal is
available to worker callers. Engine calls have a 30-second timeout; output files total at most 4 MiB,
JSON stdout at most 8 MiB, checked before loading into memory. Temporary output is spooled to disk;
these are acceptance bounds, not a hard disk/CPU sandbox during the subprocess. Unsupported RDF,
invalid shapes, resource limits, unavailable/wrong engine, timeout, engine failure, stale schema/
inputs, forbidden input and lost lease have separate stable error codes. stderr is discarded.
Unexpected parser/storage failures roll back output and use sanitized worker_error history.

Identical job requests return the original job, including terminal failures/cancellation; there is
no manual retry override in this bounded foundation. Transient failures retry within three claims;
new inputs produce new jobs. Artifacts/facts/manifests and job histories have indefinite retention,
with no autonomous purge. Artifacts have bounded individual size and content/configuration dedup;
production storage quotas/retention scheduling remain later operational work. Temporary subprocess
state is always removed; interrupted PostgreSQL transactions roll back partial artifacts/facts.
HTTP POST bodies are bounded at 64 KiB before JSON parsing; the internal artifact bound is 4 MiB.
No API returns a server filesystem path, accepts SQL/SPARQL, or resolves owl:imports remotely.
