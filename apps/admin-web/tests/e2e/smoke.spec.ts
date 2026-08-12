import { expect, test } from "@playwright/test";

/**
 * Admin-web pilot e2e.
 *
 * The login-page smoke runs without a backend (CI). When CENTRAL_E2E_TOKEN is
 * set (local Compose verification), the full pilot flow runs against the
 * proxied central API: sign-in, overview counts, history filtering, and
 * detail rendering with authorized evidence.
 */

test("login page renders the pilot sign-in", async ({ page }) => {
  await page.goto("/login");
  await expect(
    page.getByRole("heading", { name: "AssemblyVision Central" }),
  ).toBeVisible();
  await expect(page.getByPlaceholder("Administrator token")).toBeVisible();
});

const token = process.env.CENTRAL_E2E_TOKEN;

test("pilot flow: sign in, overview, history filter, detail", async ({ page }) => {
  test.skip(!token, "full pilot flow needs a Compose-backed central API");
  await page.goto("/login");
  await page.getByPlaceholder("Administrator token").fill(token!);
  await page.getByRole("button", { name: "Sign in" }).click();

  // Overview renders counts from the proxied dashboard API.
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.locator(".metric-value").first()).toBeVisible();

  // History lists inspections and filters by result.
  await page.getByRole("link", { name: "Inspections" }).click();
  await expect(page.getByRole("heading", { name: "Inspection history" })).toBeVisible();
  await page.getByPlaceholder("Barcode").fill("SN-0001");
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page.locator(".el-table__body")).toContainText("SN-0001");

  // Detail renders decision, evidence, and authorized media.
  const row = page.locator(".el-table__body tr").first();
  await row.getByRole("link", { name: "Detail" }).click();
  await expect(page.getByRole("heading", { name: /Inspection/ })).toBeVisible();
  await expect(page.getByText("Component evidence")).toBeVisible();
});
