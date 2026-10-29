# Phase 3 governed actions

Actions execute only from the active published ontology snapshot. REST does not accept action
code or definitions. Draft/publish/activate metadata through the existing registry APIs first.
`ontologies/examples/manufacturing-actions.json` supplies four definitions to include in a draft's
`action_types`; it does not change the canonical manufacturing fixtures or automatically activate
anything. Action changes retain the registry's conservative breaking-change approval rules.

All routes are under `/api/v1/ontologies/{ontology_id}/actions`, require the server-configured
trusted local principal and enforce tenant scope. Client headers/parameters cannot select identity.

| Route | Contract |
|---|---|
| POST `/{action_id}/preview` | ActionRequest → ActionResult |
| POST `/{action_id}/execute` | ExecuteRequest → ActionResult |
| GET `/executions?limit=50&offset=0` | HistoryPage; limit 1–100, offset 0–10,000 |
| GET `/executions/{execution_id}` | ExecutionView |
| GET `/executions/{execution_id}/audit` | At most 64 redacted Change records |

Execute example (omit `idempotency_key` for preview):

```json
{
  "idempotency_key": "machine-stop-001",
  "parameters": {
    "machineId": "MCH-001",
    "newStatus": "STOPPED",
    "expectedRevision": 1
  }
}
```

Responses identify execution/action/schema versions and ordered proposed/committed changes,
including identities, affected property names and previous/new revisions. They omit property
values. Preview returns `advisory:true` and no execution ID. Invalid previews use the same structured
error envelope as execution; they do not persist a failed preview record. History uses deterministic
creation-time/UUID ordering and bounded offset pagination, not a cross-request snapshot.

## Inert definition language

The canonical `ActionTypeDefinition` and `ActionOperation` are extended in place. The operation
names remain `CREATE_OBJECT`, `UPDATE_OBJECT`, `DELETE_OBJECT`, `CREATE_LINK`, `DELETE_LINK`, with
`target` naming a canonical object/link type. Older target-only Phase 0 declarations remain readable
but cannot execute. Existing published snapshots are never rewritten to adopt new defaults.

Parameters reuse `ParameterDefinition`/`PropertyDefinition` strict canonical validation, including
required/default/nullability/enum/precision/scale constraints. Scalar types are string, integer,
float, decimal, boolean, date, timestamp and UUID; existing JSON/array contracts remain supported.
Dates, decimals, timestamps and UUIDs retain canonical string representation. Integer/float/bool
are distinct JSON types. `object_type_id` on a string/UUID parameter declares an existing object
identity inside the authenticated tenant and requested ontology; existence/read permission is
checked against current state. New identities use ordinary parameters and create operations.
Integer primary keys still use the canonical string operational object ID for binding.

Value references have exactly one discriminated representation:

```json
{"kind":"literal","value":"STOPPED"}
{"kind":"parameter","parameter":"newStatus"}
{"kind":"object","binding":"machine"}
{"kind":"object","binding":"machine","property":"operationalStatus"}
```

Object references without `property` return only the stable ID. Property references require explicit
read permission. No whole-object expansion, arithmetic, arbitrary expression, Python, SQL, HTTP,
loops, conditional execution or unrestricted graph traversal exists.

`bindings` declare named existing-object identities using `id`, `object_type`, `object_id`.
Bindings resolve in declaration order; an ID may refer to parameters, literals or a previously
resolved object's property. A binding can represent an absent identity for NOT_EXISTS checks.
Preconditions evaluate next, against current database state. Operations then execute in list order.
Create operations publish a new binding only after resolving their own inputs; subsequent operations
can reference it. Forward/self/circular references, duplicate bindings and unknown metadata are
rejected. Static checks validate referenced types/properties/links and compatible property inputs;
canonical property and relational validation run again against current state at execution.

Object create requires `binding`, `object_id`, `properties`; update requires `binding`,
`expected_version`, `properties`; delete requires `binding`, `expected_version`. `expected_version`
is a value reference resolving to a positive integer. Relationship operations require `source` and
`destination` binding names matching the forward link's canonical endpoint types. Remove existing
links explicitly before deleting endpoints. Canonical cardinality enforces maxima, as in Phase 1;
no required minimum-edge constraint is invented.

Precondition types are EXISTS, NOT_EXISTS (binding); PROPERTY_EQUALS (binding/property/value);
REVISION_EQUALS (binding/value); LINK_EXISTS, LINK_NOT_EXISTS (link/source/target); PARAMETER_PRESENT
(parameter). Field combinations are strictly checked. Active schema/type resolution and tenant-safe
identity lookup enforce ontology membership independently of preconditions. Property equality uses
strict canonical JSON representation; it does not coerce numeric or temporal spellings.

| Bound | Maximum |
|---|---|
| Raw action request / canonical definition | 65,536 UTF-8 bytes each |
| Parameters | 32 |
| Operations / preconditions | 64 each |
| Object reference slots | 64 including bindings, created bindings and typed identity parameters; duplicate slots count conservatively |
| Properties per operation | 64 |
| Idempotency key | 128 characters, required for execute |
| Action/preview work | 3-second elapsed budget; diminishing PostgreSQL statement timeout before each statement, plus operation checks |
| Preview complexity | Same limits and service operations as execute |

The time budget applies to database/operation work and rolls back on expiry. Connection acquisition,
authorizer implementations, network/commit acknowledgement and OS scheduling cannot be promised
as a hard process-level deadline. A lost commit acknowledgement is an uncertain result: retry the
same key. The request stream is bounded before FastAPI parses action JSON; other existing endpoints
retain their existing limits.

## Transactions, preview and authorization

The service owns one PostgreSQL transaction, takes the retained ontology FOR UPDATE lock, resolves
the active snapshot, checks preconditions and calls existing object/link services using the caller's
session. Object uniqueness, endpoint FKs, cardinality, stable identity, defaults and revision checks
are reused. Mutations, execution/idempotency history, audits, overlays and outbox event commit
atomically. Failed transactions leave none of those action effects. A database constraint or timeout
cannot produce a partial action. Activation uses the same ontology lock, so cannot change schema
mid-action. Queries retain their existing shared lock.

Preview uses the real service path in an always-rolled-back savepoint, including on errors. It creates
no execution/audit/outbox records and performs no HTTP. Object/link/overlay changes and revisions
are rolled back; UUID identities avoid sequence consumption. It briefly takes the write lock and
can contend with queries/actions. Preview is advisory: execute independently resolves, authorizes
and validates current state.

Authorization calls cover `action:invoke`, referenced `object:read`, existing object/link mutations,
`property:read` references/preconditions and `property:update` for modifications. Create defaults
and every deleted property are included. Relationship endpoints retain `object:link` checks.
History/audit require `action:history`/`action:audit`; history checks each returned record. No
property values are present in history or replay results. Policy providers must implement these
operations coherently with existing CRUD/query grants. The local provider remains an own-tenant
administrator, disabled unless explicitly configured; production OIDC/policy administration is not
part of Phase 3.

Errors retain `{ "error": {"code":"...", "message":"..."} }`: invalid_action/invalid_properties
422; authentication 401; forbidden 403; missing resource 404; revision_conflict,
precondition_failed, cardinality_conflict, unique_conflict, idempotency_conflict and persistence
constraint conflicts 409. Raw oversized requests return 413. Deadline/database failures return
sanitized 503 responses; database details and parameter values are not returned.

## Durable idempotency and history

A key is scoped to tenant, principal and ontology, with uniqueness on its SHA256 digest. It cannot
be reused for a different action. Its request digest includes action identity and normalized
parameters (including applied defaults). The execution fingerprint additionally includes tenant,
principal, ontology, definition hash and schema version. Definition hashes are action versions.
Raw keys and parameters are not retained in history.

The ontology lock serializes competing requests; PostgreSQL uniqueness provides a durable second
guard. An identical retry returns the original committed result, including after process restart,
schema activation, action retirement or deletion of an affected object. Invocation/history access
is checked anew. Retried parameters normalize against the original immutable published definition;
the retry does not execute the new active definition. Different normalized parameters conflict.
An explicitly new key targets the current active schema. Clients needing different effects after
activation must use a new key and current revisions.

Rolled-back failures leave no committed execution/key reservation, audit or event. The same key may
be retried after correcting a failure; successful prior keys remain bound indefinitely. Timeouts or
lost responses may have an uncertain commit outcome: always retry the same key and request before
considering a new key. Durable history contains committed executions; failed attempts are structured
request errors, not durable failed-execution rows.

Execution and audit tables reject UPDATE/DELETE through PostgreSQL triggers and have no mutation
API. Audit captures actor, execution, timestamp, ordered-operation details, identities, revisions
and approved redacted representations (changed property names, no before/after values). Execution
results preserve operation order; audit rows sharing a timestamp are UUID ordered. This is
append-only application history, not tamper-proof or externally verifiable storage. Database owners
can bypass triggers. No raw secrets, HTTP bodies, source values or parameters enter audit/outbox.

Retention policy: keep execution/key/audit records indefinitely in this foundation so retries and
history remain valid. No automatic purge or TTL exists. Backups and operator access must protect
hashes and identities too. Any future retention/redaction job must explicitly coordinate idempotency
expiry, FKs and privileged trigger handling; it requires separate design/approval. Source values in
reconciliation tables are operational provenance, not public audit payloads.

## Outbox delivery

Each committed action inserts one `action.committed` event with execution/action/schema identifiers.
The event's tenant/ontology ownership and execution FK commit with the action. Webhooks never run
from the action handler. The bounded runner processes one due event per call or up to 100 via CLI:

```bash
uv run python -m ontology_platform.jobs.webhooks \
  --ontology manufacturing --destination https://receiver.example/events --max-events 10
```

Configure the trusted local principal on the server as for the API; the runner requires
`outbox:deliver`. The destination is administrative configuration, never an action parameter.
An event's destination is fixed on its first claim so retries do not silently redirect to a new
configuration. Unconfigured events remain pending. Phase 3 supports one notification destination
per event; no fan-out subscription registry or external pre-commit validation hooks are supported.

Allowed category: action.committed. Allowed destination: HTTPS port 443, no userinfo, fragment or
query; up to 2,048 characters. Delivery resolves all addresses, rejects nonpublic destinations,
pins a validated address for the socket and verifies TLS against the original hostname. No proxies,
redirect following, response-body storage or credential forwarding. Socket connect/read timeout is
5 seconds; DNS lookup follows host resolver timing and is not a hard overall delivery deadline.

Claims use PostgreSQL FOR UPDATE SKIP LOCKED and a durable UUID lease token. The claim transaction
commits before network I/O. A 60-second lease recovers abandoned workers; stale completions cannot
replace a newer claim. Each claim records an UNKNOWN delivery attempt before sending, so a crash
is visible. A 2xx response delivers; 429/5xx and transport failures retry with delays 2,4,8,16 seconds
before successive attempts, maximum five claims. Other HTTP statuses/destination rejection are
permanent. Exhaustion enters DEAD; an expired fifth claim also enters DEAD. No automatic dead-letter
replay API exists. Attempts and sanitized error categories survive restart. Failed delivery cannot
roll back an already committed action.

Delivery is **at least once**, with possible duplicates after lost responses/crashes/lease expiry.
Consumers deduplicate the stable `event_id` payload and `X-Ontology-Event-ID` header. The minimal
runner requires an operator/scheduler to invoke it; production orchestration, webhook signing,
fan-out, custom CA/authentication and compensation workflows are deferred.

## Ownership and reconciliation

`ReconciliationService.refresh` is a governed foundation for future ingestion, not a connector or
batch pipeline. Each property has source/pipeline/user/action ownership, latest observed source
value, resolved edited value, schema/revision, updater/time and optional action execution reference.
Direct CRUD creates/patches record user ownership; actions record action ownership. Legacy values
without overlays are conservatively user-owned. No missing source row deletes an object.

The default edit_wins policy accepts changes to source/pipeline-owned properties from the same
source and preserves user/action values. Equal source observations never release edit ownership.
source_wins explicitly transfers ownership and requires `edit:override` in addition to reconcile
and property/object update permissions. Different source identities cannot silently take over an
owned source property. The initial release of legacy values to a source requires explicit source_wins.
Policies are server-owned service-call configuration, not untrusted ingestion-row input.

reject/manual policies persist deterministic OPEN conflicts for differing governed values. A
conflicting multi-property refresh changes no object properties or overlay ownership. Repeated
identical observations reuse the same conflict for the same schema/revision/source/property/value.
Explicit resolution requires `edit:resolve`, current expected revision and compatible schema; it
records ACCEPTED/PRESERVED, resolver and timestamp. Source acceptance also passes ordinary mutation
and override authorization. It never bypasses canonical validation or revisions.

Visible source changes increment object revisions through ObjectService; preserved observations
update provenance only. Action records/audits remain immutable as source observations change.
Compatible activation can carry edits forward; changed property types or invalid edited values
require a governed rebase, and conflicts from older schemas require a fresh observation before
resolution. Full ingestion jobs, source snapshots, deletion policies and batch reconciliation are
Phase 4 work.

Manufacturing examples: UpdateMachineStatus uses exact Machine status enum/revision;
ScheduleMaintenance creates all three MaintenanceTask properties and both taskForMachine and
assignedEmployee edges; CompleteMaintenance permits IN_PROGRESS → COMPLETED only; AssignTask
assigns an unassigned task and rejects an existing assignment by cardinality. Reassignment requires
an explicitly authored delete/create-link action. No completed timestamp or invented fixture field
is added.
