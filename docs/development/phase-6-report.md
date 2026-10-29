# Phase 6 report — Protégé interoperability and governed ontology import

PHASE: **6 only**. Date: 2026-10-29, America/New_York.
Base revision: `07d28eb621486060357e80f07335c1135aedf722`.
STATUS: Implemented and validated within the documented Phase 6 bounds.
Changes remain uncommitted. No Phase 7 implementation or external deployment was performed.
Environment: macOS ARM64, Python 3.12.0, PostgreSQL 17.6, existing uv/Java/Maven/Docker,
RDFLib 7.1.4, pySHACL 0.30.1, Open Ontologies 2.1.0 and OWLAPI 4.5.29.
Exact environment and fixture hashes: `docs/architecture/evidence/phase-6/integrity.txt`.

## Functionality implemented

- Explicit Turtle and RDF/XML import contracts, PREVIEW_ONLY and CREATE_DRAFT, server-derived
  tenant/principal, optional description/source metadata, namespace expansion and conflict choices.
- Bounded no-network parser subprocess, fixed format selection, UTF-8 size/statement/axiom-budget/
  namespace/blank-node/term limits and a five-second deadline covering blank-node canonicalization.
  XML DTD/entities and ambiguous OWL/XML roots reject. Imports declarations never resolve.
- Vocabulary inspection, complete original text/SHA256 preservation, canonical source graph,
  immutable private request/result/diagnostic provenance, bounded inline results and paginated details.
- Explicit supported class, datatype property, object property and canonical inverse-navigation
  mappings using existing canonical Pydantic definitions. Operational primary keys/constraints are
  author choices, never inferred from OWL functionality/keys/open-world cardinality. No actions,
  access policies, individuals, sameAs identity merges or custom reasoning are inferred.
- Unsupported/unmapped semantic axioms remain in the original with predicate-grouped diagnostics.
  RDF statement units and conservative axiom admission are documented; no false logical-axiom counts.
- Canonical-definition keep/replace review, duplicate/IRI/target/domain/range/punning conflicts,
  immutable accepted vocabulary binding provenance and mutable-base hash checks. Multiple ontology/
  version identities conflict rather than choosing silently.
- Schema-change preview and existing additive/breaking analysis. CREATE_DRAFT composes the existing
  RegistryService in one transaction with provenance/bindings. Late failure rolls everything back.
  Drafting never publishes or activates; ordinary registry migration/approval/activation guards apply.
- Deterministic published canonical Turtle exports, exact output/canonical hashes, explicit canonical
  reimport mappings, and version/hash-bound source vocabulary. New drafts cannot change old exports.
  Editing an imported draft invalidates its vocabulary projection with an explicit diagnostic.
- Supported-subset round trips preserve operational constraints through mapping manifests; complete
  unsupported OWL remains separately downloadable. Canonical exports never union stale restrictions
  from an old source into a changed schema. This is not arbitrary OWL reconstruction or live sync.
- Tenant-safe FastAPI routes and current authorization/private-result checks; ordinary operations
  work with no Protégé/WebProtégé application. Future native authoring uses the same canonical APIs.

## Files created or modified

| Area | Paths |
|---|---|
| New interoperability module | `services/api/src/ontology_platform/interoperability/{__init__,contracts,parser,mapping,service,routes}.py` |
| Existing service wiring/persistence | `services/api/src/ontology_platform/main.py`, `db/models.py`, `db/governance.py` |
| New migration | `services/api/migrations/versions/0012_ontology_imports.py` |
| Tests | New `services/api/tests/test_ontology_import.py` (38 cases) |
| Authoring compatibility | Extended `integrations/protege/src/main/java/CompatibilityCheck.java`; new `integrations/protege/fixtures/{README.md,manufacturing-rdfxml.owl}` |
| Reused smoke tooling | Extended `scripts/smoke_semantic.py` and `scripts/smoke_semantic_container.py` with optional `--interchange`; existing default behavior retained |
| API/architecture | New `docs/api/interchange.md`, ADR `0027-governed-ontology-interchange.md`; updated API README, architecture overview/canonical schema/migrations/semantic compatibility |
| Phase documentation | Updated README and Phase 6 checklist; new this report |
| Evidence | `docs/architecture/evidence/phase-6/` baseline/final validation, original/extended/canonical OWLAPI, HTTP, engine, image build/smoke and integrity |

No dependency, upstream pin, canonical schema contract/JSON Schema, supplied fixture, AGENTS.md,
PLANS.md, semantic compiler/engine/worker, action policy, ingestion ownership or activation guard was
changed. No extra database, microservice, parser dependency, native extension, frontend or SDK added.

## Database migrations

`0012_ontology_imports` adds two provenance structures, not a second ontology registry:

- `ontology_imports`: tenant/ontology/import identity, initiating principal/time, format, original
  source/hash, canonical graph, request/result/diagnostics, accepted draft/version hash and explicit
  vocabulary mappings. Composite ontology/version FKs, accepted-draft uniqueness, format/byte checks.
- `ontology_vocabulary_bindings`: tenant/ontology scoped IRI and target hashes with complete original
  terms and import FK. A canonical target and external IRI cannot silently gain conflicting aliases.
- UPDATE/DELETE triggers preserve import/binding history. DDL uses existing two-second lock and
  30-second statement budgets. No published metadata or operational objects are rewritten.

Development is at **0012_ontology_imports**. Tests execute fresh/base/head, existing prior-phase
migration cycles, Phase 5 → Phase 6 → Phase 5 → Phase 6, metadata drift, immutable history and
operational-data preservation in disposable schemas. Downgrade removes Phase 6 provenance/bindings;
canonical drafts, published versions and operational objects remain. Local new-revision development
DDL was rebuilt while refining the uncommitted migration; existing prior-phase data was preserved.

## Baseline and validation

Initial Git tree was clean. Alembic reported **0011_semantic_history**. `uv sync --frozen` verified
locked packages; actual engine smoke verified unchanged release identity. Before implementation,
`uv run python scripts/validate_phase0.py` passed **363 tests, one preserved strict expected failure,
no skips, 185.74 seconds**. Ruff/format/strict mypy/Alembic drift passed. Existing semantic engine
and OWLAPI harness tests reproduced the reported Phase 5 baseline.

Focused final authoring tests: **38 passed**, 16.40 seconds. A preceding full run passed **399 tests,
one expected failure**, 192.84 seconds, before the two final multiline tests were added. Final
complete configured runner passed **401 tests, one preserved expected failure, zero skips**,
402 collected, **209.21 seconds**. Evidence: `validation-final.txt`.

| Check | Result | Evidence / scope |
|---|---|---|
| Phase 5 baseline | PASS | `baseline-validation.txt`: 363 passed, 1 xfailed, zero skips; reported pins/revision match |
| Complete final configured regression | PASS | `validation-final.txt`: 401 passed, 1 xfailed, zero skips; 209.21s |
| Ruff lint/format and strict mypy | PASS | Final runner preamble; 75 application/schema source modules |
| Alembic current/upgrade/downgrade/re-upgrade/drift | PASS | Real PostgreSQL suite plus `alembic check`; head 0012 |
| Turtle parsing | PASS | Unchanged fixture suite and isolated import parser tests |
| CSV identity/count/FK and RDF consistency | PASS | Retained fixture/Polars regressions; exact input hashes retained |
| Raw pySHACL conformance | FAIL | Preserved strict expected failure: simple/xsd:string sh:in mismatch; never counted as raw PASS |
| Normalized SHACL and nine negative cases | PASS | Existing explicit in-memory RDF 1.1 compatibility harness, no fixture edits |
| Pinned engine raw SHACL/negative/invalid input | PASS | Existing configured tests plus `engine-smoke.json` and `engine-smoke.txt` |
| CriticalMachine owl-rl-ext reasoning | PASS | Existing actual raw and operational manufacturing workflows |
| CriticalMachine under base owl-rl | NOT SUPPORTED | Existing executed profile limitation unchanged |
| Generated certificates / independent proof checking | PASS / NOT RUN | Existing jobs generate certificates; no installed Lean checker; no verified-proof claim |
| PostgreSQL import transactions and lifecycle | PASS | Late serialization failure rolls back already-written draft; concurrent creation commits once |
| Canonical mapping/conflicts/base hashes | PASS | Explicit datatypes/domains/ranges, duplicates, punning, aliases, keep/replace, stale bases and migration guard |
| Original/unsupported preservation and diagnostics | PASS | Exact original text/hash; restrictions/keys retained; vocabulary, pagination/truncation, multiline literals |
| Supported round trip/deterministic export | PASS | Canonical properties/links/constraints and accepted IRIs retained; version/hash-bound export regression |
| FastAPI object queries/actions/reconciliation/Polars ingestion | PASS | Existing full PostgreSQL regression suites and real HTTP manufacturing semantic workflow |
| Authorization and tenant/principal boundaries | PASS | Current operation checks, denied parser admission, private originals/results, cross-tenant denials and retained semantic/query regressions |
| Actual host Uvicorn/HTTP workflow | PASS | `http-run.txt`, `http-smoke.txt`: import/draft/original/vocabulary/export; active unchanged; 63-object/70-link RDF validation, reasoning, approvals/facts |
| Final Docker build/readiness/OpenAPI/identity denial | PASS | `docker-build.txt`, `docker-smoke.txt`; image rebuilt after final source changes |
| Existing OWLAPI compatibility check | PASS | `baseline-protege.txt`; known xsd:date declaration delta remains |
| Extended OWLAPI source and canonical export round trips | PASS | `protege.txt`, `canonical-protege.txt`: Turtle/RDFXML/OWLXML; ontology/version and source axioms retained |
| Platform OWL/XML parsing | NOT SUPPORTED | Explicitly rejected; RDFLib importer supports Turtle and rdf:RDF-rooted RDF/XML |
| Protégé desktop GUI validation | NOT RUN | No Protégé application installed under /Applications; verified OWLAPI fixture is not called GUI-authored |
| Live WebProtégé / external deployment | NOT RUN | Optional deployment not requested/approved; pinned readme documents file transfer/WAR/optional MongoDB, no invented endpoint |
| Fixture/instruction/pin integrity | PASS | `integrity.txt`, unchanged input Git diff and `git diff --check` |
| Remote CI / production identity/deployment | NOT RUN | No push/deployment requested; trusted local identity remains, Phase 7 not implemented |

Intermediate issues were corrected without weakening fixtures or existing tests: OWLAPI inverse
orientation/RDF 1.1 string serialization differences; RDF/XML versus OWL/XML root ambiguity; test
imports; binding provenance that could affect older exports; canonical inverse-property declarations;
and multiline literal escaping between parser and service. One early full run was deliberately
interrupted for provenance review; its partial output is `validation-initial.txt`, not a passing
full-suite claim. Raw source graph inequality is explicitly tested before the documented in-memory
serialization normalization. The original strict Java compatibility check is retained.

## Architectural decisions and known limitations

ADR **0027** defines explicit optional authoring through the existing canonical registry, isolated
bounded parsing, exact source preservation, immutable provenance, transactional draft creation and
version/hash-bound deterministic exports. Published canonical metadata/PostgreSQL remain authoritative.
Existing semantic artifacts require published schema FKs; import provenance can precede publication,
so the import record stores its own original rather than misusing an approved semantic artifact.

1. Trusted local identity only. No production OIDC/RBAC, delegated sharing, GUI authoring, live sync,
   WebProtégé deployment or Phase 7 implementation.
2. Explicit mappings and conservative scalar subset. No general OWL 2 DL-to-operational translation,
   inherited property flattening, automatic constraint/key/cardinality inference, object ingestion,
   actions or access-policy inference. Unsupported axioms remain original semantic content.
3. Only Turtle and rdf:RDF-rooted RDF/XML UTF-8 text imports; no OWL/XML, archives, remote URLs or
   automatic imports resolution. Protégé/OWLAPI conversion is an optional external authoring step.
4. Original semantic reconstruction and supported canonical projection are separate exports. Mapping
   manifests retain supported operational constraints; bare OWL cannot preserve all canonical policy.
5. The HTTP body is 64 KiB, internal source 256 KiB, parser 4,000 statements/conservative axiom budget,
   512 blank nodes, 64 namespace bindings, 8 KiB terms, five seconds. Parsing/canonicalization runs in
   a killed/reaped subprocess outside PostgreSQL locks. Hard OS memory/aggregate admission and durable
   large-import orchestration remain later work, not claimed by these bounded logical checks.
6. No UPDATE_DRAFT mode, automatic publication/activation, arbitrary IRI reassignment, identity merge,
   source axiom union, or idempotent replay-key API. Existing target versions reject concurrent/repeated
   creation; previews never authorize later execution.
7. Immutable source/binding history retains indefinitely; no deletion, expiry, aggregate quota or
   sharing API. Database owners can bypass triggers. This is application provenance, not tamper-proof
   storage or independently verified logical proof.
8. Existing raw pySHACL failure, base owl-rl fixture limitation, unverified certificates, activation
   size limits and coarse ontology locks are preserved. No production scalability claim is made.

## Failures, not-run reasons and next checks

No unexpected final failure remains. The unchanged raw pySHACL conformance check still fails and is
reported as a strict expected failure, not successful raw validation. The existing upstream
Starlette/httpx deprecation warning remains. Base owl-rl cannot infer the fixture classification.

Protégé GUI validation was not run because the application is not installed; the Java harness and
its generated fixtures are identified accurately. WebProtégé deployment and remote CI were not run
because neither was requested. Independent certificate verification was not run because the Lean
checker is unavailable. These are not converted to passing results. General OWL/XML parsing is
unsupported by the selected platform parser, even though OWLAPI conversions were executed.

No required implementation check remains within the supported Phase 6 backend scope. Optional GUI
acceptance and independently checked certificates remain explicit external validation gaps. API
processes/containers and disposable PostgreSQL schemas were cleaned up; development PostgreSQL
remains running. No push, commit or external deployment was performed.

## Next recommended phase

Stop after Phase 6. **Phase 7 — Authentication and authorization** is next, following review and
separate explicit approval. The existing canonical schema APIs also remain the intended future
native Ontology Manager backend. No later phase was started.
