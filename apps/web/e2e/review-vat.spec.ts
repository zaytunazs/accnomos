import type { Page } from "@playwright/test";
import { createBooksFolder, expect, GOLD, pickVatPeriod, signIn, test, confirmScan } from "./fixtures";

/** The amount cell of one row of the live 9-box return on /vat. */
function box(page: Page, label: string) {
  return page.getByRole("region", { name: /Your return/ }).getByRole("row").filter({ hasText: label }).getByRole("cell").nth(2);
}

test("upload a gold receipt → scan → proposal → approve → VAT boxes change", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);

  await page.goto("/vat");
  await expect(page.getByRole("region", { name: /Your return/ })).toContainText("Oct–Dec 2026 (current period)");
  await pickVatPeriod(page, "Jul–Sep 2026"); // the gold receipt is dated 14 Aug 2026
  await expect(page).toHaveURL(/\/vat\?period=2026-Q3$/); // the period can be linked
  await expect(page.getByRole("region", { name: /Your return/ })).toContainText("Your return · Jul–Sep 2026");
  await expect(box(page, "VAT reclaimed on purchases")).toHaveText("£0.00");
  await expect(box(page, "Total purchases excluding VAT")).toHaveText("£0");

  await page.goto("/review");
  await expect(page.getByText("No receipts waiting")).toBeVisible();
  // .first(): the empty state has its own upload button too.
  await page.locator('input[type="file"]').first().setInputFiles({ name: `${GOLD}.png`, mimeType: "image/png", buffer: await runtime.goldPng() });
  await expect(page.getByText("1 file added to 00 Inbox")).toBeVisible();

  await confirmScan(page);
  await expect(page.locator('p[role="status"][aria-live="polite"]')).toHaveText("1 new proposal"); // caches warmed at startup
  const card = page.getByRole("region", { name: "Novex Office Supplies Ltd · £51.90" });
  await expect(card).toBeVisible();
  await expect(card).toContainText("£43.25 · £8.65 · £51.90");

  await card.getByRole("button", { name: /^Approve Novex/ }).click();
  await expect(page.locator('p[role="status"][aria-live="polite"]')).toHaveText("Approved · posted to your books · U to undo");
  await expect(page.getByText("No receipts waiting")).toBeVisible();

  await page.goto("/vat"); // the pick is remembered
  await expect(page.getByRole("region", { name: /Your return/ })).toContainText("Your return · Jul–Sep 2026");
  await expect(page.getByRole("region", { name: /Your return/ })).toContainText("1 approved entries");
  await expect(box(page, "VAT reclaimed on purchases")).toHaveText("£8.65");
  await expect(box(page, "Total purchases excluding VAT")).toHaveText("£43");
  expect((await runtime.files()).some((f) => f.startsWith("_System/Ledger/events/"))).toBeTruthy();

  // Box 5 reads as reclaim with its due date and days left; every box explains itself.
  const region = page.getByRole("region", { name: /Your return/ });
  await expect(region).toContainText("£8.65 to reclaim · due 7 Nov · 11 days left");
  await expect(region.getByRole("button", { name: /Explain: Box 5/ })).toBeVisible();

  // Arrow keys move through the periods and the URL follows.
  await page.getByRole("radio", { name: "Jul–Sep 2026" }).focus();
  await page.keyboard.press("ArrowUp");
  await expect(region).toContainText("Oct–Dec 2026 (current period)");
  await expect(page).toHaveURL(/\/vat$/);
});

