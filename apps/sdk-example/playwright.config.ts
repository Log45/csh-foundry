import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  workers: 1,
  timeout: 120000,
  use: {
    baseURL: process.env.STUDIO_ORIGIN ?? "http://127.0.0.1:3200",
    ignoreHTTPSErrors: true,
    trace: "retain-on-failure",
  },
  reporter: "list",
});
