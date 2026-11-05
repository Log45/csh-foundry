import { FoundryError, responseError } from "./errors.js";
export interface RequestOptions {
  signal?: AbortSignal;
}
export type Transport = <T>(
  method: string,
  path: string,
  input: { path?: object; query?: object; body?: unknown },
  read: boolean,
  options?: RequestOptions,
) => Promise<T>;
export interface ClientConfig {
  /** Same-origin API path sent to the approved BFF. */
  baseUrl?: string;
  bffUrl?: string;
  tenantId: string;
  principalId: string;
  /** New opaque generation for each login/identity/policy change; never a token. */
  sessionKey: string;
  projectId?: string;
  auth: { csrf: string };
  timeoutMs?: number;
  readRetries?: 0 | 1 | 2;
  apiVersion?: "v1";
  fetch?: typeof globalThis.fetch;
  onSessionExpired?: () => void;
}
export function localPath(path: string): string {
  if (
    !/^\/(?!\/)[A-Za-z0-9_/-]+$/.test(path) ||
    path.split("/").some((s) => s === "." || s === "..")
  )
    throw new FoundryError("validation", "unsafe_url");
  return path.replace(/\/$/, "");
}
export function serialize(value: unknown): string {
  try {
    return JSON.stringify(value, (_, v: unknown) => {
      if (typeof v === "number" && !Number.isFinite(v)) throw new Error();
      if (typeof v === "bigint") throw new Error();
      return v;
    });
  } catch {
    throw new FoundryError("validation", "invalid_json");
  }
}
export async function boundedJson(response: Response): Promise<unknown> {
  const reader = response.body?.getReader();
  if (!reader) return null;
  let size = 0;
  const decoder = new TextDecoder();
  let text = "";
  try {
    for (;;) {
      const part = await reader.read();
      if (part.done) break;
      size += part.value.byteLength;
      if (size > 5 * 1024 * 1024)
        throw new FoundryError("validation", "response_too_large");
      text += decoder.decode(part.value, { stream: true });
    }
    text += decoder.decode();
    return text ? (JSON.parse(text) as unknown) : null;
  } catch (e) {
    if (e instanceof SyntaxError)
      throw new FoundryError("network", "invalid_response");
    throw e;
  } finally {
    await reader.cancel().catch(() => undefined);
  }
}
function segment(value: unknown): string {
  if (
    (typeof value !== "string" && typeof value !== "number") ||
    !String(value) ||
    /[/%\\?#\x00-\x20]/.test(String(value)) ||
    [".", ".."].includes(String(value))
  )
    throw new FoundryError("validation", "unsafe_path_segment");
  return encodeURIComponent(String(value));
}
export function operationPath(
  template: string,
  input: { path?: object; query?: object },
): string {
  let path = template.replace(/\{([^}]+)\}/g, (_, key: string) =>
    segment((input.path as Record<string, unknown> | undefined)?.[key]),
  );
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(input.query ?? {}).sort(
    ([a], [b]) => a.localeCompare(b),
  )) {
    if (value === undefined || value === null) continue;
    if (
      !["string", "number", "boolean"].includes(typeof value) ||
      (typeof value === "number" && !Number.isFinite(value))
    )
      throw new FoundryError("validation", "invalid_query");
    if (
      key === "limit" &&
      (!Number.isInteger(value) || Number(value) < 1 || Number(value) > 100)
    )
      throw new FoundryError("validation", "invalid_page");
    if (
      key === "offset" &&
      (!Number.isInteger(value) || Number(value) < 0 || Number(value) > 10000)
    )
      throw new FoundryError("validation", "invalid_page");
    query.set(key, String(value));
  }
  if (query.size) path += "?" + query;
  return path;
}
export function createTransport(config: ClientConfig) {
  const { tenantId, principalId, sessionKey, projectId, onSessionExpired } =
    config;
  const csrf = config.auth?.csrf;
  if (
    ![tenantId, principalId, sessionKey, csrf].every(
      (v) =>
        typeof v === "string" &&
        v.length > 0 &&
        v.length <= 4096 &&
        !/[\r\n]/.test(v),
    )
  )
    throw new FoundryError("validation", "identity_context_required");
  if (config.apiVersion && config.apiVersion !== "v1")
    throw new FoundryError("unsupported", "api_version");
  const baseUrl = localPath(config.baseUrl ?? "/api/v1");
  const bffUrl = localPath(config.bffUrl ?? "/bff");
  const timeoutMs = config.timeoutMs ?? 45000;
  const retries = config.readRetries ?? 1;
  if (
    !Number.isInteger(timeoutMs) ||
    timeoutMs < 1 ||
    timeoutMs > 120000 ||
    ![0, 1, 2].includes(retries)
  )
    throw new FoundryError("validation", "invalid_request_budget");
  const fetcher = config.fetch ?? globalThis.fetch.bind(globalThis);
  const lifetime = new AbortController();
  let active = true;
  let invalidationError = new FoundryError(
    "authentication",
    "client_invalidated",
  );
  const listeners = new Set<() => void>();
  function invalidate(reason = invalidationError) {
    if (!active) return;
    invalidationError = reason;
    active = false;
    lifetime.abort();
    for (const listener of listeners) listener();
  }
  const send: Transport = async (method, template, input, read, options) => {
    if (!active) throw new FoundryError("authentication", "client_invalidated");
    const path = operationPath(template, input).replace(/^\/api\/v1/, baseUrl);
    const envelope = serialize({
      path,
      method,
      body: input.body,
      expected_tenant: tenantId,
    });
    if (new TextEncoder().encode(envelope).byteLength > 65536)
      throw new FoundryError("validation", "request_too_large");
    const timeout = AbortSignal.timeout(timeoutMs);
    const signal = AbortSignal.any([
      lifetime.signal,
      timeout,
      ...(options?.signal ? [options.signal] : []),
    ]);
    for (let attempt = 0; ; attempt++) {
      try {
        signal.throwIfAborted();
        const response = await fetcher(bffUrl, {
          method: "POST",
          credentials: "same-origin",
          redirect: "error",
          cache: "no-store",
          signal,
          headers: { "content-type": "application/json", "x-csrf-token": csrf },
          body: envelope,
        });
        const body = await boundedJson(response).catch((error: unknown) => {
          if (!response.ok) throw responseError(response.status, null);
          throw error;
        });
        if (!response.ok) throw responseError(response.status, body);
        signal.throwIfAborted();
        return body as never;
      } catch (cause) {
        const error = signal.aborted
          ? new FoundryError(
              timeout.aborted ? "timeout" : "cancelled",
              timeout.aborted ? "request_timeout" : "request_cancelled",
            )
          : cause instanceof FoundryError
            ? cause
            : new FoundryError("network", "network_failure");
        if (error.status === 401 || error.status === 403) {
          invalidate(error);
          if (error.status === 401) onSessionExpired?.();
        }
        if (!read || !error.retryable || signal.aborted || attempt >= retries)
          throw error;
        await new Promise<void>((resolve, reject) => {
          const done = () => {
            signal.removeEventListener("abort", abort);
            resolve();
          };
          const timer = setTimeout(done, 250 * 2 ** attempt);
          const abort = () => {
            clearTimeout(timer);
            signal.removeEventListener("abort", abort);
            reject(
              new FoundryError(
                timeout.aborted ? "timeout" : "cancelled",
                timeout.aborted ? "request_timeout" : "request_cancelled",
              ),
            );
          };
          signal.addEventListener("abort", abort, { once: true });
          if (signal.aborted) abort();
        });
      }
    }
  };
  return {
    send,
    invalidate,
    get active() {
      return active;
    },
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    get invalidationError() {
      return invalidationError;
    },
    context: Object.freeze({
      baseUrl,
      bffUrl,
      tenantId,
      principalId,
      sessionKey,
      projectId,
    }),
    // Browser fetch streams existing binary BFF bytes; caller owns consumption/cancellation.
    async download(
      datasetId: string,
      versionId: string,
      options?: RequestOptions,
      family: "datasets" | "media-sets" = "datasets",
      preview = false,
    ): Promise<ReadableStream<Uint8Array>> {
      if (!active)
        throw new FoundryError("authentication", "client_invalidated");
      const uuid =
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
      if (!uuid.test(datasetId) || !uuid.test(versionId))
        throw new FoundryError("validation", "invalid_transfer");
      const timeout = AbortSignal.timeout(1800000);
      const signal = AbortSignal.any([
        lifetime.signal,
        timeout,
        ...(options?.signal ? [options.signal] : []),
      ]);
      if (signal.aborted)
        throw new FoundryError("cancelled", "request_cancelled");
      const response = await fetcher(
        bffUrl +
          "/artifacts?" +
          new URLSearchParams({
            family,
            artifact: datasetId,
            version: versionId,
            operation: preview ? "preview" : "download",
          }),
        {
          method: "POST",
          credentials: "same-origin",
          redirect: "error",
          cache: "no-store",
          signal,
          headers: { "x-csrf-token": csrf, "x-expected-tenant": tenantId },
        },
      ).catch(() => {
        if (signal.aborted)
          throw new FoundryError(
            timeout.aborted ? "timeout" : "cancelled",
            timeout.aborted ? "request_timeout" : "request_cancelled",
          );
        throw new FoundryError("network", "transfer_failed");
      });
      if (!response.ok) {
        const error = responseError(
          response.status,
          await boundedJson(response).catch(() => null),
        );
        if ([401, 403].includes(response.status)) {
          invalidate(error);
          if (response.status === 401) onSessionExpired?.();
        }
        throw error;
      }
      if (!response.body)
        throw new FoundryError("network", "missing_transfer_body");
      return response.body;
    },
  };
}
