import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { exportJWK, generateKeyPair, SignJWT } from "jose";
const jar = vi.hoisted(() => new Map<string, string>());
vi.mock("next/headers", () => ({
  cookies: async () => ({ get: (name: string) => ({ value: jar.get(name) }) }),
}));
import { GET } from "../app/auth/[operation]/route";
import { beginLogin, session, sessions } from "../lib/server";
import { logCallbackFailure } from "../lib/auth-diagnostics";
beforeEach(() => {
  for (const [key, value] of Object.entries({
    STUDIO_ORIGIN: "https://foundry.csh.rit.edu",
    STUDIO_API_ORIGIN: "http://api:8000",
    STUDIO_INTERNAL_HTTP: "true",
    STUDIO_OIDC_ISSUER: "https://identity.example/realm",
    STUDIO_OIDC_CLIENT_ID: "foundry-studio",
    STUDIO_API_AUDIENCE: "foundry-api",
    STUDIO_STATE_SECRET: "",
    STUDIO_ENVIRONMENT: "development",
  }))
    vi.stubEnv(key, value);
  vi.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => {
  sessions.clear();
  jar.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
async function callback(fault = "") {
  const login = beginLogin(),
    issuer = process.env.STUDIO_OIDC_ISSUER!;
  jar.set("foundry-login", fault === "cookie" ? "unknown" : login.id);
  const keys = await generateKeyPair("RS256");
  const jwk = {
    ...(await exportJWK(keys.publicKey)),
    kid: "test",
    alg: "RS256",
  };
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("openid-configuration")) {
      if (fault === "transport")
        throw new TypeError("private transport detail");
      return Response.json({
        issuer,
        authorization_endpoint: issuer + "/authorize",
        token_endpoint: issuer + "/token",
        jwks_uri: issuer + "/keys",
        code_challenge_methods_supported: ["S256"],
      });
    }
    if (url.endsWith("/keys"))
      return fault === "json"
        ? new Response("private JSON")
        : Response.json({ keys: [jwk] });
    const form = init?.body as URLSearchParams;
    expect(form.get("client_id")).toBe("foundry-studio");
    expect(form.get("redirect_uri")).toBe(
      "https://foundry.csh.rit.edu/auth/callback",
    );
    expect(form.get("code_verifier")).toBe(login.verifier);
    expect(form.has("client_secret")).toBe(false);
    expect(
      (init?.headers as Record<string, string>).Authorization,
    ).toBeUndefined();
    if (fault === "grant")
      return Response.json(
        { error: "invalid_grant", error_description: "private" },
        { status: 400 },
      );
    const id = await new SignJWT({
      nonce: fault === "nonce" ? "wrong" : login.nonce,
    })
      .setProtectedHeader({ alg: "RS256", kid: "test" })
      .setIssuer(issuer)
      .setSubject("operator")
      .setAudience("foundry-studio")
      .setIssuedAt()
      .setExpirationTime("5m")
      .sign(keys.privateKey);
    const signer =
      fault === "signature"
        ? (await generateKeyPair("RS256")).privateKey
        : keys.privateKey;
    const access = await new SignJWT({
      jti: "one",
      ...(fault === "client_id" ? {} : { client_id: "foundry-studio" }),
    })
      .setProtectedHeader({
        alg: "RS256",
        kid: "test",
        typ: fault === "typ" ? "JWT" : "at+jwt",
      })
      .setIssuer(fault === "issuer" ? "https://other.example" : issuer)
      .setSubject("operator")
      .setAudience(fault === "audience" ? "account" : "foundry-api")
      .setIssuedAt()
      .setExpirationTime(fault === "expired" ? 1 : "5m")
      .sign(signer);
    return Response.json({
      access_token: access,
      id_token: id,
      token_type: "Bearer",
    });
  });
  vi.stubGlobal("fetch", fetch);
  const response = await GET(
    new Request(
      `https://foundry.csh.rit.edu/auth/callback?code=private-code&state=${fault === "state" ? "wrong" : login.state}`,
    ),
    { params: Promise.resolve({ operation: "callback" }) },
  );
  const logs = JSON.stringify(vi.mocked(console.error).mock.calls);
  for (const secret of [
    login.id,
    login.state,
    login.verifier,
    login.nonce,
    "private-code",
    "private transport detail",
    "private JSON",
  ])
    expect(logs).not.toContain(secret);
  return response;
}
it("completes the callback with PKCE and a public client", async () => {
  const response = await callback();
  expect(response.status).toBe(303);
  expect(response.headers.get("location")).toBe("https://foundry.csh.rit.edu/");
  expect(response.headers.get("set-cookie")).toContain("HttpOnly");
  expect(response.headers.get("set-cookie")).toContain("Secure");
  const id = /foundry-session=([^;]+)/.exec(
    response.headers.get("set-cookie")!,
  )![1];
  expect(session(id).token).toContain(".");
  expect(console.error).not.toHaveBeenCalled();
});
it.each([
  [
    "audience",
    "access_token",
    "ERR_JWT_CLAIM_VALIDATION_FAILED",
    "aud",
    401,
    "authentication_failed",
  ],
  [
    "client_id",
    "access_token",
    "ERR_JWT_CLAIM_VALIDATION_FAILED",
    "client_id",
    401,
    "authentication_failed",
  ],
  [
    "issuer",
    "access_token",
    "ERR_JWT_CLAIM_VALIDATION_FAILED",
    "iss",
    401,
    "authentication_failed",
  ],
  [
    "signature",
    "access_token",
    "ERR_JWS_SIGNATURE_VERIFICATION_FAILED",
    undefined,
    401,
    "authentication_failed",
  ],
  [
    "expired",
    "access_token",
    "ERR_JWT_EXPIRED",
    undefined,
    401,
    "authentication_failed",
  ],
  [
    "typ",
    "access_token_binding",
    "boundary_error",
    undefined,
    401,
    "invalid_access_token",
  ],
  [
    "nonce",
    "id_token_binding",
    "boundary_error",
    undefined,
    401,
    "invalid_nonce",
  ],
  [
    "cookie",
    "login_state",
    "boundary_error",
    undefined,
    401,
    "invalid_login_state",
  ],
  [
    "state",
    "login_state",
    "boundary_error",
    undefined,
    401,
    "invalid_login_state",
  ],
  [
    "grant",
    "token_exchange",
    "boundary_error",
    undefined,
    502,
    "identity_provider_unavailable",
  ],
  [
    "transport",
    "discovery",
    "type_or_transport_error",
    undefined,
    401,
    "authentication_failed",
  ],
  ["json", "jwks", "invalid_json", undefined, 401, "authentication_failed"],
])(
  "diagnoses %s without changing client errors",
  async (fault, stage, category, claim, status, code) => {
    const response = await callback(fault);
    expect(response.status).toBe(status);
    expect(await response.json()).toEqual({ error: { code } });
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(response.headers.get("referrer-policy")).toBe("no-referrer");
    expect(sessions.size).toBe(0);
    expect(JSON.parse(vi.mocked(console.error).mock.calls[0][0])).toEqual({
      event: "studio_auth_callback_failed",
      stage,
      category,
      ...(claim ? { claim } : {}),
      status,
    });
  },
);
it("does not serialize arbitrary thrown objects or error messages", () => {
  logCallbackFailure("discovery", {
    code: "secret",
    message: "secret",
    stack: "secret",
  });
  logCallbackFailure("discovery", new Error("secret"));
  expect(JSON.stringify(vi.mocked(console.error).mock.calls)).not.toContain(
    "secret",
  );
});
