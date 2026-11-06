# ADR 0044: Governed declarative applications

Status: accepted design for explicitly authorized Phase 19 / milestone I; local acceptance pending.

APPLICATION identity belongs to the existing Project resource registry. Folder moves, names, shares,
archive and audit retain their existing semantics. Two additive tables hold actor-private current
working drafts (revision compare-and-swap) and immutable publications. Publication snapshots include
the canonical v1 document, SHA-256 digest, exact dependency manifest and actor. Identical content
publication returns the existing version. A tenant governance lock serializes saves and publication.
No blob store is required for declarative JSON; existing ArtifactStore remains the asset boundary.

Strict bounded Pydantic documents define pages, flat widget trees via parent IDs, closed layout
choices, state, sources, bindings and interactions. No executable content, HTML or CSS language.
Incomplete references may be saved, but authoritative validation blocks publication. Future formats
fail closed; migration requires an explicit new draft and publication, never rewriting history.

Dependencies reference registered published ontology assets, with exact ontology version pins.
Runtime requires the pinned version to remain active: live values are current operational values,
not historical snapshots. Schema activation requires explicit application republishing. Every
manifest read rechecks registry sharing and independent schema permission; unavailable references
produce fixed diagnostics. Current object/property/action authority remains canonical service policy.
Application runtime gateways compose those existing services inside the same governed transaction,
rechecking app/dependency access and pins before querying or executing. No privileged identity.

Renderer precedes the structured editor. Both consume the identical generated schema. The renderer
uses the existing SDK/BFF/session boundary. State updates use closed one-step select/set/navigate/
refresh vocabulary, no recursive event propagation. Query pagination, cancellation, active-page-only
loading and bounded concurrency prevent full dataset downloads. Existing actions own preview,
validation, optimistic revisions, idempotency, transactions and audit. App action bindings never
grant action authority. The editor uses semantic controls and explicit move buttons; React Flow
adds no value for a structured page layout, and is not introduced here.

No OAuth registration expansion, hosting, arbitrary code, Phase 20 or production certification.
Milestone F external client registration and standalone Action Builder expansion remain deferred.

Contract preservation refinement: application Pydantic class names are namespaced. The canonical
query input AST uses Pydantic's validation-mode schema identity override, preventing recursive filter
components from acquiring Input/Output suffixes merely because requests are stored in app documents.
Query responses keep their serialization mode. The exported contract comparison proves that all 187
baseline component identities and shapes are preserved, with only APPLICATION added to ResourceView.
The local SDK also exposes the existing canonical aggregate endpoint for renderer/editor preview.
