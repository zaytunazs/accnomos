import { join } from "node:path";
import { createBooksFolder, expect, signIn, test } from "./fixtures";

// SAMPLE — FICTIONAL COMPANY: Hollybank Joinery Ltd as at 31 Mar 2026 in Sage 50's layout
// (services/runtime/tests/fixtures/import/README.md): 66,185.10 each side, 3 open invoices, 2 open bills.
const SAGE = join(__dirname, "../../../services/runtime/tests/fixtures/import/sage50");

test("import from Sage 50: upload → map → check → post → reconciled → undo", async ({ page, runtime }) => {
  await runtime.reset();
  await signIn(page);
  await createBooksFolder(page);

  await page.goto("/import");
  await expect(page.getByRole("heading", { name: "Import history", level: 1 })).toBeVisible();
  await page.getByLabel("Old system").selectOption("sage50");
  await page.getByLabel(/Conversion date/).fill("2026-04-01");
  await expect(page.getByText("Export everything as at 31 Mar 2026, the day before.")).toBeVisible();

  const file = page.locator('input[type="file"]');
  for (const name of ["trial_balance.csv", "aged_debtors.csv", "aged_creditors.csv"]) {
    await file.setInputFiles(join(SAGE, name));
    await page.getByRole("button", { name: "Upload", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: `Read ${name}.` })).toBeVisible();
  }
  const files = page.getByRole("list", { name: "Uploaded files" });
  await expect(files.getByRole("listitem")).toHaveCount(3);
  await expect(files).toContainText("Left out: Row 5 (Carter & Sons): a 'SR' is not an invoice or bill");

  // Mapping: Sage keeps its codes; the VAT liability goes to our VAT control by name.
  const mapping = page.getByRole("region", { name: "Account mapping" });
  await expect(mapping.getByLabel("Accnomos account for 2202 VAT Liability")).toHaveValue("2200 VAT control");
  await expect(mapping.getByLabel("Accnomos account for 0050 Motor Vehicles")).toHaveValue("0050 Motor Vehicles");

  // A change is saved and comes back as the user's choice.
  const motor = mapping.getByLabel("Accnomos account for 7300 Fuel and Oil");
  await motor.fill("7310 Motor — fuel");
  await motor.press("Enter");
  await expect(mapping.locator('tr[data-account="code:7300"]')).toContainText("your choice");

  const checks = page.getByRole("list", { name: "Checks" });
  await expect(checks.locator('[data-check="tb_balanced"]')).toHaveAttribute("data-ok", "yes");
  await expect(checks.locator('[data-check="debtors_match"]')).toHaveAttribute("data-ok", "yes");
  await expect(checks.locator('[data-check="creditors_match"]')).toHaveAttribute("data-ok", "yes");
  await expect(page.getByTestId("import-debits")).toHaveText("£66,185.10");

  const post = page.getByRole("button", { name: "Post opening balances" });
  await expect(post).toBeDisabled(); // nothing is posted until the user ticks that they checked it
  await page.getByLabel(/I have checked the mapping and the opening entry/).check();
  await post.click();
  await expect(page.getByTestId("import-proved")).toHaveText(
    "Reconciled: the Accnomos trial balance equals the one you uploaded, to the penny.",
  );
  const recon = page.getByRole("region", { name: "Reconciliation by account" });
  await expect(recon.getByRole("row", { name: /2200 VAT control/ })).toContainText("£1,842.20 Cr");
  const saved = await runtime.files();
  expect(saved.some((f) => f.startsWith("07 Reports/") && f.endsWith("-opening-balances-reconciliation.csv"))).toBeTruthy();
  expect(saved.some((f) => f.startsWith("_System/Import/sources/"))).toBeTruthy();

  // Aged debtors are there from day one (the sample's three open invoices, 4,560.00).
  const aged = await runtime.api<{ debtors: { total_pence: number }; creditors: { total_pence: number } }>(
    "GET",
    "/reports/aged?as_of=2026-04-01",
  );
  expect(aged.debtors.total_pence).toBe(456_000);
  expect(aged.creditors.total_pence).toBe(213_050);

  await page.getByLabel(/Undo the import/).check();
  await page.getByRole("button", { name: "Undo import" }).click();
  await expect(page.getByRole("heading", { name: "Opening balances undone" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Start a new import" })).toBeVisible();
});

test("Settings › Your data links to the import", async ({ page, runtime }) => {
  await runtime.reset();
  await signIn(page);
  await page.goto("/settings#settings-data-import");
  await page.getByRole("link", { name: "Import history" }).click();
  await expect(page).toHaveURL(/\/import/);
});
