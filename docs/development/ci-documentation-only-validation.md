# Documentation-only CI validation — 2026-11-21

Scope: the explicit request to plan and implement skipping expensive jobs for documentation-only
changes. This is CI maintenance, not a new product implementation phase. Validation ran locally
on macOS with Python 3.12.0, Git, the existing locked Python environment, actionlint 1.7.7 and
the checksum-verified Open Ontologies 2.1.0 executable. `fixtures/VALIDATION.md` was consulted.

## Plan implemented

1. Classify complete push, PR and merge-group Git comparisons before dependency setup.
2. Gate storage, static/contracts, SDK, Studio, backend shards and integration jobs on that decision.
3. Retain the required `CI / regression` job, rejecting failed detection and unintended skips.
4. Test real Git histories and both aggregate outcomes; update the CI guide and decision record.

The policy and rationale are in [ADR 0053](../decisions/0053-documentation-only-ci.md) and
[the CI guide](ci.md#documentation-only-changes). Documentation-only checks report expensive
suites as intentionally NOT RUN. No domain authorization, execution budget or test-report
acceptance rule changed.

## Files created or modified

- `.github/workflows/ci.yaml`: lightweight scope job, conditional expensive jobs, strict aggregate.
- `scripts/ci_changes.py`: standard-library detector, complete Git comparisons and conservative fallback.
- `services/api/tests/test_ci_changes.py`: actual Git histories, CLI outputs and workflow wiring.
- `services/api/tests/test_ci_reports.py`: aggregate success/failure/cancellation/skip policy checks.
- `README.md`, `docs/development/ci.md`, `docs/decisions/0050-ci-regression-scope.md`:
  current behavior and link to the superseding scoped decision.
- `docs/decisions/0053-documentation-only-ci.md`: plan, operating decision and tradeoffs.
- This validation report.

Database migrations: **none**. External resource or repository-settings changes: **none**.

## Executed checks

Commands ran from the repository root. `UV_CACHE_DIR` pointed at a disposable temporary cache.

| Check | Result | Evidence |
| --- | --- | --- |
| CI change-detection and aggregate policy | PASS | `uv run --frozen pytest services/api/tests/test_ci_changes.py services/api/tests/test_ci_reports.py -ra`: **132 passed**, zero skips, 14.86 seconds |
| Push, PR and merge-group comparisons | PASS | Real temporary Git repositories cover docs-only and mixed changes, earlier PR code followed by docs, unrelated base advancement, renames, deletions and unusual filenames |
| Conservative fallback and large diffs | PASS | New refs, invalid/missing revisions, malformed events, empty comparisons and manual/unknown events require full CI; 350 documentation paths do not hide a code change |
| Required aggregate behavior | PASS | Executes the workflow's actual inline gate with dependency results; only successful full regression or explicitly confirmed documentation skips pass; failures, cancellations and unintended results fail |
| All workflow syntax and expressions | PASS | actionlint 1.7.7 on ci.yaml, ci-storage.yaml, ci-suite.yaml, acceptance.yaml and release.yaml |
| Python lint and formatting | PASS | `uv run --frozen ruff check .`; `uv run --frozen ruff format --check .`: 341 files formatted |
| Python types | PASS | `uv run --frozen mypy`: 171 source files |
| Turtle parsing, CSV identities/FKs and RDF consistency | PASS | `test_fixtures.py` in the fixture/semantic invocation below |
| Normalized SHACL and negative fixtures | PASS | Fixture/semantic invocation: **16 passed**, one strict expected failure, zero skips |
| Open Ontologies SHACL and OWL reasoning | PASS | `OPEN_ONTOLOGIES_BIN="$PWD/.external/open-ontologies" uv run --frozen pytest services/api/tests/test_fixtures.py services/api/tests/test_semantic.py -ra`; extended profile infers the three expected CriticalMachines |
| Raw pySHACL conformance | FAIL — expected failure | Preserved strict RDFLib simple/string-term incompatibility; not counted as PASS |
| CriticalMachine inference with base owl-rl | NOT SUPPORTED | The executed profile check confirms no inferred CriticalMachine instances; owl-rl-ext provides this fixture's inference |
| Full PostgreSQL, ingestion, action, authorization, storage and browser suites | NOT RUN | Scoped CI-control change; local policy tests use temporary Git repositories, not application services. Full regression remains selected for this implementation's workflow/code changes |
| Interactive Protégé | NOT RUN | No authoring or interchange changes; no GUI session started |
| Hosted GitHub scheduling and branch protection | NOT RUN | No push, workflow dispatch or repository settings mutation performed |

## Limitations and next check

Confirm the first hosted code-change run executes all existing regression jobs, then confirm a
subsequent documentation-only PR skips expensive jobs and receives a terminal successful aggregate.
Manual dispatch must still run full regression. New-branch pushes conservatively run full regression.
Code changes still trigger both push and PR events when both apply. Full-history checkout and the
final aggregate remain small costs on documentation-only events.

Keep `CI / regression` as the required check. The repository's external ruleset was not inspected
or modified. Scheduled acceptance and release behavior remain unchanged; production remains
subject to PLANS.md §23B. No further product phase is recommended or authorized by this task.
