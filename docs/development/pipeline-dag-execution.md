# General DAG pipelines

Phase 20 extends the existing PIPELINE resource, immutable definition service, Polars adapter and
ExecutionWorker. PostgreSQL remains authoritative. No second scheduler or executable user language.

## Canonical format and compatibility

Legacy definitions retain their existing `engine`, named `inputs`, ordered `steps` and one output
contract. Their JSON is never rewritten; the original lazy planner and publication path remain.
Visual graph format 1 continues to compile through the historical chain compiler. Upgrade a draft
explicitly to graph format 2 to author arbitrary supported dependencies. Published versions remain
immutable and independently addressable. New canvases use format 2.

Canonical v2 separates named immutable source pins, transformations, and outputs:

```json
{
  "format_version": 2,
  "engine": "polars",
  "inputs": [{"name": "source", "dataset_id": "<UUID>", "version_id": "<UUID>"}],
  "nodes": [
    {"id": "shared", "inputs": {"input": "source"}, "config": {"op": "select", "columns": ["id"]}},
    {"id": "combined", "inputs": {"input": "shared", "right": "shared"}, "config": {"op": "union", "input": "right"}}
  ],
  "outputs": [
    {"id": "clean", "source": "shared", "format": "parquet", "dataset_id": "<UUID>"},
    {"id": "combined", "source": "combined", "format": "csv", "project_id": "<UUID>", "name": "Combined records"}
  ]
}
```

Source names/node IDs occupy one namespace. IDs are stable nonempty ASCII alphanumeric/underscore/
hyphen strings (up to 80 characters for node references). Output IDs form a separate unique namespace.
Binary nodes have exactly `input` and `right`; all other nodes have exactly `input`. Their reused Step
configuration names the binary binding `right`, regardless of its upstream node's ID. The visual
compiler sets this binding automatically. Output sources can be inputs or transformations.

Node catalog: select, rename, drop, filter, sort, cast, derive, fill_null, deduplicate, aggregate,
join and union. Semantics, strict casts, expression arity/depth, checked integer arithmetic, nulls,
ordering and collision checks reuse the Phase 14 adapter. Joins use equal-named compatible keys;
rename one branch first when keys differ. Non-key column collisions are errors. Union schemas must
match exactly, including column order. Scalar Functions remain nonexecuting authoring references.
Output formats are Parquet, CSV and NDJSON; serialization must preserve the declared logical schema.
Text formats that cannot roundtrip a type fail before publication. JSON-array output is not supported.

## Planning and scheduling

Backend validation rejects duplicate identities/targets, missing references/ports, invalid direction,
unsupported operators/formats, cycles/self-loops, disconnected inputs/nodes and graph budgets.
Polars schema propagation over metadata-only lazy frames verifies column/type/output contracts before
publication and again at run admission. Actual data-dependent validity remains an execution check.

Kahn layers and IDs sorted lexically within each layer define deterministic order. Inputs, nodes and
outputs are sorted for canonical serialization; JSON key/declaration order and canvas layout do not
change semantic identity. The durable plan additionally pins source SHA-256s, engine version, limits,
tenant and execution order. SHA-256 covers canonical compact sorted JSON. One parent execution job
owns final state, lease, cancellation, retries and output decision. Nodes execute sequentially in
existing bounded child processes. Concurrent node execution is intentionally one; global/tenant/
Project job admission is unchanged.

## Intermediate materialization and recovery

Every transformation materializes exactly once into streaming Parquet in an owned run directory.
Downstream operations scan that immutable result, including transformed join/union inputs. No shared
upstream DataFrame is mutated. This conservative materialization policy trades I/O for predictable
reuse and restartability; linear legacy execution still fuses its lazy chain.

Before executing, a fenced node record persists RUNNING, parent attempt/token, timestamp and a
run/node/plan-derived UUID. Private intermediate bytes use the existing ArtifactStore ObjectKey with
the job UUID as opaque artifact namespace. There is no registry resource or normal dataset/artifact
metadata for intermediates; API identity checks cannot resolve them. Completion stores checksum,
size, schemas, input checksums, row counts and measured child metrics. Intermediate preview rows are
removed from durable node records. Exact input checksums, immutable plan, object size and SHA-256
must verify before a replacement worker reuses a COMPLETED node. Missing objects are recomputed;
checksum mismatches fail closed. Retries of unfinished nodes replace attempt state under a live fence.

TemporaryDirectory releases ordinary attempt-local files on return. Durable private intermediates
remain through retryable interruptions, then cleanup removes them after success, terminal failure or
cancellation. A bounded worker sweep retries terminal cleanup after controller/cleanup interruption.
A terminal parent lock prevents cleanup racing manual retry. Committed output keys are never cleanup
candidates. Physical host death may require ordinary maintenance of abandoned local temp directories;
object manifests remain recoverable. See the publication protocol for private output cleanup.

## Monitoring and authoring

The existing React Flow editor supports fan-out, convergence, transformed binary inputs and multiple
output nodes with format and existing-dataset/new-Project/name target configuration. Existing saved
v1 drafts remain loadable; upgrading creates a new draft/publication, not a historical rewrite.
Schema diagnostics and output contracts are backend authority. New output resources appear only on
commit. Prepared objects are not shown as published datasets.

Existing job status/history adds plan_digest, publication_state, prepared_output_count, typed node
states/attempts/errors and independently authorized committed outputs. No staged keys or percentages.
Studio polls at bounded intervals; session-aware SDK useExecution supports cancellation and bounded
polling without mutation auto-retries. Each committed output has preview/lineage controls.

Lineage resolves only that output's ancestor subgraph, deduplicates source identity and filters each
input independently. Without pipeline authority, definition/node metadata is omitted. If an ancestor
input is hidden, its node configuration is omitted. Sibling output declarations are never returned.
No output grants input, pipeline or sibling access. Phase 19 application consumers remain unchanged.

## API and SDK

Reuse `/pipelines/{id}/validate`, `/definitions`, `/graph/compile`, `/graph/publish`, `/runs`, existing
job status/cancel/retry and dataset-version lineage endpoints. A v2 StartRun supplies definition_id
and exact published input pins; output_dataset_id is omitted/null. Outputs come from the immutable
v2 definition. Legacy StartRun still requires its single output_dataset_id. OpenAPI declares the
explicit legacy/v2 union; generated @foundry/sdk and @foundry/react share those contracts and existing
BFF/CSRF/session/tenant boundaries. Pipeline request envelopes are bounded to 512 KiB; other request
families retain 64 KiB. Graph/definition semantic payloads are independently bounded to 256 KiB.

```ts
const run = await client.pipelines.start({
  path: { pipeline_id: pipelineId },
  body: { definition_id: definitionId, inputs: exactPublishedPins }
});
const status = await client.execution.get({ path: { job_id: run.id } });
for (const output of status.outputs ?? []) {
  console.log(output.output_id, output.dataset_id, output.version_id);
}
```

Check generated endpoint names in `packages/typescript-sdk/src/endpoints.ts` when adapting examples.
No deployment or shared database migration is implied by these local development instructions.

Terminal cleanup is repeated after stale workers return and rechecked daily for late private uploads.
The parent lock and COMMITTED output state prevent any such recheck from deleting published data.
