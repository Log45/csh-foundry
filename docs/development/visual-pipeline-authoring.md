# Visual pipeline authoring

Phase 18 adds a visual authoring representation over the Phase 14 canonical pipeline definition. The
graph is never sent to a separate executor. Validation compiles it to `Definition`; publication writes
that immutable definition and its graph metadata in one PostgreSQL transaction; execution uses the
existing durable job worker, immutable dataset publication, fencing, provenance and lineage.

## Authoring lifecycle

1. Create or open a Pipeline resource in Studio.
2. Add dataset sources, transformation nodes and one dataset output. A source selects an authorized
   dataset and exact committed version; it never follows `latest`.
3. Connect nodes on the canvas or with the keyboard-accessible connection editor. Configure each
   operation in the inspector. Pan, zoom, fit-to-view, selection and deletion are available on canvas.
4. Save a private working draft. Draft revision compare-and-swap prevents silent lost updates. An
   incomplete draft is allowed; it cannot publish.
5. Validate. Backend diagnostics are authoritative and name the affected node or edge without exposing
   unauthorized resource metadata. The same Polars planner propagates schemas over empty metadata-only
   frames, so compilation never loads dataset rows.
6. Publish a valid graph. Publication rechecks source versions, output access and current Project
   permissions and creates a canonical immutable definition. Canvas positions have a separate identity
   and do not change the executable digest.
7. Run the selected published definition. A visual definition accepts only its publication-time input
   version pins and output dataset. Monitor the existing job state, cancellation/retry, output preview
   and authorized lineage in Studio.

The advanced JSON editor remains available for compatible historical workflows and as a read-only or
editing fallback when an existing definition cannot be represented visually. Historical definitions
are never modified.

## Graph v1 and compiler contract

`format_version` is exactly `1`. Nodes and edges have stable 1–80 character identifiers. Unknown fields
and node kinds are rejected. Presentation positions are finite and bounded. Node kinds are:

| Kind                 | Ports                                             | Execution behavior                                                               |
| -------------------- | ------------------------------------------------- | -------------------------------------------------------------------------------- |
| `dataset_source`     | dataset `output`                                  | Pins logical input name, dataset UUID, version UUID and selected schema contract |
| `transform`          | dataset `input`, `output`; `right` for join/union | Contains one existing canonical `Step`                                           |
| `dataset_output`     | dataset `input`                                   | Pins the one supported output dataset and optional output schema contract        |
| `function_reference` | scalar capability placeholder                     | Pins a Function/version for inspection; always blocks publication                |

The compiler rejects duplicate identifiers, missing nodes, duplicate input-port connections, wrong
directions/types, self-loops and cycles, missing inputs, disconnected nodes, multiple outputs and
unsupported branches. A transformed stream cannot branch because Phase 14 is an ordered chain. Dataset
sources can feed the main chain or the right port of join/union. The right port must be an untransformed
source whose logical name matches the canonical operation's `input` field. Exactly one output is
required.

Compilation walks backward from the output, emits the main source first, sorts secondary sources by
logical input name and emits transformations in execution order. The semantic SHA-256 covers normalized
canonical JSON, sorted exact input bindings and output dataset identity. Node/edge order, JSON key order,
positions and styling are excluded. Equivalent graphs therefore compile to the same definition/digest.

Existing canonical definitions can be reconstructed when the caller supplies exact input pins and an
output dataset. Select, rename, drop, filter, sort, cast, derive, fill-null, deduplicate, aggregate, join
and union round-trip. Missing pins, unused inputs or a shape outside the graph-v1 subset produces an
explicit diagnostic and leaves the JSON fallback available.

## Node configuration and schema rules

Studio provides column lists for select/drop/sort/deduplicate, line-oriented typed mappings for rename
and cast, a bounded comparison/arithmetic expression builder for filter/derive, typed scalar fill-null,
group keys and aggregates, and join/union input controls. It does not evaluate JavaScript or accept
Python, SQL, paths, URLs, imports or callbacks.

Schema propagation uses the immutable dataset schema returned by the dataset API and the actual
canonical Polars planner. Select/drop/rename/cast/derive/fill-null/deduplicate/sort, aggregation,
join and union therefore have the same planning semantics as execution. Unsupported physical types or
an output schema that cannot be proven are reported; no schema is fabricated. Data-dependent failures
remain possible at bounded execution time.

## Diagnostics

Common codes are `duplicate_node`, `duplicate_edge`, `missing_node`, `port_type`, `duplicate_port`,
`cycle`, `output_count`, `source_reference_required`, `output_reference_required`, `missing_input`,
`disconnected`, `unsupported_branch`, `input_binding`, `function_execution_unsupported`,
`reference_unavailable` and `schema_invalid`. Resource failures use one fixed message so a guessed
private UUID cannot reveal existence, names, schemas or Function contracts. Publication returns
`graph_invalid` until all diagnostics are resolved. A stale draft save returns `draft_conflict` and
instructs the user to reopen while retaining local edits.

## Functions and future code transformations

Phase 17 Functions are pure bounded scalar calls. Studio can select an exact published Function version
and inspect its typed input/output contract, but graph validation returns
`function_execution_unsupported`; a scalar result is never treated as a dataset stream. There is no
per-row adapter and no fake execution provenance.

A future code node requires a separately approved isolated service and must pin immutable code,
runtime/dependency lock, declared dataset inputs/output, parameters, CPU/memory/wall/disk budgets,
network/filesystem policy, tenant/Project identity and publication fencing. Phase 18 provides no source
editor, `exec`/`eval`, subprocess shortcut, workspace, IDE container, Git integration, application
hosting or arbitrary-code runtime.

## API and SDK example

The graph endpoints use the same browser BFF/CSRF boundary and are generated in `@foundry/sdk` and
`@foundry/react`:

```ts
const compiled = await foundry.pipelines.compileGraph({
  path: { pipeline_id: pipelineId },
  body: graph,
});
if (compiled.valid) {
  await foundry.pipelines.saveDraft({
    path: { pipeline_id: pipelineId },
    body: { expected_revision: revision, graph },
  });
  await foundry.pipelines.publishGraph({
    path: { pipeline_id: pipelineId },
    body: graph,
  });
}
```

Job-level states are backend-reported. Phase 14 exposes no trustworthy per-node runtime progress, so
Studio does not invent it. Multiple output publication, executable Functions, arbitrary Python, Code
Workspaces and production deployment remain unsupported.
