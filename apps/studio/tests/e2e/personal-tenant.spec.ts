import { expect, test } from "@playwright/test";
import { login, signIn } from "./login";

test("first and repeat sign-in use the same personal tenant", async ({
  browser,
}) => {
  const first = await browser.newPage();
  await signIn(first, "newcomer");
  const tenant = first.getByLabel("Tenant", { exact: true });
  const personal = tenant.getByRole("option", { name: "Personal workspace" });
  const id = await personal.getAttribute("value");
  expect(id).toMatch(/^[a-f0-9-]{36}$/);
  await expect(tenant).toHaveValue(id!);
  await first.close();

  const next = await browser.newPage();
  await signIn(next, "newcomer");
  await expect(next.getByLabel("Tenant", { exact: true })).toHaveValue(id!);
  await next.close();
});

test("shares an ontology across tenants and revokes it from Studio", async ({
  page: owner,
  browser,
}) => {
  const recipient = await browser.newPage();
  try {
    await login(owner);
    const tenant = owner.getByLabel("Tenant", { exact: true });
    const owningTenant = await tenant.inputValue();
    await tenant.selectOption({ label: "Other E2E" });
    await expect(
      owner.getByLabel("Ontology", { exact: true }).getByRole("option", {
        name: "manufacturing",
      }),
    ).toHaveCount(0);
    await tenant.selectOption(owningTenant);

    await signIn(recipient, "newcomer");
    await recipient
      .getByRole("button", { name: "Sharing", exact: true })
      .click();
    const principal = recipient.getByText(/^Principal ID /).locator("code");
    await expect(principal).toHaveText(/^[a-f0-9-]{36}$/);

    await owner.getByRole("button", { name: "Sharing", exact: true }).click();
    await owner.getByRole("button", { name: "Shared by me" }).click();
    await owner
      .getByLabel("Resource", { exact: true })
      .selectOption("ontology");
    await owner.getByLabel("Search ontology", { exact: true }).fill("manuf");
    const ontology = owner.getByLabel("Ontology to share", { exact: true });
    await expect(ontology.locator("option[value=manufacturing]")).toHaveCount(
      1,
    );
    await ontology.selectOption("manufacturing");
    await owner
      .getByLabel("Recipient type", { exact: true })
      .selectOption("principal");
    await owner
      .getByLabel("Recipient principal ID", { exact: true })
      .fill(await principal.innerText());
    await owner.getByRole("button", { name: "Send invitation" }).click();
    await expect(owner.getByText(/viewer · pending/)).toBeVisible();

    await recipient.reload();
    await recipient
      .getByRole("button", { name: "Sharing", exact: true })
      .click();
    await expect(
      recipient.getByText(`Owning tenant ${owningTenant}`),
    ).toBeVisible();
    await recipient.getByRole("button", { name: "Accept invitation" }).click();
    await recipient
      .getByRole("button", { name: "Open shared resource" })
      .click();
    await expect(
      recipient.getByText(/1\.0\.0 · (DRAFT|PUBLISHED)/),
    ).toBeVisible();

    await owner.getByRole("button", { name: "Revoke share" }).click();
    await expect(owner.getByText(/viewer · revoked/)).toBeVisible();
    await recipient.reload();
    await recipient
      .getByRole("button", { name: "Sharing", exact: true })
      .click();
    await expect(recipient.getByText(/viewer · revoked/)).toBeVisible();
    await expect(
      recipient.getByRole("button", { name: "Open shared resource" }),
    ).toHaveCount(0);
  } finally {
    await recipient.close();
  }
});
