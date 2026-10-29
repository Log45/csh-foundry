# ADR 0026: Fenced semantic jobs and certificate-backed inferred facts

Status: Accepted for Phase 5

Reuse Phase 4 PostgreSQL SKIP LOCKED, database-clock leases, random tokens, initiating-principal
restriction, three-claim recovery and bounded-runner patterns. Keep the semantic job row as its job
registry, with immutable request and append-only-in-practice bounded claim/error/completion history.
Schema/input/policy checks occur at submission, preparation and completion. Engine execution occurs
outside PostgreSQL transactions and ontology locks; results/artifacts/facts/job completion commit
atomically only while the current token and lease remain valid. Cancellation fences outstanding work.
Terminal job state, artifact/fact content and approval events are protected by PostgreSQL triggers.

The pinned CLI has no --version flag. Verify the release bytes against committed trusted SHA256
identities; don't claim a version from an arbitrary binary. Use a 30-second subprocess deadline;
60-second lease and explicit renewal. Timeout/unavailability retry up to three claims; other errors
are durable failures. Operators schedule one-job CLI invocations. Hard OS memory/disk isolation,
production admission/backoff and delegated workers are deferred.

Use native reason --certificate and save in the existing batch invocation. Persist certificate
assertions, rule/conclusion/premise derivations and scope. Derived statements come from the engine's
certificate conclusions, not a second reasoner or type-only query. Canonicalize result blank nodes
with RDFLib graph canonicalization and result-local stable skolem IRIs; certificate terms remain
original engine terms. Proof generation
is supported; independent Lean checking is NOT RUN because no checker exists on this host. No proof
is labeled verified. Native diff reports exact graph additions/removals; it is not operational
migration approval or an entailment-preservation proof. No inferred statement promotes operational
objects, revisions, source ownership, links or actions.
