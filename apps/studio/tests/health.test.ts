import { afterEach, expect, it, vi } from "vitest";
import { GET as live } from "../app/health/live/route";
import { GET as ready } from "../app/health/ready/route";
vi.mock("../lib/server", () => ({
  config: () => ({ api: "http://api:8000" }),
}));
afterEach(() => vi.unstubAllGlobals());
it("keeps liveness independent of dependencies", () => {
  expect(live().status).toBe(200);
});
it("readiness reflects API availability without credentials", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response("", { status: 503 }));
  vi.stubGlobal("fetch", fetch);
  expect((await ready()).status).toBe(503);
  fetch.mockResolvedValue(new Response("", { status: 200 }));
  expect((await ready()).status).toBe(200);
  expect(fetch.mock.calls[0][1].headers).toBeUndefined();
});
