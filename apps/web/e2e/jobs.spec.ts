import { createBooksFolder, expect, settingsTab, signIn, test } from "./fixtures";

test("job + staff + timesheet → proposed invoice lines", async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);

  // Staff and rates live in Settings › Business.
  await page.goto("/settings");
  const staff = (await settingsTab(page, "Business")).getByRole("region", { name: "Staff" });
  await expect(staff).toContainText("No staff yet.");
  await staff.getByRole("button", { name: "Add person" }).click();
  const person = staff.getByRole("form", { name: "Staff member" });
  await person.getByLabel("Name").fill("Alex Carter");
  await person.getByLabel("Role").fill("Joiner");
  await person.getByLabel("Cost £/h").fill("25");
  await person.getByLabel("Charge £/h").fill("45");
  await person.getByRole("button", { name: "Save" }).click();
  await expect(staff.getByRole("row", { name: /Alex Carter/ })).toContainText("£45.00");

  await page.goto("/jobs");
  const form = page.getByRole("form", { name: "New job" });
  await form.getByLabel("New job").fill("Kitchen refit, 12 Harbour Lane");
  await form.getByLabel("Site address with postcode (optional)").fill("12 Harbour Lane, Bristol BS1 4RW");
  await form.getByRole("button", { name: "Add job" }).click();
  await page.getByRole("link", { name: "Kitchen refit, 12 Harbour Lane" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "Kitchen refit, 12 Harbour Lane" })).toBeVisible();
  const hours = page.getByRole("form", { name: "Add hours" });
  await expect(hours.getByLabel("Staff")).toHaveValue(/.+/); // the only active person is preselected
  await hours.getByLabel("Hours").fill("6");
  await hours.getByLabel("Note").fill("First fix");
  await hours.getByRole("button", { name: "Add", exact: true }).click();
  await expect(hours.getByRole("row", { name: /First fix/ })).toContainText("Alex Carter (Joiner)");

  const invoice = page.getByRole("region", { name: "Invoice" });
  await invoice.getByRole("button", { name: "Create invoice from unbilled hours" }).click();
  const line = invoice.getByRole("row", { name: /Alex Carter/ });
  await expect(line.getByRole("cell").nth(1)).toHaveText("6");
  await expect(line.getByRole("cell").nth(2)).toHaveText("£45.00");
  await expect(line.getByRole("cell").nth(3)).toHaveText("£270.00");
  await expect(invoice.getByRole("row", { name: /Total ex VAT/ })).toContainText("£270.00");
  await expect(invoice.getByRole("link", { name: "New invoice" })).toHaveAttribute("href", "/invoices/new");
});
