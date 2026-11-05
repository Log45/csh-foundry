export type ErrorCategory =
  | "authentication"
  | "permission"
  | "not_found"
  | "validation"
  | "conflict"
  | "admission"
  | "execution"
  | "network"
  | "timeout"
  | "unsupported"
  | "cancelled";
export class FoundryError extends Error {
  readonly name = "FoundryError";
  constructor(
    public readonly category: ErrorCategory,
    public readonly code: string,
    public readonly status?: number,
  ) {
    super(code);
  }
  get retryable() {
    return (
      this.category === "network" ||
      this.category === "timeout" ||
      this.status === 429 ||
      this.status === 503
    );
  }
}
export function responseError(status: number, body: unknown): FoundryError {
  const category: ErrorCategory =
    status === 401
      ? "authentication"
      : status === 403
        ? "permission"
        : status === 404
          ? "not_found"
          : status === 409
            ? "conflict"
            : [400, 413, 415, 422].includes(status)
              ? "validation"
              : [429, 503].includes(status)
                ? "admission"
                : [405, 501].includes(status)
                  ? "unsupported"
                  : "network";
  const code = (body as { error?: { code?: unknown } } | null)?.error?.code;
  // Only the platform's sanitized machine code is retained, never arbitrary response text.
  return new FoundryError(
    category,
    typeof code === "string" && /^[a-zA-Z0-9_.:-]{1,128}$/.test(code)
      ? code
      : `http_${status}`,
    status,
  );
}
