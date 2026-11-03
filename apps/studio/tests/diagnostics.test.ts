import { afterEach, expect, it, vi } from "vitest";
import { diagnosticFetch, diagnosticRequest } from "../lib/diagnostics";
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});
it("keeps concurrent trace contexts separate and redacts request contents", async () => {
  vi.stubEnv("STUDIO_DIAGNOSTIC_TIMING", "true");
  const logs = vi.spyOn(console, "info").mockImplementation(() => {});
  const parents: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url, options) => {
      parents.push(new Headers(options.headers).get("traceparent")!);
      await Promise.resolve();
      return Response.json({ ok: true });
    }),
  );
  const traces = ["1", "2"].map(
    (c) => `00-${c.repeat(32)}-${"3".repeat(16)}-01`,
  );
  await Promise.all(
    traces.map((parent) =>
      diagnosticRequest(
        new Request("https://studio/bff", {
          headers: { traceparent: parent },
        }),
        () =>
          diagnosticFetch("backend_headers_ms", "https://api/private-path", {
            headers: { authorization: "Bearer secret" },
            body: "sensitive",
            method: "POST",
          }),
      ),
    ),
  );
  expect(parents.sort()).toEqual(traces);
  expect(logs).toHaveBeenCalledTimes(2);
  const text = JSON.stringify(logs.mock.calls);
  expect(text).not.toMatch(/secret|sensitive|private-path/);
  await diagnosticFetch("backend_headers_ms", "https://api", {});
  expect(parents[2]).toBeNull();
});
it("leaves diagnostics disabled by default", async () => {
  const logs = vi.spyOn(console, "info").mockImplementation(() => {});
  const response = await diagnosticRequest(
    new Request("https://studio/bff"),
    async () => Response.json({ ok: true }),
  );
  expect(response.status).toBe(200);
  expect(logs).not.toHaveBeenCalled();
});
