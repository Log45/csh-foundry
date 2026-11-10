import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { exportJWK, generateKeyPair, SignJWT } from "jose";
const jar = vi.hoisted(() => new Map<string, string>());
vi.mock("next/headers", () => ({
  cookies: async () => ({ get: (name: string) => ({ value: jar.get(name) }) }),
}));
import { GET } from "../app/auth/[operation]/route";
import cases from "../../../fixtures/security/access-token-profiles.json";
import { beginLogin, config, session, sessions } from "../lib/server";
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
  vi.stubEnv("FOUNDRY_OIDC_PROVIDERS", undefined);
  vi.stubEnv("STUDIO_DIAGNOSTIC_OIDC_AUDIENCE", "false");
  vi.spyOn(console, "info").mockImplementation(() => {});
  vi.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => {
  sessions.clear();
  jar.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
async function callback(
  fault = "",
  options: {
    claims?: Record<string, unknown>;
    header?: Record<string, unknown>;
    omit?: string[];
  } = {},
) {
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
    const now = Math.floor(Date.now() / 1000);
    const claims: Record<string, unknown> = {
      jti: "one",
      client_id: "foundry-studio",
      iss: fault === "issuer" ? "https://other.example" : issuer,
      sub: "operator",
      aud: fault === "audience" ? "account" : "foundry-api",
      iat: now,
      exp: fault === "expired" ? 1 : now + 300,
      ...options.claims,
    };
    for (const key of [
      ...(options.omit ?? []),
      ...(fault === "client_id" ? ["client_id"] : []),
    ])
      delete claims[key];
    const access =
      fault === "id_as_access"
        ? id
        : await new SignJWT(claims)
            .setProtectedHeader({
              alg: "RS256",
              kid: "test",
              typ: fault === "typ" ? "JWT" : "at+jwt",
              ...options.header,
            })
            .sign(
              options.header?.alg === "HS256"
                ? new TextEncoder().encode(
                    "test-secret-long-enough-for-hmac-sha256",
                  )
                : signer,
            );
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
  const logs = JSON.stringify([
    vi.mocked(console.error).mock.calls,
    vi.mocked(console.info).mock.calls,
  ]);
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

function policy(profile: string = "keycloak") {
  return [
    {
      id: "keycloak",
      issuer: "https://identity.example/realm",
      audience: "foundry-api",
      clients: ["foundry-studio", "foundry-worker"],
      algorithms: ["RS256"],
      access_token_profile: profile,
    },
  ];
}
it.each(["rfc9068", "keycloak"])(
  "enforces shared client and JWT contracts: %s",
  async (profile) => {
    vi.stubEnv("FOUNDRY_OIDC_PROVIDERS", JSON.stringify(policy(profile)));
    for (const entry of cases) {
      sessions.clear();
      vi.mocked(console.error).mockClear();
      const response = await callback("", entry);
      expect(response.status, entry.name).toBe(
        entry[profile as "rfc9068" | "keycloak"] ? 303 : 401,
      );
      if (response.status !== 303) {
        expect(sessions.size, entry.name).toBe(0);
        expect(await response.json()).toHaveProperty("error.code");
        expect(console.error).toHaveBeenCalledOnce();
      }
    }
  },
);
it.each(["rfc9068", "keycloak"])(
  "retains signature, algorithm, nonce and subject checks: %s",
  async (profile) => {
    vi.stubEnv("FOUNDRY_OIDC_PROVIDERS", JSON.stringify(policy(profile)));
    for (const fault of ["signature", "nonce", "id_as_access"]) {
      const response = await callback(fault);
      expect(response.status).toBe(401);
      expect(sessions.size).toBe(0);
    }
    expect(
      (await callback("", { claims: { sub: "another-subject" } })).status,
    ).toBe(401);
    expect((await callback("", { header: { alg: "HS256" } })).status).toBe(401);
    expect(sessions.size).toBe(0);
  },
);
it.each([
  "garbage",
  "null",
  "[]",
  JSON.stringify(policy("unknown")),
  JSON.stringify(policy().map((p) => ({ ...p, audience: "other" }))),
  JSON.stringify(policy().map((p) => ({ ...p, clients: ["other"] }))),
  JSON.stringify([...policy(), ...policy()]),
])("fails closed on invalid shared provider configuration: %s", (raw) => {
  vi.stubEnv("FOUNDRY_OIDC_PROVIDERS", raw);
  expect(() => config()).toThrow("invalid_oidc_provider_configuration");
});
it("uses strict defaults when profile is omitted and limits algorithms from shared policy", () => {
  expect(config().profile).toBe("rfc9068");
  const providers: Record<string, unknown>[] = policy();
  delete providers[0].access_token_profile;
  vi.stubEnv("FOUNDRY_OIDC_PROVIDERS", JSON.stringify(providers));
  expect(config().profile).toBe("rfc9068");
  expect(config().algorithms).toEqual(["RS256"]);
});

it("does not emit audience metadata unless explicitly enabled", async () => {
  expect((await callback("audience")).status).toBe(401);
  expect(console.info).not.toHaveBeenCalled();
});
it.each(["rfc9068", "keycloak"])(
  "reports only the verified audience and still rejects a mismatch (%s)",
  async (profile) => {
    vi.stubEnv("FOUNDRY_OIDC_PROVIDERS", JSON.stringify(policy(profile)));
    vi.stubEnv("STUDIO_DIAGNOSTIC_OIDC_AUDIENCE", "true");
    const response = await callback("audience", {
      claims: { private_claim: "private-payload" },
    });
    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({
      error: { code: "authentication_failed" },
    });
    expect(sessions.size).toBe(0);
    expect(console.info).toHaveBeenCalledOnce();
    expect(JSON.parse(vi.mocked(console.info).mock.calls[0][0])).toEqual({
      event: "studio_oidc_access_token_audience",
      audience: "account",
      audience_status: "present",
      expected_audience: "foundry-api",
    });
    expect(JSON.stringify(vi.mocked(console.info).mock.calls)).not.toContain(
      "private-payload",
    );
  },
);
it("reports an audience array without changing successful authentication", async () => {
  vi.stubEnv("STUDIO_DIAGNOSTIC_OIDC_AUDIENCE", "true");
  expect(
    (await callback("", { claims: { aud: ["foundry-api", "another-api"] } }))
      .status,
  ).toBe(303);
  expect(JSON.parse(vi.mocked(console.info).mock.calls[0][0]).audience).toEqual(
    ["foundry-api", "another-api"],
  );
});
it.each(["signature", "issuer", "expired"])(
  "does not report audience for %s failures",
  async (fault) => {
    vi.stubEnv("STUDIO_DIAGNOSTIC_OIDC_AUDIENCE", "true");
    expect((await callback(fault)).status).toBe(401);
    expect(console.info).not.toHaveBeenCalled();
    expect(sessions.size).toBe(0);
  },
);
it.each(["exp", "iat"])(
  "does not report audience with missing %s",
  async (claim) => {
    vi.stubEnv("STUDIO_DIAGNOSTIC_OIDC_AUDIENCE", "true");
    expect((await callback("", { omit: [claim] })).status).toBe(401);
    expect(console.info).not.toHaveBeenCalled();
  },
);
it("reports a missing audience explicitly without accepting the token", async () => {
  vi.stubEnv("STUDIO_DIAGNOSTIC_OIDC_AUDIENCE", "true");
  expect((await callback("", { omit: ["aud"] })).status).toBe(401);
  expect(JSON.parse(vi.mocked(console.info).mock.calls[0][0])).toMatchObject({
    audience: null,
    audience_status: "missing",
  });
  expect(sessions.size).toBe(0);
});
it.each([
  "x".repeat(257),
  "injected\nline",
  Array(17).fill("value"),
  { secret: "private-value" },
])("omits invalid or oversized audience data from logs", async (aud) => {
  vi.stubEnv("STUDIO_DIAGNOSTIC_OIDC_AUDIENCE", "true");
  expect((await callback("", { claims: { aud } })).status).toBe(401);
  expect(JSON.parse(vi.mocked(console.info).mock.calls[0][0])).toMatchObject({
    audience: null,
    audience_status: "omitted_invalid_or_oversized",
  });
  expect(sessions.size).toBe(0);
});
