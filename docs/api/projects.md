# Projects, folders and governed resource references (Phase 11)

All routes are under `/api/v1`, use the existing verified principal and selected tenant,
and compose existing platform permissions with explicit Project membership. UUIDs are opaque
and stable across presentation changes. No path identifies an asset. Responses omit tenant storage
and credential details. Lists have `limit` 1–100 (default 50), `offset` 0–10000 (default 0),
deterministic name/UUID ordering (members by principal, shares by Project), and no total counts.

| Routes | Behavior |
| --- | --- |
| `POST /projects` | Create active Project; caller becomes explicit owner |
| `GET /projects`, `GET /projects/{id}` | Discover only the caller's memberships, including archived Projects |
| `PATCH /projects/{id}` | Owner changes name/description with `expected_revision` |
| `POST /projects/{id}/archive` | Owner archives without deleting contents; revision required |
| `GET /projects/{id}/members` | Bounded collaboration roster |
| `PUT /projects/{id}/members` | Owner adds/replaces role, or removes with `role: null`; Project revision required |
| `GET/POST /projects/{id}/folders` | List direct active children (`parent_id`, default root), or create |
| `GET/PATCH /projects/{id}/folders/{folder}` | Retrieve, or rename/move with revision |
| `POST /projects/{id}/folders/{folder}/archive` | Archive empty active folder with revision |
| `GET/POST /projects/{id}/resources` | Browse root/folder or register a published reference |
| `POST /projects/{id}/catalog-import` | Restart-safe bounded page of published references |
| `GET/PATCH /resources/{id}` | Authorized direct read, or owner-Project editor rename/move with revision |
| `POST /resources/{id}/archive` | Owner-Project editor archives and removes shares with revision |
| `GET/PUT /resources/{id}/shares` | Owner lists shares or grants/revokes with resource revision |

`GET .../resources` accepts `folder_id`, literal case-sensitive substring `search` (max 200),
and `shared=true` to browse incoming shares instead of owned folder contents. Shared resources
are not inserted into the consumer's folder tree. Search is confined to the selected folder or
incoming shares; SQL escaping treats `%`/`_` literally. No dynamic sorting or arbitrary SQL.

Creation requires `project:create`, `project:read`, and `project:manage` so its first owner can
administer it. Other endpoints require `project:read`, then
`project:write` for editor mutations or `project:manage` for owner administration.
Folders add no separate ACL: owning-Project roles inherit through all nested folders and owned
resources; incoming shares grant discovery/read only. The Project role further restricts global permissions: viewer reads, editor mutates folders and
resources, owner also administers membership/sharing/Project lifecycle. No platform role grants
implicit membership. Editors additionally need write permission to organize contents.
Schema/resource discovery additionally requires `schema:read`; membership never grants operational
object/property/action authority. Existing operational APIs remain authoritative and unchanged.
Delegated ingestion/semantic identities cannot use Project endpoints through existing worker policy.

Member changes validate enabled platform principal and tenant membership. Owner grants additionally
require current platform `project:read` and `project:manage`; losing these permissions removes an
owner from the last-authorized-owner count. Grant another owner
before removing/demoting the last enabled owner. Disabled owners do not count as an available
replacement. Global security administrators can still intentionally disable identities/tenant
memberships; recovery of an orphaned Project after such an external administrative action requires
an authorized database operator, not an implicit membership bypass.

Sharing requires an owner in the owning Project plus membership in the destination Project.
Revocation does not require continued destination membership. Shared access is read-only and
rechecks both active Projects, current membership, live share and schema permission per transaction.
The owner cannot enumerate consumer Project names or members through sharing. Existing direct
ontology access remains controlled by schema permissions, independent of resource shares.

## Canonical ontology references

Implemented kinds: `ONTOLOGY_OBJECT_TYPE`, `ONTOLOGY_LINK_TYPE`, `ONTOLOGY_ACTION`,
`ONTOLOGY_VERSION`. Resource creation requires `name`, `resource_type`, `ontology_id`,
`schema_version`, `entity_id`, and optional `description`/`folder_id`. For a version asset,
`entity_id` equals `schema_version`. For the other kinds it is the existing entity ID. The
published snapshot stays authoritative; the registry stores no copied definition. PostgreSQL
validates published existence and entity membership, and prevents reference or owning-Project changes.

There is no default Project migration or reassignment. Legacy ontology-only clients keep working.
Use catalog import with `ontology_id`, `schema_version`, optional `folder_id`, `limit`, `offset`.
Repeat pages return existing active references owned by that Project; archived references stay
archived. Advance offset by the requested page size to visit subsequent canonical entries. The
canonical candidate ordering is kind/entity ID. Empty/fewer returned rows can reflect already
archived entries; pagination is over candidates. A reference is unique per owning Project and
canonical kind/version/entity, including archived entries. Independent Projects may register their
own reference to an already-readable canonical entity. Such references do not disclose other
private Projects or compete as schema authorities. Explicit sharing instead preserves the same
resource ID and one Project owner. Resource names collide across kinds within an active folder;
catalog defaults use `entity (KIND)` names and respect ordinary collision errors atomically.

## Lifecycle and concurrency

Names trim outer whitespace, preserve Unicode/case, reject slash/backslash/control characters and
`.`/`..`. Active Project names are tenant-unique; active folder/resource sibling names are unique
within their own families, including root. Archived names can be reused. Folders support depth 32
and at most 10,000 active entries per Project. Cycles, self-parenting, inactive parents and
cross-Project destinations fail. Folder moves validate the entire bounded descendant structure.

Mutations hold the tenant row lock inside the existing authorization transaction. This serializes
Project operations conservatively; no distributed authorization cache is introduced. Rename, move,
archive, member and share changes require `expected_revision >= 1`; stale requests return 412.
Already-started reads finish before a revocation commits. After commit, no stale grant survives.
This does not provide snapshot pagination across multiple requests.

Archive is final and non-destructive in this phase. Archived Projects show metadata to their
members but become read-only, browse no contents, and expose no outgoing shares. Archived resources
are unavailable through direct IDs and browse; underlying ontology remains unchanged. Folder
archive requires no active child/resource. There is no hard delete, recursive archive, retention
purge or restore endpoint. Cross-Project ownership moves are unsupported; explicitly share instead.

Missing/inaccessible IDs return the same structured 404. Recognized membership with inadequate
mutation role returns 403. Collision/closed lifecycle returns 409; invalid contract/page returns 422.
Mutations append existing redacted `authorization_audit` events in the business transaction;
PlatformAuthorizer also retains its independent decision evidence on denial/rollback.

## Upgrade and deployment boundary

`0018_projects` follows the verified `0017_capacity` head. Five new tables have tenant-qualified
foreign keys and partial sibling indexes. No existing ontology/object/branch/action/audit records
are rewritten. Existing `tenant-administrator` assignments receive an additive immutable
`phase11-project-administrator` role; historical role rows/assignments remain unchanged. Other users
need explicit permission provisioning. New bootstraps include the new permissions normally.

Populated installations are forward-only: downgrade refuses when any Project exists. Empty
installations may drop only the five new empty tables/function for legacy migration regression;
immutable additive security history is retained and upgrade inserts are restart-safe. Back up before
any developer upgrade. No migration has been applied to the shared developer database by this task.
Production deployment/migrations remain blocked under PLANS.md Section 23B.
