import { createBooksFolder, expect, GOLD, signIn, test } from "./fixtures";

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

test("edit a journey, rename a vehicle, delete refuses while journeys reference it", async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);

  await page.goto("/vehicles");
  const vehicles = page.getByRole("region", { name: "Vehicles" });
  await vehicles.getByLabel("Name").fill("Ford Transit");
  await vehicles.getByRole("button", { name: "Add vehicle" }).click();
  await expect(page.getByRole("status")).toHaveText("Added Ford Transit");

  const log = page.getByRole("region", { name: "Mileage log" });
  await log.getByLabel("From").fill("Bristol");
  await log.getByLabel("To").fill("Bath");
  await log.getByLabel("Miles").fill("100");
  await log.getByLabel("Purpose").fill("Quote for kitchen, Harbour Lane");
  await log.getByRole("button", { name: "Add journey" }).click();
  await expect(page.getByRole("status")).toHaveText("Logged 100 miles");

  // Edit the journey: 120 miles at 45p is £54.00 in the quarter totals
  await log.getByRole("button", { name: /^Edit the journey/ }).click();
  const edit = page.getByRole("form", { name: "Edit journey" });
  await edit.getByLabel("Miles").fill("120");
  await edit.getByLabel("Purpose").fill("Quote for kitchen, Harbour View");
  await edit.getByRole("button", { name: "Save journey" }).click();
  await expect(page.getByRole("status")).toHaveText("Journey updated");
  await expect(log.getByRole("row").filter({ hasText: "Harbour View" })).toContainText("120.0");

  // Rename the vehicle
  await vehicles.getByRole("button", { name: "Rename Ford Transit" }).click();
  const rename = page.getByRole("form", { name: "Rename vehicle" });
  await rename.getByLabel("Name").fill("Transit Van");
  await rename.getByRole("button", { name: "Save name" }).click();
  await expect(page.getByRole("status")).toHaveText("Renamed to Transit Van");
  await expect(vehicles).toContainText("Transit Van");

  // Delete refuses while a journey references it, and says why
  await vehicles.getByRole("button", { name: "Delete Transit Van" }).click();
  await expect(page.getByRole("status")).toContainText("has journeys in the mileage log");
  await expect(vehicles).toContainText("Transit Van");

  // Once the journey is gone the vehicle deletes
  await log.getByRole("button", { name: /^Delete the journey/ }).click();
  await expect(page.getByRole("status")).toHaveText("Journey deleted");
  await vehicles.getByRole("button", { name: "Delete Transit Van" }).click();
  await expect(page.getByRole("status")).toHaveText("Deleted Transit Van");
  await expect(vehicles).not.toContainText("Transit Van");
});

test("Review offers Add a vehicle when no business vehicle is active", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);

  await page.goto("/review");
  await page.locator('input[type="file"]').first().setInputFiles({ name: `${GOLD}.png`, mimeType: "image/png", buffer: await runtime.goldPng() });
  await expect(page.getByText("1 file added to 00 Inbox")).toBeVisible();
  await page.getByRole("button", { name: "Scan 00 Inbox now" }).click();
  const novex = page.getByRole("region", { name: "Novex Office Supplies Ltd · £51.90" });
  await expect(novex).toBeVisible();
  const add = novex.getByRole("link", { name: "Add a vehicle" });
  await expect(add).toBeVisible();
  await expect(add).toHaveAttribute("href", "/vehicles");
});
