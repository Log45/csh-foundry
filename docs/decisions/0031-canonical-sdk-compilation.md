# ADR 0031: Canonical SDK compilation and governed artifact issuance

Status: Accepted for Phase 9.

One bounded Python compiler consumes canonical OntologyDefinition plus actual FastAPI OpenAPI.
It verifies required HTTP bindings and emits independent Python/Pydantic/httpx and strict TypeScript/
Fetch packages. No SDK imports backend or Next modules. Existing query AST, opaque identity query
aliases, action preview/execute, expected revisions and caller-supplied idempotency keys remain the
transport contract. The server retains all authorization and canonical data validation authority.
There is no new schema or query language, token broker or saved-query database.

API issuance selects immutable published registry versions under current schema:read authority.
That existing explicit schema-disclosure permission also governs generation, metadata and download.
Artifacts are tenant/ontology owned and accessible to current schema readers, not publicly served or
permanently authorized by possession of an artifact ID. Generation is synchronous for <=64 KiB
schemas with <=4 MiB source output. The ontology write lock admits one generator per ontology across
processes. Existing FastAPI worker/thread limits apply; global production workload admission remains
Phase 10. PostgreSQL stores immutable files/manifests and archive hashes; no new queue or blob store.

Safe deterministic aliases preserve canonical wire identifiers. Collision detection rejects ambiguous
names, including inverse-link aliases; generated types distinguish missing read properties (projection/
ABAC) from required create/action inputs. Python supports date/datetime/UUID/Decimal values with JSON
serialization; TypeScript uses ISO/UUID/decimal strings. TypeScript rejects nonfinite or unsafe integer
numbers rather than silently losing integer precision. Full signed-64-bit integer transport outside
JavaScript safe integers is unsupported by the TypeScript SDK. Backend constraints stay authoritative.

Generated source/file ordering is deterministic. Manifest uses a fixed reproducible epoch; issuance
actor/time is separate database metadata. The manifest hashes the sorted source-file digest map,
excluding itself. The database separately hashes the deterministic ZIP (fixed epoch, permissions,
sorted paths). No self-referential fixed-point artifact hash is claimed. Compiler version, schema hash,
API hash, language, symbols and per-file digests bind each build. CLI shares this exact compiler and
supports trusted published exports or authenticated remote selection plus a non-mutating --check.

SDKs operate against the server's active published version. A generated package for an older published
version cannot request historical operational data; schema-version mismatch fails explicitly. Cursor
errors and conflicts are preserved without retries/restarts. Tokens are obtained per request through
an async provider; browser cookies, external IdP tokens, connector and worker secrets never enter
artifacts. No package registry distribution or live SSO is introduced.
