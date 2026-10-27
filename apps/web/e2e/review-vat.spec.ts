import type { Page } from "@playwright/test";
import { createBooksFolder, expect, GOLD, signIn, test } from "./fixtures";

/** The amount cell of one row of the live 9-box return on /vat. */
function box(page: Page, label: string) {
  return page.getByRole("region", { name: /Your return/ }).getByRole("row").filter({ hasText: label }).getByRole("cell").nth(2);
}

test("upload a gold receipt → scan → proposal → approve → VAT boxes change", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);

  await page.goto("/vat");
  await expect(page.getByRole("region", { name: /Your return/ })).toContainText("key 26A3");
  await expect(box(page, "VAT reclaimed on purchases")).toHaveText("£0.00");
  await expect(box(page, "Total purchases excluding VAT")).toHaveText("£0");

  await page.goto("/review");
  await expect(page.getByText("No receipts waiting")).toBeVisible();
  await page.locator('input[type="file"]').setInputFiles({ name: `${GOLD}.png`, mimeType: "image/png", buffer: await runtime.goldPng() });
  await expect(page.getByText("1 file added to 00 Inbox")).toBeVisible();

  await page.getByRole("button", { name: "Scan 00 Inbox now" }).click();
  await expect(page.locator('p[role="status"][aria-live="polite"]')).toHaveText("1 new proposal");
  const card = page.getByRole("region", { name: "Novex Office Supplies Ltd · £51.90" });
  await expect(card).toBeVisible();
  await expect(card).toContainText("£43.25 · £8.65 · £51.90");

  await card.getByRole("button", { name: /^Approve Novex/ }).click();
  await expect(page.locator('p[role="status"][aria-live="polite"]')).toHaveText("Approved · posted to your books · U to undo");
  await expect(page.getByText("No receipts waiting")).toBeVisible();

  await page.goto("/vat");
  await expect(page.getByRole("region", { name: /Your return/ })).toContainText("1 approved entries");
  await expect(box(page, "VAT reclaimed on purchases")).toHaveText("£8.65");
  await expect(box(page, "Total purchases excluding VAT")).toHaveText("£43");
  expect((await runtime.files()).some((f) => f.startsWith("_System/Ledger/events/"))).toBeTruthy();
});
