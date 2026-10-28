# Validation Guide — Manufacturing Ontology Platform

**Audience:** Coding agents implementing the platform described in `PLANS.md` and `AGENTS.md`.

**Purpose:** Provide reproducible checks and acceptance criteria for the canonical manufacturing fixtures and the eventual FastAPI → PostgreSQL → semantic-engine workflow. **Do not report a check as passing unless you executed it.** If a required tool or service is unavailable, report **NOT RUN** and the reason.

## 1. Fixture inventory and contracts

All paths below are relative to this file (`fixtures/`).

| File | Role | Expected baseline |
| --- | --- | --- |
| `manufacturing.ttl` | OWL ontology / vocabulary | Parses as Turtle |
| `manufacturing-shapes.ttl` | SHACL shapes graph | Parses as Turtle |
| `manufacturing-data.ttl` | RDF instance **data graph** | Parses as Turtle; 63 typed instances |
| `factories.csv` | Source records for `Factory` | 6 rows |
| `machines.csv` | Source records for `Machine` | 20 rows |
| `employees.csv` | Source records for `Employee` | 12 rows |
| `maintenance_tasks.csv` | Source records for `MaintenanceTask` | 25 rows |

The ontology namespace is `https://example.org/ontologies/manufacturing#`.

**Critical distinction:** SHACL validates `manufacturing-data.ttl` against `manufacturing-shapes.ttl`. `manufacturing.ttl` is the OWL schema, **not** the RDF instance data graph. OWL reasoning and SHACL validation are separate tests. The fixture dates and identifiers are deterministic.

## 2. Environment setup

Run commands from the repository root, adjusting `fixtures/` if the directory is elsewhere.

```bash
# Python dependencies for fixture validation (if not already installed)
uv run --with rdflib --with pyshacl python -c 'import rdflib, pyshacl; print("RDF validation tools available")'
```

If `uv` is unavailable, use the project's documented Python environment and install `rdflib` and `pyshacl` there. Pin versions in the project lockfile for reproducible CI. Avoid installing unpinned dependencies in the production environment.

## 3. Static fixture validation — required in Phase 0

### 3.1 Parse all Turtle files

```bash
uv run --with rdflib python - <<'PY'
from pathlib import Path
from rdflib import Graph

for filename in (
    'manufacturing.ttl',
    'manufacturing-shapes.ttl',
    'manufacturing-data.ttl',
):
    path = Path('fixtures') / filename
    graph = Graph().parse(path, format='turtle')
    assert len(graph) > 0, f'Empty RDF graph: {path}'
    print(f'PASS {path}: {len(graph)} triples')
PY
```

**Pass:** All three files parse without errors and contain at least one triple. Triple counts can be recorded as a regression baseline, but should not be hard-coded as a requirement after intentional fixture edits.

### 3.2 Verify CSV counts, keys, and references

```bash
python - <<'PY'
import csv
from pathlib import Path

root = Path('fixtures')
expected = {
    'factories.csv': (6, 'factoryId'),
    'machines.csv': (20, 'machineId'),
    'employees.csv': (12, 'employeeId'),
    'maintenance_tasks.csv': (25, 'taskId'),
}
rows = {}
for name, (count, key) in expected.items():
    with (root / name).open(newline='', encoding='utf-8') as f:
        rows[name] = list(csv.DictReader(f))
    assert len(rows[name]) == count, (name, len(rows[name]), count)
    ids = [r[key] for r in rows[name]]
    assert all(ids), f'{name}: empty IDs'
    assert len(ids) == len(set(ids)), f'{name}: duplicate IDs'
    print(f'PASS {name}: {count} rows, unique {key}')

factory_ids = {r['factoryId'] for r in rows['factories.csv']}
machine_ids = {r['machineId'] for r in rows['machines.csv']}
employee_ids = {r['employeeId'] for r in rows['employees.csv']}
assert all(r['factoryId'] in factory_ids for r in rows['machines.csv'])
assert all(r['machineId'] in machine_ids for r in rows['maintenance_tasks.csv'])
assert all(r['assignedEmployeeId'] in employee_ids for r in rows['maintenance_tasks.csv'])
print('PASS all CSV foreign-key references')
PY
```

**Pass:** Expected row counts, nonempty unique keys, and valid foreign-key references. The CSV check is separate from SHACL: SHACL does not guarantee SQL uniqueness or referential integrity for ingestion.

### 3.3 Run SHACL validation

```bash
uv run --with pyshacl --with rdflib pyshacl \
  -s fixtures/manufacturing-shapes.ttl \
  -df turtle -sf turtle \
  fixtures/manufacturing-data.ttl
```

**Pass:** SHACL reports `Conforms: True` and exits successfully. This tests closed-world constraints, including required properties, datatypes, allowed statuses, link cardinalities, and target types. Do **not** treat a successful Turtle parse as a successful SHACL validation.

### 3.4 Verify the RDF data graph matches CSV identities

The RDF data graph must contain exactly 6 `Factory`, 20 `Machine`, 12 `Employee`, and 25 `MaintenanceTask` instances with explicit `rdf:type` declarations. Use RDFLib or SPARQL to count each type. Check that each machine has exactly one `locatedInFactory` link, and each task has exactly one `taskForMachine` and one `assignedEmployee` link. Compare IDs to the corresponding CSV keys. This is an independent consistency check; SHACL alone does not compare RDF and CSV files.

## 4. Negative tests — required for the validator implementation

**Never modify the canonical fixture files to perform negative tests.** Copy them to a temporary directory or construct an in-memory RDF graph, introduce one invalid condition at a time, and assert validation fails with an understandable diagnostic.

| Mutation | Expected failure |
| --- | --- |
| Remove a machine's `machineId` | `sh:minCount` violation |
| Add a second `machineId` value to a machine | `sh:maxCount` violation |
| Change `operationalStatus` to `BROKEN` | `sh:in` violation |
| Change `temperatureCelsius` to a string literal | `sh:datatype` violation |
| Set `temperatureCelsius` below -273.15 | `sh:minInclusive` violation |
| Remove a machine's `locatedInFactory` link | `sh:minCount` violation |
| Point `locatedInFactory` to a resource not typed `Factory` | `sh:class` violation |
| Change a task's `scheduledDate` to an untyped string | `sh:datatype` violation |
| Add a second `assignedEmployee` link to a task | `sh:maxCount` violation |

Also test **ingestion-level** failures that SHACL may not catch: duplicate CSV IDs, missing referenced factory/machine/employee IDs, malformed CSV headers, invalid numeric conversions, and partial batches. These must be rejected or quarantined according to the ingestion contract.

## 5. OWL reasoning — independent semantic check

`manufacturing.ttl` defines `CriticalMachine` as a `Machine` whose `operationalStatus` has the value `"CRITICAL"` (OWL `owl:hasValue` restriction). For an OWL reasoner that supports this construct:

1. Load the OWL ontology and RDF instance data using the documented engine workflow.
2. Run the supported OWL reasoning operation.
3. Check that machines with `operationalStatus = "CRITICAL"` are classified as `CriticalMachine`.
4. Confirm that a noncritical machine is **not asserted as inferred critical** by this rule.
5. Record the reasoner version, supported profile, command/API call, and output artifact.

**Important:** RDFLib parsing and SHACL conformance do not perform this inference. Do not claim Open Ontologies supports this exact OWL axiom until tested against the pinned version. If unsupported, report the limitation and preserve the OWL fixture; do not silently rewrite the semantic rule.

## 6. Open Ontologies adapter validation — Phase 0 smoke test, Phase 5 full integration

Before calling Open Ontologies, inspect its **pinned** source/docs to establish actual CLI, REST, or MCP contracts. Do not invent endpoints, payloads, or flags.

- **Phase 0:** Confirm the selected version can be built or launched; run one documented command against a fixture or record why no applicable command exists.
- **Phase 5:** Validate the RDF data with the SHACL shapes using a supported engine operation; capture structured results and failure diagnostics.
- **Phase 5:** Exercise the supported reasoning functionality independently of SHACL.
- **Phase 5:** Confirm timeouts, invalid input, engine unavailability, and retry behavior are handled without corrupting PostgreSQL state.
- **Phase 5:** Persist engine version, input hashes, timestamps, and semantic results.

The Python semantic adapter must remain replaceable; no application domain service should depend directly on undocumented Open Ontologies internals.

## 7. Operational backend validation — phases 1–4

Run these checks against a **real test PostgreSQL database**, not only mocked repositories.

### Phase 1: Schema and persistence

- Create object types `Factory`, `Machine`, `Employee`, `MaintenanceTask` from canonical metadata.
- Create the three link types: machine→factory, task→machine, task→employee. Inverse navigation must be supported by the API; do not store redundant inverse edges unless the design explicitly requires it.
- Insert objects with stable IDs matching the CSV fixtures.
- Reject duplicate identities and invalid property types.
- Reject links with nonexistent endpoints.
- Verify rollback of failed multi-object transactions.
- Verify optimistic concurrency conflicts do not overwrite newer changes.

### Phase 2: FastAPI queries

- Fetch an object by type and ID.
- Filter machines by `operationalStatus` and numeric `temperatureCelsius`.
- Sort and paginate deterministically.
- Traverse machine→factory and task→machine/employee links.
- Reject unknown properties and unsupported query operators.
- Ensure all SQL parameters are bound; no user-controlled SQL identifiers are interpolated without allowlisting.

### Phase 3: Actions and edits

- Execute a valid `ScheduleMaintenance` action that creates a task and the required links in one transaction.
- Reject an invalid action without partial writes.
- Verify idempotency keys prevent duplicate effects.
- Verify audit records and outbox entries commit with the action.
- Verify a source refresh respects the configured edit-overlay conflict policy.
- Simulate webhook failure and confirm committed operational state remains consistent and delivery can retry.

### Phase 4: Polars ingestion

- Load all four CSV files with explicit schemas.
- Materialize 6 factories, 20 machines, 12 employees, and 25 tasks.
- Verify all expected links exist.
- Repeat ingestion and confirm object counts remain unchanged (idempotency).
- Change a source property and verify the intended update/reconciliation behavior.
- Reject or quarantine invalid rows with recorded diagnostics.
- Test interrupted jobs and bounded-memory batch processing.

**Important:** `manufacturing-data.ttl` is a reference representation of the CSV fixtures. RDF export from the operational backend should be compared semantically (graph equivalence or canonicalized content), not by raw Turtle file bytes or triple ordering.

## 8. Security and tenant-isolation validation — before public deployment

- All object queries and mutations require authenticated tenant context.
- Cross-tenant object reads, links, and actions are rejected.
- Restricted properties are not returned in projections, link traversals, aggregations, exports, or semantic outputs.
- Action authorization is rechecked at execution time, including after previews.
- Agents and MCP tools use the same authorization service as REST APIs.
- No secret values or sensitive object properties are written to logs.

These are release-blocking checks, even if the full authorization implementation is scheduled after the initial persistence milestones.

## 9. Protégé compatibility validation — Phase 6

- Open `manufacturing.ttl` in Protégé and verify the four primary classes, `CriticalMachine`, datatype properties, object properties, inverses, and keys are visible.
- Export the ontology in a supported format, then import it through the platform.
- Confirm supported constructs become an **unpublished operational schema draft**.
- Confirm unsupported OWL axioms are reported, not discarded silently.
- Ensure no operational action definitions or access policies are inferred from OWL unless explicitly mapped.
- Verify the operational platform remains functional when Protégé/WebProtégé is unavailable.

## 10. Automated test organization

Recommended test files (adapt paths to actual repository structure):

```text
tests/
  fixtures/
    test_fixture_integrity.py
    test_shacl_conformance.py
    test_owl_reasoning.py
  integration/
    test_object_storage.py
    test_link_integrity.py
    test_query_api.py
    test_actions.py
    test_ingestion.py
    test_semantic_adapter.py
    test_protege_import.py
    test_authorization.py
  e2e/
    test_manufacturing_workflow.py
```

Mark tests requiring PostgreSQL, Open Ontologies, or WebProtégé as integration tests with explicit setup requirements. Do not silently skip them in CI without surfacing the reason. Add fixture integrity and SHACL validation to the earliest practical CI stage.

## 11. Required agent validation report

At the end of **each phase**, report:

```text
PHASE:
COMMIT / REVISION:
ENVIRONMENT:

CHECK                         RESULT       EVIDENCE
Turtle parsing                PASS/FAIL/NOT RUN  <command/output>
CSV identity and FK checks    PASS/FAIL/NOT RUN  <command/output>
SHACL conformance             PASS/FAIL/NOT RUN  <command/output>
OWL reasoning                 PASS/FAIL/NOT RUN  <command/output>
PostgreSQL integration        PASS/FAIL/NOT RUN  <test results>
FastAPI object queries        PASS/FAIL/NOT RUN  <test results>
Actions and reconciliation    PASS/FAIL/NOT RUN  <test results>
Polars ingestion              PASS/FAIL/NOT RUN  <test results>
Authorization                 PASS/FAIL/NOT RUN  <test results>
Protégé import/export         PASS/FAIL/NOT RUN  <test results>

FAILURES:
- ...

NOT-RUN REASONS:
- ...

KNOWN LIMITATIONS:
- ...

NEXT REQUIRED CHECKS:
- ...
```

Do not report **Phase 0 complete** without the static fixture checks and documented Open Ontologies integration findings. Do not report **MVP validated** without real PostgreSQL integration tests, end-to-end ingestion/query/action tests, and authorization tests.

## 12. Definition of validation success

Validation is complete for the initial manufacturing reference workflow when:

1. All Turtle fixtures parse.
2. CSV row counts, keys, and references are valid.
3. SHACL reports conformance for the RDF instance graph.
4. Deliberately invalid data produces expected validation failures.
5. PostgreSQL contains the expected 63 objects with valid relationships after ingestion.
6. Repeated ingestion is idempotent and reconciliation behaves as configured.
7. FastAPI returns the correct authorized objects, filters, and traversals.
8. A maintenance action creates consistent task and link records transactionally.
9. RDF exported from operational objects is semantically consistent with the fixture data.
10. The Open Ontologies integration has documented, executed compatibility tests; unsupported reasoning features are explicitly reported.
11. Protégé import/export works for the supported subset of OWL.
12. Security and tenant-isolation tests pass before public release.

**Validation policy:** Distinguish **PASS**, **FAIL**, **NOT RUN**, and **NOT SUPPORTED**. Never convert missing tooling, unsupported features, or skipped tests into a passing result.
