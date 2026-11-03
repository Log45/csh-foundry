// Optional diagnostic context, scoped to one BFF request and bounded to stage totals.
import { AsyncLocalStorage } from "node:async_hooks";
import { randomBytes } from "node:crypto";
const context = new AsyncLocalStorage<{
  parent: string;
  stages: Record<string, number>;
}>();
export async function diagnosticRequest(
  request: Request,
  run: () => Promise<Response>,
) {
  if (process.env.STUDIO_DIAGNOSTIC_TIMING !== "true") return run();
  const incoming = request.headers.get("traceparent") ?? "";
  const parent =
    /^00-(?!0{32})[a-f0-9]{32}-(?!0{16})[a-f0-9]{16}-[a-f0-9]{2}$/.test(
      incoming,
    )
      ? incoming
      : `00-${randomBytes(16).toString("hex")}-${randomBytes(8).toString("hex")}-01`;
  return context.run({ parent, stages: {} }, async () => {
    const started = performance.now();
    try {
      return await run();
    } finally {
      console.info(
        JSON.stringify({
          event: "bff_span",
          timestamp: new Date().toISOString(),
          trace_id: parent.split("-")[1],
          duration_ms: performance.now() - started,
          stages: context.getStore()!.stages,
        }),
      );
    }
  });
}
export async function diagnosticFetch(
  stage: string,
  url: string,
  options: RequestInit,
) {
  const value = context.getStore();
  if (!value) return fetch(url, options);
  const headers = new Headers(options.headers);
  headers.set("traceparent", value.parent);
  const started = performance.now();
  try {
    return await fetch(url, { ...options, headers });
  } finally {
    value.stages[stage] =
      (value.stages[stage] ?? 0) + performance.now() - started;
  }
}
