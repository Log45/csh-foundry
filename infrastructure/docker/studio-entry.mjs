import { readFileSync } from "node:fs";
if (process.env.STUDIO_STATE_SECRET_FILE)
  process.env.STUDIO_STATE_SECRET = readFileSync(process.env.STUDIO_STATE_SECRET_FILE, "utf8").trim();
if (process.env.STUDIO_ENVIRONMENT === "production" && !process.env.STUDIO_STATE_SECRET)
  throw new Error("Shared session credential is required");
await import("./server.js");
