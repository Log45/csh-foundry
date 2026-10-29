import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import {
  backend,
  BoundaryError,
  csrfCheck,
  input,
  session,
} from "@/lib/server";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function POST(request: Request) {
  try {
    const value = session((await cookies()).get("foundry-session")?.value);
    csrfCheck(request, value);
    if (!value.tenant)
      throw new BoundaryError(403, "tenant_selection_required");
    const { path, method, body, expected_tenant } = await input(request);
    if (expected_tenant !== value.tenant)
      throw new BoundaryError(409, "tenant_changed");
    if (
      typeof path !== "string" ||
      typeof method !== "string" ||
      !["GET", "POST", "PUT", "PATCH", "DELETE"].includes(method)
    )
      throw new BoundaryError(400, "invalid_request");
    const data = await backend(value, path, method, body);
    return NextResponse.json(data, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    const e =
      error instanceof BoundaryError
        ? error
        : new BoundaryError(502, "backend_unavailable");
    return NextResponse.json(
      { error: { code: e.code } },
      { status: e.status, headers: { "Cache-Control": "no-store" } },
    );
  }
}
