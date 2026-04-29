import { expect, test } from "@playwright/test";

test("frontend renders and reads backend health", async ({ page }) => {
  await page.goto("/");

  await expect(
    page.getByRole("heading", { name: /ai-driven development starter/i }),
  ).toBeVisible();

  await expect(page.getByTestId("health-status")).toHaveText("ok");
});
