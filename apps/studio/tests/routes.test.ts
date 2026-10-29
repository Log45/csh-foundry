import { beforeEach, afterEach, it, expect, vi } from "vitest";
const jar = vi.hoisted(() => ({ id: "" }));
vi.mock("next/headers", () => ({
  cookies: async () => ({ get: () => ({ value: jar.id }) }),
}));
import { POST } from "../app/bff/route";
import { POST as auth } from "../app/auth/[operation]/route";
import { issueSession, session, sessions } from "../lib/server";
beforeEach(() => {
  vi.stubEnv("STUDIO_ORIGIN", "http://127.0.0.1:3000");
  vi.stubEnv("STUDIO_OIDC_ISSUER", "https://identity.example/realm");
  vi.stubEnv("STUDIO_OIDC_CLIENT_ID", "studio");
  vi.stubEnv("STUDIO_API_AUDIENCE", "foundry");
  jar.id = issueSession("private", Date.now() + 60000);
  session(jar.id).tenant = "tenant-a";
});
afterEach(() => {
  sessions.clear();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
function request(body: unknown, csrf = session(jar.id).csrf) {
  return new Request("http://127.0.0.1:3000/bff", {
    method: "POST",
    headers: {
      origin: "http://127.0.0.1:3000",
      "content-type": "application/json",
      "x-csrf-token": csrf,
    },
    body: JSON.stringify(body),
  });
}
it("blocks a queued mutation from another selected tenant before upstream I/O", async () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  const response = await POST(
    request({
      path: "/api/v1/ontologies",
      method: "POST",
      expected_tenant: "previous-tenant",
      body: {},
    }),
  );
  expect(response.status).toBe(409);
  expect(fetch).not.toHaveBeenCalled();
  expect(response.headers.get("cache-control")).toBe("no-store");
});
it("returns sanitized backend errors without reflecting tokens or arbitrary bodies", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        Response.json(
          { error: { code: "forbidden", message: "server private detail" } },
          { status: 403 },
        ),
      ),
  );
  const response = await POST(
    request({
      path: "/api/v1/ontologies",
      method: "GET",
      expected_tenant: "tenant-a",
    }),
  );
  expect(response.status).toBe(403);
  expect(await response.json()).toEqual({ error: { code: "forbidden" } });
});
it("requires CSRF for logout and invalidates the session on success", async () => {
  const params = { params: Promise.resolve({ operation: "logout" }) };
  expect((await auth(request({}, "wrong"), params)).status).toBe(403);
  const response = await auth(request({}), params);
  expect(response.status).toBe(200);
  expect(() => session(jar.id)).toThrow();
  expect(response.headers.get("set-cookie")).toContain("HttpOnly");
});
it("rejects unauthorized tenant selection without mutating the session", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        Response.json({ error: { code: "forbidden" } }, { status: 403 }),
      ),
  );
  const response = await auth(
    request({ tenant: "00000000-0000-0000-0000-000000000002" }),
    { params: Promise.resolve({ operation: "tenant" }) },
  );
  expect(response.status).toBe(403);
  expect(session(jar.id).tenant).toBe("tenant-a");
});
