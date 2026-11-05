import { cookies } from "next/headers";
import { BoundaryError, browserSession, config, csrfCheck } from "@/lib/server";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const MAX = 1024 ** 3;
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
    if (!["artifacts", "datasets", "media-sets"].includes(family))
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
      !["upload", "download", "preview"].includes(operation ?? "") ||
      (family === "media-sets"
        ? operation === "upload"
        : operation === "preview")
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
    const target =
      family === "media-sets"
        ? `${config().api}/api/v1/media-sets/${artifact}/items/${version}/content?preview=${operation === "preview"}`
        : `${config().api}/api/v1/${family}/${artifact}/versions/${version}/content`;
    const response = await fetch(target, {
      method: upload ? "PUT" : "GET",
      headers: {
        Authorization: `Bearer ${value.token}`,
        "X-Tenant-ID": value.tenant,
        "Content-Type":
          operation === "preview" ? "image/jpeg" : "application/octet-stream",
      },
      ...(upload && request.body
        ? { body: request.body.pipeThrough(bound()), duplex: "half" }
        : {}),
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(1800000),
    } as RequestInit);
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
          : operation === "preview"
            ? "image/jpeg"
            : "application/octet-stream",
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
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
      {
        status: e.status,
        headers: {
          "Cache-Control": "no-store",
          "Content-Security-Policy":
            "default-src 'none'; frame-ancestors 'none'",
        },
      },
    );
  }
}
