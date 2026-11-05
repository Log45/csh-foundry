import { endpoints } from "./endpoints.js";
import {
  createTransport,
  type ClientConfig,
  type RequestOptions,
} from "./transport.js";
export { FoundryError } from "./errors.js";
export type { ErrorCategory } from "./errors.js";
export type { ClientConfig, RequestOptions } from "./transport.js";
export type { EndpointInput, EndpointOutput } from "./endpoints.js";
export type { components, operations, paths } from "./schema.js";
export * from "./session.js";
export function createFoundryClient(config: ClientConfig) {
  const transport = createTransport(config);
  const api = endpoints(transport.send);
  return Object.freeze({
    ...api,
    datasets: Object.freeze({ ...api.datasets, download: transport.download }),
    mediaSets: Object.freeze({
      ...api.mediaSets,
      download: (setId: string, itemId: string, options?: RequestOptions) =>
        transport.download(setId, itemId, options, "media-sets"),
      preview: (setId: string, itemId: string, options?: RequestOptions) =>
        transport.download(setId, itemId, options, "media-sets", true),
    }),
    context: transport.context,
    /** Unique per instance, ensuring even accidental sessionKey reuse cannot share a cache. */
    cacheId: globalThis.crypto.randomUUID(),
    get active() {
      return transport.active;
    },
    get invalidationError() {
      return transport.invalidationError;
    },
    invalidate: transport.invalidate,
    subscribe: transport.subscribe,
  });
}
export type FoundryClient = ReturnType<typeof createFoundryClient>;
