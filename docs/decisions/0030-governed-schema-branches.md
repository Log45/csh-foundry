# ADR 0030: Governed schema branches

Status: Accepted for Phase 9.

PostgreSQL branch records are development references within the canonical registry. Each branch
pins an immutable published base and immutable canonical revision snapshots; the mutable branch
record points to its head. UUID branch identity is independent of names. Lifecycle is ACTIVE to
MERGED or ABANDONED; terminal branches retain history and reject further edits.

Use existing schema:read/schema:write permissions, tenant composite foreign keys, governed security
transactions and ontology locks. Revision preconditions are mandatory. Merge previews bind exact
source/target revisions and a deterministic result hash; execution recomputes under the write lock.
Only branches sharing an explicit published base may merge initially. Source branches become MERGED;
there is no implicit rebase or arbitrary ancestry inference. Independent fields combine recursively;
ID-keyed collections match stable IDs; existing target definition order is preserved and new IDs
append in sorted order. Ordered action bindings/operations are atomic. Missing definitions
remain distinct from null values. Canonical cross-reference validation gates persistence.

Merge commits update a target branch and append provenance atomically. A separate explicit handoff
creates a new ordinary canonical draft through RegistryService. Breaking changes can live in a
branch/draft; approved migration plans are enforced by existing publication and activation, which
remain separate. No operational object/version/identity changes occur through branch operations.

Cross-definition canonical failures are explicit /$schema conflicts supporting a complete manual
canonical resolution or explicit target/source selection. Every result is revalidated. Comparison
uses the existing compatibility classifier on affected definition slices; no second classifier exists.
