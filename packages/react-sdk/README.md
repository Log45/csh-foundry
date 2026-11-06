# @foundry/react

Headless React bindings over @foundry/sdk and TanStack Query v5. React 18.3/19 is a peer.
ESM and declarations; no Next.js, Node crypto, backend credentials or server code in this package.

```tsx
const client = useMemo(() => createFoundryClient(config), [identityContext]);
return <FoundryProvider client={client}><Application /></FoundryProvider>;
// In Application:
const objects = useObjectsQuery({
  path: { ontology_id: 'manufacturing', type_id: 'Machine' },
  body: { object_type: 'Machine', limit: 50, cursor },
});
const mutation = useObjectsUpdate();
// mutateAsync({path, query:{object_id}, body:{expected_version,properties}})
const run = useExecution(jobId, { intervalMs: 2000, maxPolls: 120 });
```

Generated hook names are `use<Group><Operation>` matching every core operation; examples:
useOntologiesObjectTypes, useObjectsQuery/Get/Links/Create/Update, useActionsExecute,
useDatasetsGet/Versions/Schema/Preview, usePipelinesStart/Publish/History,
useMappingsStart/Preview/Provenance, useExecutionCancel/Retry. Full inventory: src/hooks.ts.
Reads accept generated input plus `{enabled?, staleTime?}` and return TanStack loading/data/error,
refetch and status fields. Query pagination is explicit in input; switching cursor/page selects a new
cache key. No previous-page placeholder is retained across contexts. Mutations return mutate,
mutateAsync, pending/success/error states and never retry or optimistically publish.

Every provider owns its own QueryClient, keyed by immutable SDK client.cacheId. Query keys include
API/BFF, tenant, principal, session generation, Project, operation and complete input. Never persist
or externally hydrate private caches across sessions. Replacing client remounts this scope before
children can render old data; cleanup cancels consumed fetch signals and clears cache. Strict Mode
cleanup does not invalidate the caller-owned SDK client. Identical context in another client cannot
reuse private cache. No global QueryClient. SSR can render an explicitly supplied per-request client;
fetching starts on the client. Private SSR dehydration/persistence is intentionally not provided.

401/403 invalidate the SDK client, synchronously disable hooks, clear cached data and expose its
structured invalidation error. Explicit logout should call client.invalidate() before awaiting the
session endpoint; drop private state in the host. Provider only owns its own queries; caller retains
responsibility for requests made outside React hooks. Unmount cancels reads, not already admitted
mutations. Mutation settlement cancels stale reads and invalidates all active queries in that scope,
including errors where server effects might already have committed. This is conservative, bounded
by active observers, and does not invent backend transaction rollback.

Cache stale time 15 seconds, inactive retention 60 seconds. React retries are disabled; the core
owns bounded safe-read retries. `useExecution` defaults to two-second intervals, 120 attempts and ten
minutes. Interval supports 1–60 seconds, maxPolls 1–1000, maxDurationMs 1 second–1 hour. Disabled or
terminal SUCCEEDED/FAILED/CANCELLED stops polling; unknown future states stop rather than guess.
Background-tab polling is paused. Authorization failures stop and clear private data; transient
transport failures can be retried on the next bounded poll. Explicit refetch remains available after
a budget is consumed. A new job/client resets its budget; toggling enabled does not create an infinite
budget. Polling observes jobs only and never schedules backend execution.

`executionState(job)` supplies terminal/succeeded/executionError/possiblePartialCommits/metrics.
`ExecutionStatus` is a small accessible text component with an explicit materialization warning.
FAILED transport and FAILED execution are distinct. Materialization RUNNING/FAILED/CANCELLED can
already have committed visible batches; no atomic activation or automatic rollback is implied.

[Core security, API inventory and package build instructions](../typescript-sdk/README.md).
The [example](../../apps/sdk-example/README.md) demonstrates live sessions and tenant replacement.

Execution monitoring also refreshes observed domain queries when run state, reconciliation metrics or
output version changes, so delayed/partial publication can appear after admission. It excludes execution
queries from that invalidation to avoid polling loops.

Permanent query errors hide prior data, including the server's non-enumerating private-resource 404.
Job monitoring stops on non-retryable transport errors; transient failures can retain last-known data
with a visible error until an authorized refetch succeeds. A resource 404 does not invalidate unrelated
client capabilities. Full identity/permission errors (401/403) still invalidate and clear the scope.

Phase 17 / 0.17.0 exports generated `useMediaSets*`, `useFunctions*` and `useAutomations*` hooks.
Use `useFunctionsInvoke` for explicit mutation confirmation and `useExecution(jobId)` for bounded
monitoring. Successful admission is not execution success. `useFunctionsResult` is appropriate only
for bounded typed results after success. Download/preview media with the client's streaming methods,
outside React query caches, and cancel streams on unmount. Existing private cache invalidation and
session isolation apply unchanged. Automation retries/cancellation use the receipt's execution job ID.

Visual application hooks are generated alongside the existing capability hooks, including
`useApplicationsDraft`, `useApplicationsSaveDraft`, `useApplicationsPublish`,
`useApplicationsVersions`, `useApplicationsRuntime` and `useApplicationsQuery`.
Use the same session-scoped provider and cache invalidation contract. See
[applications](../../docs/api/applications.md) for publication and core SDK examples.
