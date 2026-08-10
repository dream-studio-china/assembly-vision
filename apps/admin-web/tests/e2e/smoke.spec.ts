import { expect, test } from "@playwright/test";

test("pilot admin web loads the overview shell", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "AssemblyVision Central Administration" }),
  ).toBeVisible();
});
