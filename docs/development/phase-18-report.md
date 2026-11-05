# Phase 18 — Visual Pipeline Builder

Implementation date: 2026-11-05 (America/New_York). Changes are uncommitted.
Status: **PASS — Phase 18 implementation and local development acceptance.**
Base revision: `70af08ecc19a58565b61b2ebbd51ce4b570b64c0` (`70af08e`). This is not production
certification. Production remains **BLOCKED** by `PLANS.md` section 23B. No deployment, Phase 19,
Code Workspace, arbitrary-code runtime, application hosting, Spark or Rust work was performed.

## 1–3. Initial state and roadmap alignment

Reconnaissance found a clean worktree at the base revision and repository migration head
`0023_media_functions`; the shared developer database was intentionally still at `0017_capacity`.
Phase 14 already supplied one canonical engine-neutral ordered `Definition`, Polars execution,
durable jobs, one output per run, immutable dataset publication and authorized lineage. Its operations
were `select`, `rename`, `drop`, `filter`, `sort`, `cast`, `derive`, `fill_null`, `deduplicate`,
`aggregate`, `join` and `union`. Studio exposed JSON definition editing and manual runs. Phase 17
Functions were closed, pure scalar calls rather than DataFrame transformations.

The explicit request separately authorizes roadmap milestone H / Phase 18 and supersedes the prior
Phase 17 stop statement only for that milestone; `PLANS.md` now records that authorization. The
implementation follows §23A.5's required single pipeline IR/control plane and does not expand into
milestone I or §23B. The shared database was never migrated, downgraded or reset.

## 4–6. Architecture, graph compiler and node catalog

[ADR 0043](../decisions/0043-visual-pipeline-authoring.md) records the design. Graph format v1 is a
strict Pydantic discriminated union with stable IDs, finite bounded positions, bounded configuration,
explicit typed ports and no executable payload. Position and insertion order are presentation only.
Published graphs are authoring metadata over an immutable canonical definition, never executable
plans in their own right.

The backend compiler validates identifiers, node/edge references, direction and type, port
cardinality, cycles/self-loops, required inputs, disconnected nodes, source reachability, supported
branching and exactly one output. It walks the output's primary chain, deterministically orders named
raw secondary sources, emits the unchanged Phase 14 `Definition`, exact input version bindings and
output dataset, then hashes normalized canonical semantics. Node/edge order, JSON key order and canvas
layout do not affect that digest. Authoritative compilation rechecks every reference and uses the
actual Polars planner over metadata-only empty lazy frames for schema propagation; it reads no dataset
bytes and never trusts client-provided schema as authorization evidence.

| Visual node | Canonical behavior | Ports / boundary |
| --- | --- | --- |
| Dataset source | Exact active committed dataset/version and logical input contract | dataset `output` |
| Select | `select` | dataset `input`/`output` |
| Rename | `rename` | dataset `input`/`output` |
| Drop | `drop` | dataset `input`/`output` |
| Filter | `filter` with closed expression AST | dataset `input`/`output` |
| Sort | `sort` | dataset `input`/`output` |
| Cast | `cast` | dataset `input`/`output` |
| Derive | `derive` with closed expression AST | dataset `input`/`output` |
| Fill null | `fill_null` | dataset `input`/`output` |
| Deduplicate | `deduplicate` | dataset `input`/`output` |
| Aggregate | `aggregate` | dataset `input`/`output` |
| Join | `join`; right side must be an untransformed named source | dataset `input`/`right`/`output` |
| Union | `union`; right side must be an untransformed named source | dataset `input`/`right`/`output` |
| Dataset output | Existing single-output publication contract | dataset `input` |
| Function reference | Exact Function/definition inspection only | scalar placeholder; blocks publication |

The canonical engine has no limit operation, transformed-branch DAG execution or multiple outputs,
so none is fabricated visually. Source fan-out and raw-source right inputs are the supported branch
subset. The full graph/compiler/diagnostics contract is documented in the
[authoring guide](visual-pipeline-authoring.md).

## 7. Studio functionality

Studio now provides a React Flow canvas with drag/drop palette, pan/zoom, fit-to-view, minimap,
selection and deletion; `@xyflow/react` is pinned at 12.12.1 under its MIT license. A maintained graph
interaction library was selected instead of a custom geometry engine. Dataset and exact-version
selectors load authorized owned and shared resources, expose immutable schema, and keep output
selection explicit. Typed inspector forms cover every canonical operation, including bounded
expression, mapping, aggregate, join and union configuration.

An accessible node list and connection editor support keyboard-only authoring; controls have labels
and visible focus, diagnostics are textual and tied to node/edge IDs, and reduced-motion styling is
present. Unsaved, saved-draft, invalid, published and backend job states are distinct. Definition
history, graph validation, publication, run/cancel/retry, output navigation and lineage reuse the
existing pipeline panel. Backend job state is shown without invented per-node progress. The advanced
JSON path remains available as compatibility fallback.

## 8. Existing pipeline compatibility

Existing JSON-authored definitions and endpoints are unchanged. Visualization requires caller-supplied
exact input version pins and output dataset because historical Phase 14 definitions did not store run
bindings. Compatible definitions reconstruct into graph v1 and compile back to equal canonical
semantics. Missing pins, unused inputs or unsupported shapes return diagnostics and retain the JSON
fallback; no historical definition is rewritten. All twelve existing operations round-trip within
the raw-right-source branch restriction.

## 9. Function-node status

Option B was selected. Studio can reference an authorized Function and exact immutable published
definition and display its typed input/output schema. Backend validation still returns
`function_execution_unsupported`, and publication cannot admit the node. Scalar values are never
connected to dataset streams, Function changes are never followed implicitly, and no arbitrary code
field or execution shortcut exists.

## 10. Execution and lineage

Graph publication and canonical definition insertion occur in one governed PostgreSQL transaction.
Starting a visually published definition must reproduce its publication-time exact source pins and
output dataset; substitutions are rejected. The existing Phase 14 queue, admission, worker, leases,
fencing, retry/cancellation, output verification, immutable dataset publication and provenance remain
authoritative. Existing lineage returns actual pipeline definition, job, input dataset versions and
checksums, output dataset/version and artifact identity subject to current authorization filtering.

## 11. API and SDK

New typed API v1 operations compile, publish, load/save a private draft, fetch published graph metadata
and reconstruct an existing definition. They use the existing BFF/CSRF and service authorization
boundary. OpenAPI, Studio types, `@foundry/sdk` endpoints/schema and `@foundry/react` hooks were
regenerated from the actual app; generated-drift, package consumer, cancellation and cache-isolation
contracts remain intact. Examples are in [pipelines.md](../api/pipelines.md).

## 12. Database migration

Forward-only migration `0024_pipeline_graphs` follows actual head `0023_media_functions`. It adds:

- `pipeline_drafts`: one actor-private graph per tenant/pipeline/actor, revision compare-and-swap,
  tenant-qualified pipeline FK and database size/revision guards.
- `pipeline_graphs`: one immutable graph/digest per canonical definition, tenant-qualified composite
  FK, database size guard and update/delete rejection trigger.

Fresh migration, previous-head upgrade with preserved sentinel data and Alembic drift checks passed in
disposable schemas. Historical migrations were not modified. The shared developer database remains at
`0017_capacity` by final read-only verification.

## 13. Limits and security boundaries

[Phase 18 limits](phase-18-limits.md) records 118 nodes, 216 edges, 256 KiB API graph, 512 KiB SQL
guard, 16 KiB per configuration, 16 expression levels, 256 diagnostics, 16 canonical sources and 100
operations. Draft writes use exact revision CAS. Graph parsing rejects unknown fields/kinds and
executable source. Compilation is bounded and metadata-only.

Current tenant, Project, pipeline, dataset/version, output and Function authority is rechecked in the
service transaction at compile/publication and again where execution requires it. Unauthorized
references collapse to a fixed diagnostic without names/schema/identity leakage. Published graph
records grant no resource access; draft contents are actor-private. Existing BFF credentials remain
server-side and writes retain CSRF/session enforcement.

## 14–16. Complete validation, browser and large datasets

The final runner command was:

```text
PATH=/Users/log/.nvm/versions/node/v26.7.0/bin:$PATH caffeinate -dimsu uv run python scripts/validate_phase18.py
```

All final commands and exit codes are in
[`results.json`](evidence/phase-18/final/results.json). Environment: macOS 15.6.1 arm64, Python 3.12.0,
uv 0.7.11, Node 26.7.0, Docker 28.3.0, PostgreSQL server 17.6, FastAPI 0.162.0, Pydantic 2.14.1,
SQLAlchemy 2.0.55 and Polars 1.44.2; see [environment.txt](evidence/phase-18/environment.txt).

All **16 final validation commands exited 0**. The complete real-service Python regression reported
**848 passed, 1 preserved strict xfail, zero skips and 2 dependency warnings** in 1030.34s. Alembic
reported no new upgrade operations. The durable real-browser suite reported **12 passed** in 2.4m,
including the exact 1 GiB browser upload (1.2m). The expected failure is only the documented raw
pySHACL/RDFLib simple-versus-xsd:string incompatibility; the supported semantic path passed.

The focused graph suite passed **14 tests** against real PostgreSQL/private MinIO. SDK tests passed
**63**, Studio unit tests passed **48**, strict mypy checked **150 source files**, and Python/SDK/Studio
format, build, generated-contract, independent package-consumer and type checks passed. The durable
browser exercised actual visual source/select/output creation, accessible connection editing, draft
save, backend validation, immutable publication, durable execution, output publication and authorized
lineage, alongside existing upload, authoring, mapping, media/function/automation, SDK/BFF, CSRF,
tenant/session-loss and replica-restart workflows.

The complete Python suite executed all sixteen existing exact-size dataset cases (CSV, NDJSON, JSON
and Parquet at 8 MiB, 100 MiB, 500 MiB and 1 GiB). The 1 GiB CSV case additionally published and ran
the graph-authored select pipeline through the real worker and verified the real output. Compilation
remained metadata-only. The tests measured worker RSS/disk and asserted the existing configured
bounds, exact source byte count/checksum and output correctness; no new memory guarantee is claimed.
Suite/browser timings and the browser's exact byte/row evidence are in
[full-platform-browser.txt](evidence/phase-18/final/full-platform-browser.txt). The separately focused
[visual 1 GiB CSV run](evidence/phase-18/large-visual-focused.txt) also passed before the final complete
run (one test in 66.84s).

## fixtures/VALIDATION.md status

The guide was consulted before completion. These are final executed statuses, not inherited claims.

| Check | Result | Evidence / scope |
| --- | --- | --- |
| Turtle parsing | PASS | Complete `test_fixtures.py` run |
| CSV counts, keys, FKs and RDF identity consistency | PASS | Complete fixture suite; 6/20/12/25 and 63 instances |
| Normalized SHACL and negative mutations | PASS | Complete fixture/semantic suites |
| Raw pySHACL simple/xsd:string compatibility | NOT SUPPORTED | Executed preserved strict expected failure |
| Supported Open Ontologies SHACL/reasoning profile | PASS | Complete pinned semantic/compiler suites |
| Base owl-rl exact fixture axiom | NOT SUPPORTED | Preserved documented engine-profile limitation |
| PostgreSQL persistence and FastAPI queries | PASS | Complete real-database suite |
| Actions, reconciliation and Polars ingestion | PASS | Complete action/ingestion/recovery suites |
| Authorization and tenant/Project isolation | PASS | Complete security, service, SDK and browser suites |
| Supported Protégé import/export | PASS | Complete interchange/import and authoring workflow |
| Manual desktop Protégé GUI | NOT RUN | No desktop session; no new OWL construct |
| Linux/OKD4/production certification | NOT RUN | Separate target environment and §23B scope |
| Standalone TypeScript lint | NOT SUPPORTED | No lint script; format/typecheck/tests/build all executed |

## 17. Preservation checks

[Preservation evidence](evidence/phase-18/preservation.txt) records the clean base, read-only shared
database revision, unchanged fixtures and historical migrations, migration preservation/drift and
whitespace check. Tests created only random disposable schemas and private MinIO Compose projects and
volumes, which their runners removed. No credentials, persistent user data or shared object storage
was changed. No test assertion, fixture, timeout or skip was weakened.

## 18–19. Known limitations and deferred code workspace

Graph v1 is an authoring subset of a general DAG: one output, ordered primary transform chain, raw
dataset source only on join/union right ports, and no transformed fan-out. Dataset preview uses the
existing bounded dataset UI rather than graph execution preview. Compile-time schema proves planner
compatibility but data-dependent execution can still fail. Drafts retain only the current actor
revision; there is no multi-user merge/autosave history. Runtime observability is job-level, not
per-node. Functions are nonexecuting; no arbitrary Python, SQL, JavaScript, package or shell execution
is accepted. No production or Linux isolation claim is made.

A future executable code transformation needs a separately approved isolated service that pins code
artifact, runtime/dependency lock, declared datasets/output, execution parameters, CPU/memory/wall/disk
budgets, network/filesystem policy, tenant/Project identity, provenance and fenced publication. A Code
Workspace additionally needs governed project/test/artifact publication and compatible insertion
contracts. FastAPI, Studio and the ordinary worker must not become that sandbox.

## 20. Exact changed-file inventory

[changed-files.txt](evidence/phase-18/changed-files.txt) enumerates every implementation/source/document
path. Acceptance evidence is stored separately under `docs/development/evidence/phase-18/`. No commit
or staging operation was performed.

## 21. Production status and next phase

Phase 18 is locally accepted only. Production remains **BLOCKED** until the independent §23B supplier,
security, Linux/OKD4, capacity, recovery, operator and organizational approval gates pass. The
recommended next separately approved work is milestone I only after product authorization; custom
code isolation/Code Workspace and production certification remain independent prerequisites, not
implicit Phase 19 work.

## Phase 18 acceptance matrix

All 32 requested criteria are satisfied for the documented local scope: canvas/palette/forms, immutable
pins, port/cycle/schema/determinism checks, layout independence, compatible reconstruction/fallback,
private CAS drafts, immutable publication, existing durable execution/output/lineage, actual job state,
explicitly rejected Function execution, no arbitrary code, governed authorization/BFF isolation,
budgets, browser workflow, synchronized SDK/OpenAPI, Phase 14–17 regressions, real PostgreSQL/MinIO,
1 GiB compatibility, migration preservation/drift, documentation, no later-phase infrastructure and
production blocked status. Unsupported environments and features are explicitly marked above rather
than converted into PASS.

Intermediate failures were retained honestly. The first complete attempt is under
`evidence/phase-18/attempt-1` and exposed a case-sensitive forward-only migration message expected by
an artifact regression. Earlier browser iterations exposed a stale standalone build, owned-dataset
discovery that queried only shared resources, and an asynchronous source-schema update overwriting a
new node. The message, discovery merge and functional state update were corrected; the final complete
run includes all corrections. Failed/interrupted attempts are not counted as acceptance.
