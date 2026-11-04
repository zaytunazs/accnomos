import type { Page } from "@playwright/test";
import { createBooksFolder, expect, signIn, test } from "./fixtures";

/**
 * Books kept outside the UK (src/lib/region.ts, services/runtime/app/region.py): onboarding asks the country first,
 * then the tax and its rate and the currency; the menu then has none of HMRC's pages (VAT returns, payroll,
 * MTD Income Tax, CIS), Reports has the Tax summary with its CSV, and Bank offers statement upload only (bank
 * connections reach UK banks only).
 */

const mainNav = (page: Page) => page.getByRole("navigation", { name: "Main" });

async function onboardInAustralia(page: Page): Promise<void> {
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/connect/business");
  // Country first, the UK by default
  const country = page.getByLabel("Country", { exact: true });
  await expect(country).toHaveValue("GB");
  await expect(page.getByText("VAT return period")).toBeVisible(); // UK: HMRC's questions
  await page.getByLabel("Search countries").fill("Australia");
  await expect(country).toHaveValue("AU");
  await expect(page.getByText("VAT return period")).toBeHidden();
  await expect(page.getByRole("checkbox", { name: /not VAT-registered/ })).toHaveCount(0);
  // "Do you charge VAT, GST or sales tax?" -> GST, "What percentage?" -> 10, currency prefilled
  await page.getByRole("radio", { name: "GST" }).click();
  await expect(page.getByRole("radio", { name: "GST" })).toHaveAttribute("aria-checked", "true");
  await page.getByLabel("What percentage?").fill("10");
  await expect(page.getByLabel("Currency")).toHaveValue("AUD");
  await page.getByLabel("Business name").fill("Kim Design Pty Ltd");
  await page.getByRole("button", { name: "Save and continue" }).click();
  await expect(page).toHaveURL(/\/connect\/ready/);
}

test("a business outside the UK: GST at 10%, no HMRC pages, a Tax summary CSV, statement upload only", async ({ page }) => {
  test.slow();
  await onboardInAustralia(page);

  await page.goto("/");
  const nav = mainNav(page);
  await expect(nav.getByRole("link", { name: "Home" })).toBeVisible();
  // No Tax group at all (VAT returns, MTD Income Tax, CIS and Tax settings are HMRC's)
  await expect(nav.getByRole("button", { name: /^Tax/ })).toHaveCount(0);
  await nav.getByRole("button", { name: /^Reporting/ }).click();
  await expect(nav.getByRole("link", { name: "All reports" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "VAT returns" })).toHaveCount(0);
  await nav.getByRole("button", { name: /^Reporting/ }).click();
  await nav.getByRole("button", { name: /^More/ }).click();
  await expect(nav.getByRole("link", { name: "Goals & progress" })).toBeVisible();
  for (const name of ["Employees", "Pay runs", "RTI files", "Pensions"]) {
    await expect(nav.getByRole("link", { name })).toHaveCount(0);
  }
  await nav.getByRole("button", { name: /^More/ }).click();
  await expect(page.getByRole("navigation").getByText(/HMRC/)).toHaveCount(0);

  // Reports: the Tax summary, its CSV, and no VAT by period
  await page.goto("/reports");
  await expect(page.getByRole("heading", { name: "Tax summary" })).toBeVisible();
  await expect(page.getByText(/GST summary/)).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "GST on sales" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "VAT by period" })).toHaveCount(0);
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download tax summary CSV" }).click();
  expect((await download).suggestedFilename()).toMatch(/^tax-summary-.*\.csv$/);

  // Bank: no bank connection (TrueLayer is UK banks only), statement upload as CSV or PDF
  await page.goto("/bank");
  await expect(page.getByRole("button", { name: /Drop a bank statement \(CSV or PDF\)/ })).toBeVisible();
  await expect(page.getByRole("region", { name: "Bank feed" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Connect a bank/ })).toHaveCount(0);

  // Settings: no HMRC set-up wizard (its questions are Companies House and HMRC)
  await page.goto("/settings");
  await expect(page.getByText("Open the set-up wizard")).toHaveCount(0);
});

test("UK books keep HMRC and the bank connection as before", async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/");
  await expect(mainNav(page).getByRole("button", { name: /^Tax/ })).toBeVisible();
  await page.goto("/bank");
  await expect(page.getByRole("button", { name: /Drop a bank statement \(CSV or PDF\)/ })).toBeVisible();
  await expect(page.getByRole("region", { name: "Bank feed" })).toBeVisible();
});
