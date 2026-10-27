import { join } from "node:path";
import type { Page } from "@playwright/test";
import { createBooksFolder, expect, signIn, test } from "./fixtures";

// Throwaway probe (deleted after the run): arrange each live state the shots need and count visible
// occurrences of the exact SAMPLE label in the DOM.
const BARCLAYS = join(__dirname, "../../../evals/gold/bank/barclays.csv");

async function count(pageLabel: string, page: Page) {
  const n = await page.evaluate(() => document.body.innerText.split("SAMPLE — FICTIONAL COMPANY").length - 1);
  console.log(`label-count ${pageLabel}: ${n}`);
}

test("probe: label on contacts statement and duplicates", async ({ page, runtime }) => {
  await runtime.reset("demo");
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold();
  await runtime.postGold("002_mixed");
  await runtime.api("POST", "/contacts/refresh");
  const before: { contacts: { id: string }[] } = await runtime.api("GET", "/contacts");
  for (const c of before.contacts) {
    await runtime.api("PUT", `/contacts/${c.id}`, { phone: "0117 496 0123", vrn: null });
  }
  await runtime.api("POST", "/invoices", {
    customer: { name: "Harbour Cafe Ltd", email: "accounts@harbourcafe.example" },
    lines: [
      { description: "Kitchen first fix", quantity: "6", unit: "hours", unit_price_pence: 4500, vat_code: "S" },
      { description: "Fixings", quantity: "4", unit: "boxes", unit_price_pence: 1000, vat_code: "S" },
    ],
  });
  await runtime.api("POST", "/invoices/INV-0001/send", { confirm: true });

  await page.goto("/contacts");
  await page.getByRole("button", { name: "Novex Office Supplies Ltd" }).click();
  const panel = page.getByRole("complementary", { name: "Novex Office Supplies Ltd: statement" });
  await expect(panel.getByRole("row").filter({ hasText: "14 Aug 2026" })).toContainText("£51.90");
  await count("contacts-statement-live", page);
  await expect(page.getByLabel("Possible duplicates").getByRole("heading", { name: "Possible duplicates (1)" })).toBeVisible();
  await count("contacts-duplicates-live", page);
});

test("probe: label on part-paid invoice (canonical conditions)", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.api("POST", "/invoices", {
    customer: { name: "Harbour Cafe Ltd", email: "accounts@harbourcafe.example" },
    lines: [
      { description: "Kitchen first fix", quantity: "6", unit: "hours", unit_price_pence: 4500, vat_code: "S" },
      { description: "Fixings", quantity: "4", unit: "boxes", unit_price_pence: 1000, vat_code: "S" },
    ],
  });
  await runtime.api("POST", "/invoices/INV-0001/send", { confirm: true });

  await page.goto("/invoices");
  const row = page.getByRole("listitem").filter({ hasText: "INV-0001 · Harbour Cafe Ltd" });
  await expect(row).toContainText("£372.00");
  await row.getByRole("button", { name: "Record payment" }).click();
  const pay = page.getByRole("dialog", { name: "Record payment on INV-0001" });
  await expect(pay).toContainText("balance £372.00");
  await pay.getByLabel("Amount (£)").fill("100.00");
  await expect(pay).toContainText("£272.00 stays owed.");
  await pay.getByRole("button", { name: "Record payment" }).click();
  await expect(page.getByRole("status")).toContainText("Payment recorded on INV-0001: £272.00 still owed.");
  await expect(row).toContainText("Part paid");
  await expect(row).toContainText("balance £272.00");
  await count("invoices-part-paid-live", page);
});

test("probe: label on bank reconcile and rules", async ({ page, runtime }) => {
  await runtime.reset("bank");
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/bank");
  await page.locator('input[type="file"]').setInputFiles(BARCLAYS);
  await expect(page.getByRole("status").filter({ hasText: "barclays.csv" })).toContainText("6 new lines");

  const panel = page.getByRole("tabpanel");
  await page.getByRole("tab", { name: "Rules" }).click();
  await panel.getByRole("button", { name: "Add a rule" }).click();
  await panel.getByLabel("Rule name").fill("Fees");
  await panel.getByLabel("Match text").fill("BUSINESS ACCOUNT FEE");
  await panel.getByLabel("Account").selectOption("7900 Bank charges");
  await panel.getByRole("button", { name: "Save rule" }).click();
  await expect(panel.getByText("When the description contains BUSINESS ACCOUNT FEE")).toBeVisible();
  await count("bank-rules-live", page);

  await page.getByRole("tab", { name: "Reconcile" }).click();
  const fee = panel.getByRole("listitem").filter({ hasText: "BUSINESS ACCOUNT FEE" });
  await expect(fee.getByText("Bank rule")).toBeVisible();
  await count("bank-reconcile-live", page);
});
