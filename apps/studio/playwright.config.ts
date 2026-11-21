import { defineConfig } from "@playwright/test";
const profile = process.env.STUDIO_E2E_PROFILE;
if (profile && !["browser", "directory", "browser-scale"].includes(profile)) {
  throw new Error(`Unknown Studio CI profile: ${profile}`);
}
export default defineConfig({
  testDir: "./tests/e2e",
  ...(profile === "browser"
    ? { testIgnore: ["**/maximum.spec.ts", "**/directory-sharing.spec.ts"] }
    : profile === "directory"
      ? { testMatch: "**/directory-sharing.spec.ts" }
      : profile === "browser-scale"
        ? { testMatch: "**/maximum.spec.ts" }
        : {}),
  retries: 0,
  workers: 1,
  timeout: 120000,
  use: {
    baseURL: process.env.STUDIO_ORIGIN || "http://127.0.0.1:3000",
    ignoreHTTPSErrors: true,
    trace: process.env.STUDIO_E2E_TRACE === "true" ? "on" : "retain-on-failure",
    screenshot: "only-on-failure",
  },
  reporter: "list",
});
