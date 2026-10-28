# ADR 0011: Approved data migrations and atomic bounded activation

Status: Accepted for Phase 1

## Decision

Classify uncertain changes conservatively as breaking. Publication and activation of breaking
changes require an explicitly approved plan bound to base version and target content hash.
An approved plan is immutable. It contains only bounded full property replacements and expected
object revisions, never SQL/Python/eval. Even an empty plan requires explicit approval.
Validate all existing objects, uniqueness and forward links after applying migration updates in
the same transaction; only then switch active pointer and record activation actor/time/history.
Increment each object's revision on activation so stale clients cannot overwrite after schema change.
Failed validation, stale revisions, authorization denials or SQL constraints roll back every update.
The synchronous initial path caps activation at 1,000 objects / 5,000 links and plans at 1,000 updates;
larger migrations fail explicitly until a durable worker implementation is approved. No arbitrary
identity rewrite, object deletion, live branching or automatic multi-version data storage is added.

## Consequences

Preserve existing canonical identity, semantic adapter and fixture contracts.
Validate persistence on real PostgreSQL. Later phases require separate approval.
