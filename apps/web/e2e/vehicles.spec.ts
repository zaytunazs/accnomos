import { createBooksFolder, expect, signIn, test } from "./fixtures";

test("vehicle + journey → the quarter's mileage allowance is proposed in Review", async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);

  await page.goto("/vehicles");
  const vehicles = page.getByRole("region", { name: "Vehicles" });
  await vehicles.getByLabel("Name").fill("Ford Transit");
  await vehicles.getByLabel("Registration (optional)").fill("SA26 MPL");
  await vehicles.getByRole("button", { name: "Add vehicle" }).click();
  await expect(page.getByRole("status")).toHaveText("Added Ford Transit");

  const log = page.getByRole("region", { name: "Mileage log" });
  await expect(log.getByLabel("Date")).toHaveValue("2026-10-27");
  await log.getByLabel("From").fill("Bristol");
  await log.getByLabel("To").fill("Bath");
  await log.getByLabel("Miles").fill("100");
  await log.getByLabel("Purpose").fill("Quote for kitchen, Harbour Lane");
  await log.getByRole("button", { name: "Add journey" }).click();
  await expect(page.getByRole("status")).toHaveText("Logged 100 miles");
  await expect(log.getByRole("row").filter({ hasText: "Bristol → Bath" })).toContainText("Ford Transit");

  // 100 business miles at 45p (under 10,000 this tax year) = £45.00, worked out by code
  await page.getByRole("button", { name: "Claim this quarter's mileage" }).click();
  await expect(page.getByRole("status")).toContainText("mileage claim for £45.00 is waiting in Review for you to approve.");
  await expect(page.getByRole("region", { name: "Quarters" }).getByRole("link", { name: "Waiting in Review" })).toBeVisible();

  await page.getByRole("status").getByRole("link", { name: "Open Review" }).click();
  await expect(page).toHaveURL(/\/review$/);
  await expect(page.getByRole("region", { name: /£45\.00/ })).toBeVisible();
});
