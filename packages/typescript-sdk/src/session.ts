import type { operations } from "./schema.js";
import { boundedJson, localPath } from "./transport.js";
import { FoundryError, responseError } from "./errors.js";
/** BFF envelope; API identity members reuse generated operational types. No bearer token. */
export interface BrowserSession {
  csrf: string;
  tenant?: string;
  tenants: operations["own_tenants_api_v1_security_tenants_get"]["responses"][200]["content"]["application/json"];
  me:
    | operations["me_api_v1_security_me_get"]["responses"][200]["content"]["application/json"]
    | null;
  expires: number;
}
export function createSessionClient(
  config: { authUrl?: string; fetch?: typeof globalThis.fetch } = {},
) {
  const base = localPath(config.authUrl ?? "/auth");
  const fetcher = config.fetch ?? globalThis.fetch.bind(globalThis);
  async function call<T>(
    operation: string,
    method: string,
    csrf?: string,
    body?: object,
    signal?: AbortSignal,
  ): Promise<T> {
    const timeout = AbortSignal.timeout(15000);
    const combined = AbortSignal.any([timeout, ...(signal ? [signal] : [])]);
    try {
      const response = await fetcher(base + "/" + operation, {
        method,
        credentials: "same-origin",
        redirect: "error",
        cache: "no-store",
        signal: combined,
        headers: {
          ...(csrf ? { "x-csrf-token": csrf } : {}),
          ...(body ? { "content-type": "application/json" } : {}),
        },
        body: body ? JSON.stringify(body) : undefined,
      });
      const data = await boundedJson(response).catch((error: unknown) => {
        if (!response.ok) throw responseError(response.status, null);
        throw error;
      });
      if (!response.ok) throw responseError(response.status, data);
      return data as T;
    } catch (error) {
      if (combined.aborted)
        throw new FoundryError(
          timeout.aborted ? "timeout" : "cancelled",
          timeout.aborted ? "request_timeout" : "request_cancelled",
        );
      if (error instanceof FoundryError) throw error;
      throw new FoundryError("network", "network_failure");
    }
  }
  return Object.freeze({
    session: (offset = 0, signal?: AbortSignal) => {
      if (!Number.isInteger(offset) || offset < 0 || offset > 10000)
        throw new RangeError("invalid_page");
      return call<BrowserSession>(
        `session?offset=${offset}`,
        "GET",
        undefined,
        undefined,
        signal,
      );
    },
    login: (signal?: AbortSignal) =>
      call<{ authorization: string }>(
        "login",
        "POST",
        undefined,
        undefined,
        signal,
      ),
    selectTenant: (tenant: string, csrf: string, signal?: AbortSignal) =>
      call<{ status: string }>("tenant", "POST", csrf, { tenant }, signal),
    /** Invalidate the active Foundry client before awaiting server logout; discard private UI state. */
    logout: (csrf: string, signal?: AbortSignal) =>
      call<{ status: string; logout?: string }>(
        "logout",
        "POST",
        csrf,
        undefined,
        signal,
      ),
  });
}
