"use client";
import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FoundryError, type components } from "@foundry/sdk";
import { foundryQueryKey, useFoundryClient } from "./runtime.js";
type Job = components["schemas"]["ExecutionJobView"];
const terminal = new Set(["SUCCEEDED", "FAILED", "CANCELLED"]);
const running = new Set(["QUEUED", "ADMITTED", "RUNNING", "CANCELLING"]);
export function executionState(job: Job) {
  return {
    state: job.state,
    terminal: terminal.has(job.state),
    succeeded: job.state === "SUCCEEDED",
    executionError:
      job.state === "FAILED"
        ? new FoundryError("execution", job.error ?? "execution_failed")
        : undefined,
    possiblePartialCommits: job.kind === "MATERIALIZATION",
    metrics: job.metrics,
    planDigest: job.plan_digest,
    nodes: job.nodes ?? [],
    outputs: job.outputs ?? [],
    publicationState: job.publication_state,
  };
}
export interface ExecutionOptions {
  enabled?: boolean;
  intervalMs?: number;
  maxPolls?: number;
  maxDurationMs?: number;
}
/** Bounded monitoring. Explicit refetch remains available after the automatic budget ends. */
export function useExecution(jobId: string, options: ExecutionOptions = {}) {
  const client = useFoundryClient();
  const cache = useQueryClient();
  const interval = options.intervalMs ?? 2000;
  const maxPolls = options.maxPolls ?? 120;
  const duration = options.maxDurationMs ?? 600000;
  if (
    !Number.isFinite(interval) ||
    interval < 1000 ||
    interval > 60000 ||
    !Number.isInteger(maxPolls) ||
    maxPolls < 1 ||
    maxPolls > 1000 ||
    !Number.isFinite(duration) ||
    duration < 1000 ||
    duration > 3600000
  )
    throw new RangeError("invalid_poll_budget");
  const budget = useRef({ key: "", count: 0, start: 0 });
  const key = client.cacheId + jobId;
  if (budget.current.key !== key)
    budget.current = { key, count: 0, start: Date.now() };
  const isActive = useClientActivity(client);
  const result = useQuery<Job, FoundryError>({
    queryKey: foundryQueryKey(client, "execution.get", {
      path: { job_id: jobId },
    }),
    enabled: isActive && options.enabled !== false && !!jobId,
    retry: false,
    queryFn: ({ signal }) => {
      budget.current.count++;
      budget.current.start ||= Date.now();
      return client.execution.get({ path: { job_id: jobId } }, { signal });
    },
    refetchInterval: (query) => {
      if (
        !isActive ||
        options.enabled === false ||
        budget.current.count >= maxPolls ||
        Date.now() - budget.current.start >= duration ||
        (query.state.error && !query.state.error.retryable)
      )
        return false;
      if (query.state.data && !running.has(query.state.data.state))
        return false;
      return interval;
    },
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: false,
  });
  const publication = result.data
    ? JSON.stringify([
        result.data.state,
        result.data.metrics,
        result.data.output_version_id,
        result.data.publication_state,
        result.data.outputs,
      ])
    : undefined;
  useEffect(() => {
    if (!publication || !client.active) return;
    // Durable work can publish after admission, including partial materialization batches.
    // Refresh observed domain data when progress changes without refetching this monitor itself.
    const filter = {
      predicate: (query: { queryKey: readonly unknown[] }) =>
        !String(query.queryKey.at(-2)).startsWith("execution."),
    };
    void cache.cancelQueries(filter).then(() => {
      if (client.active) return cache.invalidateQueries(filter);
    });
  }, [cache, client, publication]);
  return {
    ...result,
    data:
      isActive && (!result.error || result.error.retryable)
        ? result.data
        : undefined,
    error: isActive ? result.error : client.invalidationError,
    isPending: isActive && result.isPending,
    isError: !isActive || result.isError,
    isSuccess: isActive && result.isSuccess,
  };
}
import { useSyncExternalStore } from "react";
import type { FoundryClient } from "@foundry/sdk";
function useClientActivity(client: FoundryClient) {
  return useSyncExternalStore(
    client.subscribe,
    () => client.active,
    () => client.active,
  );
}
/** Deliberately small/headless-friendly text primitive; never hides partially committed objects. */
export function ExecutionStatus({ job }: { job: Job }) {
  return (
    <span role="status">
      {job.state}
      {job.kind === "MATERIALIZATION"
        ? " — committed batches may already be visible, including after failure or cancellation"
        : ""}
    </span>
  );
}
