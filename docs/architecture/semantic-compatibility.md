# Dependency and semantic compatibility — Phase 0

Verified 2026-10-28 on macOS ARM64, Python 3.12.0, Java 23.0.1, Docker Engine 28.3.0.
Exact Python package versions are in `uv.lock`; external pins are in
`integrations/dependencies.json`. No external service or WebProtégé instance was deployed.

## Dependency matrix

| Dependency | Selected pin / license | Required capability | Verified capability | Unsupported / deferred | Approach and limitations |
|---|---|---|---|---|---|
| Open Ontologies | v2.1.0, `ef6e781c71aaccaa35c2a1cd06169f0c862d5769`; MIT | Parse Turtle, SHACL, supported inference | Release binary launched; ontology/data parsed; SHACL baseline/negative diagnostics; owl-rl-ext infers all 3 critical machines | Base owl-rl lacks fixture hasValue/intersection rules; full OWL 2 DL is not promised; HTTP/MCP, change/proof operations not executed | Isolated JSON batch subprocess, temporary state, timeout and structured errors |
| Protégé Desktop | 5.6.9, `d2a5b4f3346b3c22b6dea26dc77547bbbe51b5ec`; BSD-2-Clause | OWL file interchange | Exact compatible OWLAPI 4.5.29 interprets five classes, 13 data properties, six object properties, keys, inverses and equivalent class; RDF/XML export/reload | GUI not launched; platform draft translation deferred to Phase 6 | Java/Maven verification harness; additional xsd:date declaration recorded |
| WebProtégé | 4.0.2, `e4a5d156b867b3e614a0ac0fa5ea051b10d8e3ea`; BSD-2-Clause | Optional collaborative authoring | Pinned README/pom/license inspected; documented upload/download Turtle, RDF/XML, OWL/XML, OBO; OWLAPI 4.5.13 | No deployed integration or HTTP API verified | File interchange initially; Java WAR/servlet deployment and MongoDB documented upstream, deliberately excluded from operational Compose |
| RDFLib / pySHACL | 7.1.4 / 0.30.1; BSD-3-Clause / Apache-2.0 | Independent fixture validation | All Turtle parses; normalized RDF 1.1 SHACL baseline and nine isolated negative cases | Raw baseline FAIL (45 string sh:in violations) | Test-only normalization of simple string terms in an in-memory shapes graph; canonical bytes unchanged |
| FastAPI / Pydantic | 0.162.0 / 2.14.1; MIT / MIT | API and canonical validation | Health, readiness, OpenAPI, errors; valid/invalid schema tests | Domain APIs and actual publication deferred | Locked uv runtime |
| SQLAlchemy / Alembic / psycopg | 2.0.55 / 1.20.1 / 3.3.6; MIT / MIT / LGPL-3.0-or-later | PostgreSQL sessions/migrations | Real PostgreSQL commit, rollback, ready probe; upgrade/downgrade/check | Object/relationship storage deferred | psycopg binary wheel for development; preserve upstream notices on redistribution |
| PostgreSQL | 17.6-bookworm image; PostgreSQL License | Operational source of truth | Healthy Compose service, migration and transaction tests | No production/backup claim | Loopback port, named volume, environment password |
| Polars | 1.44.2; MIT | Dataframes | CSV fixture keys/counts/reference checks | Operational ingestion deferred to Phase 4 | Used only in validation at Phase 0 |

Direct/transitive licenses must accompany redistributed distributions as applicable. Protégé and
WebProtégé BSD notices must be retained; optional plugins have their own licenses. No upstream
binaries or authoring applications are vendored. Maven resolves a compatibility harness only.

## Actual engine contract

Inspected pinned `Cargo.toml`, `src/main.rs`, `src/batch.rs`, `src/server.rs`,
`src/reason.rs`, `docs/reasoning.md`, `Dockerfile`, release workflow and MIT license.
[Source at the selected pin](https://github.com/fabio-rovai/open-ontologies/tree/ef6e781c71aaccaa35c2a1cd06169f0c862d5769).
Default Cargo features are empty. No optional feature is required for the exercised commands.
Release workflow builds with `embeddings,plugins`; the binary's feature set is not runtime
attested. Dockerfile builds `embeddings,plugins,sql`. The latter SQL connectors and optional
DuckDB are not used. No separate platform database or Rust accelerator is added.

The adapter executes an argv array (no shell):

```text
open-ontologies --no-connect --data-dir TEMP/state --json batch --bail -
```

stdin is a JSON array of `{"command":"load","args":["/absolute/input.ttl"]}` and
subsequent commands. One JSON result envelope is returned per command: `seq`, `command`,
`result`. `load` takes a path; `shacl` takes the shapes path against loaded data;
`reason` takes `--profile owl-rl-ext`; `query` takes one SPARQL string. In-memory RDF
state is per process, so loading and querying must share a batch. A temporary data
folder isolates upstream SQLite bookkeeping and is removed after each run.

Batch nonzero exits, missing output and nested `result.error` are errors. A successful
batch can still report `conforms:false`; the adapter retains this result and violations.
It does not infer conformance from exit 0. Timeout, missing executable, malformed input and
invalid RDF have explicit application errors. No retry/persistence workflow is claimed.

The pinned source supports Turtle, N-Triples, RDF/XML, N-Quads, TriG, JSON-LD and OWL
functional syntax input; unsupported functional constructs are rejected. Save/convert supports
Turtle, N-Triples, RDF/XML, N-Quads and TriG. Only Turtle ingestion is runtime-tested here.
CLI includes validate/load/stats/query/save/shacl/reason/diff/plan/apply/rollback and additional
governance commands. `serve` exposes MCP over stdio; `serve-http` exposes streamable MCP
at `/mcp` and routes under `/api` including `/stats`, `/query`, `/update`, `/load`,
`/load-turtle`, `/save`, `/batch`, `/lineage`, plus `/health`. These were source-inspected,
not launched. No generic REST reasoning or SHACL endpoint is invented. MCP tools include
`onto_load`, `onto_shacl`, `onto_reason`, and governance tools; not runtime-tested.

Profiles documented in pinned `docs/reasoning.md`: rdfs, owl-rl, owl-rl-ext and owl-dl.
The DL tableaux is SHIQ-oriented; hasValue nominals and datatype ranges have limitations.
It is not evidence of general OWL 2 completeness. Proof certificates require separate Lean
checkers; no certificate verification was executed. Change analysis is deferred to Phase 5,
even though upstream provides governance operations. There is no custom reasoner fallback.

## Executed capability checks

Evidence: `docs/architecture/evidence/semantic-smoke.json`, automated tests and phase report.

| Capability / fixture | Result | Actual evidence |
|---|---|---|
| Released ARM64 executable launches | PASS | checksum matches committed upstream SHA256; CLI --help works |
| Ontology Turtle / OWL vocabulary | PASS | load manufacturing.ttl: 115 triples; OWLAPI checks full expected signature |
| Data Turtle parsing | PASS | load manufacturing-data.ttl: 412 triples |
| Shapes parsing | PASS | RDFLib parses 115 triples (see final validation output for baseline) |
| Engine SHACL on unchanged data/shapes | PASS | conforms=true, 63 focus nodes, 0 violations |
| Engine invalid status | PASS | conforms=false with violations; invalid RDF produces structured failure |
| CriticalMachine with owl-rl | NOT SUPPORTED | empty result, source places cls-hv/cls-int rules in extended profile |
| CriticalMachine with owl-rl-ext | PASS | MCH-005, MCH-011, MCH-017 only; noncritical MCH-001 excluded |
| pySHACL raw fixtures | FAIL | simple literals in sh:in compare differently from explicit xsd:string; 45 InConstraint violations |
| pySHACL RDF 1.1 normalized shapes | PASS | conformance; all nine negative cases produce expected constraint diagnostics |
| Protégé-compatible OWLAPI import/export | PASS | five classes, 13 data / six object properties, four keys, three inverses, one equivalent class preserved |
| Protégé GUI / WebProtégé / platform import | NOT RUN | optional GUI/deployment and Phase 6 draft translation deferred |
| Semantic change analysis / proof checking | NOT RUN | later/optional functionality, no runtime claim |

## pySHACL interoperability finding

Both RDFLib 7.6.0/pySHACL 0.40.1 and the selected 7.1.4/0.30.1 pair reject the raw
baseline for the same 45 sh:in string comparisons. The older pair avoids extensive
Dataset deprecation noise; it does not fix the raw comparison. No fixture was changed.
The strict expected-failure test preserves and surfaces this incompatibility; it is not a
passing raw conformance check. RDF 1.1 treats simple literals as xsd:string. A separate
harness normalizes only those literal terms in a temporary shapes graph, then requires
conformance before running nine negative tests. This is a test interoperability measure,
not a replacement SHACL engine or a production adapter. Open Ontologies directly validates
the unmodified fixture pair. Production validator selection remains a Phase 5 decision.

## Authoring workflow

Inspected [Protégé pinned pom](https://github.com/protegeproject/protege/blob/d2a5b4f3346b3c22b6dea26dc77547bbbe51b5ec/pom.xml)
and [WebProtégé pinned README](https://github.com/protegeproject/webprotege/blob/e4a5d156b867b3e614a0ac0fa5ea051b10d8e3ea/README.md),
licenses and dependency declarations. Open `manufacturing.ttl` in Protégé; save RDF/XML
for transport. The generated `ontologies/examples/manufacturing.owl` is a compatibility
artifact, not claimed to have been authored in the GUI. OWLAPI adds a declaration of the
already-used xsd:date datatype during serialization; no source axiom is removed. The
Java harness checks that exact delta and fails on any other change. Later platform import
must preserve originals, diagnose unsupported axioms and create an unpublished reviewed
draft. No access policy or action is inferred from OWL and no live synchronization is planned.
