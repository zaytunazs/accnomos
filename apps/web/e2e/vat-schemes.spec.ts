import type { Page } from "@playwright/test";
import { createBooksFolder, expect, settingsTab, signIn, test, type Runtime } from "./fixtures";

/** VAT schemes: chosen in Settings › Business › VAT scheme, saved in the books, used by the VAT page. */

function box(page: Page, label: string) {
  return page.getByRole("region", { name: /Your return/ }).getByRole("row").filter({ hasText: label }).getByRole("cell").nth(2);
}

async function oneInvoice(runtime: Runtime) {
  await runtime.api("POST", "/invoices", {
    customer: { name: "Harbour Cafe Ltd", email: "accounts@harbourcafe.example" },
    lines: [{ description: "Kitchen first fix", quantity: "6", unit: "hours", unit_price_pence: 4500, vat_code: "S" }],
  });
  await runtime.api("POST", "/invoices/INV-0001/send", { confirm: true }); // 27 Oct 2026: £270 + £54 VAT = £324.00
}

test("flat rate chosen in Settings: the VAT page works box 1 out as a % of turnover", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await oneInvoice(runtime);

  await page.goto("/vat");
  await expect(box(page, "VAT due on sales")).toHaveText("£54.00"); // standard accounting

  await page.goto("/settings");
  const panel = await settingsTab(page, "Business");
  const card = panel.getByRole("region", { name: "VAT scheme" });
  await expect(card.getByTestId("vat-scheme-current")).toContainText("In use today: Standard accounting");

  // Cash accounting from the middle of a quarter breaks Notice 731 §3.1: the runtime says so and nothing is saved.
  await card.getByRole("radio", { name: /Cash accounting/ }).click();
  await card.getByLabel("From", { exact: true }).fill("2026-10-15");
  await card.getByRole("button", { name: "Save VAT scheme" }).click();
  await expect(card.getByRole("alert")).toContainText("Notice 731");

  await card.getByRole("radio", { name: /Flat rate/ }).click();
  await card.getByLabel("From", { exact: true }).fill("2026-10-01");
  await card.getByLabel("Type of business").selectOption("Photography");
  await card.getByLabel("Limited cost business (16.5%)").selectOption("no");
  await card.getByLabel(/Date you registered for VAT/).fill("2020-04-01");
  await card.getByRole("button", { name: "Save VAT scheme" }).click();
  await expect(card.getByRole("status")).toHaveText("Saved in your books.");
  await expect(card.getByTestId("vat-scheme-current")).toContainText("Flat Rate Scheme: Photography, basic turnover at 11%");
  expect(await runtime.files()).toContain("_System/vat/schemes.json");

  await page.goto("/vat");
  const region = page.getByRole("region", { name: /Your return/ });
  await expect(box(page, "VAT due on sales")).toHaveText("£35.64"); // 11% of £324.00
  await expect(box(page, "Total sales excluding VAT")).toHaveText("£324"); // box 6: turnover including VAT
  await expect(region.getByTestId("flat-rate-calc")).toHaveText("11% of £324.00 turnover including VAT = £35.64");
  await expect(region).toContainText("Not a limited cost business (your setting).");
});

test("cash accounting: VAT on what has been paid, not on the invoice", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await oneInvoice(runtime);
  await runtime.api("PUT", "/books/vat/schemes", { schemes: [{ from: "2026-10-01", scheme: "cash" }] });
  await runtime.api("POST", "/invoices/INV-0001/payments", { amount_pence: 16200, paid_on: "2026-10-27" }); // half

  await page.goto("/vat");
  const region = page.getByRole("region", { name: /Your return/ });
  await expect(box(page, "VAT due on sales")).toHaveText("£27.00"); // half of £54.00 (Notice 731 §8.1)
  await expect(box(page, "Total sales excluding VAT")).toHaveText("£135");
  await expect(region).toContainText("Cash Accounting Scheme.");
  await expect(region).toContainText("VAT on 1 payment received or made in this period, not on invoice dates.");
});
