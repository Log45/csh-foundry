# ADR 0041: Generated platform SDK and isolated React application clients

Status: accepted for explicitly authorized Phase 16; recorded before implementation.

Use existing @foundry naming: @foundry/sdk (framework independent) and @foundry/react.
The actual FastAPI OpenAPI export supplies all operational request/response types. A reviewed
endpoint manifest selects public capabilities; deterministic generation emits typed wrappers and
React hooks. No public arbitrary-path transport, backend schema changes or new mutation path.
Ontology-specific generated archives remain separate from this platform-wide SDK.

Browser access uses the existing same-origin Studio BFF envelope, HttpOnly session, CSRF token and
expected_tenant check. Never expose service credentials or access tokens. An application can mount
its UI under this origin or use an operator-approved same-origin BFF with the same contract. Cross
origin cookies/CORS and a new auth server are outside scope. Session/tenant changes create a new
immutable client; invalidation aborts outstanding requests and disables the old client.

Studio currently has no established query library. Adopt TanStack Query v5 for the new React package,
without rewriting Studio. Each provider owns a dedicated cache; keys include endpoint, tenant,
principal, session generation and caller Project context. Client replacement remounts the cache scope.
401/403 clear private cache and stop polling; mutations invalidate the complete isolated cache after
server confirmation (conservative correctness before finer-grained optimizations). No optimistic writes.
Strict Mode effect cleanup must not invalidate a reusable client.

Only explicitly classified read operations retry at most twice. Mutations never retry automatically;
action idempotency remains the generated ExecuteRequest body contract. Polling is bounded, visibility
aware and stops on terminal status or authorization errors. Materialization state/metrics are exposed
unchanged; running/failed/cancelled jobs can already have visible committed batches.

No source uploads are added. Download links reuse the existing fixed binary BFF, with CSRF and tenant
checks, and browser attachment delivery; no source JSON parsing or whole-file buffers in the SDK.
Source limits and worker resource budgets remain server authority.

Scope discrepancy: roadmap milestone F also mentions application registration and Action Builder
improvements. The explicit Phase 16 prompt narrows implementation to SDK, starter and workspace design;
no new registration backend, workspace infrastructure or builder is introduced. Existing governed
resource discovery and action APIs are exposed. Phase 17 and Production Readiness remain unauthorized.

References: TanStack Query v5 useQuery, QueryClientProvider and query-cancellation official documentation,
verified before implementation; installed version source/types are checked during builds.
