# Governed transformation and visual pipelines (Phases 14 and 18)

All paths are `/api/v1`, authenticated and tenant scoped. Use existing Project membership and resource
sharing. Pipeline sharing never grants input or output access. Unknown/private IDs have identical errors.
Run initiation requires pipeline Project write permission, every input version read permission and
target dataset write permission. These permissions are checked again at sensitive worker boundaries.
Read-only pipeline sharing does not authorize execution.
Metadata uses JSON, bounded pagination (`limit` 1–100, `offset` 0–10000), and the existing error envelope.

| Method/path                                                     | Contract                                                                                    |
| --------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| POST `/projects/{project}/pipelines`                            | Create stable registry resource; name, description, folder_id                               |
| GET `/pipelines/{pipeline}`                                     | Governed resource metadata                                                                  |
| POST `/pipelines/{pipeline}/validate`                           | Validate the closed Definition grammar; does not execute                                    |
| POST `/pipelines/{pipeline}/definitions`                        | Publish immutable DefinitionView; editing publishes a new UUID                              |
| GET `/pipelines/{pipeline}/definitions`                         | Paginated published history                                                                 |
| POST `/pipelines/{pipeline}/graph/compile`                      | Authoritative structural/resource/schema validation and deterministic canonical compilation |
| GET `/pipelines/{pipeline}/graph/draft`                         | Current actor's private working draft or null                                               |
| PUT `/pipelines/{pipeline}/graph/draft`                         | Save draft with `expected_revision` compare-and-swap                                        |
| POST `/pipelines/{pipeline}/graph/publish`                      | Revalidate and atomically publish canonical definition plus immutable graph metadata        |
| GET `/pipelines/{pipeline}/definitions/{definition}/graph`      | Authorized stored graph for a visual publication, or null for JSON-only history             |
| POST `/pipelines/{pipeline}/definitions/{definition}/visualize` | Reconstruct compatible JSON definition using caller-supplied exact source/output pins       |
| POST `/pipelines/{pipeline}/runs`                               | 202; pin definition_id, named inputs (dataset_id/version_id), output_dataset_id             |
| GET `/pipelines/{pipeline}/runs`                                | Paginated execution history                                                                 |
| GET `/execution/jobs/{job}`                                     | Validation/run state, attempts, sanitized error, metrics and output identity                |
| POST `/execution/jobs/{job}/cancel`                             | Initiator with current owning-Project write permission; idempotent terminal read            |
| POST `/execution/jobs/{job}/retry`                              | Initiator; FAILED only, bounded attempts; exact definition/input pins retained              |
| GET `/datasets/{dataset}/versions/{version}/lineage`            | Authorized successful-run provenance, bounded inputs                                        |
| POST `/datasets/{dataset}/versions/{version}/validate`          | 202; durable validation enqueue/idempotent existing status                                  |

Example definition:

```json
{
  "engine": "polars",
  "inputs": [{ "name": "source", "columns": { "id": "Int64" } }],
  "steps": [
    {
      "op": "filter",
      "expression": {
        "op": "gt",
        "args": [
          { "op": "column", "column": "id" },
          { "op": "literal", "value": 0 }
        ]
      }
    },
    { "op": "select", "columns": ["id"] }
  ],
  "output_columns": { "id": "Int64" }
}
```

Definitions allow 1–16 named inputs, 100 ordered steps, 256 columns and expression depth 16. Unknown
operations/fields are rejected. No Python, callbacks, SQL, paths, network addresses, imports or pickle.
Expressions support column/literal, add/subtract/multiply/divide, comparisons, and/or/not, is_null and
coalesce. Unknown predicates are excluded by filter. Nonfinite output (including division by zero)
fails validation. Integer add/subtract/multiply widen to Decimal before checked Int64/UInt64 narrowing;
strict casts reject overflow. Floating arithmetic follows Polars IEEE semantics. Decimal arithmetic
retains Polars precision/scale rules and rejects unsupported conversions; cast Decimal uses (38,9).

| Step        | Fields and semantics                                                                         |
| ----------- | -------------------------------------------------------------------------------------------- |
| select/drop | columns; missing names fail                                                                  |
| rename      | mapping of old to new names; collisions fail                                                 |
| filter      | expression returning Boolean; null excluded                                                  |
| sort        | columns, descending; stable ties, null order follows Polars default                          |
| cast        | mapping to String/Int64/UInt64/Float64/Boolean/Date/Datetime/Decimal; strict                 |
| derive      | new name and expression; overwriting existing columns rejected                               |
| fill_null   | name and scalar value; must have compatible type                                             |
| deduplicate | optional columns; source-first order retained                                                |
| aggregate   | columns as group keys; aggregates with column/function/alias; sum/mean/min/max/count         |
| join        | named input, common columns, inner/left/full/semi/anti; identical key types; collisions fail |
| union       | named input; schemas must match exactly; input order retained                                |

Projection/filter/cast/derive/fill preserve source order. Sort changes order explicitly. Dedup keeps
first occurrence, grouping keeps first-seen key order, joins request left/right deterministic order.
Sort/joins/aggregation/dedup can require substantial state; they can fail a resource budget even for
sources below 1 GiB. No claim that every operator can stream or every cardinality fits memory.

A run stores the exact definition, versions, SHA-256s, parameters (currently empty), principal identity,
engine/version and limits before admission. Planning checks columns/types and input/output contracts.
A trusted worker uses short transactions, fencing tokens, database-clock leases and heartbeat; API
restarts do not lose jobs. Cancellation denies publication and kills only the owned parser child.
Expired workers cannot commit; bounded retries distinguish infrastructure failures from malformed data.

Output bytes go to a reserved immutable artifact address before one transaction commits physical/logical
metadata and successful run lineage. Reserved pipeline versions cannot be uploaded/finalized/validated
through user dataset endpoints; physical/logical commit guards require the live execution token. Retries verify that same reservation, never overwrite source data
or mint a second output. A changed/nondeterministic output checksum fails closed. Temporary files are
removed on normal failure/cancellation; abrupt host death requires operating-system temp maintenance.
Committed bytes have existing indefinite retention, including abandoned output reservations.

Lineage contains actual successful-run edges only. Output permission alone reveals no private input
UUID/checksum or private pipeline/definition UUID: each is filtered using current authorization. The
run/output identities and completion time remain visible as provenance of the readable output.

Visual graph v1, deterministic identity, node catalog, diagnostics and lifecycle are documented in
[Visual pipeline authoring](../development/visual-pipeline-authoring.md). Published visual definitions
also pin their source versions and output dataset; run requests cannot substitute them. The canonical
definition and Phase 14 worker remain the sole execution authority.

## Phase 20 general DAG extension

Canonical `format_version: 2` definitions use explicit typed input/right dependencies, immutable
source pins, stable transformation IDs and multiple output declarations. Existing definition/run,
visual graph compile/publish/draft, execution status/cancel/retry and dataset lineage APIs are reused.
Legacy JSON and graph v1 remain supported without historical rewriting. DAG run requests omit the
legacy output_dataset_id; all output targets/formats come from the immutable published specification.
Status adds typed node records, plan digest, publication state/prepared count and authorized committed
outputs. Prepared identities/storage keys are never returned. Output resource creation, dataset/
artifact version visibility, manifest completion and parent success commit in one PostgreSQL transaction.
See [DAG contracts and SDK example](../development/pipeline-dag-execution.md) and
[publication/recovery protocol](../development/atomic-multi-output-publication.md).
