import { test, expect } from "@playwright/test";
test("real OIDC, tenant, SDK queries, errors and session invalidation", async ({
  page,
  context,
}) => {
  await page.route("https://127.0.0.1/oidc/**", async (route) => {
    const response = await route.fetch({
      url: route
        .request()
        .url()
        .replace("https://127.0.0.1/", "https://127.0.0.1:8443/"),
      maxRedirects: 0,
    });
    await route.fulfill({ response });
  });
  await page.goto("/");
  await page
    .getByRole("button", { name: "Sign in with OpenID Connect" })
    .click();
  const tenant = page.getByLabel("Tenant", { exact: true });
  await expect(tenant).toBeVisible();
  const option = tenant
    .locator("option")
    .filter({ hasText: "Manufacturing test tenant" });
  await tenant.selectOption((await option.getAttribute("value"))!);
  await expect(
    page.getByRole("heading", { name: "Ontology objects" }),
  ).toBeVisible();
  // The fixture starts with an unpublished schema. Use the already governed BFF to publish/activate.
  const session = await page.evaluate(
    async () => await (await fetch("/auth/session")).json(),
  );
  for (const operation of ["publish", "activate"]) {
    const status = await page.evaluate(
      async ({ csrf, tenant, operation }) =>
        (
          await fetch("/bff", {
            method: "POST",
            headers: {
              "content-type": "application/json",
              "x-csrf-token": csrf,
            },
            body: JSON.stringify({
              path: `/api/v1/ontologies/manufacturing/versions/1.0.0/${operation}`,
              method: "POST",
              body: {},
              expected_tenant: tenant,
            }),
          })
        ).status,
      { csrf: session.csrf, tenant: session.tenant, operation },
    );
    expect(status).toBe(200);
  }
  await page.getByRole("button", { name: "Refresh objects" }).click();
  await expect(page.locator("pre").first()).toContainText("schema_version");
  await page.getByLabel("Object type", { exact: true }).fill("MissingType");
  await expect(page.locator("main [role=alert]").first()).toContainText(
    "validation: unknown_object_type",
  );
  await page.getByLabel("Object type", { exact: true }).fill("Machine");
  await expect(page.locator("pre").first()).toContainText("items");
  const seeded = await page.evaluate(
    async ({ csrf, tenant }) => {
      async function api(path: string, method = "GET", body?: unknown) {
        const response = await fetch("/bff", {
          method: "POST",
          headers: { "content-type": "application/json", "x-csrf-token": csrf },
          body: JSON.stringify({
            path: "/api/v1" + path,
            method,
            body,
            expected_tenant: tenant,
          }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(JSON.stringify(data));
        return data;
      }
      const project = await api("/projects", "POST", { name: "SDK browser" });
      const dataset = await api(`/projects/${project.id}/datasets`, "POST", {
        name: "SDK source",
      });
      const bytes = new TextEncoder().encode(
        "id,name\nSDK-BROWSER,Example Factory\n",
      );
      const checksum = Array.from(
        new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
        (b) => b.toString(16).padStart(2, "0"),
      ).join("");
      const version = await api(`/datasets/${dataset.id}/uploads`, "POST", {
        filename: "sdk.csv",
        size: bytes.length,
        checksum,
        format: "csv",
      });
      const transfer = await fetch(
        "/bff/artifacts?" +
          new URLSearchParams({
            family: "datasets",
            artifact: dataset.id,
            version: version.id,
            operation: "upload",
          }),
        {
          method: "POST",
          headers: { "x-csrf-token": csrf, "x-expected-tenant": tenant },
          body: bytes,
        },
      );
      if (!transfer.ok) throw new Error("upload failed");
      await api(
        `/datasets/${dataset.id}/versions/${version.id}/finalize`,
        "POST",
      );
      const output = await api(`/projects/${project.id}/datasets`, "POST", {
        name: "SDK output",
      });
      const pipeline = await api(`/projects/${project.id}/pipelines`, "POST", {
        name: "SDK pipeline",
      });
      const definition = await api(
        `/pipelines/${pipeline.id}/definitions`,
        "POST",
        {
          engine: "polars",
          inputs: [
            { name: "source", columns: { id: "String", name: "String" } },
          ],
          steps: [{ op: "select", columns: ["id"] }],
          output_columns: { id: "String" },
        },
      );
      const run = await api(`/pipelines/${pipeline.id}/runs`, "POST", {
        definition_id: definition.id,
        inputs: [
          { name: "source", dataset_id: dataset.id, version_id: version.id },
        ],
        output_dataset_id: output.id,
      });
      const target = await api(`/projects/${project.id}/resources`, "POST", {
        name: "Ontology",
        resource_type: "ONTOLOGY_VERSION",
        ontology_id: "manufacturing",
        schema_version: "1.0.0",
        entity_id: "1.0.0",
      });
      const mapping = await api(`/projects/${project.id}/mappings`, "POST", {
        name: "SDK mapping",
      });
      const mapped = await api(`/mappings/${mapping.id}/definitions`, "POST", {
        target_resource_id: target.id,
        ontology_id: "manufacturing",
        schema_version: "1.0.0",
        columns: { id: "String", name: "String" },
        objects: [
          {
            object_type: "Factory",
            identity: { components: [{ column: "id", conversion: "string" }] },
            properties: {
              factoryName: { column: "name", conversion: "string" },
              location: { constant: "North", conversion: "string" },
            },
          },
        ],
      });
      const materialization = await api(
        `/mappings/${mapping.id}/runs`,
        "POST",
        {
          definition_id: mapped.id,
          dataset_id: dataset.id,
          version_id: version.id,
        },
      );
      return {
        dataset: dataset.id,
        version: version.id,
        run: run.id,
        mapping: mapping.id,
        materialization: materialization.id,
      };
    },
    { csrf: session.csrf, tenant: session.tenant },
  );
  await page.getByLabel("Dataset UUID", { exact: true }).fill(seeded.dataset);
  await page.getByLabel("Version UUID", { exact: true }).fill(seeded.version);
  const datasetPanel = page.locator("section").filter({
    has: page.getByRole("heading", { name: "Dataset schema and preview" }),
  });
  await expect(datasetPanel.locator("pre").last()).toContainText(
    "Example Factory",
  );
  await page.getByLabel("Pipeline run UUID", { exact: true }).fill(seeded.run);
  const pipelinePanel = page.locator("section").filter({
    has: page.getByRole("heading", { name: "Pipeline run", exact: true }),
  });
  await expect(pipelinePanel.getByRole("status")).toContainText("SUCCEEDED", {
    timeout: 60000,
  });
  await page.getByLabel("Mapping UUID", { exact: true }).fill(seeded.mapping);
  await page
    .getByLabel("Materialization run UUID", { exact: true })
    .fill(seeded.materialization);
  const mappingPanel = page.locator("section").filter({
    has: page.getByRole("heading", {
      name: "Materialization run",
      exact: true,
    }),
  });
  await expect(mappingPanel.getByRole("status")).toContainText("SUCCEEDED", {
    timeout: 60000,
  });
  await expect(mappingPanel.getByRole("status")).toContainText(
    "committed batches",
  );
  expect(
    (await context.cookies()).find((c) => c.name === "foundry-session")
      ?.httpOnly,
  ).toBe(true);
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([]);
  await page.route("**/bff", (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ error: { code: "session_expired" } }),
    }),
  );
  await page.getByRole("button", { name: "Refresh objects" }).click();
  await expect(page.locator("main [role=alert]")).toContainText(
    "Session expired",
  );
  await expect(
    page.getByRole("heading", { name: "Ontology objects" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Sign in with OpenID Connect" }),
  ).toBeVisible();
});
