import { join } from "node:path";
import { createBooksFolder, expect, signIn, test } from "./fixtures";

// SAMPLE — FICTIONAL COMPANY: the gold Barclays statement (six lines).
const BARCLAYS = join(__dirname, "../../../evals/gold/bank/barclays.csv");

/**
 * Offline uploads: a statement dropped while the reader is down waits in
 * memory (the strip says the reader isn't answering) and resumes on its own
 * at reconnect — here an `online` event after the routes recover, as a real
 * browser fires it. No service worker involved.
 */
test("bank statement queued while down resumes on reconnect", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await page.route("**/books/bank/import", (route) => route.abort());
  await page.route("**/health", (route) => route.abort());

  await page.goto("/bank");
  const strip = page.getByRole("alert").filter({ hasText: /isn't answering/ });
  await expect(strip).toBeVisible();

  await page.locator('input[type="file"]').setInputFiles(BARCLAYS);
  await expect(page.getByText(/queued, and will resume on its own/)).toBeVisible();
  await expect(page.getByText(/1 statement waiting/)).toBeVisible();

  await page.unroute("**/books/bank/import");
  await page.unroute("**/health");
  await page.evaluate(() => window.dispatchEvent(new Event("online")));
  await expect(page.getByRole("status").filter({ hasText: "barclays.csv" })).toContainText("6 new lines");
  expect((await runtime.files()).some((f) => f.startsWith("04 Bank statements/") && f.endsWith(".csv"))).toBeTruthy();
  await expect(strip).toHaveCount(0);
});
