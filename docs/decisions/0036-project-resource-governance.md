# ADR 0036: Project governance and canonical resource references

Status: accepted for Phase 11. Design recorded before implementation.

- Existing assets stay in the tenant ontology with no implicit default Project or membership.
  An authorized Project editor explicitly registers references to published snapshots, individually
  or through bounded, restart-safe catalog import. No migration reassigns historical ownership.
- A resource has one owning Project; its creator is provenance, not a separate access grant.
  A Project-unique canonical reference (kind, ontology, version, entity) prevents duplicate
  references within a Project. Independent private references may point to the same canonical
  entity without disclosing another Project through registration conflicts. Other Projects consume
  explicit read-only shares of the same resource ID.
  Registration does not copy definitions. Published versions themselves are supported assets.
- Explicit Project roles are owner, editor and viewer. All require current tenant permissions;
  owners with current read/manage permissions manage members/shares/archive; editors manage
  folders/resources; viewers browse. These roles inherit throughout nested folders and resources;
  folders do not introduce independent ACLs.
  Platform administrators do not automatically enter private Projects. Creators become owners.
  Creation requires create/read/manage permissions; ownership targets must retain read/manage.
  Membership targets must be enabled tenant members. Owner changes cannot remove the last owner.
- Folder names are trimmed, case-sensitive Unicode, 1–200 characters, without slash, control
  characters, dot or dot-dot. Active siblings collide exactly; root uses the same rule. Resource
  names are independent of folder names, with the same active sibling collision rule.
  Paths are computed navigation, never identifiers. Maximum folder depth is 32; maximum 10,000
  folders per Project. Cross-Project folder/resource ownership moves are rejected.
- Tenant row locks serialize Project operations including browsing, membership and sharing.
  This conservative lock prevents cycles, stale share access and concurrent archive/move races.
  Mutations require expected revision; stale updates return 412. SQL uniqueness remains a backstop.
  Revocation takes effect after commit; earlier transactions finish before the revoking transaction.
- Archive is non-destructive and final in this phase. Archived Projects remain visible to members
  but cannot mutate or expose their resources through shares. Folders must be empty of active
  children/resources before archive. Archived resources stop appearing in normal browsing and
  shares. Names may be reused after archive. No hard delete or implicit recursive archive.
- Only server-registered ontology adapters are implemented. References pin immutable published
  versions and entity IDs. Future resource families need their own handlers and migrations.
  Existing schema read authorization is cumulative on every discovery/read; operational object,
  property and action endpoints retain their own independent policies. No background elevation.
- Reuse GovernedService, PlatformAuthorizer and authorization_audit. Committed mutation events
  hash stable IDs and membership/share change details, including roles and targets, and record
  actor/time; no credentials or canonical definitions enter audit. Missing and inaccessible IDs
  return identical 404s. Lists filter membership/shares in SQL before pagination, without totals.
- New permissions are explicit: project:create/read/write/manage. Existing immutable roles are
  preserved; an additive migration grants a new immutable Project role only to existing principals
  assigned the bootstrap tenant-administrator role. Other users need explicit permission provisioning.
  Project access still requires explicit membership. Local trusted identity keeps its existing mode.

PostgreSQL is authoritative. No RDF coupling, new storage, execution engine or service is added.
Production remains blocked under Section 23B. Phase 12 is not implemented.
