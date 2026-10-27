import { createBooksFolder, expect, signIn, test } from "./fixtures";

test("Settings toggles persist across a reload", async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/settings");

  await expect(page.getByRole("region", { name: "Connections" })).toContainText("Signed in");
  const autopilot = page.getByRole("radiogroup", { name: "Autopilot level" });
  const period = page.getByRole("radiogroup", { name: "VAT return period" });
  const intake = page.getByRole("switch", { name: "Outlook intake" });
  await expect(autopilot.getByRole("radio", { name: /L1 Assist/ })).toHaveAttribute("aria-checked", "true");

  await autopilot.getByRole("radio", { name: /L2 Autopilot/ }).click();
  await period.getByRole("radio", { name: "Monthly" }).click();
  await intake.click();
  await expect(intake).toHaveAttribute("aria-checked", "true");

  await page.reload();
  await expect(autopilot.getByRole("radio", { name: /L2 Autopilot/ })).toHaveAttribute("aria-checked", "true");
  await expect(autopilot.getByRole("radio", { name: /L1 Assist/ })).toHaveAttribute("aria-checked", "false");
  await expect(period.getByRole("radio", { name: "Monthly" })).toHaveAttribute("aria-checked", "true");
  await expect(intake).toHaveAttribute("aria-checked", "true");
});
