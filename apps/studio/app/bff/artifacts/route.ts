import { cookies } from "next/headers";
import { BoundaryError, browserSession, config, csrfCheck } from "@/lib/server";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const MAX = 64 * 1024 * 1024;
// Binary transfers use a dedicated, fixed-destination path. JSON BFF limits stay unchanged.
export async function POST(request: Request) {
  try {
    const value = await browserSession(
      (await cookies()).get("foundry-session")?.value,
    );
    csrfCheck(request, value);
    if (!value.tenant)
      throw new BoundaryError(403, "tenant_selection_required");
    if (request.headers.get("x-expected-tenant") !== value.tenant)
      throw new BoundaryError(409, "tenant_changed");
    const url = new URL(request.url);
    const family = url.searchParams.get("family") ?? "artifacts";
    if (!["artifacts", "datasets"].includes(family))
      throw new BoundaryError(400, "invalid_transfer");
    const artifact = url.searchParams.get("artifact");
    const version = url.searchParams.get("version");
    const operation = url.searchParams.get("operation");
    const uuid =
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (
      !artifact ||
      !version ||
      !uuid.test(artifact) ||
      !uuid.test(version) ||
      !["upload", "download"].includes(operation ?? "")
    )
      throw new BoundaryError(400, "invalid_transfer");
    const length = request.headers.get("content-length");
    if (length && (!/^\d+$/.test(length) || Number(length) > MAX))
      throw new BoundaryError(413, "transfer_too_large");
    let count = 0;
    const bound = () =>
      new TransformStream<Uint8Array, Uint8Array>({
        transform(chunk, controller) {
          count += chunk.byteLength;
          if (count > MAX) throw new BoundaryError(413, "transfer_too_large");
          controller.enqueue(chunk);
        },
      });
    const upload = operation === "upload";
    const response = await fetch(
      `${config().api}/api/v1/${family}/${artifact}/versions/${version}/content`,
      {
        method: upload ? "PUT" : "GET",
        headers: {
          Authorization: `Bearer ${value.token}`,
          "X-Tenant-ID": value.tenant,
          "Content-Type": "application/octet-stream",
        },
        ...(upload && request.body
          ? { body: request.body.pipeThrough(bound()), duplex: "half" }
          : {}),
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.timeout(55000),
      } as RequestInit,
    );
    if (!response.ok) {
      await response.body?.cancel();
      // Fixed error categories; never reflect provider responses, credentials or endpoint details.
      const code =
        response.status === 403
          ? "forbidden"
          : response.status === 503
            ? "storage_unavailable"
            : "transfer_failed";
      throw new BoundaryError(response.status, code);
    }
    count = 0;
    return new Response(response.body?.pipeThrough(bound()), {
      headers: {
        "Content-Type": upload
          ? "application/json"
          : "application/octet-stream",
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        ...(!upload
          ? { "Content-Disposition": 'attachment; filename="artifact.bin"' }
          : {}),
      },
    });
  } catch (error) {
    const e =
      error instanceof BoundaryError
        ? error
        : new BoundaryError(502, "storage_unavailable");
    return Response.json(
      { error: { code: e.code } },
      { status: e.status, headers: { "Cache-Control": "no-store" } },
    );
  }
}
