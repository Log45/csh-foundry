import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import {
  authorization,
  backend,
  beginBrowserLogin,
  BoundaryError,
  config,
  consumeBrowserLogin,
  csrfCheck,
  exchange,
  input,
  originCheck,
  browserSession,
  revokeBrowserSession,
  selectBrowserTenant,
  brokerLogout,
} from "@/lib/server";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const sessionName = "foundry-session",
  loginName = "foundry-login";
function options(age: number) {
  return {
    httpOnly: true,
    secure: config().secure,
    sameSite: "lax" as const,
    path: "/",
    maxAge: age,
  };
}
async function handle(
  request: Request,
  context: { params: Promise<{ operation: string }> },
) {
  const jar = await cookies();
  const { operation } = await context.params;
  try {
    if (operation === "login" && request.method === "POST") {
      originCheck(request);
      const login = await beginBrowserLogin();
      const url = await authorization(login);
      const result = NextResponse.json({ authorization: url.href });
      result.cookies.set(loginName, login.id, options(300));
      return result;
    }
    if (operation === "callback" && request.method === "GET") {
      const url = new URL(request.url);
      const login = await consumeBrowserLogin(
        jar.get(loginName)?.value ?? "",
        url.searchParams.get("state") ?? "",
      );
      const id = await exchange(url.searchParams.get("code") ?? "", login);
      const old = jar.get(sessionName)?.value;
      if (old) await revokeBrowserSession(old);
      const result = NextResponse.redirect(config().origin, 303);
      result.cookies.set(sessionName, id, options(3600));
      result.cookies.set(loginName, "", options(0));
      return result;
    }
    const value = await browserSession(jar.get(sessionName)?.value);
    if (operation === "session" && request.method === "GET") {
      const offset = new URL(request.url).searchParams.get("offset") ?? "0";
      if (!/^[0-9]{1,5}$/.test(offset) || Number(offset) > 10000)
        throw new BoundaryError(400, "invalid_page");
      const tenants = await backend(
        value,
        `/api/v1/security/tenants?limit=100&offset=${offset}`,
      );
      const me = value.tenant
        ? await backend(value, "/api/v1/security/me")
        : null;
      return NextResponse.json(
        {
          csrf: value.csrf,
          tenant: value.tenant,
          tenants,
          me,
          expires: value.expires,
        },
        { headers: { "Cache-Control": "no-store" } },
      );
    }
    if (request.method !== "POST")
      throw new BoundaryError(405, "method_not_allowed");
    csrfCheck(request, value);
    if (operation === "logout") {
      await revokeBrowserSession(jar.get(sessionName)!.value);
      // Local invalidation succeeds even during a broker outage. No tokens in logout URLs.
      const logout = await brokerLogout().catch(() => undefined);
      const result = NextResponse.json({ status: "signed_out", logout });
      result.cookies.set(sessionName, "", options(0));
      return result;
    }
    if (operation === "tenant") {
      const { tenant } = await input(request);
      if (typeof tenant !== "string" || !/^[a-f0-9-]{36}$/.test(tenant))
        throw new BoundaryError(403, "forbidden");
      await backend(value, "/api/v1/security/me", "GET", undefined, tenant);
      await selectBrowserTenant(jar.get(sessionName)!.value, value, tenant);
      return NextResponse.json({ status: "selected" });
    }
    throw new BoundaryError(404, "not_found");
  } catch (error) {
    const failure =
      error instanceof BoundaryError
        ? error
        : new BoundaryError(401, "authentication_failed");
    return NextResponse.json(
      { error: { code: failure.code } },
      { status: failure.status, headers: { "Cache-Control": "no-store" } },
    );
  }
}
async function protectedHandle(
  request: Request,
  context: { params: Promise<{ operation: string }> },
) {
  const response = await handle(request, context);
  response.headers.set("Cache-Control", "no-store");
  response.headers.set("Referrer-Policy", "no-referrer");
  return response;
}
export const GET = protectedHandle;
export const POST = protectedHandle;
