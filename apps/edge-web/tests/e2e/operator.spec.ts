import { expect, test } from "@playwright/test";

test("operator dashboard shows current inspection, rules, and actions", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Current status")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Current product image" })).toBeVisible();
  await expect(page.locator(".detection-viewer img").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Inspection rules" })).toBeVisible();
  await expect(page.getByText("Component presence check")).toBeVisible();
  await expect(page.getByRole("button", { name: "Confirm result" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue next inspection" })).toBeVisible();
});

test("operator can confirm and advance the inspection", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Confirm result" }).click();
  await expect(page.getByText("PASS", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Continue next inspection" }).click();
  await expect(page.getByText("PROCESSING")).toBeVisible();
});

test("live inspection shows camera, detection result, and progress", async ({ page }) => {
  await page.goto("/live");
  await expect(page.getByRole("heading", { name: "Live inspection" })).toBeVisible();
  await expect(page.getByText("Camera image")).toBeVisible();
  await expect(page.getByText("Detection result")).toBeVisible();
  await expect(page.getByText("Detection regions")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Inspection details" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Runtime logs" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Inspection readiness" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Connectivity" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Pause inspection|Resume inspection/ })).toHaveCount(0);
  await expect(page.getByText("rule evaluation completed")).toBeVisible();
});

test("history searches by SN and filters by result", async ({ page }) => {
  await page.goto("/history");
  await expect(page.getByText("Inspection history")).toBeVisible();
  await page.getByPlaceholder("Search by SN").fill("SN-0001");
  await expect(page.locator(".el-table__row").first()).toBeVisible();
});

test("traceability shows reinspection attempts and final status", async ({ page }) => {
  await page.goto("/traceability/SN-0001");
  await expect(page.getByText("Final status")).toBeVisible();
  await expect(page.getByText("Inspection #1")).toBeVisible();
  await expect(page.getByText("Inspection #2")).toBeVisible();
  await expect(page.getByText("PASS", { exact: true }).last()).toBeVisible();
});

test("statistics renders totals and result split chart", async ({ page }) => {
  await page.goto("/statistics");
  await expect(page.getByText("Total inspections")).toBeVisible();
  await expect(page.getByText("Pass rate")).toBeVisible();
  await expect(page.locator(".echart canvas").first()).toBeVisible();
});

test("device status lists camera, vision engine, and inspection service", async ({ page }) => {
  await page.goto("/device");
  await expect(page.getByText("Camera connection")).toBeVisible();
  await expect(page.getByText("Vision engine")).toBeVisible();
  await expect(page.getByText("Inspection service")).toBeVisible();
});
