import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";
const root = new URL("../../../../", import.meta.url);
async function operation(page: Page, name: string, body?: unknown) {
  const panel = page
    .locator("details.operation")
    .filter({ has: page.locator("summary", { hasText: name }) });
  await panel.locator("summary").click();
  if (body !== undefined)
    await panel.getByRole("textbox").last().fill(JSON.stringify(body));
  const response = page.waitForResponse((r) => r.url().endsWith("/bff"));
  await panel.getByRole("button", { name, exact: true }).click();
  await response;
  await expect(panel.getByRole("button", { name, exact: true })).toBeEnabled();
  await expect(panel.locator(".result")).toBeVisible();
  await expect(panel.locator("[role=alert]")).toHaveCount(0);
  return JSON.parse(await panel.locator(".result").innerText());
}
async function login(page: Page) {
  await page.route("https://127.0.0.1/oidc/**", async (route) => {
    const result = await route.fetch({
      url: route
        .request()
        .url()
        .replace("https://127.0.0.1/", "https://127.0.0.1:8443/"),
      maxRedirects: 0,
    });
    await route.fulfill({ response: result });
  });
  await page.goto("/");
  await page
    .getByRole("button", { name: "Sign in with OpenID Connect" })
    .click();
  await expect(page.getByLabel("Tenant", { exact: true })).toBeVisible();
  const option = page
    .getByLabel("Tenant", { exact: true })
    .locator("option")
    .filter({ hasText: "Manufacturing test tenant" });
  await page
    .getByLabel("Tenant", { exact: true })
    .selectOption((await option.getAttribute("value")) ?? "");
  await expect(
    page.getByRole("heading", { name: "manufacturing", exact: true }),
  ).toBeVisible();
}
test("verified browser reference workflow", async ({ page, context }) => {
  page.on("dialog", (dialog) => dialog.accept());
  await login(page);
  const cookies = await context.cookies();
  expect(cookies.find((c) => c.name === "foundry-session")?.httpOnly).toBe(
    true,
  );
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([]);
  expect(await page.evaluate(() => document.cookie)).not.toContain(
    "foundry-session",
  );
  await page.getByRole("button", { name: "Validate compatibility" }).click();
  await expect(page.locator(".result").first()).toContainText("additive");
  await page
    .getByRole("button", { name: "Publish schema", exact: true })
    .click();
  await expect(page.getByText("PUBLISHED", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Activate schema", exact: true })
    .click();
  await expect(page.getByText("Active 1.0.0", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Ingestion", exact: true }).click();
  const schema = JSON.parse(
    fs.readFileSync(
      new URL("ontologies/examples/manufacturing.json", root),
      "utf8",
    ),
  );
  const relations: Record<string, unknown[]> = {
    Machine: [{ link: "locatedInFactory", target_column: "factoryId" }],
    MaintenanceTask: [
      { link: "taskForMachine", target_column: "machineId" },
      { link: "assignedEmployee", target_column: "assignedEmployeeId" },
    ],
  };
  for (const type of schema.object_types) {
    const src = page
      .locator("details.operation")
      .filter({ has: page.locator("summary", { hasText: "Publish source" }) });
    if (await src.locator(".result").count())
      await src.locator("summary").click();
    await operation(page, "Publish source", {
      id: type.id,
      name: type.name,
      binding: type.id,
      identity_namespace: type.id,
      version: 1,
    });
    const map = page
      .locator("details.operation")
      .filter({ has: page.locator("summary", { hasText: "Publish mapping" }) });
    if (await map.locator(".result").count())
      await map.locator("summary").click();
    await operation(page, "Publish mapping", {
      id: type.id,
      source_id: type.id,
      source_version: 1,
      schema_version: "1.0.0",
      object_type: type.id,
      identity_column: type.primary_key,
      properties: type.properties.map(
        (p: { id: string; data_type: string }) => ({
          property: p.id,
          column: p.id,
          conversion: p.data_type === "string" ? "identity" : p.data_type,
        }),
      ),
      relationships: relations[type.id] ?? [],
    });
  }
  await operation(page, "Submit ingestion run", {
    mappings: schema.object_types.map((t: { id: string }) => ({
      id: t.id,
      version: 1,
    })),
    idempotency_key: "browser-reference",
    validation_policy: "reject_run",
    batch_size: 25,
  });
  await operation(page, "Refresh ingestion runs");
  const runs = page.locator("details.operation").filter({
    has: page.locator("summary", { hasText: "Refresh ingestion runs" }),
  });
  await expect(async () => {
    await runs
      .getByRole("button", { name: "Refresh ingestion runs", exact: true })
      .click();
    await expect(runs.locator(".result")).toContainText("COMPLETED");
  }).toPass({ timeout: 40000 });
  await expect(runs.locator(".result")).toContainText('"created": 63');
  await page.getByRole("button", { name: "Objects & Object Sets" }).click();
  await page.getByLabel("Object type", { exact: true }).selectOption("Machine");
  await page.getByRole("button", { name: "Run query", exact: true }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "objects ·" }),
  ).toContainText("20 objects");
  await page.getByLabel("Filter property").selectOption("operationalStatus");
  await page.getByLabel("Filter value").fill("CRITICAL");
  await page.getByRole("button", { name: "Run query", exact: true }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "objects ·" }),
  ).toContainText("3 objects");
  await page.getByLabel("Filter property").selectOption("");
  await page
    .getByLabel("Traverse relationship")
    .selectOption("locatedInFactory");
  await page.getByRole("button", { name: "Run query", exact: true }).click();
  await expect(page.getByRole("table")).toHaveAccessibleName(
    "Authorized Factory objects",
  );
  await page.getByRole("button", { name: "Actions", exact: true }).click();
  await page
    .getByLabel("Action", { exact: true })
    .selectOption("UpdateMachineStatus");
  await page.getByLabel("machineId (string, required)").fill("MCH-001");
  await page.getByLabel("newStatus (string, required)").selectOption("STOPPED");
  await page.getByLabel("expectedRevision (integer, required)").fill("1");
  await page.getByRole("button", { name: "Preview action" }).click();
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Execute action" }).click();
  await expect(page.locator(".result").last()).toContainText("execution_id");
  await page
    .getByRole("button", { name: "Semantic results", exact: true })
    .click();
  const compiled = await operation(page, "Compile ontology and shapes");
  const asserted = await operation(page, "Export operational RDF", {
    schema_version: "1.0.0",
    selections: schema.object_types.map((t: { id: string }) => ({
      object_type: t.id,
      limit: 200,
    })),
    links: ["locatedInFactory", "taskForMachine", "assignedEmployee"],
  });
  await operation(page, "Submit semantic job", {
    operation: "validation",
    primary_artifact: asserted,
    secondary_artifact: compiled[1],
    profile: "owl-rl-ext",
  });
  await operation(page, "Refresh semantic jobs");
  const jobs = page.locator("details.operation").filter({
    has: page.locator("summary", { hasText: "Refresh semantic jobs" }),
  });
  await expect(async () => {
    await jobs
      .getByRole("button", { name: "Refresh semantic jobs", exact: true })
      .click();
    await expect(jobs.locator(".result")).toContainText("COMPLETED");
  }).toPass({ timeout: 40000 });
  await page.screenshot({
    path: "../../artifacts/studio-e2e/studio.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Sign in with OpenID Connect" }),
  ).toBeVisible();
});
test("CSRF and unauthenticated proxy requests fail closed", async ({
  page,
}) => {
  await page.goto("/");
  const unauth = await page.request.post("/bff", {
    data: { path: "/api/v1/ontologies", method: "GET" },
  });
  expect(unauth.status()).toBe(401);
  await login(page);
  const csrf = await page.request.post("/bff", {
    headers: { origin: "http://127.0.0.1:3000" },
    data: { path: "/api/v1/ontologies", method: "GET" },
  });
  expect(csrf.status()).toBe(403);
});
test("native authoring, OWL diagnostics, tenant isolation and session loss", async ({
  page,
  context,
}) => {
  page.on("dialog", (d) => d.accept());
  await login(page);
  const create = page
    .locator("details.panel")
    .filter({ has: page.locator("summary", { hasText: "Create ontology" }) });
  await create.locator("summary").click();
  await page.getByLabel("Ontology id", { exact: true }).fill("native-test");
  await create.getByLabel("Ontology name", { exact: true }).fill("Native test");
  await page.getByRole("button", { name: "Create ontology draft" }).click();
  await expect(
    page.getByRole("heading", { name: "native-test", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Add object type", exact: true })
    .click();
  await page.getByLabel("Type name").fill("Native object");
  await page.getByRole("button", { name: "Add property", exact: true }).click();
  await page.getByText("New property", { exact: false }).first().click();
  await page.getByLabel("Property name").last().fill("Temperature");
  await page.getByRole("button", { name: "Apply property" }).last().click();
  await page
    .getByRole("button", { name: "Add relationship", exact: true })
    .click();
  await page.getByLabel("Relationship name").fill("Related");
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page.getByText("Unsaved changes", { exact: true })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("img", { name: "Ontology schema relationships" }),
  ).toBeVisible();
  await page.screenshot({
    path: "../../artifacts/studio-e2e/manager.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Validate compatibility" }).click();
  await expect(page.locator(".result").first()).toContainText("additive");
  const request = {
    format: "turtle",
    mode: "PREVIEW_ONLY",
    content:
      "@prefix owl: <http://www.w3.org/2002/07/owl#> . <https://example.org/Foo> a owl:Class .",
    version: "2.0.0",
    base_version: "1.0.0",
    mappings: { classes: [], links: [] },
    namespace_mappings: {},
    conflict_choices: {},
  };
  await page
    .getByLabel("Import and vocabulary mapping request")
    .fill(JSON.stringify(request));
  await page
    .getByRole("button", { name: "Preview import", exact: true })
    .click();
  await expect(page.getByLabel("Import ID")).not.toHaveValue("");
  await page.getByRole("button", { name: "vocabulary", exact: true }).click();
  await expect(page.locator(".result").last()).toContainText("Foo");
  const other = page
    .getByLabel("Tenant", { exact: true })
    .locator("option")
    .filter({ hasText: "Other E2E" });
  await page
    .getByLabel("Tenant", { exact: true })
    .selectOption((await other.getAttribute("value")) ?? "");
  await expect(
    page.getByRole("heading", { name: "Welcome to Foundry", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByLabel("Ontology", { exact: true }).locator("option"),
  ).toHaveCount(1);
  await context.clearCookies();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Sign in with OpenID Connect" }),
  ).toBeVisible();
  await expect(
    page.getByText("Your session expired. Sign in to continue."),
  ).toBeVisible();
});
