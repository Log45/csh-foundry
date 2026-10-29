import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { exportJWK, generateKeyPair, SignJWT } from "jose";
import {
  allowed,
  authorization,
  backend,
  beginLogin,
  config,
  consumeLogin,
  csrfCheck,
  digest,
  exchange,
  issueSession,
  session,
  sessions,
} from "../lib/server";
beforeEach(() => {
  vi.stubEnv("STUDIO_ORIGIN", "http://127.0.0.1:3000");
  vi.stubEnv("STUDIO_OIDC_ISSUER", "https://identity.example/realm");
  vi.stubEnv("STUDIO_OIDC_CLIENT_ID", "studio");
  vi.stubEnv("STUDIO_API_AUDIENCE", "foundry");
  sessions.clear();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
describe("server session boundary", () => {
  it("rejects expired, forged and logged-out sessions", () => {
    expect(() => session("forged")).toThrow();
    const id = issueSession("private-token", Date.now() + 50000);
    expect(session(id).token).toBe("private-token");
    expect([...sessions.keys()]).not.toContain(id);
    sessions.delete(digest(id));
    expect(() => session(id)).toThrow();
    const old = issueSession("old", Date.now() - 1);
    expect(() => session(old)).toThrow();
  });
  it("binds single-use login state to browser cookie", () => {
    const a = beginLogin();
    expect(() => consumeLogin("attacker", a.state)).toThrow();
    expect(consumeLogin(a.id, a.state).verifier).toBe(a.verifier);
    expect(() => consumeLogin(a.id, a.state)).toThrow();
    const b = beginLogin();
    expect(() => consumeLogin(b.id, "wrong")).toThrow();
    expect(() => consumeLogin(b.id, b.state)).toThrow();
  });
  it("requires exact Origin and per-session CSRF for all browser operations", () => {
    const s = session(issueSession("token", Date.now() + 10000));
    const r = (origin: string, csrf: string) =>
      new Request("http://127.0.0.1:3000/bff", {
        method: "POST",
        headers: { origin, "x-csrf-token": csrf },
      });
    expect(() => csrfCheck(r("https://attacker.example", s.csrf), s)).toThrow();
    expect(() => csrfCheck(r(config().origin, "wrong"), s)).toThrow();
    expect(() => csrfCheck(r(config().origin, s.csrf), s)).not.toThrow();
  });
  it.each([
    "/api/v1/ontologies/../security/me",
    "/api/v1/ontologies/%2e%2e/versions",
    "/api/v1/ontologies/%252f/versions",
    "https://evil.example/api/v1/ontologies",
    "/api/v1/security/roles",
    "/api/v1/ontologies/a/versions?url=https://evil.example",
    "/api/v1/ontologies/%2f%2fevil/versions",
  ])("blocks proxy target %s", (path) =>
    expect(allowed(path, "GET")).toBe(false),
  );
  it("forwards only server token and verified tenant to fixed API origin", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response('{"ok":true}', {
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);
    await backend(
      {
        token: "secret",
        expires: Date.now() + 10000,
        csrf: "csrf",
        tenant: "authorized",
      },
      "/api/v1/ontologies",
    );
    expect(fetch.mock.calls[0][0]).toBe(
      "http://127.0.0.1:8000/api/v1/ontologies",
    );
    expect(fetch.mock.calls[0][1].headers).toEqual({
      Authorization: "Bearer secret",
      "X-Tenant-ID": "authorized",
    });
  });
});
async function provider(
  overrides: {
    nonce?: string;
    aud?: string;
    typ?: string;
    sub?: string;
    expired?: boolean;
  } = {},
) {
  const keys = await generateKeyPair("RS256"),
    jwk = await exportJWK(keys.publicKey);
  jwk.kid = "test";
  jwk.alg = "RS256";
  const login = beginLogin(),
    issuer = config().issuer;
  const id = await new SignJWT({ nonce: overrides.nonce ?? login.nonce })
    .setProtectedHeader({ alg: "RS256", kid: "test" })
    .setIssuer(issuer)
    .setSubject("operator")
    .setAudience("studio")
    .setIssuedAt()
    .setExpirationTime("5m")
    .sign(keys.privateKey);
  const access = await new SignJWT({ client_id: "studio", jti: "one" })
    .setProtectedHeader({
      alg: "RS256",
      kid: "test",
      typ: overrides.typ ?? "at+jwt",
    })
    .setIssuer(issuer)
    .setSubject(overrides.sub ?? "operator")
    .setAudience(overrides.aud ?? "foundry")
    .setIssuedAt()
    .setExpirationTime(overrides.expired ? 1 : "5m")
    .sign(keys.privateKey);
  const mock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("openid-configuration"))
      return Response.json({
        issuer,
        authorization_endpoint: issuer + "/authorize",
        token_endpoint: issuer + "/token",
        jwks_uri: issuer + "/keys",
        code_challenge_methods_supported: ["S256"],
      });
    if (url.endsWith("/keys")) return Response.json({ keys: [jwk] });
    expect(
      new URLSearchParams(init?.body as URLSearchParams).get("code_verifier"),
    ).toBe(login.verifier);
    return Response.json({
      access_token: access,
      id_token: id,
      token_type: "Bearer",
    });
  });
  vi.stubGlobal("fetch", mock);
  return { login, access };
}
it("completes Code + PKCE and stores only API access token server-side", async () => {
  const { login, access } = await provider();
  const url = await authorization(login);
  expect(url.searchParams.get("code_challenge")).toBe(digest(login.verifier));
  expect(url.searchParams.get("nonce")).toBe(login.nonce);
  const id = await exchange(
    "single-use-code",
    consumeLogin(login.id, login.state),
  );
  expect(session(id).token).toBe(access);
  expect(id).not.toContain(".");
});
it.each([
  { nonce: "wrong" },
  { aud: "another-api" },
  { typ: "JWT" },
  { sub: "other-subject" },
  { expired: true },
])("rejects invalid token binding %j", async (overrides) => {
  const { login } = await provider(overrides);
  await expect(exchange("code", login)).rejects.toThrow();
  expect(sessions.size).toBe(0);
});
it("rejects cross-origin discovery and unconfigured authentication", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      Response.json({
        issuer: config().issuer,
        code_challenge_methods_supported: ["S256"],
        authorization_endpoint: "https://evil.example",
        token_endpoint: "https://evil.example",
        jwks_uri: "https://evil.example",
      }),
    ),
  );
  await expect(authorization(beginLogin())).rejects.toThrow();
  vi.stubEnv("STUDIO_OIDC_ISSUER", "");
  expect(() => config()).toThrow();
});
