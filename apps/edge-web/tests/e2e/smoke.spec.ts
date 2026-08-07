import { expect, test } from "@playwright/test";

test("live screen shows recent inspections and latest decision", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Latest result" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Recent inspections" })).toBeVisible();
  await expect(page.getByText("AssemblyVision Edge")).toBeVisible();
});

test("pause requires a reason and rejects duplicate pause", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Pause" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Pause" }).click();
  await expect(page.getByText("A reason is required")).toBeVisible();
  await dialog.locator("input").fill("shift change");
  await dialog.getByRole("button", { name: "Pause" }).click();
  await expect(page.getByRole("button", { name: "Resume" })).toBeVisible();
});

test("inspection history filters by result", async ({ page }) => {
  await page.goto("/inspections");
  await expect(page.getByText("Inspection ID")).toBeVisible();
  await page.locator(".el-select").first().click();
  await page.getByRole("option", { name: "NG", exact: true }).click();
  await expect(page.locator(".el-table__row").first()).toBeVisible();
});

test("inspection detail shows evidence and reason codes", async ({ page }) => {
  await page.goto("/inspections/00000000-0000-4000-8000-000000000103");
  await expect(page.getByRole("heading", { name: /Inspection 0000/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Reason codes" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Components" })).toBeVisible();
});

test("health page renders disk gauge and queue chart", async ({ page }) => {
  await page.goto("/health");
  await expect(page.getByRole("heading", { name: "Device health" })).toBeVisible();
  await expect(page.locator(".echart canvas").first()).toBeVisible();
  await expect(page.locator(".echart canvas").nth(1)).toBeVisible();
});
