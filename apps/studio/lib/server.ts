// Server-only module: import only from route handlers. Never export tokens to components.
import { randomBytes, createHash, timingSafeEqual } from "node:crypto";
import { createLocalJWKSet, jwtVerify, type JSONWebKeySet } from "jose";
import contract from "./openapi.json";

export class BoundaryError extends Error {
  constructor(
    public status: number,
    public code: string,
  ) {
    super(code);
  }
}
export function config() {
  const origin = new URL(process.env.STUDIO_ORIGIN ?? "http://127.0.0.1:3000");
  const issuer = process.env.STUDIO_OIDC_ISSUER;
  const client = process.env.STUDIO_OIDC_CLIENT_ID;
  const audience = process.env.STUDIO_API_AUDIENCE;
  if (!issuer || !client || !audience)
    throw new BoundaryError(503, "authentication_not_configured");
  const loopback = (url: URL) =>
    ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if (
    origin.protocol !== "https:" &&
    !(origin.protocol === "http:" && loopback(origin))
  )
    throw new BoundaryError(503, "invalid_origin");
  const provider = new URL(issuer);
  const test =
    process.env.STUDIO_TEST_LOOPBACK_OIDC === "true" &&
    process.env.NODE_ENV !== "production" &&
    loopback(provider);
  if (
    provider.protocol !== "https:" &&
    !(test && provider.protocol === "http:")
  )
    throw new BoundaryError(503, "https_issuer_required");
  if (
    provider.search ||
    provider.hash ||
    provider.username ||
    provider.password
  )
    throw new BoundaryError(503, "invalid_issuer");
  const api = new URL(process.env.STUDIO_API_ORIGIN ?? "http://127.0.0.1:8000");
  if (
    !["https:", "http:"].includes(api.protocol) ||
    api.username ||
    api.password ||
    api.search ||
    api.hash ||
    api.pathname !== "/"
  )
    throw new BoundaryError(503, "invalid_api_origin");
  if (
    api.protocol === "http:" &&
    !loopback(api) &&
    process.env.STUDIO_INTERNAL_HTTP !== "true"
  )
    throw new BoundaryError(503, "https_api_required");
  return {
    origin: origin.origin,
    issuer,
    client,
    audience,
    api: api.origin,
    secure: origin.protocol === "https:",
  };
}
export const random = () => randomBytes(32).toString("base64url");
export const digest = (value: string) =>
  createHash("sha256").update(value).digest("base64url");
export function equal(a: string, b: string) {
  return (
    a.length === b.length && timingSafeEqual(Buffer.from(a), Buffer.from(b))
  );
}
export interface Session {
  token: string;
  expires: number;
  csrf: string;
  tenant?: string;
}
interface Login {
  state: string;
  nonce: string;
  verifier: string;
  expires: number;
}
const state = globalThis as typeof globalThis & {
  foundrySessions?: Map<string, Session>;
  foundryLogins?: Map<string, Login>;
};
export const sessions = (state.foundrySessions ??= new Map<string, Session>());
const logins = (state.foundryLogins ??= new Map<string, Login>());
function prune<T extends { expires: number }>(store: Map<string, T>) {
  for (const [key, value] of store)
    if (value.expires <= Date.now()) store.delete(key);
  if (store.size >= 1000) throw new BoundaryError(503, "session_capacity");
}
export function beginLogin() {
  prune(logins);
  const id = random(),
    login = {
      state: random(),
      nonce: random(),
      verifier: random(),
      expires: Date.now() + 300_000,
    };
  logins.set(digest(id), login);
  return { id, ...login };
}
export function consumeLogin(id: string, value: string) {
  const key = digest(id),
    login = logins.get(key);
  logins.delete(key);
  if (!login || login.expires <= Date.now() || !equal(login.state, value))
    throw new BoundaryError(401, "invalid_login_state");
  return login;
}
export function issueSession(token: string, expires: number) {
  prune(sessions);
  const id = random();
  sessions.set(digest(id), {
    token,
    expires: Math.min(expires, Date.now() + 3_600_000),
    csrf: random(),
  });
  return id;
}
export function session(id?: string) {
  const found = id ? sessions.get(digest(id)) : undefined;
  if (!found || found.expires <= Date.now()) {
    if (id) sessions.delete(digest(id));
    throw new BoundaryError(401, "session_expired");
  }
  return found;
}
export function originCheck(request: Request) {
  if (
    request.headers.get("origin") !== config().origin ||
    request.headers.get("sec-fetch-site") === "cross-site"
  )
    throw new BoundaryError(403, "invalid_origin");
}
export function csrfCheck(request: Request, value: Session) {
  originCheck(request);
  if (!equal(request.headers.get("x-csrf-token") ?? "", value.csrf))
    throw new BoundaryError(403, "invalid_csrf");
}
export async function bounded(response: Response, limit = 5 * 1024 * 1024) {
  const reader = response.body?.getReader();
  if (!reader) return "";
  let size = 0;
  const chunks: Uint8Array[] = [];
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) throw new BoundaryError(413, "payload_too_large");
      chunks.push(value);
    }
  } finally {
    await reader.cancel();
  }
  return Buffer.concat(chunks).toString("utf8");
}
export async function input(request: Request) {
  if (!request.headers.get("content-type")?.startsWith("application/json"))
    throw new BoundaryError(415, "json_required");
  return JSON.parse(await bounded(new Response(request.body), 65536)) as Record<
    string,
    unknown
  >;
}
async function document(url: string, options: RequestInit = {}) {
  const result = await fetch(url, {
    ...options,
    redirect: "error",
    cache: "no-store",
    signal: AbortSignal.timeout(5000),
  });
  if (!result.ok) throw new BoundaryError(502, "identity_provider_unavailable");
  return JSON.parse(await bounded(result, 262144));
}
export async function discovery() {
  const c = config();
  const data = await document(
    c.issuer.replace(/\/$/, "") + "/.well-known/openid-configuration",
  );
  if (
    data.issuer !== c.issuer ||
    !data.code_challenge_methods_supported?.includes("S256")
  )
    throw new BoundaryError(502, "invalid_discovery");
  for (const field of [
    "authorization_endpoint",
    "token_endpoint",
    "jwks_uri",
  ]) {
    const url = new URL(data[field]);
    if (
      url.origin !== new URL(c.issuer).origin ||
      url.username ||
      url.password ||
      url.search ||
      url.hash
    )
      throw new BoundaryError(502, "invalid_discovery");
  }
  return data as {
    issuer: string;
    authorization_endpoint: string;
    token_endpoint: string;
    jwks_uri: string;
  };
}
export async function authorization(login: ReturnType<typeof beginLogin>) {
  const c = config(),
    metadata = await discovery();
  const url = new URL(metadata.authorization_endpoint);
  url.search = new URLSearchParams({
    client_id: c.client,
    redirect_uri: c.origin + "/auth/callback",
    response_type: "code",
    scope: "openid",
    state: login.state,
    nonce: login.nonce,
    code_challenge: digest(login.verifier),
    code_challenge_method: "S256",
    audience: c.audience,
  }).toString();
  return url;
}
export async function exchange(
  code: string,
  login: ReturnType<typeof consumeLogin>,
) {
  const c = config(),
    metadata = await discovery();
  if (!code || code.length > 4096) throw new BoundaryError(401, "invalid_code");
  const tokens = await document(metadata.token_endpoint, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      client_id: c.client,
      code,
      redirect_uri: c.origin + "/auth/callback",
      code_verifier: login.verifier,
    }),
  });
  if (
    tokens.token_type?.toLowerCase() !== "bearer" ||
    typeof tokens.access_token !== "string" ||
    typeof tokens.id_token !== "string" ||
    tokens.access_token.length > 16384 ||
    tokens.id_token.length > 16384
  )
    throw new BoundaryError(401, "invalid_token_response");
  const jwks = (await document(metadata.jwks_uri)) as JSONWebKeySet;
  if (
    !Array.isArray(jwks.keys) ||
    jwks.keys.length < 1 ||
    jwks.keys.length > 32
  )
    throw new BoundaryError(401, "invalid_jwks");
  const keys = createLocalJWKSet(jwks);
  const id = await jwtVerify(tokens.id_token, keys, {
    issuer: c.issuer,
    audience: c.client,
    algorithms: ["RS256", "ES256"],
    requiredClaims: ["sub", "iat", "exp", "nonce"],
  });
  if (
    id.payload.nonce !== login.nonce ||
    (Array.isArray(id.payload.aud) &&
      id.payload.aud.length > 1 &&
      id.payload.azp !== c.client) ||
    (id.payload.azp !== undefined && id.payload.azp !== c.client)
  )
    throw new BoundaryError(401, "invalid_nonce");
  const access = await jwtVerify(tokens.access_token, keys, {
    issuer: c.issuer,
    audience: c.audience,
    algorithms: ["RS256", "ES256"],
    requiredClaims: ["sub", "exp", "iat", "jti", "client_id"],
  });
  const p = access.payload,
    h = access.protectedHeader;
  if (
    !["at+jwt", "application/at+jwt"].includes(h.typ ?? "") ||
    ["jku", "x5u", "jwk", "crit"].some((key) => key in h) ||
    p.sub !== id.payload.sub ||
    p.client_id !== c.client ||
    (p.azp !== undefined && p.azp !== c.client) ||
    (p.token_use !== undefined && p.token_use !== "access") ||
    !Number.isInteger(p.iat) ||
    !Number.isInteger(p.exp) ||
    (p.iat as number) >= (p.exp as number) ||
    typeof p.jti !== "string" ||
    !p.jti ||
    !p.sub ||
    p.sub.length > 512 ||
    (p.iat as number) > Date.now() / 1000
  )
    throw new BoundaryError(401, "invalid_access_token");
  // ID tokens are used only above; only the independently validated API access token is retained.
  return issueSession(tokens.access_token, (p.exp as number) * 1000);
}
export function allowed(path: string, method: string) {
  if (
    path.length > 20000 ||
    !path.startsWith("/api/v1/") ||
    path.includes("#") ||
    path.includes("\\")
  )
    return false;
  const [pathname, search = ""] = path.split("?");
  const segments = pathname.split("/");
  try {
    if (
      segments.some((s) => {
        const d = decodeURIComponent(s);
        return d === "." || d === ".." || /[/%\\?#\x00-\x20]/.test(d);
      })
    )
      return false;
  } catch {
    return false;
  }
  if (
    pathname.startsWith("/api/v1/security/") &&
    !["/api/v1/security/me", "/api/v1/security/tenants"].includes(pathname)
  )
    return false;
  if (pathname === "/api/v1/tenant" || pathname === "/api/v1/openapi.json")
    return false;
  if (
    [...new URLSearchParams(search).keys()].some(
      (k) =>
        ![
          "limit",
          "offset",
          "cursor",
          "version",
          "direction",
          "expected_version",
          "object_id",
          "expected_hash",
        ].includes(k),
    )
  )
    return false;
  return Object.entries(contract.paths).some(([template, ops]) => {
    const parts = template.split("/");
    return (
      method.toLowerCase() in ops &&
      parts.length === segments.length &&
      parts.every((p, i) =>
        p.startsWith("{") ? !!segments[i] : p === segments[i],
      )
    );
  });
}
export async function backend(
  value: Session,
  path: string,
  method = "GET",
  body?: unknown,
  tenant = value.tenant,
) {
  if (!allowed(path, method))
    throw new BoundaryError(400, "unsupported_operation");
  const response = await fetch(config().api + path, {
    method,
    headers: {
      Authorization: `Bearer ${value.token}`,
      ...(tenant ? { "X-Tenant-ID": tenant } : {}),
      ...(body === undefined ? {} : { "content-type": "application/json" }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
    redirect: "error",
    signal: AbortSignal.timeout(45000),
  });
  const text = await bounded(response);
  if (!response.ok) {
    // Return only the backend's sanitized structured error, never transport details or tokens.
    let code = "backend_error";
    try {
      code = JSON.parse(text).error?.code ?? code;
    } catch {
      /* sanitized */
    }
    throw new BoundaryError(response.status, code);
  }
  return text
    ? response.headers.get("content-type")?.includes("application/json")
      ? (JSON.parse(text) as unknown)
      : text
    : null;
}
