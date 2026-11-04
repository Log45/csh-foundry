import type { Page } from "@playwright/test";
import { expect } from "@playwright/test";
export async function login(page: Page) {
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
