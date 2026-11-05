// @vitest-environment jsdom
import React, { StrictMode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import {
  renderHook,
  waitFor,
  act,
  cleanup,
  render,
  screen,
} from "@testing-library/react";
import {
  createFoundryClient,
  FoundryError,
  type FoundryClient,
  type components,
} from "@foundry/sdk";
import {
  FoundryProvider,
  useDatasetsGet,
  useObjectsCreate,
  useExecution,
  ExecutionStatus,
  executionState,
  foundryQueryKey,
} from "@foundry/react";
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});
function client(
  fetch: typeof globalThis.fetch,
  tenantId = "tenant",
  sessionKey = "session",
) {
  return createFoundryClient({
    tenantId,
    principalId: "user",
    sessionKey,
    auth: { csrf: "csrf" },
    fetch,
    readRetries: 0,
  });
}
function wrapper(c: FoundryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <StrictMode>
        <FoundryProvider client={c}>{children}</FoundryProvider>
      </StrictMode>
    );
  };
}
it("requires provider", () => {
  expect(() =>
    renderHook(() => useDatasetsGet({ path: { dataset_id: "d" } })),
  ).toThrow("FoundryProvider");
});
it("loads typed data under Strict Mode and reuses the cache", async () => {
  const fetch = vi.fn(async () => Response.json({ name: "dataset" }));
  const c = client(fetch);
  const w = wrapper(c);
  const hook = renderHook(() => useDatasetsGet({ path: { dataset_id: "d" } }), {
    wrapper: w,
  });
  expect(hook.result.current.isPending).toBe(true);
  await waitFor(() => expect(hook.result.current.data?.name).toBe("dataset"));
  const count = fetch.mock.calls.length;
  const second = renderHook(
    () => useDatasetsGet({ path: { dataset_id: "d" } }),
    { wrapper: w },
  );
  await waitFor(() => expect(second.result.current.data?.name).toBe("dataset"));
  expect(c.active).toBe(true);
  expect(fetch.mock.calls.length).toBeGreaterThanOrEqual(count);
});
it("returns structured errors and respects disabled queries", async () => {
  const fetch = vi.fn(async () =>
    Response.json({ error: { code: "missing" } }, { status: 404 }),
  );
  const { result, rerender } = renderHook(
    ({ enabled }) => useDatasetsGet({ path: { dataset_id: "d" } }, { enabled }),
    { wrapper: wrapper(client(fetch)), initialProps: { enabled: false } },
  );
  expect(fetch).not.toHaveBeenCalled();
  rerender({ enabled: true });
  await waitFor(() =>
    expect(result.current.error).toBeInstanceOf(FoundryError),
  );
  expect(result.current.error?.category).toBe("not_found");
});
it("isolates replacement tenant/session/client caches", async () => {
  const fetch = vi.fn(async (_url, init) =>
    Response.json({ name: JSON.parse(init?.body as string).expected_tenant }),
  );
  const first = client(fetch, "one");
  const second = client(fetch, "two", "next");
  function W({ c }: { c: FoundryClient }) {
    const q = useDatasetsGet({ path: { dataset_id: "d" } });
    return <span>{q.data?.name ?? "loading"}</span>;
  }
  const view = render(
    <FoundryProvider client={first}>
      <W c={first} />
    </FoundryProvider>,
  );
  await screen.findByText("one");
  view.rerender(
    <FoundryProvider client={second}>
      <W c={second} />
    </FoundryProvider>,
  );
  expect(screen.queryByText("one")).toBeNull();
  await screen.findByText("two");
  expect(foundryQueryKey(first, "x", {})).not.toEqual(
    foundryQueryKey(second, "x", {}),
  );
  const sameTenant = client(fetch, "two", "other-user-session");
  expect(foundryQueryKey(second, "x", {})).not.toEqual(
    foundryQueryKey(sameTenant, "x", {}),
  );
});
it("aborts consumed requests on unmount", async () => {
  let signal: AbortSignal | undefined;
  const fetch: typeof globalThis.fetch = async (_url, init) =>
    new Promise((_, reject) => {
      signal = init?.signal ?? undefined;
      signal?.addEventListener("abort", () => reject(new Error()), {
        once: true,
      });
    });
  const hook = renderHook(() => useDatasetsGet({ path: { dataset_id: "d" } }), {
    wrapper: wrapper(client(fetch)),
  });
  await waitFor(() => expect(signal).toBeDefined());
  hook.unmount();
  expect(signal?.aborted).toBe(true);
});
it("invalidates cached reads only after confirmed mutation and surfaces conflicts", async () => {
  let reads = 0;
  let status = 200;
  let resolveMutation: ((v: Response) => void) | undefined;
  const fetch: typeof globalThis.fetch = async (_url, init) => {
    const body = JSON.parse(init?.body as string);
    if (body.method === "POST")
      return new Promise((resolve) => {
        resolveMutation = resolve;
      });
    reads++;
    return Response.json({ name: String(reads) });
  };
  const c = client(fetch);
  const { result } = renderHook(
    () => ({
      read: useDatasetsGet({ path: { dataset_id: "d" } }),
      mutation: useObjectsCreate(),
    }),
    { wrapper: wrapper(c) },
  );
  await waitFor(() => expect(result.current.read.isSuccess).toBe(true));
  let pending: Promise<unknown>;
  act(() => {
    pending = result.current.mutation.mutateAsync({
      path: { ontology_id: "o", type_id: "T" },
      body: { object_id: "x", properties: {} },
    });
  });
  await waitFor(() => expect(result.current.mutation.isPending).toBe(true));
  expect(result.current.mutation.isSuccess).toBe(false);
  const before = reads;
  await act(async () => {
    resolveMutation?.(Response.json({}, { status }));
    await pending;
  });
  expect(reads).toBeGreaterThan(before);
  status = 409;
  act(() => {
    pending = result.current.mutation.mutateAsync({
      path: { ontology_id: "o", type_id: "T" },
      body: { object_id: "x", properties: {} },
    });
    void pending.catch(() => {});
  });
  await waitFor(() => expect(result.current.mutation.isPending).toBe(true));
  await act(async () => {
    resolveMutation?.(
      Response.json({ error: { code: "conflict" } }, { status }),
    );
    await pending.catch(() => {});
  });
  await waitFor(() =>
    expect(result.current.mutation.error?.category).toBe("conflict"),
  );
});
const job = (state: string): components["schemas"]["ExecutionJobView"] => ({
  id: "j",
  resource_id: "m",
  kind: "MATERIALIZATION",
  state,
  attempts: 1,
  error: state === "FAILED" ? "conversion_failed" : null,
  metrics: { created: 100 },
  output_version_id: null,
  output_dataset_id: null,
  created_at: "2026-01-01T00:00:00Z",
  admitted_at: null,
  started_at: null,
  completed_at: null,
});
it.each(["SUCCEEDED", "FAILED", "CANCELLED"])(
  "stops polling at terminal %s and preserves partial metrics",
  async (state) => {
    const fetch = vi.fn(async () => Response.json(job(state)));
    const { result } = renderHook(
      () => useExecution("j", { intervalMs: 1000 }),
      { wrapper: wrapper(client(fetch)) },
    );
    await waitFor(() => expect(result.current.data?.state).toBe(state));
    const count = fetch.mock.calls.length;
    vi.useFakeTimers();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100);
    });
    vi.useRealTimers();
    expect(fetch).toHaveBeenCalledTimes(count);
    expect(executionState(result.current.data!).possiblePartialCommits).toBe(
      true,
    );
    render(<ExecutionStatus job={result.current.data!} />);
    expect(screen.getByRole("status").textContent).toContain(
      "committed batches",
    );
  },
);
it("polls running jobs then stops at its request budget", async () => {
  const fetch = vi.fn(async () => Response.json(job("RUNNING")));
  const hook = renderHook(
    () => useExecution("j", { intervalMs: 1000, maxPolls: 2 }),
    { wrapper: wrapper(client(fetch)) },
  );
  await waitFor(() => expect(hook.result.current.data).toBeDefined());
  const initial = fetch.mock.calls.length;
  await waitFor(
    () => expect(fetch.mock.calls.length).toBeGreaterThan(initial),
    { timeout: 2000 },
  );
  const count = fetch.mock.calls.length;
  vi.useFakeTimers();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1100);
  });
  vi.useRealTimers();
  expect(fetch).toHaveBeenCalledTimes(count);
});
it("does not poll while disabled", async () => {
  const fetch = vi.fn(async () => Response.json(job("RUNNING")));
  renderHook(() => useExecution("j", { enabled: false }), {
    wrapper: wrapper(client(fetch)),
  });
  await new Promise((r) => setTimeout(r, 10));
  expect(fetch).not.toHaveBeenCalled();
});
it("clears private data on explicit logout invalidation", async () => {
  const c = client(async () => Response.json({ name: "private" }));
  const { result } = renderHook(
    () => useDatasetsGet({ path: { dataset_id: "d" } }),
    { wrapper: wrapper(c) },
  );
  await waitFor(() => expect(result.current.data?.name).toBe("private"));
  act(() => c.invalidate());
  await waitFor(() => expect(result.current.data).toBeUndefined());
  expect(c.active).toBe(false);
});
it("stops on authorization revocation", async () => {
  let denied = false;
  const fetch = vi.fn(async () =>
    denied
      ? Response.json({ error: { code: "forbidden" } }, { status: 403 })
      : Response.json(job("RUNNING")),
  );
  const c = client(fetch);
  const { result } = renderHook(() => useExecution("j", { intervalMs: 1000 }), {
    wrapper: wrapper(c),
  });
  await waitFor(() => expect(result.current.data).toBeDefined());
  denied = true;
  await act(async () => {
    await result.current.refetch();
  });
  expect(c.active).toBe(false);
  await waitFor(() => expect(result.current.data).toBeUndefined());
  const count = fetch.mock.calls.length;
  vi.useFakeTimers();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1100);
  });
  vi.useRealTimers();
  expect(fetch).toHaveBeenCalledTimes(count);
});
it("deduplicates simultaneous observers inside one provider", async () => {
  const fetch = vi.fn(async () => Response.json({ name: "shared" }));
  const c = client(fetch);
  const { result } = renderHook(
    () => ({
      a: useDatasetsGet({ path: { dataset_id: "d" } }),
      b: useDatasetsGet({ path: { dataset_id: "d" } }),
    }),
    {
      wrapper: ({ children }) => (
        <FoundryProvider client={c}>{children}</FoundryProvider>
      ),
    },
  );
  await waitFor(() => expect(result.current.a.data?.name).toBe("shared"));
  expect(result.current.b.data?.name).toBe("shared");
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("refreshes observed domain data as durable publication progresses", async () => {
  let state = "RUNNING",
    reads = 0;
  const c = client(async (_url, init) =>
    JSON.parse(init?.body as string).path.includes("/execution/")
      ? Response.json(job(state))
      : Response.json({ name: String(++reads) }),
  );
  const { result } = renderHook(
    () => ({
      data: useDatasetsGet({ path: { dataset_id: "d" } }),
      run: useExecution("j"),
    }),
    { wrapper: wrapper(c) },
  );
  await waitFor(() => expect(result.current.run.data?.state).toBe("RUNNING"));
  await waitFor(() => expect(result.current.data.isSuccess).toBe(true));
  const before = reads;
  state = "SUCCEEDED";
  await act(async () => {
    await result.current.run.refetch();
  });
  await waitFor(() => expect(reads).toBeGreaterThan(before));
});
it("resumes monitoring a fresh cached running job after observer remount", async () => {
  const fetch = vi.fn(async () => Response.json(job("RUNNING")));
  const c = client(fetch);
  function Monitor() {
    useExecution("j", { intervalMs: 1000 });
    return null;
  }
  const view = render(
    <FoundryProvider client={c}>
      <Monitor />
    </FoundryProvider>,
  );
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  await act(async () => {
    await new Promise((r) => setTimeout(r, 5));
  });
  view.rerender(<FoundryProvider client={c}>{null}</FoundryProvider>);
  const before = fetch.mock.calls.length;
  view.rerender(
    <FoundryProvider client={c}>
      <Monitor />
    </FoundryProvider>,
  );
  await waitFor(() => expect(fetch.mock.calls.length).toBeGreaterThan(before), {
    timeout: 2000,
  });
});
it("hides previously cached resource data after a non-enumerating 404 denial", async () => {
  let denied = false;
  const c = client(async () =>
    denied
      ? Response.json({ error: { code: "not_found" } }, { status: 404 })
      : Response.json({ name: "private" }),
  );
  const { result } = renderHook(
    () => useDatasetsGet({ path: { dataset_id: "d" } }),
    { wrapper: wrapper(c) },
  );
  await waitFor(() => expect(result.current.data?.name).toBe("private"));
  denied = true;
  await act(async () => {
    await result.current.refetch();
  });
  await waitFor(() => expect(result.current.error?.status).toBe(404));
  expect(result.current.data).toBeUndefined();
  expect(c.active).toBe(true);
});
it("stops job polling and hides old status on a non-enumerating 404 denial", async () => {
  let denied = false;
  const fetch = vi.fn(async () =>
    denied
      ? Response.json({ error: { code: "not_found" } }, { status: 404 })
      : Response.json(job("RUNNING")),
  );
  const c = client(fetch);
  const { result } = renderHook(() => useExecution("j", { intervalMs: 1000 }), {
    wrapper: wrapper(c),
  });
  await waitFor(() => expect(result.current.data?.state).toBe("RUNNING"));
  denied = true;
  await act(async () => {
    await result.current.refetch();
  });
  await waitFor(() => expect(result.current.error?.status).toBe(404));
  expect(result.current.data).toBeUndefined();
  const count = fetch.mock.calls.length;
  vi.useFakeTimers();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1100);
  });
  vi.useRealTimers();
  expect(fetch).toHaveBeenCalledTimes(count);
  expect(c.active).toBe(true);
});
