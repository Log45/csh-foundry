import { NextRequest, NextResponse } from "next/server";

export function proxy(request: NextRequest) {
  const nonce = crypto.getRandomValues(new Uint8Array(24));
  const value = Buffer.from(nonce).toString("base64");
  const development = process.env.NODE_ENV === "development";
  // React graph coordinates use style attributes; scripts require a fresh nonce.
  const csp = `default-src 'self'; script-src 'self' 'nonce-${value}' 'strict-dynamic'${development ? " 'unsafe-eval'" : ""}; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`;
  const headers = new Headers(request.headers);
  headers.set("x-nonce", value);
  headers.set("Content-Security-Policy", csp);
  const response = NextResponse.next({ request: { headers } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}
export const config = {
  // Binary BFF enforces its own session/CSRF/tenant boundary. Excluding it prevents
  // Next Proxy from cloning/buffering the upload body before the streaming handler.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|bff/artifacts).*)"],
};
