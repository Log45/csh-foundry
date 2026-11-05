import { expect, it, vi } from "vitest";
import { createFoundryClient } from "@foundry/sdk";
const config = {
  tenantId: "tenant",
  principalId: "user",
  sessionKey: "s",
  auth: { csrf: "secret-csrf" },
  readRetries: 0 as const,
};
it("uses generated typed function and automation contracts through the existing BFF", async () => {
  const fetch = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) =>
    Response.json({ id: "run", state: "QUEUED" }),
  );
  const client = createFoundryClient({ ...config, fetch });
  const body = {
    definition_id: "version",
    inputs: { text: "hello" },
    idempotency_key: "once",
  };
  await client.functions.invoke({ path: { function_id: "fn" }, body });
  expect(JSON.parse(String(fetch.mock.calls[0][1]!.body))).toMatchObject({
    path: "/api/v1/functions/fn/runs",
    body,
    expected_tenant: "tenant",
  });
  await client.automations.activate({
    path: { automation_id: "auto" },
    body: { definition_id: "v", enabled: false },
  });
  expect(JSON.parse(String(fetch.mock.calls[1][1]!.body)).method).toBe("PUT");
  client.invalidate();
  await expect(
    client.mediaSets.items({ path: { set_id: "set" } }),
  ).rejects.toMatchObject({ code: "client_invalidated" });
});
it("streams media outside query caches with CSRF and tenant checks", async () => {
  const fetch = vi.fn(
    async (_url: RequestInfo | URL, _init?: RequestInit) =>
      new Response(new Uint8Array([1, 2, 3])),
  );
  const client = createFoundryClient({ ...config, fetch });
  const set = "11111111-1111-4111-8111-111111111111",
    item = "22222222-2222-4222-8222-222222222222";
  const result = await client.mediaSets.preview(set, item);
  expect(result).toBeInstanceOf(ReadableStream);
  expect(fetch.mock.calls[0][0]).toContain("family=media-sets");
  expect(fetch.mock.calls[0][0]).toContain("operation=preview");
  expect(fetch.mock.calls[0][1]!.headers).toMatchObject({
    "x-csrf-token": "secret-csrf",
    "x-expected-tenant": "tenant",
  });
  await result.cancel();
});
