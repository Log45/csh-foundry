import { test, expect, type Page } from "@playwright/test";
import { login } from "./login";
async function request(
  page: Page,
  path: string,
  method = "GET",
  body?: unknown,
) {
  return page.evaluate(
    async (args) => {
      const session = await (await fetch("/auth/session")).json();
      const response = await fetch("/bff", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-csrf-token": session.csrf,
        },
        body: JSON.stringify({ ...args, expected_tenant: session.tenant }),
      });
      return { status: response.status, value: await response.json() };
    },
    { path, method, body },
  );
}
test("another signed-in principal cannot borrow application, object or action authority", async ({
  page,
  browser,
}) => {
  await login(page);
  const created = await request(page, "/api/v1/projects", "POST", {
    name: `Private application ${Date.now()}`,
  });
  expect(created.status).toBe(200);
  const project = created.value;
  const app = (
    await request(page, `/api/v1/projects/${project.id}/applications`, "POST", {
      name: "Private application",
    })
  ).value;
  expect(app.id).toBeTruthy();
  const saved = await request(
    page,
    `/api/v1/applications/${app.id}/draft`,
    "PUT",
    {
      expected_revision: 0,
      document: {
        title: "Private application",
        home: "home",
        pages: [
          {
            id: "home",
            title: "Private page",
            widgets: [
              { id: "text", kind: "text", text: "Private author content" },
            ],
          },
        ],
      },
    },
  );
  expect(saved.status).toBe(200);
  const pub = (
    await request(page, `/api/v1/applications/${app.id}/versions`, "POST", {
      expected_revision: 1,
    })
  ).value;
  expect(pub.id).toBeTruthy();
  const viewerContext = await browser.newContext();
  try {
    const viewer = await viewerContext.newPage();
    await login(viewer, "application-viewer");
    await viewer.goto(`/applications/${app.id}/versions/${pub.id}`);
    await expect(viewer.getByRole("main").getByRole("alert")).toContainText(
      "Application unavailable",
    );
    await expect(viewer.getByText("Private author content")).toHaveCount(0);
    expect(
      (
        await request(
          viewer,
          "/api/v1/ontologies/manufacturing/objects/Machine/query",
          "POST",
          { object_type: "Machine", limit: 1 },
        )
      ).status,
    ).toBe(403);
    expect(
      (
        await request(
          viewer,
          "/api/v1/ontologies/manufacturing/actions/UpdateMachineStatus/execute",
          "POST",
          {
            parameters: {
              machineId: "MCH-001",
              newStatus: "STOPPED",
              expectedRevision: 1,
            },
            idempotency_key: "unauthorized-viewer",
          },
        )
      ).status,
    ).toBe(403);
  } finally {
    await viewerContext.close();
  }
});
