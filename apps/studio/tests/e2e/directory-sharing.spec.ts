import { expect, test, type Page } from "@playwright/test";
import { startSignIn } from "./login";

async function nameWorkspace(page: Page, name: string) {
  await page.getByLabel("Workspace name").fill(name);
  await page.getByRole("button", { name: "Create workspace" }).click();
}

test("claims a directory invitation after OIDC and workspace naming", async ({
  page: sender,
  browser,
}) => {
  test.skip(
    process.env.STUDIO_E2E_LDAP !== "true",
    "Requires the disposable directory and named-onboarding fixture",
  );
  await startSignIn(sender);
  await nameWorkspace(sender, "Sender workspace");
  const tenant = sender.getByLabel("Tenant", { exact: true });
  await tenant.selectOption({ label: "Manufacturing test tenant" });
  await expect(
    sender.getByRole("heading", { name: "manufacturing", exact: true }),
  ).toBeVisible();
  await sender.getByRole("button", { name: "Sharing", exact: true }).click();
  await sender.getByRole("button", { name: "Shared by me" }).click();
  await sender.getByLabel("Resource", { exact: true }).selectOption("ontology");
  await sender.getByLabel("Search ontology", { exact: true }).fill("manuf");
  const ontology = sender.getByLabel("Ontology to share", { exact: true });
  await expect(ontology.locator("option[value=manufacturing]")).toHaveCount(1);
  await ontology.selectOption("manufacturing");
  const picker = sender.getByRole("combobox", {
    name: "Recipient",
    exact: true,
  });
  await picker.focus();
  await expect(
    sender.getByRole("option", {
      name: /Invited Newcomer \(invite-newcomer\)/,
    }),
  ).toBeVisible();
  await picker.press("ArrowDown");
  await picker.press("Enter");
  await sender.getByRole("button", { name: "Send invitation" }).click();
  const link = new URL(await sender.getByLabel("Invitation link").inputValue());
  expect(link.search).toBe("");
  expect(link.hash).toMatch(/^#share=[a-f0-9-]{36}\.[A-Za-z0-9_-]{43}$/);

  const recipient = await browser.newPage();
  try {
    const idpRequests: string[] = [];
    recipient.on("request", (request) => {
      if (request.url().startsWith("https://127.0.0.1/oidc/"))
        idpRequests.push(request.url());
    });
    await startSignIn(recipient, "invite-newcomer", link.href);
    await nameWorkspace(recipient, "Recipient workspace");
    await recipient.getByRole("button", { name: "Accept invitation" }).click();
    await recipient
      .getByRole("button", { name: "Open shared resource" })
      .click();
    await expect(
      recipient.getByText(/1\.0\.0 · (DRAFT|PUBLISHED)/),
    ).toBeVisible();
    expect(new URL(recipient.url()).hash).toBe("");
    expect(idpRequests.length).toBeGreaterThan(0);
    for (const request of idpRequests) {
      expect(request).not.toContain(link.hash.slice(7));
    }
  } finally {
    await recipient.close();
  }
});
