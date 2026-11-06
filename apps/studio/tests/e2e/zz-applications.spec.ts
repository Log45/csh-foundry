import { test, expect, type Page } from "@playwright/test";
import { login } from "./login";
async function api(page: Page, path: string, method = "GET", body?: unknown) {
  return page.evaluate(
    async ({ path, method, body }) => {
      const session = await (await fetch("/auth/session")).json();
      const response = await fetch("/bff", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-csrf-token": session.csrf,
        },
        body: JSON.stringify({
          path,
          method,
          body,
          expected_tenant: session.tenant,
        }),
      });
      const value = await response.json();
      if (!response.ok)
        throw new Error(`${path}: ${response.status} ${JSON.stringify(value)}`);
      return value;
    },
    { path, method, body },
  );
}
test("visual manufacturing application publishes and invokes an audited canonical action", async ({
  page,
}, info) => {
  page.on("dialog", (dialog) => dialog.accept());
  await login(page);
  const ontology = await api(page, "/api/v1/ontologies/manufacturing");
  if (!ontology.active_version) {
    await page
      .getByRole("button", { name: "Validate compatibility", exact: true })
      .click();
    await expect(page.locator(".result").first()).toContainText("additive");
    await page
      .getByRole("button", { name: "Publish schema", exact: true })
      .click();
    await expect(page.getByText("PUBLISHED", { exact: true })).toBeVisible();
    await page
      .getByRole("button", { name: "Activate schema", exact: true })
      .click();
    await expect(page.getByText("Active 1.0.0", { exact: true })).toBeVisible();
  }
  const key = `APP-${Date.now()}`;
  await api(page, "/api/v1/ontologies/manufacturing/objects/Machine", "POST", {
    object_id: key,
    properties: {
      machineId: key,
      machineName: "Application test machine",
      operationalStatus: "RUNNING",
      temperatureCelsius: "42.0",
    },
  });
  await page.getByRole("button", { name: "Projects", exact: true }).click();
  const projectName = `Applications ${Date.now()}`;
  await page.getByLabel("New Project name").fill(projectName);
  await page
    .getByRole("button", { name: "Create Project", exact: true })
    .click();
  await page
    .getByLabel("Project", { exact: true })
    .selectOption({ label: `${projectName} (owner, ACTIVE)` });
  const projects = await api(page, "/api/v1/projects?limit=100");
  const project = projects.find(
    (p: { name: string }) => p.name === projectName,
  );
  const dep = await api(
    page,
    `/api/v1/projects/${project.id}/resources`,
    "POST",
    {
      resource_type: "ONTOLOGY_VERSION",
      name: "Manufacturing published schema",
      ontology_id: "manufacturing",
      schema_version: ontology.active_version ?? "1.0.0",
      entity_id: ontology.active_version ?? "1.0.0",
    },
  );
  await page
    .locator("summary")
    .filter({ hasText: /^Create application$/ })
    .click();
  await page
    .getByLabel("Application name", { exact: true })
    .fill("Manufacturing Operations Dashboard");
  await page
    .getByRole("button", { name: "Create application", exact: true })
    .click();
  const panel = page.locator("article.panel").filter({
    has: page.getByRole("heading", {
      name: "Manufacturing Operations Dashboard",
      exact: true,
    }),
  });
  await panel.getByText("Open application builder", { exact: true }).click();
  await expect(
    panel.getByLabel("Application title", { exact: true }),
  ).toBeVisible();
  await panel.getByLabel("Registered ontology resource").selectOption(dep.id);
  await panel
    .getByRole("button", { name: "Insert manufacturing dashboard" })
    .click();
  await expect(
    panel.getByLabel("Application title", { exact: true }),
  ).toHaveValue("Manufacturing Operations Dashboard");
  await panel
    .getByLabel("Dependency schema resource", { exact: true })
    .selectOption(dep.id);
  await panel.getByRole("button", { name: "Add page", exact: true }).click();
  await panel
    .getByLabel("Page title", { exact: true })
    .fill("Temporary authoring page");
  await panel.getByRole("button", { name: "Delete page", exact: true }).click();
  await panel
    .getByRole("button", { name: "Machines (table)", exact: true })
    .click();
  await panel
    .getByLabel("Data source", { exact: true })
    .selectOption("machines");
  await panel
    .getByLabel("State / selected object", { exact: true })
    .selectOption("selection");
  const machines = panel.getByRole("group", {
    name: "Data source machines",
    exact: true,
  });
  await machines
    .getByLabel("Projected properties (comma separated)")
    .fill("machineId,machineName,operationalStatus,temperatureCelsius");
  await machines
    .getByLabel("Sort property", { exact: true })
    .fill("machineName");
  await machines.getByLabel("Result page size").fill("5");
  await machines
    .getByLabel("operationalStatus source", { exact: true })
    .selectOption("literal");
  await machines
    .getByLabel("operationalStatus source", { exact: true })
    .selectOption("state");
  await machines
    .getByLabel("operationalStatus state", { exact: true })
    .selectOption("status_filter");
  await panel
    .getByRole("button", { name: "Selected machine (detail)", exact: true })
    .click();
  await panel
    .getByLabel("State / selected object", { exact: true })
    .selectOption("selection");
  const actionBinding = panel.getByRole("group", {
    name: "Action UpdateMachineStatus · update_status",
    exact: true,
  });
  for (const [label, property] of [
    ["machineId (string)", "$id"],
    ["expectedRevision (integer)", "$version"],
  ]) {
    await actionBinding
      .getByLabel(`${label} source`, { exact: true })
      .selectOption("literal");
    await actionBinding
      .getByLabel(`${label} source`, { exact: true })
      .selectOption("selected");
    await actionBinding
      .getByLabel(`${label} state`, { exact: true })
      .selectOption("selection");
    await actionBinding
      .getByLabel(`${label} selected property ($id / $version)`, {
        exact: true,
      })
      .fill(property);
  }
  await actionBinding
    .getByLabel("newStatus (string) source", { exact: true })
    .selectOption("literal");
  await actionBinding
    .getByLabel("newStatus (string) source", { exact: true })
    .selectOption("state");
  await actionBinding
    .getByLabel("newStatus (string) state", { exact: true })
    .selectOption("new_status");
  // Keyboard authoring exercises an independent insertion and inspector edit.
  await panel.getByLabel("Widget palette").selectOption("text");
  await panel
    .getByRole("button", { name: "Insert widget", exact: true })
    .focus();
  await page.keyboard.press("Enter");
  await panel
    .getByLabel("Widget text", { exact: true })
    .fill("Keyboard authored note");
  await panel.getByRole("button", { name: "Move widget up" }).click();
  await panel
    .getByRole("button", { name: "Delete widget", exact: true })
    .click();
  await panel.getByRole("button", { name: "Save application draft" }).click();
  await expect(panel.getByRole("status").first()).toContainText("Saved draft");
  await panel
    .getByRole("button", { name: "Validate application", exact: true })
    .click();
  await expect(panel.getByRole("status").first()).toContainText("Valid");
  await panel
    .getByRole("button", { name: "Preview application", exact: true })
    .click();
  await expect(
    panel.getByRole("heading", { name: "Operations", exact: true }),
  ).toBeVisible();
  await panel.getByRole("button", { name: "Return to editor" }).click();
  await panel
    .getByRole("button", { name: "Publish application", exact: true })
    .click();
  const link = panel.getByRole("link", { name: "Open version 1" });
  await expect(link).toBeVisible();
  const url = await link.getAttribute("href");
  await link.click();
  await expect(
    page.getByRole("heading", { name: "Manufacturing Operations Dashboard" }),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: "Operational status filter", exact: true })
    .selectOption("RUNNING");
  // Fixture can contain more than one page; the new machine sorts before MCH IDs.
  await page
    .getByRole("button", { name: `Select ${key}`, exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Selected machine" }),
  ).toContainText(key);
  await page
    .getByRole("combobox", { name: "New operational status", exact: true })
    .selectOption("STOPPED");
  await page
    .getByRole("button", { name: "Preview Update machine status", exact: true })
    .click();
  await expect(page.getByRole("status").last()).toContainText(
    "proposed changes",
  );
  await page
    .getByRole("button", { name: "Execute Update machine status", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Confirm Update machine status", exact: true })
    .click();
  await expect(page.getByRole("status").last()).toContainText(
    "Action committed",
  );
  const objects = await api(
    page,
    "/api/v1/ontologies/manufacturing/objects/Machine/query",
    "POST",
    {
      object_type: "Machine",
      filter: { property: "machineId", operator: "eq", value: key },
      limit: 1,
    },
  );
  expect(objects.items[0].properties.operationalStatus).toBe("STOPPED");
  const history = await api(
    page,
    "/api/v1/ontologies/manufacturing/actions/executions?limit=100",
  );
  const execution = history.items.find(
    (v: { action_id: string }) => v.action_id === "UpdateMachineStatus",
  );
  expect(execution.principal_id).toBeTruthy();
  expect(
    (
      await api(
        page,
        `/api/v1/ontologies/manufacturing/actions/executions/${execution.id}/audit`,
      )
    ).length,
  ).toBeGreaterThan(0);
  await page
    .getByRole("button", { name: "About this application", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "About", exact: true }),
  ).toBeVisible();
  await page.goto(url!);
  await expect(
    page.getByRole("heading", { name: "Operations", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: `Select ${key}`, exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBe(true);
  await info.attach("published-application", {
    body: await page.screenshot({
      path: info.outputPath("published-application.png"),
    }),
    contentType: "image/png",
  });
  await page.route("**/bff", async (route) => {
    const body = route.request().postDataJSON();
    if (body?.path?.endsWith("/query"))
      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "session_expired" } }),
      });
    else await route.continue();
  });
  await page.getByRole("button", { name: "Refresh application data" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    /session|access/i,
  );
  await expect(page.getByRole("table")).toHaveCount(0);
  await page.unroute("**/bff");
  await page.goto("/");
  const otherTenant = await page
    .getByLabel("Tenant", { exact: true })
    .locator("option")
    .filter({ hasText: "Other E2E" })
    .getAttribute("value");
  const switching = page.waitForResponse(
    (response) =>
      response.url().endsWith("/auth/tenant") &&
      response.request().method() === "POST",
  );
  await page
    .getByLabel("Tenant", { exact: true })
    .selectOption({ label: "Other E2E" });
  expect((await switching).status()).toBe(200);
  await expect
    .poll(() =>
      page.evaluate(
        async () => (await (await fetch("/auth/session")).json()).tenant,
      ),
    )
    .toBe(otherTenant);

  await expect(
    page.getByRole("heading", { name: "Welcome to Foundry" }),
  ).toBeVisible();
  await page.goto(url!);
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "Application unavailable",
  );
  await expect(page.getByRole("table")).toHaveCount(0);
});
