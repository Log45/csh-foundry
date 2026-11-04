import { test, expect } from "@playwright/test";
import fs from "node:fs";
import { login } from "./login";
// Avoid test-driver copies of the 1 GiB request body. Functional checks remain enabled.
test.use({ trace: "off" });
test("exact 1 GiB browser upload streams through BFF and asynchronous validation", async ({
  page,
}, testInfo) => {
  test.setTimeout(300000);
  test.skip(
    process.env.FOUNDRY_ARTIFACT_BACKEND !== "s3",
    "NOT RUN: requires isolated MinIO runner",
  );
  const source = testInfo.outputPath("maximum.csv");
  const size = 1024 ** 3;
  const header = Buffer.from("payload\n");
  const row = Buffer.from("p".repeat(4095) + "\n");
  const block = Buffer.from(row.toString().repeat(256));
  const fd = fs.openSync(source, "w");
  try {
    fs.writeSync(fd, header);
    let remaining = size - header.length;
    while (remaining >= block.length) {
      fs.writeSync(fd, block);
      remaining -= block.length;
    }
    while (remaining >= row.length) {
      fs.writeSync(fd, row);
      remaining -= row.length;
    }
    if (remaining)
      fs.writeSync(fd, Buffer.from("q".repeat(remaining - 1) + "\n"));
  } finally {
    fs.closeSync(fd);
  }
  expect(fs.statSync(source).size).toBe(size);
  try {
    await login(page);
    await page.unroute("https://127.0.0.1/oidc/**");
    await page.getByRole("button", { name: "Projects", exact: true }).click();
    const name = `Maximum browser Project ${Date.now()}`;
    await page.getByLabel("New Project name").fill(name);
    await page
      .getByRole("button", { name: "Create Project", exact: true })
      .click();
    await page
      .getByLabel("Project", { exact: true })
      .selectOption({ label: `${name} (owner, ACTIVE)` });
    await page.getByLabel("New dataset name").fill("Maximum browser dataset");
    await page
      .getByRole("button", { name: "Create dataset", exact: true })
      .click();
    await page
      .getByText("Dataset versions, schema and preview", { exact: true })
      .click();
    await page.getByLabel("Dataset file (up to 1 GiB)").setInputFiles(source);
    await page
      .getByRole("button", { name: "Upload new version", exact: true })
      .click();
    await expect(page.getByText(/Version 1 · COMMITTED/)).toBeVisible({
      timeout: 240000,
    });
    const previewResponse = page.waitForResponse(
      (r) =>
        r.url().endsWith("/bff") &&
        r.request().postDataJSON()?.path?.includes("/preview"),
    );
    await page
      .getByRole("button", {
        name: "Inspect schema and preview version 1",
        exact: true,
      })
      .click();
    await expect(
      page.getByRole("columnheader", { name: /payload.*String/ }),
    ).toBeVisible();
    expect((await (await previewResponse).json()).row_count).toBe(262144);
    console.log(
      "PASS_BROWSER_MAXIMUM",
      JSON.stringify({
        source_bytes: size,
        rows: 262144,
        format: "csv",
        asynchronous_validation: true,
      }),
    );
  } finally {
    fs.unlinkSync(source);
  }
});
