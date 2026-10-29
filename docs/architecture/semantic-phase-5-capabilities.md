# Phase 5 pinned semantic capability matrix

Inspected installed macOS ARM64 release bytes and local source at the unchanged pinned commit
`ef6e781c71aaccaa35c2a1cd06169f0c862d5769` (Open Ontologies 2.1.0). Source entry points:
[`batch.rs`](https://github.com/fabio-rovai/open-ontologies/blob/ef6e781c71aaccaa35c2a1cd06169f0c862d5769/src/batch.rs),
[`graph.rs`](https://github.com/fabio-rovai/open-ontologies/blob/ef6e781c71aaccaa35c2a1cd06169f0c862d5769/src/graph.rs),
[`reason.rs`](https://github.com/fabio-rovai/open-ontologies/blob/ef6e781c71aaccaa35c2a1cd06169f0c862d5769/src/reason.rs),
[`shacl.rs`](https://github.com/fabio-rovai/open-ontologies/blob/ef6e781c71aaccaa35c2a1cd06169f0c862d5769/src/shacl.rs)
and pinned reasoning/Lean certificate docs. No upgrade, engine HTTP/MCP endpoint or additional
reasoner is introduced. Preserve MIT notices when redistributing the engine; it is not vendored.
The installed release hash is `493f6db51550112528d19f3ca88caf133b46c2a9054a195a98bc588b57ba07b6`.
The CLI rejects --version; identity is established by source/release checksum, not a version banner.

| Requested capability | Status | Native engine vs platform / executed evidence |
|---|---|---|
| Pinned executable identity/launch | SUPPORTED | Trusted release checksum, actual CLI --help; capabilities.json |
| Turtle input | SUPPORTED | Native load; raw fixtures, generated canonical graphs and invalid-input tests |
| N-Triples output | SUPPORTED | Native batch save --format ntriples after reasoning; persisted bounded file extraction |
| Other input/output formats | NOT VERIFIED | Pinned source enumerates RDF/XML, N-Quads, TriG, JSON-LD and functional syntax input; only Turtle input/N-Triples output exercised here |
| Deterministic canonical RDF/OWL/SHACL | SUPPORTED | Platform compilation, named deterministic nodes, sorted full-IRI statements; compiler tests |
| Canonical inheritance/custom OWL rules | NOT SUPPORTED | Canonical v1 has no such constructs; no duplicate ontology model added; separately approved native semantic artifacts can contain engine-supported rules |
| Scalar datatypes, required fields/enums/maxima/target classes | SUPPORTED | Platform SHACL generation; actual engine validates operational manufacturing export |
| JSON/ordered arrays, required nullable presence, SQL uniqueness/default/index semantics, decimal precision and UUID lexical constraints | PARTIALLY SUPPORTED | Explicit diagnostics; nonnull JSON/array export rejects; canonical operational services enforce the original contract |
| Raw manufacturing SHACL with Open Ontologies | SUPPORTED | Unchanged fixtures conform, plus negative cases and invalid RDF execution |
| Raw pySHACL fixture conformance | NOT SUPPORTED | Preserved strict expected failure; raw test actually fails; not a claim that the source RDF is invalid |
| RDF 1.1 normalized pySHACL and nine negative mutations | SUPPORTED | Separate in-memory normalization tests; fixtures unchanged |
| SHACL complete general specification | PARTIALLY SUPPORTED | Engine exposes skipped constraints/unmatched shapes and nullable conforms; platform preserves undetermined results |
| Base owl-rl | SUPPORTED | Native profile, two raw-fixture schema inferences; separate test confirms no CriticalMachine classification |
| CriticalMachine under base owl-rl | NOT SUPPORTED | Engine omits required hasValue/intersection rules in base profile |
| CriticalMachine under owl-rl-ext | SUPPORTED | Actual raw fixture and mapped operational-export execution: MCH-005/011/017 only; 11 raw derivations |
| Complete OWL 2 DL, other engine profiles | NOT VERIFIED | Source has rdfs/owl-dl, but Phase 5 API permits only the two tested profiles; no completeness claim |
| Full inferred statements with rule/premise provenance | SUPPORTED | Native reason --certificate; platform stores engine derivation conclusions separately, certificate assertions/premises/scope preserved |
| Independent proof checking | PARTIALLY SUPPORTED | Native certificate generation executed. Lean oo-cert verification NOT RUN: no lake/checker installed on this macOS host; never labeled verified |
| Native semantic change analysis | PARTIALLY SUPPORTED | Batch diff old.ttl new.ttl executes additions/removals; not an operational migration or preservation proof; advanced plan/conservativity not verified |
| Durable jobs/retry/fencing/cancel | SUPPORTED | Platform PostgreSQL SKIP LOCKED, 60s leases, three claims, restart/actual SIGKILL/commit-boundary tests |
| Authorized export/result reads and freshness | SUPPORTED | Platform existing query grants/services; private artifacts; current input reauthorization, stale-value detection and schema-change refusal |
| Inference approval and operational authority separation | SUPPORTED | Immutable set-level approval audit; no inferred operational mutations or action triggers |
| Timeout/unavailable/invalid input/engine failure | SUPPORTED | Actual tiny-timeout probe, nonexistent executable, raw invalid RDF, sanitized unit/integration worker failure tests |
| HTTP/MCP engine transport, optional build features | NOT VERIFIED | Deliberately use the existing isolated batch adapter; no feature attestation from this binary |

Evidence: [executed capability probe](evidence/phase-5/capabilities.json),
[semantic smoke](evidence/phase-5/semantic-smoke.json),
[full regression log](evidence/phase-5/validation.txt),
[host HTTP](evidence/phase-5/http-smoke.txt) and [container smoke](evidence/phase-5/docker-smoke.txt).
Native blank-node identifiers/certificate files can differ across engine processes. Platform compiled
outputs are byte deterministic; result graph canonicalization and result-local skolem IRIs normalize
inferred blank nodes. Original proof bytes retain their per-invocation hashes and provenance.
