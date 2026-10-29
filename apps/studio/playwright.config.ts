import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/e2e",
  workers: 1,
  timeout: 120000,
  use: {
    baseURL: "http://127.0.0.1:3000",
    ignoreHTTPSErrors: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  reporter: "list",
});
