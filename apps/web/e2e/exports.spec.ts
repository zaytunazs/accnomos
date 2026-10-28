import { createBooksFolder, expect, signIn, test } from "./fixtures";

test("signed out: the labelled sample, grouped, with downloads switched off", async ({ page }) => {
  await page.goto("/reports/exports");
  await expect(page.getByRole("heading", { name: "Reports & exports", level: 1 })).toBeVisible();
  for (const group of ["Financial statements", "Payables and receivables", "Reconciliations", "Taxes and balances", "Export to another package"]) {
    await expect(page.getByRole("heading", { name: group, level: 2 })).toBeVisible();
  }
  await page.getByRole("button", { name: /^Trial balance Debit and credit/ }).click();
  const table = page.getByRole("table", { name: "Trial balance: Trial balance" });
  await expect(table.getByRole("row", { name: /Total/ })).toContainText("£58,545.50");
  await expect(page.locator("#report-preview").getByText("SAMPLE — FICTIONAL COMPANY")).toBeVisible();
  await expect(page.getByRole("button", { name: "Download CSV" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Save to 07 Reports" })).toBeDisabled();
});

test("signed out at 360 px: no sideways scroll, the preview's tables scroll on their own", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/reports/exports");
  await page.getByRole("button", { name: /^Trial balance Debit and credit/ }).click();
  await expect(page.getByRole("table", { name: "Trial balance: Trial balance" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test("signed in: preview, download and save a report, the HMRC return, a Xero file and a star; nothing posted", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold(); // Novex Office Supplies Ltd, 14 Aug 2026: net £43.25, VAT £8.65, paid by card
  const events = (await runtime.files()).filter((f) => f.startsWith("_System/Ledger/events/"));

  await page.goto("/reports/exports");
  await expect(page.getByText("SAMPLE — FICTIONAL COMPANY")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Taxes and balances", level: 2 })).toBeVisible();
  await page.getByRole("button", { name: /^Trial balance Debit and credit/ }).click();
  await expect(page.getByRole("heading", { name: "Trial balance", level: 2 })).toBeFocused();
  await page.getByLabel("From").fill("2026-07-01");
  await page.getByLabel("To", { exact: true }).fill("2026-09-30");
  const tb = page.getByRole("table", { name: "Trial balance: Trial balance" });
  await expect(tb.getByRole("row", { name: /Office supplies/ })).toContainText("£43.25");
  await expect(tb.getByRole("row", { name: /Total/ })).toContainText("£51.90");

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download CSV" }).click();
  expect((await download).suggestedFilename()).toBe("trial-balance-2026-07-01-to-2026-09-30.csv");

  await page.getByRole("button", { name: "Save to 07 Reports" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saved to" })).toContainText(
    "Saved to 07 Reports/trial-balance-2026-07-01-to-2026-09-30.csv in your OneDrive.",
  );
  expect(await runtime.files()).toContain("07 Reports/trial-balance-2026-07-01-to-2026-09-30.csv");

  await page.getByRole("button", { name: /^UK VAT return/ }).click();
  const vat = page.getByRole("table", { name: "UK VAT return: VAT return" });
  await expect(vat.getByRole("row", { name: /Box 4/ })).toContainText(
    "VAT reclaimed in the period on purchases and other inputs (including acquisitions from the EU)",
  );
  await expect(vat.getByRole("row", { name: /Box 4/ })).toContainText("£8.65");
  await expect(vat.getByRole("row", { name: /Box 7/ })).toContainText("£43");

  const star = page.getByRole("button", { name: "Star UK VAT return" }).first();
  await star.click();
  await expect(page.getByRole("heading", { name: "Starred", level: 2 })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Starred", level: 2 })).toBeVisible();

  await page.getByRole("button", { name: /^Xero: manual journals/ }).click();
  await expect(page.getByRole("columnheader", { name: "*Narration" })).toBeVisible();
  await expect(page.getByLabel("What to include")).toHaveValue("entries");
  await expect(page.getByLabel("Xero code for 7500 Office supplies")).toHaveValue("461");

  expect((await runtime.files()).filter((f) => f.startsWith("_System/Ledger/events/"))).toEqual(events);
});
