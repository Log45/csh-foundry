import { expect, it, vi } from "vitest";
import {
  createFoundryClient,
  createSessionClient,
  FoundryError,
  type ClientConfig,
} from "@foundry/sdk";
const config: ClientConfig = {
  tenantId: "tenant",
  principalId: "user",
  sessionKey: "login",
  auth: { csrf: "csrf" },
  readRetries: 0,
};
const response = (body: unknown, status = 200) =>
  Response.json(body, { status });
function setup(result: unknown = {}) {
  const fetch = vi.fn(async () => response(result));
  return { fetch, client: createFoundryClient({ ...config, fetch }) };
}
it.each([
  "https://evil.test/bff",
  "//evil.test/bff",
  "/bff?x=1",
  "/../bff",
  "/bff#x",
  "/bff%2fevil",
])("rejects unsafe URL %s", (url) => {
  expect(() => createFoundryClient({ ...config, bffUrl: url })).toThrow(
    "unsafe_url",
  );
});
it.each(["tenantId", "principalId", "sessionKey"] as const)(
  "requires %s",
  (key) => {
    expect(() => createFoundryClient({ ...config, [key]: "" })).toThrow(
      "identity_context_required",
    );
  },
);
it("rejects unsupported API and invalid budgets", () => {
  expect(() =>
    createFoundryClient({ ...config, apiVersion: "v2" as "v1" }),
  ).toThrow("api_version");
  expect(() => createFoundryClient({ ...config, timeoutMs: 0 })).toThrow(
    "invalid_request_budget",
  );
  expect(() => createFoundryClient({ ...config, readRetries: 3 as 2 })).toThrow(
    "invalid_request_budget",
  );
});
it("uses BFF CSRF and tenant without bearer or mutable configuration", async () => {
  const { client, fetch } = setup([]);
  await client.datasets.versions({
    path: { dataset_id: "d" },
    query: { offset: 50, limit: 10 },
  });
  const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe("/bff");
  expect(init.credentials).toBe("same-origin");
  expect(init.redirect).toBe("error");
  expect(init.headers).toEqual({
    "content-type": "application/json",
    "x-csrf-token": "csrf",
  });
  expect(JSON.parse(init.body as string)).toEqual({
    path: "/api/v1/datasets/d/versions?limit=10&offset=50",
    method: "GET",
    expected_tenant: "tenant",
  });
  const mutable = { ...config, auth: { csrf: "old" } };
  const other = createFoundryClient({ ...mutable, fetch });
  mutable.auth.csrf = "new";
  mutable.tenantId = "other";
  await other.projects.list({});
  expect(
    JSON.parse(
      (fetch.mock.calls[1] as unknown as [string, RequestInit])[1]
        .body as string,
    ).expected_tenant,
  ).toBe("tenant");
  expect(other.context).toEqual(
    expect.objectContaining({ tenantId: "tenant" }),
  );
});
it("preserves canonical slash identities in query parameters", async () => {
  const { client, fetch } = setup();
  await client.objects.get({
    path: { ontology_id: "o", type_id: "T" },
    query: { object_id: "a/b ?c" },
  });
  const init = (fetch.mock.calls[0] as unknown as [string, RequestInit])[1];
  expect(JSON.parse(init.body as string).path).toContain(
    "object_id=a%2Fb+%3Fc",
  );
});
it("forbids traversal in path identifiers", async () => {
  const { client, fetch } = setup();
  await expect(
    client.datasets.get({ path: { dataset_id: ".." } }),
  ).rejects.toThrow("unsafe_path_segment");
  expect(fetch).not.toHaveBeenCalled();
});
it.each([0, 101, -1, 1.5])("bounds page size %s", async (limit) => {
  const { client, fetch } = setup();
  await expect(
    client.datasets.versions({ path: { dataset_id: "d" }, query: { limit } }),
  ).rejects.toThrow("invalid_page");
  expect(fetch).not.toHaveBeenCalled();
});
it("preserves query pagination and filter body", async () => {
  const { client, fetch } = setup({
    items: [],
    has_more: true,
    next_cursor: "opaque",
  });
  const body = {
    object_type: "Machine",
    limit: 200,
    cursor: "cursor",
    filter: {
      property: "operationalStatus",
      operator: "eq" as const,
      value: "RUNNING",
    },
  };
  const page = await client.objects.query({
    path: { ontology_id: "o", type_id: "Machine" },
    body,
  });
  expect(page.next_cursor).toBe("opaque");
  expect(
    JSON.parse(
      (fetch.mock.calls[0] as unknown as [string, RequestInit])[1]
        .body as string,
    ).body,
  ).toEqual(body);
});
it.each([
  [401, "authentication"],
  [403, "permission"],
  [404, "not_found"],
  [422, "validation"],
  [409, "conflict"],
  [429, "admission"],
  [503, "admission"],
  [501, "unsupported"],
  [502, "network"],
])("normalizes status %s", async (status, category) => {
  const fetch = vi.fn(async () =>
    response({ error: { code: "sanitized" } }, Number(status)),
  );
  const client = createFoundryClient({ ...config, fetch });
  await expect(
    client.datasets.get({ path: { dataset_id: "d" } }),
  ).rejects.toMatchObject({ status, category, code: "sanitized" });
});
it("never exposes response stack trace", async () => {
  const client = createFoundryClient({
    ...config,
    fetch: async () =>
      response(
        { error: { code: "secret\nstack trace", message: "secret" } },
        500,
      ),
  });
  await expect(
    client.datasets.get({ path: { dataset_id: "d" } }),
  ).rejects.toMatchObject({ code: "http_500" });
});
it("retries safe POST reads with a bound, never mutations", async () => {
  const fetch = vi.fn(async () => response({ error: { code: "busy" } }, 503));
  const client = createFoundryClient({ ...config, fetch, readRetries: 2 });
  await expect(
    client.objects.query({
      path: { ontology_id: "o", type_id: "T" },
      body: { object_type: "T" },
    }),
  ).rejects.toMatchObject({ status: 503 });
  expect(fetch).toHaveBeenCalledTimes(3);
  fetch.mockClear();
  await expect(
    client.execution.cancel({ path: { job_id: "j" } }),
  ).rejects.toMatchObject({ status: 503 });
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("forwards action idempotency unchanged on confirmed response", async () => {
  const { client, fetch } = setup({ execution_id: "e" });
  await client.actions.execute({
    path: { ontology_id: "o", action_id: "A" },
    body: { idempotency_key: "unique", parameters: { x: 1 } },
  });
  expect(
    JSON.parse(
      (fetch.mock.calls[0] as unknown as [string, RequestInit])[1]
        .body as string,
    ).body.idempotency_key,
  ).toBe("unique");
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("normalizes network errors and timeout", async () => {
  const client = createFoundryClient({
    ...config,
    fetch: async () => {
      throw new Error("raw secret");
    },
  });
  await expect(client.projects.list({})).rejects.toMatchObject({
    category: "network",
    code: "network_failure",
  });
  const timeout = createFoundryClient({
    ...config,
    timeoutMs: 5,
    fetch: async (_url, init) =>
      new Promise((_, reject) =>
        init?.signal?.addEventListener("abort", () => reject(new Error()), {
          once: true,
        }),
      ),
  });
  await expect(timeout.projects.list({})).rejects.toMatchObject({
    category: "timeout",
  });
});
it("cancels in-flight requests and invalidated clients", async () => {
  let signal: AbortSignal | undefined;
  const fetch: typeof globalThis.fetch = async (_url, init) =>
    new Promise((_, reject) => {
      signal = init?.signal ?? undefined;
      signal?.addEventListener("abort", () => reject(new Error()), {
        once: true,
      });
    });
  const client = createFoundryClient({ ...config, fetch });
  const pending = client.projects.list({});
  client.invalidate();
  await expect(pending).rejects.toMatchObject({ category: "cancelled" });
  expect(signal?.aborted).toBe(true);
  await expect(client.projects.list({})).rejects.toThrow("client_invalidated");
});
it("honors caller cancellation", async () => {
  const controller = new AbortController();
  controller.abort();
  const { client, fetch } = setup();
  await expect(
    client.projects.list({}, { signal: controller.signal }),
  ).rejects.toMatchObject({ category: "cancelled" });
  expect(fetch).not.toHaveBeenCalled();
});
it("invalidates on expiration or revocation and notifies once", async () => {
  const expired = vi.fn(),
    listener = vi.fn();
  const client = createFoundryClient({
    ...config,
    onSessionExpired: expired,
    fetch: async () => response({}, 401),
  });
  client.subscribe(listener);
  await expect(client.projects.list({})).rejects.toMatchObject({ status: 401 });
  expect(client.active).toBe(false);
  expect(expired).toHaveBeenCalledOnce();
  expect(listener).toHaveBeenCalledOnce();
  client.invalidate();
  expect(listener).toHaveBeenCalledOnce();
});
it("rejects nonfinite/cyclic and oversized JSON before fetch", async () => {
  const { client, fetch } = setup();
  await expect(
    client.objects.update({
      path: { ontology_id: "o", type_id: "T" },
      query: { object_id: "x" },
      body: { expected_version: 1, properties: { n: NaN } },
    }),
  ).rejects.toThrow("invalid_json");
  await expect(
    client.actions.execute({
      path: { ontology_id: "o", action_id: "a" },
      body: { idempotency_key: "k", parameters: { text: "x".repeat(66000) } },
    }),
  ).rejects.toThrow("request_too_large");
  expect(fetch).not.toHaveBeenCalled();
});
it("bounds response reads without trusting content-length", async () => {
  const client = createFoundryClient({
    ...config,
    fetch: async () =>
      new Response(
        new ReadableStream({
          start(c) {
            c.enqueue(new Uint8Array(5 * 1024 * 1024 + 1));
            c.close();
          },
        }),
      ),
  });
  await expect(client.projects.list({})).rejects.toThrow("response_too_large");
});
it("streams source downloads via existing transfer BFF", async () => {
  const fetch = vi.fn(async () => new Response(new Uint8Array([1, 2])));
  const client = createFoundryClient({ ...config, fetch });
  const id = "00000000-0000-0000-0000-000000000001";
  const stream = await client.datasets.download(id, id);
  expect((await stream.getReader().read()).value).toEqual(
    new Uint8Array([1, 2]),
  );
  expect((fetch.mock.calls[0] as unknown as [string])[0]).toContain(
    "family=datasets",
  );
});
it("uses existing login, session, tenant and logout routes", async () => {
  const fetch = vi.fn(async () => response({}));
  const auth = createSessionClient({ fetch });
  await auth.session(100);
  await auth.login();
  await auth.selectTenant("t", "csrf");
  await auth.logout("csrf");
  expect(fetch.mock.calls.map((c) => (c as unknown as [string])[0])).toEqual([
    "/auth/session?offset=100",
    "/auth/login",
    "/auth/tenant",
    "/auth/logout",
  ]);
  expect(() => auth.session(10001)).toThrow("invalid_page");
});
it("creates unique cache scope even for identical context", () => {
  expect(createFoundryClient(config).cacheId).not.toBe(
    createFoundryClient(config).cacheId,
  );
});
it("preserves authentication status even for malformed proxy errors", async () => {
  const c = createFoundryClient({
    ...config,
    fetch: async () => new Response("<html>proxy</html>", { status: 401 }),
  });
  await expect(c.projects.list({})).rejects.toMatchObject({
    status: 401,
    category: "authentication",
  });
  expect(c.active).toBe(false);
});
it("normalizes session network errors without exposing details", async () => {
  const auth = createSessionClient({
    fetch: async () => {
      throw new Error("private endpoint");
    },
  });
  await expect(auth.session()).rejects.toMatchObject({
    category: "network",
    code: "network_failure",
  });
});
it("classifies deadline expiry during retry backoff as timeout", async () => {
  const fetch = vi.fn(async () => response({ error: { code: "busy" } }, 503));
  const c = createFoundryClient({
    ...config,
    fetch,
    timeoutMs: 20,
    readRetries: 2,
  });
  await expect(c.projects.list({})).rejects.toMatchObject({
    category: "timeout",
    code: "request_timeout",
  });
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("omits nullable optional query values while preserving JSON body nulls", async () => {
  const { client, fetch } = setup([]);
  await client.projects.resources({
    path: { project_id: "p" },
    query: { folder_id: null, search: undefined },
  });
  expect(
    JSON.parse(
      (fetch.mock.calls[0] as unknown as [string, RequestInit])[1]
        .body as string,
    ).path,
  ).toBe("/api/v1/projects/p/resources");
  await client.objects.update({
    path: { ontology_id: "o", type_id: "T" },
    query: { object_id: "x" },
    body: { expected_version: 1, properties: { nullable: null } },
  });
  expect(
    JSON.parse(
      (fetch.mock.calls[1] as unknown as [string, RequestInit])[1]
        .body as string,
    ).body.properties.nullable,
  ).toBeNull();
});
