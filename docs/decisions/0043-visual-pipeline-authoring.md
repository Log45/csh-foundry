# ADR 0043: Visual authoring of canonical pipelines

Status: Phase 18 design, recorded before implementation; acceptance is reported separately.

Milestone H authorizes a no-code DAG surface over ADR 0039, not another execution language.
Graph v1 contains strict dataset-source, transformation, single dataset-output and nonexecuting
Function-reference nodes. Ports are dataset streams (input/output/right) or unsupported scalar
Function ports. Positions are finite, bounded presentation metadata. Graphs are limited to 118
nodes, 216 edges, 256 KiB serialized JSON, 16 KiB per configuration and canonical expression depth
16. Sources retain names, exact dataset/version UUIDs and optional canonical column contracts.

The compiler walks the single output's main input chain. Join/union right ports accept raw dataset
sources only, matching Phase 14's named-input semantics. Arbitrary transformed branches are rejected;
source fan-out is supported. Node/edge insertion order and positions are nonsemantic. Input order
is main source then other sources sorted by logical input name. Canonical contracts remain unchanged.
The semantic digest covers canonical specification plus sorted exact source bindings and output ID;
layout has a separate graph document identity. Polars lazy planning over metadata-only empty frames
reuses the actual engine for schema propagation; data-dependent validity is checked at execution.
Unknown physical types are reported as unsupported, never guessed. No data files are read to compile.

Existing definitions have no source pins: Phase 14 stores those on runs. Reconstruction therefore
requires explicit input pins/output supplied by the caller; it never picks latest. First-input order,
step order, contracts and output contract are preserved; secondary input ordering is nonsemantic.
Unused inputs or shapes not representable by v1 produce diagnostics and retain the existing JSON
editor. Historical definitions are never rewritten.

Two additive PostgreSQL tables store actor-private working drafts (one per actor/pipeline, revision
compare-and-swap) and immutable graph publication metadata keyed to canonical definitions. The graph
and canonical definition publish in one governed transaction, rechecking sources and output authority.
Visual run submission must match stored publication pins. The existing durable worker consumes the
unchanged canonical definition and enforces admission, current authority, fencing and publication.
Graph records grant no source permissions; every read rechecks referenced resources before disclosure.
Drafts may contain incomplete graphs, but publication requires successful authoritative compilation.
No autosave or canvas movement creates a definition. Conflicts require explicit reopen/recovery.

Phase 17 Functions are bounded scalar contracts, not DataFrame operators. Option B is chosen: exact
Function definition references can be inspected with current authorization but always block pipeline
publication with a specific diagnostic. No scalar-to-dataset adapter or execution is implied.
Future code nodes require immutable artifact/runtime/dependency pins, declared dataset I/O, budgets,
network/filesystem policies, tenant/Project identity and isolated execution/publication fencing. No
source-code field, exec/eval, workspace provisioner, IDE, hosting, Git or runtime is added here.

Studio uses pinned MIT-licensed @xyflow/react for drag, connections, pan/zoom, fit and keyboard canvas
navigation. Upstream APIs/license are verified against https://github.com/xyflow/xyflow and installed
types. This avoids maintaining a custom geometry/interaction engine. Accessible inspector, node list
and connection form complement canvas interaction; errors include node/edge IDs and text. BFF CSRF,
server-held credentials, SDK generated contracts and tenant/session isolation remain authoritative.
Job-level monitoring uses existing job APIs; per-node execution progress is unavailable.

Rejected: executing graph documents directly, changing canonical AST to arbitrary DAGs, storing
mutable layout in immutable specification, browser-only validation, Function scalar row mapping,
localStorage drafts containing private references, and introducing a new database/queue. Production
certification remains BLOCKED under §23B. Linux/OKD4 isolation is not claimed by local validation.
