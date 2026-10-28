import { createBooksFolder, expect, signIn, test } from "./fixtures";

/**
 * CIS (services/runtime/app/cis.py): a subcontractor's invoice shows the deduction on labour only, a payment received
 * net of the deduction pays it in full, a statement is kept and the year totals say where the figures go. Every
 * figure comes from the runtime; the test only types and reads.
 */
test("subcontractor: CIS invoice, paid net of the deduction, statement and year totals", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);

  // Settings on the CIS page: we work for contractors at the 20% rate
  await page.goto("/cis");
  const settings = page.getByRole("region", { name: "Your CIS registration" });
  await settings.getByLabel("We work for contractors under CIS (subcontractor)").check();
  await settings.getByLabel("Your UTR (10 digits)").fill("1234567890");
  await settings.getByRole("button", { name: "Save CIS settings" }).click();
  await expect(settings.getByRole("status")).toContainText("Saved in your OneDrive");
  await expect(page.getByRole("region", { name: "Statements from contractors" })).toBeVisible();

  // A CIS invoice: 20 h × £50 labour + £200 materials, 20% VAT = £1,440; deduction 20% of £1,000 = £200
  await page.goto("/invoices/new");
  await page.getByLabel("Name", { exact: true }).fill("Northgate Construction Ltd");
  await page.getByLabel("Email (the invoice is sent here)").fill("accounts@northgate.example");
  const cisTick = page.getByLabel(/CIS invoice: show the 20% deduction/);
  await expect(cisTick).toBeChecked(); // on by default once CIS is switched on
  await page.getByLabel("Description").first().fill("Second fix labour");
  await page.getByLabel("Qty").first().fill("20");
  await page.getByLabel("Unit price (£, ex VAT)").first().fill("50.00");
  await page.getByRole("button", { name: "+ Add a line" }).click();
  await page.getByLabel("Description").nth(1).fill("Cable and boxes");
  await page.getByLabel("Unit price (£, ex VAT)").nth(1).fill("200.00");
  await page.getByLabel("Materials (no CIS deduction) on line 2").check();
  await expect(page.getByText("Less CIS deduction 20% of labour")).toBeVisible();
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page).toHaveURL(/\/invoices$/);

  const inv = await runtime.api<{ cis: { deduction_pence: number; payable_pence: number }; total_pence: number }>(
    "GET",
    "/invoices/INV-0001",
  );
  expect(inv.total_pence).toBe(144_000);
  expect(inv.cis).toMatchObject({ deduction_pence: 20_000, payable_pence: 124_000 });
  await runtime.api("POST", "/invoices/INV-0001/send", { confirm: true });

  // Record payment: the dialog starts from £1,240 received and £200 deducted
  await page.goto("/invoices");
  const row = page.getByRole("listitem").filter({ hasText: "INV-0001 · Northgate Construction Ltd" });
  await row.getByRole("button", { name: "Record payment" }).click();
  const pay = page.getByRole("dialog", { name: "Record payment on INV-0001" });
  await expect(pay.getByLabel("Amount (£)")).toHaveValue("1240.00");
  await expect(pay.getByLabel("CIS deducted by the contractor (£)")).toHaveValue("200.00");
  await expect(pay).toContainText("with £200.00 CIS deducted (1150 CIS suffered)");
  await pay.getByRole("button", { name: "Record payment" }).click();
  await expect(page.getByRole("status")).toContainText("INV-0001 is paid");

  // The contractor's statement for the month to 5 Nov 2026, typed in; it matches what the payment recorded
  await page.goto("/cis");
  const statements = page.getByRole("region", { name: "Statements from contractors" });
  await statements.getByLabel("Contractor").fill("Northgate Construction Ltd");
  await statements.getByLabel("Tax month ending (the 5th)").fill("2026-11-05");
  await statements.getByLabel("Gross paid, ex VAT (£)").fill("1200.00");
  await statements.getByLabel("Materials (£)").fill("200.00");
  await expect(statements).toContainText("At your 20% rate the deduction would be £200.00.");
  await statements.getByLabel("Amount deducted (£)").fill("200.00");
  await statements.getByRole("button", { name: "Add statement" }).click();
  const table = page.getByRole("region", { name: "Statements from contractors" }).getByRole("table");
  await expect(table).toContainText("Deduction is 20% of £1,000.00");
  await expect(table).not.toContainText("not recorded on a payment");

  const year = page.getByRole("region", { name: "Year totals for your tax return" });
  await expect(year).toContainText("box 38 is £200.00");
  await expect(year).toContainText("box 81 is £200.00");
  expect(await runtime.files()).toContain("_System/CIS/statements.json");
});

test("reverse charge: invoice charges no VAT and carries HMRC's wording", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/invoices/new");
  await page.getByLabel("Name", { exact: true }).fill("Northgate Construction Ltd");
  await page.getByLabel("Their VAT number (optional)").fill("GB 987 6543 21");
  await page.getByLabel(/VAT reverse charge \(building and construction services/).check();
  await page.getByLabel("Description").first().fill("Rewire, labour and materials");
  await page.getByLabel("Unit price (£, ex VAT)").first().fill("1000.00");
  await expect(page.getByText("VAT the customer accounts for (reverse charge)")).toBeVisible();
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page).toHaveURL(/\/invoices$/);
  const inv = await runtime.api<{ vat_pence: number; total_pence: number; reverse_charge_vat_pence: number }>("GET", "/invoices/INV-0001");
  expect(inv).toMatchObject({ vat_pence: 0, total_pence: 100_000, reverse_charge_vat_pence: 20_000 });

  await page.goto("/cis");
  const rc = page.getByRole("region", { name: "VAT domestic reverse charge" });
  await expect(rc).toContainText("Supplier: the net in box 6");
  await expect(rc).toContainText("VAT Act 1994 Section 55A applies");
});

test("contractor: subcontractor, payment under deduction, CIS300 saved (never submitted)", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.api("PUT", "/cis/settings", {
    contractor: true, contractor_utr: "1234567890", accounts_office_ref: "123PA00045678",
  });
  await page.goto("/cis");
  const c = page.getByRole("region", { name: "Paying subcontractors" });
  await c.getByLabel("Name (as registered with HMRC)").fill("Dale Electrical");
  await c.getByLabel("UTR").fill("1111122222");
  await c.getByRole("button", { name: "Add subcontractor" }).click();
  await expect(c.getByRole("status").filter({ hasText: "Subcontractor added." })).toBeVisible();

  // £1,000 invoice with £200 materials, reverse charge: 20% of £800 = £160 deducted, £840 paid
  await c.getByLabel("Subcontractor").selectOption({ label: "Dale Electrical" });
  await c.getByLabel("Paid on").fill("2026-10-20");
  await c.getByLabel("Their invoice, ex VAT (£)").fill("1000.00");
  await c.getByLabel("Materials they paid for (£)").fill("200.00");
  await c.getByRole("button", { name: "Record payment" }).click();
  await expect(c.getByRole("status").filter({ hasText: "£160.00 deducted at 20%, £840.00 paid to Dale Electrical." })).toBeVisible();

  await c.getByLabel("Tax month ending").fill("2026-11-05");
  const lines = c.getByRole("region", { name: "Monthly return lines" });
  await expect(lines).toContainText("1111122222");
  await expect(lines).toContainText("£160.00");
  await expect(c).toContainText("Accnomos does not submit CIS returns");
  await c.getByRole("button", { name: "Save CIS300 to OneDrive" }).click();
  await expect(c.getByText(/Saved 07 Reports\/CIS\/CIS300 2026-11-05\.csv/)).toBeVisible();
  expect(await runtime.files()).toContain("07 Reports/CIS/CIS300 2026-11-05.csv");
});
