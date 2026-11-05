// Reuse the existing session/OIDC implementation; no second authentication system.
export { GET, POST } from "../../../../studio/app/auth/[operation]/route";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
