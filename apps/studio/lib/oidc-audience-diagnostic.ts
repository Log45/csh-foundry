// Temporary opt-in metadata only. This function never supplies an authentication result.
import { jwtVerify, type JWTVerifyGetKey } from "jose";

function printable(value: unknown): value is string {
  return typeof value === "string" && /^[\x20-\x7e]{1,256}$/.test(value);
}

export async function diagnoseAccessTokenAudience(
  token: string,
  keys: JWTVerifyGetKey,
  issuer: string,
  algorithms: string[],
  expected: string,
): Promise<void> {
  if (process.env.STUDIO_DIAGNOSTIC_OIDC_AUDIENCE !== "true") return;
  try {
    // Deliberately omit audience ONLY for this diagnostic verification. The caller
    // still runs the original full verifier, including its mandatory audience check.
    const { payload } = await jwtVerify(token, keys, {
      issuer,
      algorithms,
      requiredClaims: ["exp", "iat"],
    });
    if (
      !Number.isInteger(payload.iat) ||
      !Number.isInteger(payload.exp) ||
      (payload.iat as number) < 0 ||
      (payload.iat as number) >= (payload.exp as number) ||
      (payload.iat as number) > Date.now() / 1000
    )
      return;
    const aud: unknown = payload.aud;
    const safe =
      printable(aud) ||
      (Array.isArray(aud) && aud.length <= 16 && aud.every(printable));
    console.info(
      JSON.stringify({
        event: "studio_oidc_access_token_audience",
        audience: safe ? aud : null,
        audience_status:
          aud === undefined
            ? "missing"
            : safe
              ? "present"
              : "omitted_invalid_or_oversized",
        expected_audience: printable(expected) ? expected : null,
      }),
    );
  } catch {
    // No raw errors, JWT payloads or fallback authentication. The real verifier
    // remains responsible for the original sanitized failure and its diagnostics.
  }
}
