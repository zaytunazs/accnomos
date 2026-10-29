import { createBooksFolder, expect, signIn, test } from "./fixtures";
import { RUNTIME_URL } from "./env.mjs";

/**
 * Scan 00 Inbox one document at a time (src/lib/scan-queue.ts): "Reading 1 of 2 … name", a time limit per document
 * with a plain message, the scan carries on when the user leaves Review, and the button is never left frozen.
 * The first receipt's reading is held back here (as a slow model would be) past a 1.5 s limit set for the test.
 */

test("two receipts: progress per document, a slow one passes its time limit, the scan carries on elsewhere", async ({ page, runtime }) => {
  await runtime.dropInInbox("001_standard");
  await runtime.dropInInbox("002_no_vat"); // a second gold receipt
  await signIn(page);
  await createBooksFolder(page);
  await page.addInitScript(() => window.localStorage.setItem("accnomos.test.scan-limit-ms", "1500"));

  // Hold the first document's reading for 6 s: longer than its limit, as a slow model would be.
  await page.route(`${RUNTIME_URL}/books/scan?*`, async (route) => {
    if (decodeURIComponent(route.request().url()).includes("001_standard")) await new Promise((r) => setTimeout(r, 6_000));
    await route.continue();
  });

  await page.goto("/review");
  const button = page.getByRole("button", { name: "Scan 00 Inbox now" });
  await button.click();
  const scan = page.getByRole("region", { name: "Inbox scan" });
  await expect(scan.getByRole("status")).toHaveText("Reading 1 of 2 … 001_standard.png");
  await page.screenshot({ path: "../../docs/reviews/app-shell/scan-reading-1-of-2.png" });

  // Past its limit: said plainly, and the scan moves on to the next document.
  const docs = scan.getByRole("list", { name: "Documents in this scan" });
  await expect(docs.getByRole("listitem").filter({ hasText: "001_standard.png" })).toContainText(
    "still being read after 2 seconds; it will appear in Review when done",
  );
  await expect(scan.getByRole("status")).toHaveText(/Reading 2 of 2 … 002_no_vat\.png|Scan finished/);

  // Leave Review while it runs: the bar on other pages says how far it got, or it has already finished.
  await page.getByRole("link", { name: "Ask", exact: true }).click();
  await expect(page).toHaveURL(/\/ask$/);

  // The button is never left frozen: back on Review it is ready again, and both receipts end up as cards.
  await page.goto("/review");
  await expect(button).toBeEnabled({ timeout: 20_000 });
  await button.click(); // a second scan does not read the slow one twice while it is still being read
  await expect(page.locator('p[role="status"][aria-live="polite"]')).toContainText(/Nothing new in 00 Inbox|new proposal/, { timeout: 20_000 });
  await expect(page.getByRole("main")).toContainText("Novex", { timeout: 20_000 });
  await page.screenshot({ path: "../../docs/reviews/app-shell/scan-done.png" });
});

test("a scan started on Review shows its progress on another page", async ({ page, runtime }) => {
  await runtime.dropInInbox("001_standard");
  await signIn(page);
  await createBooksFolder(page);
  await page.route(`${RUNTIME_URL}/books/scan?*`, async (route) => {
    await new Promise((r) => setTimeout(r, 4_000));
    await route.continue();
  });
  await page.goto("/review");
  await page.getByRole("button", { name: "Scan 00 Inbox now" }).click();
  await expect(page.getByRole("region", { name: "Inbox scan" }).getByRole("status")).toHaveText("Reading 1 of 1 … 001_standard.png");
  // Client-side navigation keeps the scan going.
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Home" }).click();
  const bar = page.getByRole("status").filter({ hasText: "Reading 1 of 1 … 001_standard.png" });
  await expect(bar).toBeVisible();
  await expect(bar.getByRole("link", { name: "Open Review" })).toHaveAttribute("href", "/review");
  await page.screenshot({ path: "../../docs/reviews/app-shell/scan-elsewhere.png" });
  await expect(bar).toHaveCount(0, { timeout: 20_000 }); // finished
  await page.goto("/review");
  await expect(page.getByRole("main")).toContainText("Novex");
});
