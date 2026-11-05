import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";
import { login } from "./login";
import { spawn } from "node:child_process";
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
test("verified browser reference workflow", async ({
  page,
  context,
}, testInfo) => {
  const timing: object[] = [];
  page.on("response", async (response) => {
    if (!response.url().endsWith("/bff")) return;
    const request = response.request();
    const body = request.postDataJSON();
    if (!body?.path?.includes("/ontologies")) return;
    const payload = await response.json().catch(() => ({}));
    timing.push({
      path: body.path,
      method: body.method,
      status: response.status(),
      timing: request.timing(),
      active_version: payload.active_version,
      version: payload.definition?.version,
      ontology_versions: Array.isArray(payload)
        ? payload.map((item) => ({
            id: item.id,
            active_version: item.active_version,
          }))
        : undefined,
    });
  });
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
  await testInfo.attach("activation-consistency", {
    body: JSON.stringify({
      requests: timing,
      header: await page.locator("header .badge").innerText(),
    }),
    contentType: "application/json",
  });
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
    headers: { origin: process.env.STUDIO_ORIGIN || "http://127.0.0.1:3000" },
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

test("schema branching, resolved merge and private SDK download", async ({
  page,
}) => {
  page.on("dialog", (d) => d.accept());
  await login(page);
  const development = page
    .getByRole("heading", { name: "Schema branches and SDKs" })
    .locator("..");
  await expect(
    development.getByLabel("Published SDK / branch base version"),
  ).not.toHaveValue("");
  for (const name of ["browser-source", "browser-target"]) {
    await development.getByLabel("New branch name").fill(name);
    await development
      .getByRole("button", { name: "Create schema branch", exact: true })
      .click();
    await expect(
      development.getByText(
        new RegExp(
          "Branch draft · " + name + " · ACTIVE · base .* · revision 1",
        ),
      ),
    ).toBeVisible();
    await expect(
      development.getByLabel("Branch canonical schema (JSON)"),
    ).toBeVisible();
    const editor = development.getByLabel("Branch canonical schema (JSON)");
    const data = JSON.parse(await editor.inputValue());
    data.name = name;
    await editor.fill(JSON.stringify(data));
    await development
      .getByRole("button", { name: "Save branch revision", exact: true })
      .click();
    await expect(
      development.getByText(
        new RegExp(
          "Branch draft · " + name + " · ACTIVE · base .* · revision 2",
        ),
      ),
    ).toBeVisible();
  }
  const source = development.getByLabel("Source branch for merge");
  await source.selectOption({ label: "browser-source · revision 2" });
  await development
    .getByRole("button", { name: "Preview resolved merge" })
    .click();
  await expect(
    development.getByRole("button", { name: "Use source /name", exact: true }),
  ).toBeVisible();
  await development
    .getByRole("button", { name: "Use source /name", exact: true })
    .click();
  await development
    .getByRole("button", { name: "Preview resolved merge" })
    .click();
  await expect(
    development.getByRole("button", {
      name: "Confirm branch merge",
      exact: true,
    }),
  ).toBeEnabled();
  await development
    .getByRole("button", { name: "Confirm branch merge", exact: true })
    .click();
  await expect(
    development.getByText(
      /Branch draft · browser-target · ACTIVE · base .* · revision 3/,
    ),
  ).toBeVisible();
  await development
    .getByRole("button", { name: "Inspect merge provenance" })
    .click();
  await expect(development.locator(".result").last()).toContainText(
    '"outcome": "MERGED"',
  );
  await development.getByLabel("SDK language").selectOption("python");
  await development
    .getByRole("button", { name: "Generate published SDK" })
    .click();
  const downloadButton = development
    .getByRole("button", { name: /Download python SDK/ })
    .first();
  await expect(downloadButton).toBeVisible();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    downloadButton.click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/ontology-python-.*\.zip/);
  const path = await download.path();
  expect(path && fs.statSync(path).size).toBeGreaterThan(1000);
  await development.getByLabel("SDK language").selectOption("typescript");
  await development
    .getByRole("button", { name: "Generate published SDK" })
    .click();
  await expect(
    development.getByRole("button", { name: /Download typescript SDK/ }),
  ).toBeVisible();
  await expect(development.getByRole("alert")).toHaveCount(0);
});

if (process.env.STUDIO_E2E_REPLICA_PORT) {
  test("durable sessions survive replica restart and logout revokes every replica", async ({
    page,
  }) => {
    await login(page);
    const secondary = "http://127.0.0.1:" + process.env.STUDIO_E2E_REPLICA_PORT;
    const before = await page.request.get(secondary + "/auth/session");
    expect(before.status()).toBe(200);
    const session = await before.json();
    expect(session.tenant).toBeTruthy();
    process.kill(-Number(process.env.STUDIO_E2E_REPLICA_PID), "SIGTERM");
    await new Promise((resolve) => setTimeout(resolve, 1000));
    expect((await page.request.get("/auth/session")).status()).toBe(200);
    const replacement = spawn(
      process.execPath,
      [".next/standalone/server.js"],
      {
        cwd: process.cwd(),
        env: {
          ...process.env,
          HOSTNAME: "127.0.0.1",
          PORT: process.env.STUDIO_E2E_REPLICA_PORT,
        },
        stdio: "ignore",
      },
    );
    try {
      await expect
        .poll(async () => {
          try {
            return (
              await page.request.get(secondary + "/auth/session")
            ).status();
          } catch {
            return 0;
          }
        })
        .toBe(200);
      expect(
        (await (await page.request.get(secondary + "/auth/session")).json())
          .csrf,
      ).toBe(session.csrf);
      const logout = await page.request.post("/auth/logout", {
        headers: {
          Origin: process.env.STUDIO_ORIGIN || "http://127.0.0.1:3000",
          "x-csrf-token": session.csrf,
        },
        data: {},
      });
      expect(logout.status()).toBe(200);
      expect(
        (await page.request.get(secondary + "/auth/session")).status(),
      ).toBe(401);
    } finally {
      replacement.kill("SIGTERM");
      await Promise.race([
        new Promise((resolve) => replacement.once("exit", resolve)),
        new Promise((resolve) => setTimeout(resolve, 2000)),
      ]);
      if (replacement.exitCode === null) replacement.kill("SIGKILL");
    }
  });
}

test("Project workspace navigates folders and governed canonical references", async ({
  page,
}) => {
  await login(page);
  await page.getByRole("button", { name: "Projects", exact: true }).click();
  const name = `E2E Project ${Date.now()}`;
  await page.getByLabel("New Project name").fill(name);
  await page
    .getByRole("button", { name: "Create Project", exact: true })
    .click();
  await page
    .getByLabel("Project", { exact: true })
    .selectOption({ label: `${name} (owner, ACTIVE)` });
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  await page.getByLabel("New folder name").fill("Models");
  await page
    .getByRole("button", { name: "Create folder", exact: true })
    .click();
  await page.getByRole("button", { name: "Models", exact: true }).click();
  await page.getByLabel("New folder name").fill("Nested");
  await page
    .getByRole("button", { name: "Create folder", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Nested", exact: true }),
  ).toBeVisible();
  await page
    .getByText("Register published ontology assets", { exact: true })
    .click();
  await page.getByLabel("Catalog ontology ID").fill("manufacturing");
  await page.getByLabel("Published version", { exact: true }).fill("1.0.0");
  await page.getByRole("button", { name: "Register catalog page" }).click();
  await expect(
    page.getByRole("heading", { name: "Machine (OBJECT_TYPE)", exact: true }),
  ).toBeVisible();
  const machine = page.locator("article").filter({
    has: page.getByRole("heading", {
      name: "Machine (OBJECT_TYPE)",
      exact: true,
    }),
  });
  await machine
    .getByRole("button", { name: "Open ontology in Manager" })
    .click();
  await expect(
    page.getByRole("button", { name: "Validate compatibility" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Projects", exact: true }).click();
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  await page.getByText("Manage Project", { exact: true }).click();
  await page
    .getByRole("button", { name: "Archive Project", exact: true })
    .click();
  await expect(page.getByLabel("Project", { exact: true })).toContainText(
    `${name} (owner, ARCHIVED)`,
  );
  await expect(
    page.getByRole("button", { name: "Create folder", exact: true }),
  ).toHaveCount(0);
});

test("Project artifacts upload immutable versions and download exact bytes", async ({
  page,
}) => {
  test.skip(
    process.env.FOUNDRY_ARTIFACT_BACKEND !== "s3",
    "NOT RUN: run scripts/validate_phase12.py --browser",
  );
  await login(page);
  await page.getByRole("button", { name: "Projects", exact: true }).click();
  const name = `Artifact Project ${Date.now()}`;
  await page.getByLabel("New Project name").fill(name);
  await page
    .getByRole("button", { name: "Create Project", exact: true })
    .click();
  await page
    .getByLabel("Project", { exact: true })
    .selectOption({ label: `${name} (owner, ACTIVE)` });
  await page.getByLabel("New artifact name").fill("Test file");
  await page
    .getByRole("button", { name: "Create artifact", exact: true })
    .click();
  await page.getByText("Artifact versions and files", { exact: true }).click();
  const bytes = Buffer.from("immutable artifact bytes\n");
  await page.getByLabel("Artifact file (up to 64 MiB)").setInputFiles({
    name: "sample.bin",
    mimeType: "application/octet-stream",
    buffer: bytes,
  });
  await page
    .getByRole("button", { name: "Upload new version", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Download version 1", exact: true }),
  ).toBeVisible();
  const download = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download version 1", exact: true })
    .click();
  const file = await download;
  expect(fs.readFileSync((await file.path())!)).toEqual(bytes);
  await page
    .getByRole("button", { name: "Upload new version", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Download version 2", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Download version 1", exact: true }),
  ).toBeVisible();
  await page
    .getByText("Rename, move or archive Test file", { exact: true })
    .click();
  await page
    .getByRole("button", { name: "Archive asset", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Test file", exact: true }),
  ).toHaveCount(0);
});

test("Project dataset uploads, discovers schema and previews historical versions", async ({
  page,
}) => {
  test.skip(
    process.env.FOUNDRY_ARTIFACT_BACKEND !== "s3",
    "NOT RUN: use scripts/validate_phase13.py --browser",
  );
  await login(page);
  await page.getByRole("button", { name: "Projects", exact: true }).click();
  const name = `Dataset Project ${Date.now()}`;
  await page.getByLabel("New Project name").fill(name);
  await page
    .getByRole("button", { name: "Create Project", exact: true })
    .click();
  await page
    .getByLabel("Project", { exact: true })
    .selectOption({ label: `${name} (owner, ACTIVE)` });
  await page.getByLabel("New dataset name").fill("Machines dataset");
  await page
    .getByRole("button", { name: "Create dataset", exact: true })
    .click();
  await page
    .getByText("Dataset versions, schema and preview", { exact: true })
    .click();
  await page.getByLabel("Dataset file (up to 1 GiB)").setInputFiles({
    name: "machines.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("machineId,temperature\nM-1,42\nM-2,\n"),
  });
  await page
    .getByRole("button", { name: "Upload new version", exact: true })
    .click();
  await page
    .getByRole("button", {
      name: "Inspect schema and preview version 1",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("columnheader", { name: /machineId.*String/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "M-1", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "null", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Dataset file (up to 1 GiB)").setInputFiles({
    name: "bad.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("a,a\n1,2"),
  });
  await page
    .getByRole("button", { name: "Upload new version", exact: true })
    .click();
  await expect(
    page.getByText("Too many or duplicate columns", {
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByRole("button", {
      name: "Inspect schema and preview version 1",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("cell", { name: "M-1", exact: true }),
  ).toBeVisible();
});

test("governed pipeline publishes immutable output and real lineage", async ({
  page,
}) => {
  test.skip(
    process.env.FOUNDRY_ARTIFACT_BACKEND !== "s3",
    "NOT RUN: requires isolated MinIO runner",
  );
  await login(page);
  await page.getByRole("button", { name: "Projects", exact: true }).click();
  const name = `Pipeline Project ${Date.now()}`;
  await page.getByLabel("New Project name").fill(name);
  await page
    .getByRole("button", { name: "Create Project", exact: true })
    .click();
  await page
    .getByLabel("Project", { exact: true })
    .selectOption({ label: `${name} (owner, ACTIVE)` });
  async function createDataset(name: string) {
    await page.getByLabel("New dataset name").fill(name);
    const response = page.waitForResponse(
      (r) =>
        r.url().endsWith("/bff") &&
        r.request().postDataJSON()?.path?.endsWith("/datasets") &&
        r.request().postDataJSON()?.method === "POST",
    );
    await page
      .getByRole("button", { name: "Create dataset", exact: true })
      .click();
    return (await (await response).json()) as { id: string };
  }
  const input = await createDataset("Pipeline input");
  const inputPanel = page.locator("article.panel").filter({
    has: page.getByRole("heading", { name: "Pipeline input", exact: true }),
  });
  await inputPanel
    .getByText("Dataset versions, schema and preview", { exact: true })
    .click();
  await inputPanel.getByLabel("Dataset file (up to 1 GiB)").setInputFiles({
    name: "input.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("id,value\n1,a\n2,b\n"),
  });
  const finalized = page.waitForResponse(
    (r) =>
      r.url().endsWith("/bff") &&
      r.request().postDataJSON()?.path?.endsWith("/finalize"),
  );
  await inputPanel
    .getByRole("button", { name: "Upload new version", exact: true })
    .click();
  const version = await (await finalized).json();
  await expect(inputPanel.getByText(/Version 1 · COMMITTED/)).toBeVisible();
  const output = await createDataset("Pipeline output");
  await page.getByLabel("New pipeline name").fill("Select identifiers");
  await page
    .getByRole("button", { name: "Create pipeline", exact: true })
    .click();
  const panel = page.locator("article.panel").filter({
    has: page.getByRole("heading", {
      name: "Select identifiers",
      exact: true,
    }),
  });
  await panel
    .getByText("Pipeline definitions and runs", { exact: true })
    .click();
  const builder = panel.locator("details.pipeline-builder");
  await builder.getByRole("button", { name: "Dataset source" }).click();
  await builder.getByLabel("Source logical name").fill("source");
  await builder.getByLabel("Source dataset").selectOption(input.id);
  await builder.getByLabel("Immutable source version").selectOption(version.id);
  await builder.getByRole("button", { name: "select", exact: true }).click();
  await builder.getByLabel("Columns (comma separated)").fill("id");
  await builder.getByRole("button", { name: "Dataset output" }).click();
  await builder
    .getByLabel("Output dataset", { exact: true })
    .selectOption(output.id);
  await builder
    .getByLabel("Connection source")
    .selectOption({ label: "source" });
  await builder
    .getByLabel("Connection target")
    .selectOption({ label: "select" });
  await builder.getByRole("button", { name: "Add connection" }).click();
  await builder
    .getByLabel("Connection source")
    .selectOption({ label: "select" });
  await builder
    .getByLabel("Connection target")
    .selectOption({ label: "Dataset output" });
  await builder.getByRole("button", { name: "Add connection" }).click();
  await builder.getByRole("button", { name: "Save draft" }).click();
  await expect(builder.getByRole("status")).toContainText(
    "Saved draft revision 1",
  );
  await builder
    .getByRole("button", { name: "Validate graph", exact: true })
    .click();
  await expect(
    builder.getByRole("heading", { name: "Graph is valid", exact: true }),
  ).toBeVisible();
  await builder
    .getByRole("button", {
      name: "Publish immutable visual definition",
      exact: true,
    })
    .click();
  await expect(
    panel.getByText("Published immutable visual definition 1", { exact: true }),
  ).toBeVisible();
  await panel.getByRole("button", { name: "Launch run", exact: true }).click();
  await expect(async () => {
    await panel
      .getByRole("button", { name: "Refresh pipeline", exact: true })
      .click();
    await expect(panel.getByText(/· SUCCEEDED · attempt/)).toBeVisible();
  }).toPass({ timeout: 20000 });
  await panel
    .getByRole("button", { name: "Inspect lineage", exact: true })
    .click();
  await expect(panel.locator("pre").last()).toContainText(version.id);
  await expect(panel.locator("pre").last()).toContainText(input.id);
});

test("governed mapping validates materializes and records source provenance", async ({
  page,
}) => {
  expect(process.env.FOUNDRY_ARTIFACT_BACKEND).toBe("s3");
  await login(page);
  await page.getByRole("button", { name: "Projects", exact: true }).click();
  const name = `Mapping Project ${Date.now()}`;
  await page.getByLabel("New Project name").fill(name);
  await page
    .getByRole("button", { name: "Create Project", exact: true })
    .click();
  await page
    .getByLabel("Project", { exact: true })
    .selectOption({ label: `${name} (owner, ACTIVE)` });
  await page
    .getByText("Register published ontology assets", { exact: true })
    .click();
  await page.getByLabel("Catalog ontology ID").fill("manufacturing");
  await page.getByLabel("Published version", { exact: true }).fill("1.0.0");
  const catalogResponse = page.waitForResponse(
    (r) =>
      r.url().endsWith("/bff") &&
      r.request().postDataJSON()?.path?.endsWith("/catalog-import"),
  );
  await page.getByRole("button", { name: "Register catalog page" }).click();
  const catalog = await (await catalogResponse).json();
  const target = catalog.find(
    (r: { resource_type: string }) => r.resource_type === "ONTOLOGY_VERSION",
  );
  expect(target).toBeTruthy();
  await page.getByLabel("New dataset name").fill("Mapping source");
  const datasetResponse = page.waitForResponse(
    (r) =>
      r.url().endsWith("/bff") &&
      r.request().postDataJSON()?.path?.endsWith("/datasets") &&
      r.request().postDataJSON()?.method === "POST",
  );
  await page
    .getByRole("button", { name: "Create dataset", exact: true })
    .click();
  const source = await (await datasetResponse).json();
  const inputPanel = page.locator("article.panel").filter({
    has: page.getByRole("heading", { name: "Mapping source", exact: true }),
  });
  await inputPanel
    .getByText("Dataset versions, schema and preview", { exact: true })
    .click();
  const identifier = `Mapped-${Date.now()}`;
  await inputPanel.getByLabel("Dataset file (up to 1 GiB)").setInputFiles({
    name: "mapping.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(`factoryId,name\n${identifier},Mapped factory\n`),
  });
  const finalized = page.waitForResponse(
    (r) =>
      r.url().endsWith("/bff") &&
      r.request().postDataJSON()?.path?.endsWith("/finalize"),
  );
  await inputPanel
    .getByRole("button", { name: "Upload new version", exact: true })
    .click();
  const version = await (await finalized).json();
  await expect(inputPanel.getByText(/Version 1 · COMMITTED/)).toBeVisible();
  await page.getByLabel("New mapping name").fill("Factory mapping");
  await page
    .getByRole("button", { name: "Create mapping", exact: true })
    .click();
  const panel = page.locator("article.panel").filter({
    has: page.getByRole("heading", { name: "Factory mapping", exact: true }),
  });
  await panel
    .getByText("Dataset mapping and materialization", { exact: true })
    .click();
  await panel.getByLabel("Mapping specification JSON").fill(
    JSON.stringify({
      target_resource_id: target.id,
      ontology_id: "manufacturing",
      schema_version: "1.0.0",
      columns: { factoryId: "String", name: "String" },
      objects: [
        {
          object_type: "Factory",
          identity: {
            components: [{ column: "factoryId", conversion: "string" }],
          },
          properties: {
            factoryName: { column: "name", conversion: "string" },
            location: { constant: "E2E", conversion: "string" },
          },
        },
      ],
    }),
  );
  await panel
    .getByRole("button", { name: "Validate mapping structure", exact: true })
    .click();
  await expect(panel.getByLabel("Mapping result")).toContainText("structural");
  await panel.getByLabel("Source dataset ID").fill(source.id);
  await panel.getByLabel("Source dataset version ID").fill(version.id);
  await panel
    .getByRole("button", { name: "Preview draft sample", exact: true })
    .click();
  await expect(panel.getByLabel("Mapping result")).toContainText("sample-only");
  await panel
    .getByRole("button", { name: "Publish mapping definition", exact: true })
    .click();
  await expect(panel.getByLabel("Mapping definition version")).not.toHaveValue(
    "",
  );
  await panel.getByLabel("Source dataset ID").fill(source.id);
  await panel.getByLabel("Source dataset version ID").fill(version.id);
  await panel
    .getByRole("button", { name: "Preview mapped sample", exact: true })
    .click();
  await expect(panel.getByLabel("Mapping result")).toContainText("sample-only");
  await panel
    .getByRole("button", { name: "Validate full source", exact: true })
    .click();
  await expect(async () => {
    await panel
      .getByRole("button", { name: "Refresh mapping", exact: true })
      .click();
    await expect(panel.getByText(/· SUCCEEDED · attempt/)).toHaveCount(1);
  }).toPass({ timeout: 20000 });
  await panel
    .getByRole("button", { name: "Materialize dataset", exact: true })
    .click();
  await expect(async () => {
    await panel
      .getByRole("button", { name: "Refresh mapping", exact: true })
      .click();
    await expect(panel.getByText(/· SUCCEEDED · attempt/)).toHaveCount(2);
  }).toPass({ timeout: 20000 });
  await panel.getByLabel("Materialized object ID").fill(identifier);
  await panel
    .getByRole("button", { name: "Inspect materialized object", exact: true })
    .click();
  await expect(panel.getByLabel("Mapping result")).toContainText(
    "Mapped factory",
  );
  await panel
    .getByRole("button", { name: "View source provenance", exact: true })
    .first()
    .click();
  await expect(panel.getByLabel("Mapping result")).toContainText(version.id);
});
