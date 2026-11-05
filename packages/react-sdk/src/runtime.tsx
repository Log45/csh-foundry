"use client";
import {
  createContext,
  useContext,
  useState,
  useEffect,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { FoundryError, type FoundryClient } from "@foundry/sdk";
const Context = createContext<FoundryClient | null>(null);
function Scope({
  client,
  children,
}: {
  client: FoundryClient;
  children: ReactNode;
}) {
  const [cache] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: false,
            staleTime: 15000,
            gcTime: 60000,
            refetchOnWindowFocus: false,
          },
          mutations: { retry: false },
        },
      }),
  );
  useEffect(() => {
    const unsubscribe = client.subscribe(() => {
      void cache.cancelQueries();
      cache.clear();
    });
    if (!client.active) cache.clear();
    return () => {
      unsubscribe();
      void cache.cancelQueries();
      cache.clear();
    };
  }, [client, cache]);
  return (
    <Context.Provider value={client}>
      <QueryClientProvider client={cache}>{children}</QueryClientProvider>
    </Context.Provider>
  );
}
/** Memoize the client in the host. Replace it on identity, tenant, session or Project changes. */
export function FoundryProvider({
  client,
  children,
}: {
  client: FoundryClient;
  children: ReactNode;
}) {
  return (
    <Scope key={client.cacheId} client={client}>
      {children}
    </Scope>
  );
}
export function useFoundryClient() {
  const client = useContext(Context);
  if (!client) throw new Error("Foundry hooks require FoundryProvider");
  return client;
}
function useActive(client: FoundryClient) {
  return useSyncExternalStore(
    client.subscribe,
    () => client.active,
    () => client.active,
  );
}
export interface QueryOptions {
  enabled?: boolean;
  staleTime?: number;
}
export function foundryQueryKey(
  client: FoundryClient,
  operation: string,
  input: unknown,
) {
  const c = client.context;
  return [
    "foundry",
    c.baseUrl,
    c.bffUrl,
    c.tenantId,
    c.principalId,
    c.sessionKey,
    c.projectId ?? null,
    client.cacheId,
    operation,
    input,
  ] as const;
}
export function useFoundryQuery<T>(
  operation: string,
  input: unknown,
  query: (client: FoundryClient, signal: AbortSignal) => Promise<T>,
  options: QueryOptions = {},
) {
  const client = useFoundryClient();
  const active = useActive(client);
  const result = useQuery<T, FoundryError>({
    queryKey: foundryQueryKey(client, operation, input),
    queryFn: ({ signal }) => query(client, signal),
    enabled: active && options.enabled !== false,
    staleTime: options.staleTime,
    retry: false,
  });
  return {
    ...result,
    data:
      active && (!result.error || result.error.retryable)
        ? result.data
        : undefined,
    error: active ? result.error : client.invalidationError,
    isPending: active && result.isPending,
    isError: !active || result.isError,
    isSuccess: active && result.isSuccess,
  };
}
export function useFoundryMutation<I, O>(
  mutation: (client: FoundryClient, input: I) => Promise<O>,
) {
  const client = useFoundryClient();
  const cache = useQueryClient();
  return useMutation<O, FoundryError, I>({
    mutationFn: (input) => mutation(client, input),
    retry: false,
    onSettled: async () => {
      // Error responses may follow committed work, especially materialization cancellation.
      await cache.cancelQueries();
      if (client.active) await cache.invalidateQueries();
    },
  });
}
