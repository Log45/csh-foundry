import type { components } from "./api-schema";
export type Schema = components["schemas"]["OntologyDefinition"];
export type Version = components["schemas"]["VersionView"];
export type Ontology = components["schemas"]["OntologyView"];
export type ObjectType = components["schemas"]["ObjectTypeDefinition"];
export type Property = components["schemas"]["PropertyDefinition"];
export type LinkType = components["schemas"]["LinkTypeDefinition"];
export type Query = components["schemas"]["QueryRequest"];
export type Page = components["schemas"]["QueryPage"];
export interface BrowserSession {
  csrf: string;
  tenant?: string;
  tenants: { id: string; name: string }[];
  me: null | {
    principal: { principal_id: string; tenant_id: string };
    permissions: string[];
    policy_version: number;
  };
  expires: number;
}
export class APIError extends Error {
  constructor(
    public status: number,
    code: string,
  ) {
    super(code);
  }
}
export async function browserRequest<T>(
  url: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(url, { ...init, cache: "no-store" });
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401)
      window.dispatchEvent(new Event("session-expired"));
    throw new APIError(response.status, data.error?.code ?? "request_failed");
  }
  return data as T;
}
export function client(csrf: string, expectedTenant: string) {
  return async function api<T = unknown>(
    path: string,
    method = "GET",
    body?: unknown,
  ): Promise<T> {
    return browserRequest<T>("/bff", {
      method: "POST",
      headers: { "content-type": "application/json", "x-csrf-token": csrf },
      body: JSON.stringify({
        path,
        method,
        body,
        expected_tenant: expectedTenant,
      }),
    });
  };
}
export type Client = ReturnType<typeof client>;
export const segment = (value: string) => encodeURIComponent(value);
export const ontologyPath = (id: string) => `/api/v1/ontologies/${segment(id)}`;
