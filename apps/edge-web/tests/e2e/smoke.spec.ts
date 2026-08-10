import { expect, test } from "@playwright/test";

test("app shell renders navigation and the operator dashboard", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("AssemblyVision", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Operator" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Live" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Statistics" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Config" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Logs" })).toBeVisible();
  await expect(page.getByText("Current status")).toBeVisible();
});

test("inspection history filters by result", async ({ page }) => {
  await page.goto("/inspections");
  await expect(page.getByText("Inspection ID")).toBeVisible();
  await page.getByTestId("inspection-result-filter").click();
  await page.getByRole("option", { name: "NG", exact: true }).click();
  await expect(page.locator(".el-table__row").first()).toBeVisible();
});

test("inspection detail shows evidence and reason codes", async ({ page }) => {
  await page.goto("/inspections/00000000-0000-4000-8000-000000000103");
  await expect(page.getByRole("heading", { name: /Inspection 0000/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Reason codes" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Components" })).toBeVisible();
});

test("health page renders system gauges and queue chart on one row", async ({ page }) => {
  await page.goto("/health");
  await expect(page.getByRole("heading", { name: "Device health" })).toBeVisible();
  await expect(page.locator(".health__gauges .gauge")).toHaveCount(3);
  await expect(page.locator(".gauge__label", { hasText: "Load" })).toBeVisible();
  await expect(page.locator(".gauge__label", { hasText: "Memory" })).toBeVisible();
  await expect(page.locator(".gauge__label", { hasText: "Disk" })).toBeVisible();
  await expect(page.locator(".health__gauges .health__queue .echart canvas")).toBeVisible();
});
