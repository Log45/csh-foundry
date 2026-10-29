# Phase 9 preparation (documentation only)

Phase 9 requires separate approval. No branching, merging or SDK generator is implemented in Phase 8.

The canonical Pydantic models remain the source of schema contracts. Studio's generated OpenAPI
TypeScript declarations describe actual HTTP contracts and are application integration types, not
a published SDK. `scripts/export_openapi.py` and `npm run generate:api` can be used to detect drift.

Before approving Phase 9, review the existing immutable published snapshots, active version pointer,
canonical content hashes, separate migration-plan approval/publication/activation boundaries and
Phase 8 optional expected_hash draft-save guard. Branching must not replace those invariants or
materialize a second registry. Object Sets currently contain ephemeral query definitions; there is
no durable saved-query API to assume or silently migrate. Future SDKs must use the same query AST,
structured errors, stable IDs, optimistic object revisions and required action idempotency keys.

Generated clients must distinguish browser opaque sessions from actual RFC 9068 API bearer tokens.
Never bundle BFF sessions/tokens, worker credentials or server connector secrets into generated SDKs.
A later provider broker must emit the documented API token profile; live Microsoft/Google sign-in
and scalable session persistence belong to explicitly reviewed later security/deployment work.
