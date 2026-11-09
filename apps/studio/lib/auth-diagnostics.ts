// Callback diagnostics contain only fixed stages and error categories, never raw errors.
import { errors } from "jose";
import { BoundaryError } from "./server";

export type AuthStage =
  | "login_state"
  | "configuration"
  | "discovery"
  | "token_exchange"
  | "token_response"
  | "jwks"
  | "id_token"
  | "id_token_binding"
  | "access_token"
  | "access_token_binding"
  | "session_store"
  | "previous_session"
  | "response";

export function logCallbackFailure(stage: AuthStage, error: unknown) {
  const category =
    error instanceof BoundaryError
      ? "boundary_error"
      : error instanceof errors.JOSEError
        ? error.code
        : error instanceof SyntaxError
          ? "invalid_json"
          : error instanceof TypeError
            ? "type_or_transport_error"
            : error instanceof DOMException && error.name === "TimeoutError"
              ? "timeout"
              : "unexpected_error";
  const claim =
    error instanceof errors.JWTClaimValidationFailed &&
    [
      "iss",
      "aud",
      "sub",
      "exp",
      "iat",
      "nbf",
      "jti",
      "client_id",
      "nonce",
    ].includes(error.claim)
      ? error.claim
      : undefined;
  console.error(
    JSON.stringify({
      event: "studio_auth_callback_failed",
      stage,
      category,
      claim,
      status: error instanceof BoundaryError ? error.status : 401,
    }),
  );
}
