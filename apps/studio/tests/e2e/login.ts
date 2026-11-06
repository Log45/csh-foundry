import type { Page } from "@playwright/test";
import { expect } from "@playwright/test";
export async function login(page: Page, subject = "operator") {
  await page.route("https://127.0.0.1/oidc/**", async (route) => {
    const target = new URL(
      route
        .request()
        .url()
        .replace("https://127.0.0.1/", "https://127.0.0.1:8443/"),
    );
    if (subject !== "operator" && target.pathname.endsWith("/authorize"))
      target.searchParams.set("login_hint", subject);
    const result = await route.fetch({
      url: target.toString(),
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
