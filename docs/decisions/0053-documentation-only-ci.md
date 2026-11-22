# 0053 — Skip expensive regression for confirmed documentation-only changes

Status: accepted for the explicit documentation-only CI request (2026-11-21).

## Plan and decision

1. Start the existing workflow on every supported event and classify its Git comparison in
   a lightweight job, using an explicit documentation allowlist.
2. Skip storage builds and all expensive regression jobs only when every changed path is
   documentation. Run full regression on other or uncertain comparisons.
3. Preserve `CI / regression` as an always-running aggregate. Require successful detection
   and exactly the intended dependency results for the selected path.
4. Test actual Git histories, CLI outputs, workflow wiring and aggregate behavior; document
   the event comparisons and the limits of local verification.

This supersedes ADR 0050 only for documentation-only event execution. Ordinary code changes
retain the complete regression scope, real dependency setup, strict JUnit reporting, no
whole-test retries and the separate extended acceptance/release workflows.

GitHub workflow-level path filters can leave required checks pending. Instead, all expensive
jobs depend on `changes.outputs.run_ci`, while the aggregate uses `always()`. Documentation
skips require `changes.result=success`, `run_ci=false`, and `skipped` for every expensive job.
Full regression requires each expensive job to succeed. Missing or failed detection, failure,
cancellation and unexpected skipping cannot produce a passing gate.

## Classification and tradeoffs

Recognize files named README.md, CHANGELOG.md and AGENTS.md; root PLANS.md;
fixtures/VALIDATION.md; and `.md` files under docs/. Other files, including documentation
assets, MDX and executable examples, conservatively run the full suite. The
[CI guide](../development/ci.md#documentation-only-changes) defines the operating contract.

Use complete local Git history instead of a changed-files API, avoiding pagination/truncation
and extra API permissions. Pushes use before/after; PRs use merge-base/head; merge groups use
base/head. Disable rename detection so both sides are classified, and delimit filenames by
NUL. Missing or ambiguous history and malformed/unknown events run full CI. Manual dispatch
also runs full CI. A new branch runs full CI because no safe before commit is available.

Every event still pays for a checkout/detection job and the final aggregate. Code changes
still have separate push and PR runs. Branch protection must require the aggregate, whose
name is preserved; individual job requirements may need operator review if configured.
No repository settings or external resources are modified by this change.

The workflow and its policy change in this implementation, so its own push will run full
CI. Hosted scheduling and branch-protection acceptance require an actual GitHub run;
local tests and actionlint do not establish those results.

No database migrations, domain runtime changes or new roadmap subsystem are introduced.
