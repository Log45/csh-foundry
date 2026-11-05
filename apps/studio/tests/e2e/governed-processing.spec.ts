import { test, expect } from "@playwright/test";
import { login } from "./login";

test("governed media, typed functions and manual automations use the authenticated Studio", async ({
  page,
}) => {
  expect(process.env.FOUNDRY_ARTIFACT_BACKEND).toBe("s3");
  await login(page);
  await page.getByRole("button", { name: "Projects", exact: true }).click();
  const project = `Processing ${Date.now()}`;
  await page.getByLabel("New Project name").fill(project);
  await page
    .getByRole("button", { name: "Create Project", exact: true })
    .click();
  await page
    .getByLabel("Project", { exact: true })
    .selectOption({ label: `${project} (owner, ACTIVE)` });
  function response(path: string, method = "POST") {
    return page.waitForResponse(
      (r) =>
        r.url().endsWith("/bff") &&
        r.request().postDataJSON()?.path?.endsWith(path) &&
        r.request().postDataJSON()?.method === method,
    );
  }
  function panel(name: string) {
    return page
      .locator("article.panel")
      .filter({ has: page.getByRole("heading", { name, exact: true }) });
  }
  async function create(family: string, name: string) {
    await page.getByLabel("Processing resource type").selectOption(family);
    await page.getByLabel("Processing resource name").fill(name);
    const pending = response(`/${family}`);
    await page
      .getByRole("button", { name: "Create processing resource", exact: true })
      .click();
    const resource = await (await pending).json();
    expect(resource.id).toBeTruthy();
    await panel(name)
      .getByText(`${family} versions and execution`, { exact: true })
      .click();
    return resource;
  }
  await page.getByLabel("New artifact name").fill("Image source");
  const created = response("/artifacts");
  await page
    .getByRole("button", { name: "Create artifact", exact: true })
    .click();
  const artifact = await (await created).json();
  const source = panel("Image source");
  await source
    .getByText("Artifact versions and files", { exact: true })
    .click();
  const png = await page.screenshot();
  await source
    .getByLabel("Artifact file (up to 64 MiB)")
    .setInputFiles({ name: "source.png", mimeType: "image/png", buffer: png });
  const finalized = response("/finalize");
  await source
    .getByRole("button", { name: "Upload new version", exact: true })
    .click();
  const version = await (await finalized).json();
  const media = await create("media-sets", "Photos");
  const mediaPanel = panel("Photos");
  await mediaPanel.getByLabel("Media artifact reference JSON").fill(
    JSON.stringify({
      artifact_id: artifact.id,
      artifact_version_id: version.id,
      media_type: "image/png",
    }),
  );
  await mediaPanel
    .getByRole("button", { name: "Attach media", exact: true })
    .click();
  await expect(mediaPanel.getByText(/source.png · image\/png/)).toBeVisible();
  await mediaPanel
    .getByRole("button", { name: "Include in next snapshot", exact: true })
    .click();
  await mediaPanel
    .getByRole("button", { name: "Publish version", exact: true })
    .click();
  await expect(mediaPanel.getByRole("status")).toContainText(
    "Published immutable version 1",
  );
  await mediaPanel
    .getByRole("button", { name: "Preview media", exact: true })
    .click();
  await expect(
    mediaPanel.getByAltText("Authorized media preview"),
  ).toBeVisible();
  await mediaPanel
    .getByRole("button", { name: "Media provenance", exact: true })
    .click();
  await expect(mediaPanel.locator("pre").last()).toContainText(version.id);
  const fn = await create("functions", "Normalize text");
  const functionPanel = panel("Normalize text");
  const published = response("/definitions");
  await functionPanel
    .getByRole("button", { name: "Validate definition", exact: true })
    .click();
  await expect(functionPanel.getByRole("status")).toContainText(
    "Definition valid",
  );
  await functionPanel
    .getByRole("button", { name: "Publish version", exact: true })
    .click();
  const functionVersion = await (await published).json();
  await functionPanel
    .getByRole("button", { name: "Invoke function", exact: true })
    .click();
  await expect(functionPanel.getByText(/· SUCCEEDED · attempts/)).toBeVisible({
    timeout: 20000,
  });
  await functionPanel
    .getByRole("button", { name: "Inspect function result", exact: true })
    .click();
  await expect(functionPanel.locator("pre").last()).toContainText(
    "hello world",
  );
  await create("automations", "Manual normalize");
  const auto = panel("Manual normalize");
  await auto.getByLabel("automations definition JSON").fill(
    JSON.stringify({
      trigger: { kind: "manual" },
      function_id: fn.id,
      function_definition_id: functionVersion.id,
      inputs: { text: " AUTOMATED " },
    }),
  );
  await auto
    .getByRole("button", { name: "Publish version", exact: true })
    .click();
  await expect(auto.getByRole("status")).toContainText(
    "Published immutable version 1",
  );
  await auto
    .getByRole("button", { name: "Enable automation", exact: true })
    .click();
  await expect(auto.locator("pre").last()).toContainText('"enabled": true');
  await auto
    .getByRole("button", { name: "Trigger manual automation", exact: true })
    .click();
  await expect(auto.getByText(/manual · .* · dispatched/)).toBeVisible();
  await expect(async () => {
    await auto
      .getByRole("button", { name: "Inspect automation job", exact: true })
      .click();
    await expect(auto.locator("pre").last()).toContainText(
      '"state": "SUCCEEDED"',
    );
  }).toPass({ timeout: 20000 });
  await auto
    .getByRole("button", { name: "Disable automation", exact: true })
    .click();
  await expect(auto.locator("pre").last()).toContainText('"enabled": false');
  expect(media.id).toBeTruthy();
  for (const scoped of [mediaPanel, functionPanel, auto])
    await expect(scoped.locator("[role=alert]")).toHaveCount(0);
});
