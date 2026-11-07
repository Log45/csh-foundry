import { test, expect } from "@playwright/test";
import { login } from "./login";

test("visual DAG branches converge and two outputs commit together", async ({
  page,
  browser,
}) => {
  expect(process.env.FOUNDRY_ARTIFACT_BACKEND).toBe("s3");
  await login(page);
  await page.getByRole("button", { name: "Projects", exact: true }).click();
  const project = `DAG ${Date.now()}`;
  await page.getByLabel("New Project name").fill(project);
  await page
    .getByRole("button", { name: "Create Project", exact: true })
    .click();
  await page
    .getByLabel("Project", { exact: true })
    .selectOption({ label: `${project} (owner, ACTIVE)` });
  const response = (suffix: string, method = "POST") =>
    page.waitForResponse(
      (r) =>
        r.url().endsWith("/bff") &&
        r.request().postDataJSON()?.path?.endsWith(suffix) &&
        r.request().postDataJSON()?.method === method,
    );
  const panel = (name: string) =>
    page
      .locator("article.panel")
      .filter({ has: page.getByRole("heading", { name, exact: true }) });
  async function dataset(name: string, data?: string) {
    await page.getByLabel("New dataset name").fill(name);
    const pending = response("/datasets");
    await page
      .getByRole("button", { name: "Create dataset", exact: true })
      .click();
    const resource = await (await pending).json();
    if (!data) return { ...resource, version: null };
    const scoped = panel(name);
    await scoped
      .getByText("Dataset versions, schema and preview", { exact: true })
      .click();
    await scoped.getByLabel("Dataset file (up to 1 GiB)").setInputFiles({
      name: "source.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(data),
    });
    const finalized = response("/finalize");
    await scoped
      .getByRole("button", { name: "Upload new version", exact: true })
      .click();
    const version = await (await finalized).json();
    await expect(scoped.getByText(/Version 1 · COMMITTED/)).toBeVisible();
    return { ...resource, version: version.id };
  }
  const a = await dataset("Orders", "id,value\n1,10\n2,20\n");
  const b = await dataset("Reference", "id,other\n1,100\n2,200\n");
  const outA = await dataset("Shared result");
  const outB = await dataset("Converged result");
  await page.getByLabel("New pipeline name").fill("Diamond DAG");
  const createdPipeline = response("/pipelines");
  await page
    .getByRole("button", { name: "Create pipeline", exact: true })
    .click();
  const pipeline = await (await createdPipeline).json();
  const scoped = panel("Diamond DAG");
  await scoped
    .getByText("Pipeline definitions and runs", { exact: true })
    .click();
  const builder = scoped.locator("details.pipeline-builder");
  async function add(name: string) {
    await builder.getByRole("button", { name, exact: true }).click();
    return (await builder
      .getByLabel("Connection target")
      .locator("option")
      .last()
      .getAttribute("value"))!;
  }
  // Source nodes cannot be targets, so capture their IDs from the source selector.
  async function source(
    name: string,
    resource: { id: string; version: string },
  ) {
    await add("Dataset source");
    await builder.getByLabel("Source logical name").fill(name);
    await builder.getByLabel("Source dataset").selectOption(resource.id);
    await builder
      .getByLabel("Immutable source version")
      .selectOption(resource.version);
    return (await builder
      .getByLabel("Connection source")
      .locator("option")
      .last()
      .getAttribute("value"))!;
  }
  const sourceA = await source("orders", a);
  const sourceB = await source("reference", b);
  const shared = await add("select");
  await builder.getByLabel("Columns (comma separated)").fill("id,value");
  const left = await add("drop");
  await builder.getByLabel("Columns (comma separated)").fill("value");
  const right = await add("rename");
  await builder
    .getByLabel("Renames (old:new, one per line)")
    .fill("value:renamed");
  const joined = await add("join");
  await builder.getByLabel("Join keys (comma separated)").fill("id");
  const joinedAgain = await add("join");
  await builder.getByLabel("Join keys (comma separated)").fill("id");
  const outputA = await add("Dataset output");
  await builder
    .getByLabel("Output dataset", { exact: true })
    .selectOption(outA.id);
  const outputB = await add("Dataset output");
  await builder
    .getByLabel("Output dataset", { exact: true })
    .selectOption(outB.id);
  async function connect(source: string, target: string, port = "input") {
    await builder.getByLabel("Connection source").selectOption(source);
    await builder.getByLabel("Connection target").selectOption(target);
    await builder.getByLabel("Target port").selectOption(port);
    await builder
      .getByRole("button", { name: "Add connection", exact: true })
      .click();
  }
  await connect(sourceA, shared);
  await connect(shared, left);
  await connect(shared, right);
  await connect(left, joined);
  await connect(right, joined, "right");
  await connect(joined, joinedAgain);
  await connect(sourceB, joinedAgain, "right");
  await connect(shared, outputA);
  await connect(joinedAgain, outputB);
  await builder
    .getByRole("button", { name: "Save draft", exact: true })
    .click();
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
    scoped.getByText("Published immutable visual definition 1", {
      exact: true,
    }),
  ).toBeVisible();
  const chooser = scoped.getByLabel("Published definition", { exact: true });
  const publishedOption = chooser
    .locator("option")
    .filter({ hasText: /^1 · / });
  await expect(publishedOption).toHaveCount(1);
  const publishedId = (await publishedOption.getAttribute("value"))!;
  await chooser.selectOption("");
  await chooser.selectOption(publishedId);
  await scoped.getByRole("button", { name: "Launch run", exact: true }).click();
  await expect(scoped.getByText(/· SUCCEEDED · attempt/)).toBeVisible({
    timeout: 30000,
  });
  await expect(scoped.getByText(/Publication: COMMITTED/)).toBeVisible();
  await expect(scoped.getByText(/Committed output /)).toHaveCount(2);
  await scoped
    .getByRole("button", { name: `Preview output ${outputA}`, exact: true })
    .click();
  await expect(scoped.locator("pre").last()).toContainText('"row_count": 2');
  await scoped
    .getByRole("button", { name: `Preview output ${outputB}`, exact: true })
    .click();
  await expect(scoped.locator("pre").last()).toContainText("other");
  await scoped
    .getByRole("button", { name: `Lineage output ${outputB}`, exact: true })
    .click();
  await expect(scoped.locator("pre").last()).toContainText(b.version);
  await expect(scoped.locator("pre").last()).not.toContainText(outA.id);
  // A second real run is cancelled before its publication transaction.
  await scoped.getByRole("button", { name: "Launch run", exact: true }).click();
  await scoped
    .getByRole("button", { name: "Cancel run", exact: true })
    .last()
    .click();
  await expect(scoped.getByText(/· CANCELLED · attempt/)).toBeVisible({
    timeout: 30000,
  });
  await expect(scoped.getByText(/Committed output /)).toHaveCount(2);
  const restricted = await browser.newContext();
  try {
    const viewer = await restricted.newPage();
    await login(viewer, "application-viewer");
    const denied = await viewer.evaluate(async (id) => {
      const session = await (await fetch("/auth/session")).json();
      const reply = await fetch("/bff", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-csrf-token": session.csrf,
        },
        body: JSON.stringify({
          path: `/api/v1/pipelines/${id}`,
          method: "GET",
          expected_tenant: session.tenant,
        }),
      });
      return reply.status;
    }, pipeline.id);
    expect([403, 404]).toContain(denied);
  } finally {
    await restricted.close();
  }
  // The backend rejects a cycle even after a prior immutable version succeeded.
  await connect(joinedAgain, shared);
  await builder
    .getByRole("button", { name: "Validate graph", exact: true })
    .click();
  await expect(
    builder.getByRole("heading", {
      name: "Graph needs attention",
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Lineage & observability", exact: true })
    .click();
  const observations = page.getByRole("region", {
    name: "Lineage and observability",
  });
  await observations
    .getByLabel("Lineage Project", { exact: true })
    .selectOption({ label: project });
  await observations
    .getByLabel("Lineage resource", { exact: true })
    .selectOption(outB.id);
  await expect(
    observations.getByLabel("Immutable lineage version").locator("option"),
  ).toHaveCount(2);
  await observations
    .getByRole("button", { name: "Explore lineage", exact: true })
    .click();
  await expect(
    observations.getByRole("table", { name: "Dependency evidence" }),
  ).toContainText("PRODUCES");
  await expect(
    observations.getByRole("table", { name: "Accessible lineage node list" }),
  ).toContainText("EXECUTION");
  await observations
    .getByRole("button", { name: "Select lineage node" })
    .first()
    .focus();
  await expect(
    observations.getByRole("button", { name: "Select lineage node" }).first(),
  ).toBeFocused();
  await observations.getByLabel("Maximum version age in seconds").fill("3600");
  await observations
    .getByRole("button", { name: "Save freshness policy", exact: true })
    .click();
  await expect(
    observations.getByRole("heading", { name: "Dataset freshness: FRESH" }),
  ).toBeVisible();
  await observations
    .getByLabel("Lineage resource", { exact: true })
    .selectOption(pipeline.id);
  await expect(
    observations.getByRole("table", { name: "Persisted executions" }),
  ).toContainText("CANCELLED");
  await observations
    .getByRole("button", { name: "Inspect execution" })
    .first()
    .click();
  await expect(
    observations.getByRole("region", { name: "Execution detail" }),
  ).toContainText("CANCELLED");
  await observations
    .getByRole("button", { name: "Inspect column lineage", exact: true })
    .click();
  await expect(
    observations.getByRole("table", { name: "Column lineage" }),
  ).toContainText("VALUE");
  await observations
    .getByRole("button", { name: "Analyze downstream impact", exact: true })
    .click();
  await expect(
    observations.getByRole("table", { name: "Downstream impact paths" }),
  ).toBeVisible();
  await observations
    .getByRole("button", { name: "Load operational events", exact: true })
    .click();
  await expect(
    observations.getByRole("table", { name: "Recent operational events" }),
  ).toContainText("SUCCEEDED");
  await page.screenshot({
    path: "../../artifacts/phase21/lineage-observability.png",
    fullPage: true,
  });
});
