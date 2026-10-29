# Phase 3 report — Governed Actions, Transactions, Audit and Edit Reconciliation

PHASE: **3 only**. Date: 2026-10-28 (client timezone America/New_York).
Base revision: `644601ebce20bdcbe9f34250ff9b62d88273bd63`; changes remain uncommitted.
Environment: macOS ARM64, Python 3.12.0, locked uv dependencies, Docker PostgreSQL 17.6,
existing Java/Maven and pinned Open Ontologies 2.1.0. Phase 4 is not implemented.

## Implementation summary

Implemented typed inert actions in the existing canonical schema; strict parameters and object
identity parameters; deterministic parameter/literal/object/property references; preconditions;
transactional object and relationship operations through existing services; execution-time
permissions; optimistic concurrency; pure advisory preview; durable idempotency and committed
history; redacted append-only audit; transactional outbox; bounded leased notification delivery;
source/pipeline/user/action ownership and deterministic source/edit reconciliation. Added versioned
FastAPI preview/execute/history/audit endpoints, four manufacturing definitions, tests, measurements
and documentation. No operational state moves outside PostgreSQL.

## Files created or modified

| Area | Significant files |
|---|---|
| Canonical language | `packages/ontology-schema/src/ontology_schema/models.py`; regenerated `ontologies/schemas/ontology.schema.json` |
| Action engine/API | New `services/api/src/ontology_platform/actions/{contracts,service,routes,limits,deadline}.py`; updated `main.py` |
| Shared transactions/CRUD | Updated `db/governance.py` for caller-owned session participation; `objects/service.py` for user ownership and existing-service composition |
| Persistence | Updated `db/models.py`; new Alembic `0006_actions_actions.py`, `0007_edit_provenance_edit_provenance.py` |
| Reconciliation/delivery | New `edits/service.py`, `jobs/webhooks.py` inside the modular API package |
| Examples | New `ontologies/examples/manufacturing-actions.json`; canonical fixture vocabulary unchanged |
| Tests | New `services/api/tests/test_action_models.py`, `test_actions.py`; existing regression tests preserved |
| Developer checks | New `scripts/benchmark_actions.py`, `smoke_actions.py`, `smoke_action_container.py` |
| Decisions/docs | New ADRs 0018–0020, `docs/api/actions.md`, this report, `docs/development/phase-4.md`; updated README/API/architecture/migration references |
| Evidence | `docs/architecture/evidence/phase-3/` contains baseline/final validation, HTTP/container/Protégé and benchmark output |

Package-relative source paths above are under `services/api/src/ontology_platform/`. No dependency,
semantic engine pin/adapter, AGENTS.md, PLANS.md or supplied fixture was changed. No external webhook
was contacted or deployed by validation. The development PostgreSQL migration was advanced without
replacing existing tenant data. Smoke containers/processes and disposable schemas are cleaned up.

## Action definition language

The existing ActionTypeDefinition/ActionOperation contract is extended, retaining CREATE_OBJECT,
UPDATE_OBJECT, DELETE_OBJECT, CREATE_LINK and DELETE_LINK with the existing `target` field.
Target-only legacy declarations remain readable and explicitly non-executable. No second action
format, executable metadata, dynamic SQL, expression evaluator, scripts, loops or HTTP operation
is introduced.

Parameters reuse canonical strict property validation: string/integer/float/decimal/boolean/date/
timestamp/UUID, enums, required/null/default constraints, existing JSON/array support. Existing
object identities are typed with `object_type_id` on canonical string/UUID parameters; they resolve
inside server-derived tenant/ontology context. Decimal/date/timestamp/UUID representations remain
strings. New object IDs use regular parameters, with canonical property identity validation.

Value references are discriminated literal/parameter/object references. Object references return
an ID or one explicitly authorized property, never an unrestricted document. Existing bindings
resolve in declaration order, preconditions next, operations in list order, created bindings only
after their inputs. Forward/self/circular references, unknown types/links/parameters/properties,
wrong endpoint types, malformed operation fields and incompatible property inputs are rejected.

Preconditions include EXISTS/NOT_EXISTS, PROPERTY_EQUALS, REVISION_EQUALS, LINK_EXISTS/
LINK_NOT_EXISTS and PARAMETER_PRESENT. Active schema and tenant membership are independently
resolved. Every operational mutation uses existing canonical validation and relational constraints.

| Limit | Value |
|---|---|
| Raw request and canonical action definition | 64 KiB each |
| Parameters | 32 |
| Operations / preconditions | 64 each |
| Reference slots | 64 total, conservatively counting bindings/created bindings/typed identity parameters |
| Properties per operation | 64 |
| Idempotency key | 1–128 characters, required for execution |
| Action and preview SQL work | Three-second elapsed budget with diminishing per-statement PostgreSQL timeouts |
| Execution history | Limit 1–100, offset 0–10,000 |

Savepoint recovery is allowed after budget expiry so cleanup cannot be blocked by timeout setup.
The time budget is not a hard OS/process deadline for connection acquisition, arbitrary trusted
policy code or uncertain commit acknowledgement. Full contracts/examples/errors/limits are in
[the action API](../api/actions.md).

## Transaction guarantees

ActionExecutionService takes the existing exclusive ontology lock and resolves approved active
metadata inside one PostgreSQL transaction. Existing ObjectService methods participate in the
caller's session and retain their original public transaction-owning behavior. Canonical property
validation/defaults/identity, uniqueness, expected revisions, endpoint FKs and cardinality are reused.
Object/link changes, revisions, execution/idempotency, audits, action overlays and outbox commit
or roll back together. SQL or late-operation failure leaves no partial action effects.

Ontology-wide write serialization coordinates idempotency, unique properties, link cardinality,
schema activation and actions. SQL revision predicates remain in place. Query shared locks and
all Phase 0–2 behavior are retained. No independent mutation implementation, new database, broker,
workflow engine, microservice or Rust accelerator is introduced.

## Authorization

The explicit principal and tenant remain server-derived. Calls enforce action invocation, referenced
object reads, object/link mutations, endpoint association and property read/update permissions.
Create defaults and properties removed by deletion are authorized too. History checks returned
records, and audit requires a separate permission. A successful preview grants no future authority.
Tests revoke permissions between preview and execute and exercise principal/tenant denials.

The existing `Authorizer.require` protocol expresses additional operation names without a new
identity system: action:invoke/history/audit, property:read/update, edit:reconcile/override/resolve,
outbox:deliver. Source overrides require explicit override permission. Trusted local administration
remains opt-in and tenant-scoped; production OIDC/RBAC/ABAC is intentionally outside this phase.

## Preview semantics

Preview runs the same mutations/validation in an always-rolled-back PostgreSQL savepoint. It stages
no durable execution/audit/outbox records, performs no HTTP and leaves object/link/overlay state
and revisions unchanged. UUID IDs avoid sequence effects. Even an internally supplied execute
request/key cannot turn preview into an idempotent replay. Errors return structured validation/
authorization/conflict responses. Preview can contend on the same write lock; it is advisory and
execution independently rechecks everything. Tests include a foreign-key failure after an earlier
mutation and verify savepoint recovery and complete rollback.

## Idempotency

Committed execution rows serve as the durable idempotency registry. SHA256 key uniqueness is scoped
to tenant/principal/ontology, with normalized action/parameter request digest and a complete fingerprint
including definition hash and active schema version. Raw keys and parameters are not stored. Missing
parameter defaults normalize identically to explicit identical defaults.

Concurrent identical requests commit once and return one original result; conflicting keys/parameters
cannot both succeed. Retries use the original published definition and return its committed result
across new service instances or active schema changes. Invocation/history permissions are rechecked.
A new key targets the currently active definition. Failed rollbacks retain no reservation; retry
after correction is allowed. For timeouts/lost responses/uncertain commits, retry the same key first.
No process-local coordination dictionary or lock provides these guarantees.

## Audit and history

History records committed execution ID, tenant/ontology, definition hash, schema version, principal,
request/key/fingerprint hashes, timestamp, status and structured ordered change result. Failed
requests return errors and have no durable failed-execution row. Audit records actor/time/execution,
object/link identities, operation, previous/new revisions and redacted representations consisting
of changed property names. No raw parameters, secrets or before/after property values are retained.

Database triggers reject execution/audit UPDATE/DELETE, and no ordinary mutation API exists for
those records. This is append-only application history, not tamper-proof or externally verified
storage; database owners can bypass triggers. Execution results retain operation order, while audit
rows at the same transaction timestamp are UUID ordered. Retention is indefinite for execution/
idempotency/audit in this foundation, with no automatic purge. Future retention/redaction requires
an explicit coordinated privileged design so retry/history guarantees are not silently broken.

## Transactional outbox and webhooks

One action.committed event commits with each action. Event rows include tenant/ontology, execution,
UUID event ID, minimal identifier-only payload, timestamp, delivery status/attempt/retry/error and
lease metadata. Failed actions/retries create no duplicate committed events.

The minimal runner claims due work through SKIP LOCKED in a short tenant-authorized transaction,
records UNKNOWN attempt history and commits a 60-second lease before HTTP. A durable UUID claim
token rejects stale completions. Socket connect/read timeout is five seconds. 2xx succeeds;
429/5xx and transport failures back off 2,4,8,16 seconds, with at most five claims. Permanent
failure/exhaustion is DEAD. Expired claims survive worker restart, including an abandoned fifth
claim. Stable event IDs support consumer deduplication; delivery is at least once, never exactly once.

The destination is server-configured and fixed per event on its first claim. HTTPS/443 only,
no credentials/query/fragment, public DNS addresses only, validated-address socket pinning,
original-hostname TLS verification and no redirects/proxies/response-body retention. DNS resolver
timing is an explicit limit on whole-attempt deadlines. No action parameter selects a URL. The CLI
processes at most 100 currently due events; production scheduling, signing, fan-out and external
pre-commit hooks are deferred. Network outcomes in automated tests are injected; actual external
recipient availability is NOT RUN and no external resources were modified.

## Reconciliation

Persist per-property source/pipeline/user/action ownership, source/resolved values, updater/time,
revision/schema and optional action execution reference. Direct CRUD edits are user-owned; action
edits reference their execution. Legacy data without provenance is conservatively protected.

Default edit_wins accepts same-source-owned changes and preserves governed edits, including after
an equal source observation. source_wins explicitly transfers ownership with edit:override.
Different source identities cannot silently take over another source's properties. reject/manual
persist deterministic conflicts and apply no partial properties/ownership from the source update.
Explicit acceptance/preservation rechecks current revisions/schema/permissions and records resolver/
time. Incompatible old overlays require governed rebasing; older-schema conflicts require refresh.

Only resolved property changes increment object revisions. Preserved observations change provenance
without changing visible state or immutable action history/audit. This is a governed service framework
for Phase 4, not a production ingestion pipeline, source snapshot store or implicit deletion system.

Manufacturing actions use actual fields/enums/links: UpdateMachineStatus; ScheduleMaintenance with
all task properties plus taskForMachine and assignedEmployee; CompleteMaintenance IN_PROGRESS →
COMPLETED; AssignTask for an unassigned task. Existing assignment conflicts rather than silently
reassigning. No extra fixture field is invented.

## Database migrations

| Revision | Changes / rollback |
|---|---|
| 0006_actions | Six tables: action_executions (also idempotency registry), action_audit_events, outbox_events, webhook_attempts, edit_overlays, reconciliation_conflicts; tenant/schema/execution/event FKs, uniqueness/check constraints and lookup indexes; append-only execution/audit triggers. Downgrade removes these Phase 3 structures and history, preserving Phase 0–2 objects. |
| 0007_edit_provenance | Adds updater/time and conflict resolver/time. Existing rows receive explicit legacy-unknown updater. Downgrade drops only these provenance columns. |

Both migrations use bounded DDL lock/statement settings. Disposable-schema tests exercise clean
upgrade, Phase 2 → head, head → Phase 2/base → head, constraints, metadata drift and preservation of
existing tenants/objects/properties/revisions. Downgrades are destructive to Phase 3 history and
are exercised only in disposable schemas. Local development is at 0007_edit_provenance; existing
operational rows are retained. No migration loads sample data or silently changes published metadata.

## Performance

Small local samples in a private migrated schema, with three initial objects and eleven tasks;
no production scale/percentile claim. The final benchmark ran after the regression suite. Evidence
includes raw samples, transaction durations, PostgreSQL version, a history EXPLAIN ANALYZE/BUFFERS
plan and observed lock waits in [action-benchmarks.json](../architecture/evidence/phase-3/action-benchmarks.json).

| Workload | Measured wall time |
|---|---:|
| Single object action only, median of 10 | 32.900 ms |
| Same action including separate revision read, median of 10 | 37.598 ms |
| Create task plus two links, median of 10 | 115.679 ms |
| Two concurrent updates | 67.856 ms; one revision conflict |
| Two concurrent identical retries | 44.450 ms; same execution ID |
| Relationship assignment, one sample | 78.686 ms |
| Query after action workload, median of 5 | 5.750 ms |
| Actual query and action launched concurrently | Action 52.606 ms; query 7.341 ms; both succeeded |
| Writer overlapping a controlled 100 ms shared query lock hold | 188.044 ms |
| Outbox claim/completion with injected successful transport, median of 5 | 20.186 ms |

The ten single-object action transactions measured a median of
32.684 ms from begin through completion.
Median of all 60 observed transactions (including reads/setup as well as actions):
16.565 ms. These are not production percentiles. The controlled writer's scoped
PostgreSQL activity sample showed a transactionid Lock wait with one blocker; its ontology lock
acquisition took 129.360 ms including the lock query round trip. This measures
acquisition/contended wait together, not a database-internal pure wait timer. The small scoped
history plan executed in 0.102 ms.
No measured evidence justifies replacing ontology-wide locks or adding speculative infrastructure/
indexes. Diminishing statement budgets add round trips; correctness is prioritized over speculative
optimization. The runner measurement excludes DNS/TLS/HTTP latency.

## Validation results

Before implementation, the complete existing configured runner passed: **154 passed, one expected
raw pySHACL failure, no skips**; Ruff lint/format, strict mypy and Alembic check passed. The existing
Docker image built and Protégé-compatible OWLAPI harness passed as additional baseline checks.
No unexpected preexisting failure was observed. The raw pySHACL failure, base owl-rl limitation,
Starlette/httpx deprecation and Java Unsafe warning predate Phase 3.

The final configured runner passed: **238 passed, 1 xfailed, no skips**, 239 collected,
85.02 seconds. This includes 84 new cases (28 language/model cases and 56 action/integration
cases). Ruff lint/format, strict mypy and Alembic check passed. No unexpected failure remains.
See [final validation evidence](../architecture/evidence/phase-3/validation.txt).

| Check | Result | Evidence / scope |
|---|---|---|
| Full configured pytest regression | PASS | 238 passed / 1 preserved expected failure / no skips; 239 collected |
| Ruff lint / format / strict mypy | PASS | Final runner preamble; 82 formatted files / 53 source files checked |
| Alembic upgrade/downgrade/drift | PASS | Configured PostgreSQL suites and final alembic check; data preservation tests |
| Canonical/action definitions, strict types, references and limits | PASS | New unit tests plus existing canonical regressions |
| Real PostgreSQL action transactions and concurrency | PASS | Revision/idempotency/cardinality races, unique validation, multi-operation and FK rollback |
| Preview purity, failed savepoint cleanup and revalidation | PASS | No state/revision/history/audit/outbox changes; execute-key preview cannot replay |
| Execution/property/link/history/audit authorization and tenants | PASS | Local identity denials, mutation denials, policy changes, existing cross-tenant regressions |
| Durable idempotency/defaults/schema-change retries | PASS | New service instances, racing requests, conflicting reuse and failed request retry |
| Audit/outbox commit, immutable history, tenant ownership | PASS | Real FK/trigger/rollback/dedup checks |
| Webhook retry/timeout/permanent failure/claim/restart/dedup/SSRF | PASS | Real PostgreSQL claims/history with injected network outcomes; private DNS checks |
| Source/edit reconciliation, provenance and resolution | PASS | Ownership/source policies, equal-observation protection, revisions/schema/conflict behavior |
| Actual host Uvicorn/HTTP | PASS | smoke_actions.py: health/OpenAPI, query/cursor/traversal/aggregate, actions/history/audit/schedule |
| Docker build and startup smoke | PASS | Final image; PostgreSQL readiness/OpenAPI, absent-identity action rejection |
| Turtle/CSV/RDF identities, normalized SHACL/negative cases | PASS | Existing fixture regression suite; files preserved |
| Raw unchanged pySHACL conformance | FAIL | Preserved documented expected failure; never counted as raw conformance PASS |
| Open Ontologies parse/raw SHACL/diagnostics and owl-rl-ext inference | PASS | Existing pinned semantic tests executed with configured engine |
| Equivalent inference with base owl-rl | NOT SUPPORTED | Existing executed profile comparison preserves missing fixture-rule limitation |
| Protégé-compatible file import/export | PASS | OWLAPI 4.5.29 harness re-run; existing extra xsd:date declaration remains |
| Fixture/pin/adapter/AGENTS/PLANS integrity | PASS | git diff --exit-code against supplied fixtures and unchanged inputs |
| Actual external webhook recipient / signing / production scheduler | NOT RUN | Injected transports only; no external writes; later production orchestration |
| Protégé GUI / deployed WebProtégé | NOT RUN | Existing file harness only; expansion not approved |
| GitHub-hosted CI | NOT RUN | No push/remote run requested; equivalent local runner executed |
| Production Polars ingestion / semantic materialization / OIDC / Studio / SDK | NOT RUN | Outside approved Phase 3 |

Intermediate development failures included an updated canonical JSON-schema snapshot mismatch,
new-test helper/import errors, and JSONB conflict-value binding; they were corrected without
weakening existing regression tests. The savepoint/timeout recovery edge case was corrected and
covered by a real PostgreSQL FK failure test. No missing tool or skipped check is represented as PASS.

## Known limitations

1. Trusted local identity only; public/production deployment still requires the security phase.
2. Retained coarse ontology serialization; previews also contend. Existing activation limits
   (1,000 objects/5,000 links) remain, and action limits intentionally favor small business mutations.
3. Committed history only; failed execution attempts are structured errors rather than durable rows.
   Audit values are deliberately redacted, and this storage is not tamper-proof.
4. One post-commit category/destination, at-least-once delivery, operator-invoked bounded runner;
   no production scheduler/fan-out/signing/pre-commit external hooks or dead-letter replay UI.
   DNS timing and uncertain HTTP/commit acknowledgements prevent hard whole-process deadlines.
5. Reconciliation is service-only; full source snapshots, connectors, mapping/staging and ingestion
   jobs belong to Phase 4. Existing legacy values need explicit release before source ownership.
6. AssignTask initially assigns an unassigned task; reassignment requires an approved explicit
   delete/create-link action. No additional workflow fields or edge minima are invented.
7. History offset pagination is bounded and not a cross-request snapshot. Successful keys/history
   have indefinite retention; future coordinated expiry/redaction requires a separate design.
8. Raw pySHACL mismatch, base-profile inference limitation and existing dependency warnings remain.
   Actual external recipient behavior and production-scale throughput are not validated.

## Architectural decisions

ADRs 0018–0020 record the inert canonical language/service composition, advisory rollback preview,
retained ontology locking and time budgets; durable normalized retry/history/redaction/leased outbox;
and conservative source/edit ownership/conflict resolution. PostgreSQL is authoritative; no
semantic integration, infrastructure, frontend or SDK scope expansion is included.

## Phase 4 readiness and recommended tasks

The Phase 3 foundation is suitable for Phase 4 planning within the documented local-development,
transaction/activation and reconciliation bounds, after review and explicit approval. This does
not claim production readiness or a fully validated ingestion MVP. No Phase 4 implementation was
started. Follow [the ordered Phase 4 checklist](phase-4.md): typed sources/mappings and ownership,
small tenant-safe persistence, bounded Polars connectors/staging, governed deterministic upserts,
reconciliation, durable PostgreSQL jobs, authorized APIs, manufacturing end-to-end tests, measured
contention and full validation/reporting. Stop here until that phase is approved.
