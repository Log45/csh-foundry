# Changelog and release guidance

0.16.0 — initial locally validated platform SDK / React developer experience.

Before a future public release: review generated FastAPI contract drift, run the complete validation
and packed-consumer checks, choose/confirm the repository license, review package contents and update
both package versions and lockfile together. Document API changes and migration examples. OpenAPI
v1 is the current supported server surface; immutable ontology schema versions remain separate.
Packages have ESM exports and TypeScript declarations; build before packing. npm pack is local only.
No npm publication, repository creation, deployment or production certification is authorized by Phase 16.

## 0.17.0

Add generated governed media, function and automation APIs, typed definitions and results, durable
execution integration, and authenticated media original/preview streaming. Existing APIs remain.

Phase 19 (unreleased local workspace): generated application resource/draft/validation/publication/
runtime gateways and canonical object aggregate capability. Existing sessions, tenant scoping,
mutation retry policy, request limits and typed errors remain authoritative.
