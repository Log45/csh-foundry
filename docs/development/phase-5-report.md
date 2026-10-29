# Phase 5 report — Semantic compilation, validation, reasoning and derived facts

PHASE: **5 only**. Date: 2026-10-29, America/New_York. Base revision: `580cb25299550a7c47e500d60ec5c2deca1f1e6a`.
STATUS: Implemented and validated within the documented Phase 5 bounds.
Changes remain uncommitted. Environment: macOS ARM64, Python 3.12.0, PostgreSQL 17.6,
Polars 1.44.2, RDFLib 7.1.4, pySHACL 0.30.1, pinned Open Ontologies 2.1.0,
existing Java/Maven and uv. Phase 6 implementation has not begun.

## Functionality implemented

- Deterministic published canonical schema compilation to RDF/OWL and SHACL, with stable
  category-separated vocabulary IRIs and existing tenant/object identity mapping v1. Explicit scalar
  literal normalization, deterministic named shape/list nodes and sorted full-IRI statements.
- Structured diagnostics for unsupported/lossy canonical constructs. No inheritance/rule/minimum-link
  construct is invented where canonical v1 has none. JSON/array nonnull exports reject explicitly.
- Authorized bounded RDF export through QueryService, SQL grants, property projection and individual
  object/property/schema/link/export permissions. Both endpoints must be selected/readable. Forward
  and declared inverse RDF edges are generated without redundant operational edge persistence.
- Immutable typed manifests and bounded PostgreSQL artifact storage, exact hashes, compiler/engine
  pins, principal/tenant/schema identity, source versions, available staging-run associations, selected
  revisions and edge boundaries. Exports describe a bounded query result under the existing shared
  ontology lock, not historical reconstruction or a cross-system source transaction.
- Durable validation/reasoning/change jobs, SKIP LOCKED claims, database-clock fencing, leases,
  renewal, cancellation, bounded retries and claim/error/completion history. Engine work occurs
  outside transactions; artifacts/facts/completion commit atomically after input/permission rechecks.
- Three-valued SHACL reports with bounded violations and preserved skipped/unmatched diagnostics.
  Semantic violations complete successfully as validation results; infrastructure failures remain
  distinct sanitized durable error categories.
- Full native certificate-backed inference conclusions, separate immutable derived sets/facts,
  original rule/premise/assertion/scope certificates, result-local canonical skolem IRIs for inferred
  blank nodes and explicit unverified proof status. No custom reasoner or automatic operational
  promotion exists. Engine fixpoint/profile/count summaries are retained.
- PENDING/APPROVED/REJECTED set-level review, authorized fresh-input approval and immutable actor/time
  audit history. Facts identify original reasoning job, schema/profile, asserted graph hash and engine.
- Principal-private semantic APIs, current-input permission rechecks on every payload read, STALE
  results after values/revisions/edges/provenance or execution-version changes, and explicit denial
  after schema activation or loss of authorized selection/grants. Historical identifiers and original
  immutable provenance remain retained. Native change analysis reports graph additions/removals;
  it is not an operational migration safety proof.

## Files created or modified

Paths abbreviated below are under `services/api/src/ontology_platform/` where indicated.

| Area | Files |
|---|---|
| Semantic implementation | New `semantic/{contracts,compiler,service,worker,routes,__main__}.py`; extended existing `semantic/engine.py` batch adapter/protocol, preserving legacy reason calls |
| Existing governed interfaces | Updated `queries/service.py` for caller-owned transactions and bounded authorized forward-edge projection; new `ingestion/provenance.py` public bounded provenance projection |
| Persistence | Updated `db/models.py`, `db/governance.py`; new migrations `services/api/migrations/versions/0010_semantic.py`, `0011_semantic_history.py` |
| API/dependencies | Updated `main.py`, `services/api/pyproject.toml`, `uv.lock`; RDFLib moves into runtime dependencies at its existing exact pin; no version upgrades |
| Tests | New `services/api/tests/test_semantic_compiler.py`, `test_semantic_platform.py`; existing test files/fixtures preserved |
| Reproducible developer tooling | New `scripts/benchmark_semantic.py`, `smoke_semantic.py`, `smoke_semantic_container.py` |
| Documentation | New `docs/api/semantic.md`, `docs/architecture/semantic-phase-5-capabilities.md`, ADRs 0024–0026, this report, Phase 6 checklist; updated README, API/architecture/migration references, semantic compatibility and original Phase 5 checklist |
| Evidence | `docs/architecture/evidence/phase-5/`: baseline/final validation, capabilities, graph reproducibility, semantic smoke, integrity hashes, measurements, host HTTP, Docker build/smoke and OWLAPI harness |

No canonical ontology model/JSON schema, source fixture, AGENTS.md, PLANS.md, upstream pin, ontology
activation rule, operational source/edit ownership, action definition, Studio, SDK, Rust accelerator,
additional operational database, broker or microservice was introduced or silently changed.

## Database migrations

| Revision | Changes |
|---|---|
| `0010_semantic` | Four tenant-owned tables: semantic_artifacts, semantic_jobs, semantic_derived_facts, semantic_approvals. Composite ontology/version/artifact/job FKs; content/request uniqueness and status/lease/size checks; claim index; immutable artifact/fact/approval triggers and job-plan/terminal-state guard. |
| `0011_semantic_history` | Bounded per-job JSON claim/error/completion history, including previous errors after a successful retry. Existing rows backfilled with an empty history using a temporary server default. |

Development is at **0011_semantic_history**. Both migrations use bounded DDL lock/statement settings.
Disposable-schema tests run clean/base/head and Phase 4 downgrade/re-upgrade cycles, constraints,
immutability, drift and operational data preservation. Downgrade intentionally removes Phase 5
artifacts/jobs/facts/approval history while preserving authoritative objects/relationships and earlier
phase structures. No migrations load fixture data or modify published schemas.

## Baseline and validation

The initial working tree was clean, database revision **0009_ingestion_diagnostics**, installed
release/source pin 2.1.0 verified, Polars **1.44.2**. Before implementation, the full configured runner
passed **320 tests, one strict expected failure, no skips**, in **175.47 seconds**. Ruff/format,
strict mypy and Alembic drift checks passed. This independently reproduced the reported Phase 4
baseline. Raw pySHACL mismatch, base owl-rl limitation and existing upstream warnings were retained.

The final configured runner passed **363 tests, one strict expected failure, no skips**,
364 collected, in **187.15 seconds**. Ruff lint/format, strict mypy (69 source modules),
and Alembic drift checks passed. The 43 added tests cover compiler/engine and governed
PostgreSQL/HTTP/manufacturing/recovery/version-lifecycle behavior.

| Check | Result | Evidence / scope |
|---|---|---|
| Complete configured regression | PASS | 363 passed, 1 preserved xfailed, no skips; 187.15s; `validation.txt` |
| Ruff lint/format, strict mypy | PASS | Final configured runner preamble; 69 source modules |
| Alembic upgrade/downgrade/re-upgrade/current/drift | PASS | Real PostgreSQL regressions, preserved objects, current revision 0011 |
| Turtle parsing, CSV keys/counts/FKs/RDF identities | PASS | Retained fixture suite and integrity hashes |
| Raw unchanged pySHACL conformance | FAIL | Preserved narrow strict expected failure, simple-string/xsd:string sh:in mismatch |
| Normalized pySHACL baseline and nine negative cases | PASS | Independent unchanged fixture harness; not claimed as raw conformance |
| Engine raw SHACL, invalid RDF and negative diagnostics | PASS | Actual pinned release execution in existing semantic tests |
| Deterministic canonical RDF/OWL/SHACL | PASS | Byte equality, graph equality, reordered definitions and explicit diagnostic tests |
| Generated operational RDF / SHACL | PASS | Actual engine validates manufacturing export; negative generated shape yields a completed nonconforming report |
| Manufacturing ingestion/export equality | PASS | 63 objects, 70 forward plus 70 inverse RDF edges, 412 triples; graph equality after explicit vocabulary/identity mapping |
| Actual extended-profile CriticalMachine inference | PASS | Raw fixtures and mapped operational graph both yield exactly MCH-005/011/017; MCH-001 excluded |
| Equivalent classification under base owl-rl | NOT SUPPORTED | Executed separate comparison; base profile derives two schema statements and no CriticalMachine classification |
| Independent repeated engine result reproducibility | PASS | Two actual runs have identical canonical inferred graphs; `reproducibility.txt` |
| Native graph change analysis | PASS | Actual diff reports one addition/one removal; durable change job tested |
| Certificate generation and provenance persistence | PASS | Full native assertions/derivations/scope files; original rule/premise provenance preserved |
| Independent Lean certificate verification | NOT RUN | No lake/oo-cert checker installed on this host; all proof artifacts explicitly unverified |
| General OWL 2 DL / migration-preservation proof | NOT SUPPORTED | Not part of the two verified API profiles/native graph-diff contract |
| Semantic tenant/property/row/link/result permissions | PASS | Private principal/tenant IDs, restricted properties/rows/endpoints, revoked policies, stale schema/inputs and existing query-grant regressions |
| Durable retry/renewal/cancel/exhaustion/fencing | PASS | Real PostgreSQL; token/lease expiry and stale completion tests |
| Actual process termination and recovery | PASS | SIGKILL after output insert before commit, os._exit immediately after commit; simulated lease-clock expiration explicitly distinguished |
| Partial output rollback and error history | PASS | Injected later persistence failure rolls back earlier artifact/fact inserts; retry completes with retained claim/error history |
| Engine timeout/unavailable/failed execution | PASS | Actual tiny-timeout probe and missing executable; injected worker failures retry or fail without operational effects |
| Fact approval/audit and operational authority | PASS | Set-level events and current input rechecks; object values/revisions/counts remain unchanged by semantic work |
| FastAPI queries/actions/reconciliation/Polars ingestion | PASS | Existing full real-PostgreSQL regression suites retained |
| Host Uvicorn/HTTP semantic workflow | PASS | Actual process: compile/export → PENDING → separate worker → validation/reasoning/results → approval/history/facts |
| Docker image build/readiness/OpenAPI/identity denial | PASS | Final local image; current PostgreSQL readiness and absent-principal semantic request 401 |
| Protégé-compatible OWLAPI file interchange | PASS | OWLAPI 4.5.29 harness rerun; known additional xsd:date declaration, no lost axioms |
| Protégé GUI / WebProtégé / Phase 6 operational import | NOT RUN | Existing file harness only; later authoring phase not implemented |
| Bounded workloads and query/action/ingestion contention | PASS | Private-schema local measurements below; no production performance claim |
| Fixture/pin preservation and diff whitespace | PASS | `integrity.txt`, unchanged input Git diffs, `git diff --check` |
| Remote CI / production deployment / production identity | NOT RUN | No push/deployment requested; trusted local development configuration only |

Intermediate new-test failures included diagnostic alias serialization, fixture inverse RDF edges,
new-test policy resource formatting/imports/LinkInput field names, and lint/type corrections. These
were corrected without changing existing fixtures or weakening existing tests. The generated export
now includes explicitly declared inverse RDF edges with the same endpoint restrictions. No final
unexpected failure is accepted. Starlette/httpx and Java/SLF4J warnings remain upstream findings.

## Measurements

Private migrated PostgreSQL schema, macOS ARM64, instrumented Python tracemalloc. Raw numbers and
commands are in `semantic-benchmarks.json` and `benchmark-run.txt`. Dataset 63 is the real ingested
manufacturing workflow; dataset 257 adds 194 synthetic factories through ObjectService. Both retain
70 forward operational links and authorized inverse RDF projections.

| Workload | Measured time |
|---|---:|
| Canonical compile | 42.878 ms |
| Export 63 objects / 412 triples / 148,765 bytes | 198.093 ms |
| Identical repeated export (same artifact ID) | 197.660 ms |
| Validation job including permission/freshness checks and commits | 670.818 ms |
| Reasoning job with generated ontology/certificate/fact/result persistence | 523.598 ms |
| Export 257 objects / 390,703 bytes | 404.015 ms |
| Concurrent query / export | 42.241 / 367.914 ms |
| Concurrent action / export | 397.288 / 323.281 ms |
| Concurrent ingestion refresh / export | 6205.516 / 319.180 ms |

All concurrent operations completed. Python traced peak **26,888,154 bytes (~25.64 MiB)**;
whole-process peak RSS **161,415,168 bytes (~153.94 MiB)** on macOS. Export timestamps, transaction
setup, policy checks and source metadata contribute to these small single samples. These are not
percentiles, hard isolation guarantees, native-engine memory measurements or production scalability
claims. No measurements justify replacing existing ontology locks or adding databases/infrastructure.

## Architectural decisions and limitations

ADRs **0024–0026** document bounded immutable artifacts/deterministic projection, private governed
exports/current authorization, and fenced jobs/certificate-backed derived facts. PostgreSQL remains
authoritative. Canonical RDF is a projection; the external semantic engine is replaceable.

1. Trusted local identity remains the only configured identity model. No production OIDC/RBAC,
   cross-principal sharing or delegated-worker security claim is made. Only the initiating principal
   can claim/read these jobs and payloads; independently privileged review roles remain future work.
2. Scalar mappings and explicit diagnostics only. Canonical v1 has no inheritance/custom semantic
   rule/minimum-link representation; native approved ontology/shapes can supply supported semantics.
   JSON/arrays, null-presence, precision/UUID/SQL uniqueness semantics remain governed operationally.
3. Raw pySHACL conformance still fails; owl-rl lacks fixture CriticalMachine inference. Certificates
   are generated, never claimed independently verified. Native diff is a graph delta, not a proof of
   operational compatibility, entailment preservation or automatic migration approval.
4. Artifact size/count/time limits are logical admission/acceptance limits. Native parsing/reasoning,
   RDF graph canonicalization, subprocess temporary-disk growth and preexisting large SQL values
   are not enclosed in a hard OS memory/disk/CPU sandbox. Production admission/resource isolation is
   deferred. Engine stdout is spooled to disk and bounded before loading, not continuously truncated.
5. One bounded worker invocation, 60-second lease, three claims, no scheduler/supervisor/backoff
   service. Identical terminal jobs stay deduplicated; no manual same-input retry override exists.
6. Artifacts/approval/fact/job history retain indefinitely; no automatic expiry, aggregate storage
   quota or deletion API. Temporary engine state cleans up, and partial SQL transactions roll back.
   Database owners can bypass immutability triggers; tamper-proof storage is not claimed.
7. Freshness is conservative and evaluated at payload access/job execution. Same-identity data/input
   changes mark results STALE; grant/selection/schema changes can deny historical payload entirely.
   Source run references are available retained-stage associations, not exact historical object
   reconstruction. Their cleanup may conservatively stale an earlier export. Old artifacts remain.
8. Generated vocabulary is intentionally category-separated from reference fixture vocabulary.
   Manufacturing equality and native rule integration use explicit deterministic vocabulary/identity
   translation in the acceptance test; this is not Phase 6 OWL import into operational metadata.
9. Proof certificates retain original engine blank-node terms and per-run hashes; native proof bytes
   can differ between processes. Canonical result graphs/skolem IRIs provide reproducible inferred
   graph identity. Only both verified owl-rl profiles are exposed; general OWL 2 completeness is not.

## Next recommended phase

Stop after Phase 5. The next phase is **Phase 6 — Protégé integration**, only after explicit review
and approval. Follow `docs/development/phase-6.md`: bounded OWL import to unpublished reviewed drafts,
original/unsupported axiom preservation, explicit imported IRI conflict handling, supported file
round trips and existing operational/semantic governance. No Phase 6 implementation was started.
