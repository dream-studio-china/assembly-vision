import { expect, test } from "@playwright/test";

// Theme system E2E (design 16.2.1): selection, persistence, keyboard access,
// and the compact 1280px live layout must hold in every theme.
const THEME_KEY = "assemblyvision.edge.theme";

async function selectTheme(page: import("@playwright/test").Page, label: string): Promise<void> {
  await page.getByTestId("theme-selector").click();
  await page.getByRole("option", { name: label, exact: true }).click();
}

test("theme selection persists and applies the data-theme attribute", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "industrial");

  await selectTheme(page, "Modern Light");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect
    .poll(() => page.evaluate((key) => localStorage.getItem(key), THEME_KEY))
    .toBe("light");

  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

  await selectTheme(page, "Modern Dark");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect
    .poll(() => page.evaluate((key) => localStorage.getItem(key), THEME_KEY))
    .toBe("dark");
});

test("theme selector is keyboard accessible", async ({ page }) => {
  await page.goto("/");
  const select = page.getByRole("combobox", { name: "Interface theme" });
  await select.focus();
  await select.press("Enter");
  await expect(page.getByRole("option", { name: "Industrial Minimal" })).toBeVisible();
  await page.keyboard.press("Escape");
});

test("live inspection layout renders without vertical scroll at 1280px", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/live");
  await expect(page.getByRole("heading", { name: "Live inspection" })).toBeVisible();
  // The operator dashboard and the live page must stay usable in each theme.
  for (const label of ["Modern Light", "Modern Dark"]) {
    await selectTheme(page, label);
    await expect(page.locator("html")).toHaveAttribute(
      "data-theme",
      label === "Modern Light" ? "light" : "dark",
    );
    await expect(page.getByRole("heading", { name: "Live inspection" })).toBeVisible();
  }
});
