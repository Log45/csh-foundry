import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/e2e",
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
