import { statSync } from "node:fs";
import path from "node:path";
import type { Page } from "@playwright/test";
import { createBooksFolder, DEMO_DAY, expect, settingsTab, signIn, test } from "./fixtures";

/**
 * Submission screenshots: every key page with the sample books, desktop (1280 × 800) and phone (390 × 844).
 * Run: `SHOTS=1 pnpm exec playwright test e2e/shots.spec.ts --project=desktop` (then `--project=phone`;
 * both commands capture both sizes, idempotently). Skipped from the normal e2e run unless SHOTS=1, so
 * `pnpm run e2e` never writes into docs/.
 *
 * Setup signs in through the test-mode fixtures and seeds the demo books (the runtime's `demo` reset) to
 * prove the demo tenant works. Capture itself is signed out (a fresh context per test, no sign-in): the
 * single "SAMPLE — FICTIONAL COMPANY" label lives in the signed-out banner, and signing in hides it
 * (e2e/contacts.spec.ts, e2e/reports.spec.ts and e2e/review.spec.ts all assert zero occurrences when
 * signed in). Every shot below therefore shows the labelled fictional sample books — no personal data —
 * in the light theme. Each shot asserts the label first and fails when the page shows none.
 *
 * Two states have no signed-out sample and are shot as their closest labelled state (said so in
 * docs/submission/shots/README.md): the Possible-duplicates card and part-paid invoices only exist with
 * live books, and Bank's Reconcile/Rules tabs need a signed-in statement import.
 */

test.skip(process.env.SHOTS !== "1", "submission shots run only with SHOTS=1");

const OUT = path.resolve(__dirname, "../../docs/submission/shots");
const LIMIT = 400 * 1024;
const LABEL = "SAMPLE — FICTIONAL COMPANY · demo data only";

const VIEWPORTS = [
  { name: "desktop", suffix: "", use: { viewport: { width: 1280, height: 800 } } },
  { name: "phone", suffix: "-phone", use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
] as const;

test("seed the demo books", async ({ page, runtime }) => {
  await runtime.reset("demo");
  await signIn(page, DEMO_DAY);
  await createBooksFolder(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Good morning, Sam" })).toBeVisible();
});

/** Assert the SAMPLE label, screenshot the viewport, and keep the file under 400 kB. */
async function shoot(page: Page, slug: string, suffix: string): Promise<void> {
  await expect(page.getByText(LABEL).first(), `${slug}: no SAMPLE label on the page`).toBeVisible();
  const file = path.join(OUT, `${slug}${suffix}.png`);
  await page.screenshot({ path: file, scale: "css", animations: "disabled", caret: "hide" });
  expect(statSync(file).size, `${path.basename(file)} is over 400 kB`).toBeLessThan(LIMIT);
}

for (const vp of VIEWPORTS) {
  test.describe(`shots · ${vp.name}`, () => {
    test.use({ ...vp.use, colorScheme: "light" });

    test("home", async ({ page }) => {
      await page.goto("/");
      await expect(page.getByRole("link", { name: "See the demo books" })).toBeVisible();
      await shoot(page, "home", vp.suffix);
    });

    test("review, a proposal open", async ({ page }) => {
      await page.goto("/review");
      await expect(page.getByText("4 waiting for you")).toBeVisible();
      await page.getByRole("button", { name: /Open the document for Novex Office Supplies Ltd/ }).click();
      const viewer = page.getByRole("dialog", { name: /^Document: Novex Office Supplies Ltd/ });
      await expect(viewer.getByRole("img", { name: /^Original document/ })).toBeVisible();
      await shoot(page, "review-proposal", vp.suffix);
    });

    test("vat return", async ({ page }) => {
      await page.goto("/vat");
      await expect(page.getByRole("heading", { name: "VAT return · Q3 2026" })).toBeVisible();
      await expect(page.getByText("£2,140.00").first()).toBeVisible();
      await shoot(page, "vat", vp.suffix);
    });

    test("reports, profit and loss", async ({ page }) => {
      await page.goto("/reports");
      await expect(page.getByRole("heading", { name: /Profit and loss · Jul–Sep 2026/ })).toBeVisible();
      await shoot(page, "reports-pl", vp.suffix);
    });

    test("reports, aged debtors and creditors", async ({ page }) => {
      await page.goto("/reports");
      const debtors = page.getByRole("region", { name: "Debtors", exact: true });
      await expect(debtors).toContainText("Acme Kitchens Ltd");
      await debtors.scrollIntoViewIfNeeded();
      await shoot(page, "reports-aged", vp.suffix);
    });

    test("reports, VAT by period", async ({ page }) => {
      await page.goto("/reports");
      const heading = page.getByRole("heading", { name: "VAT by period" });
      await expect(heading).toBeVisible();
      await heading.scrollIntoViewIfNeeded();
      await shoot(page, "reports-vat", vp.suffix);
    });

    test("reports, last 12 months", async ({ page }) => {
      await page.goto("/reports");
      const chart = page.getByRole("img", { name: /Sales, purchases and net per month/ });
      await expect(chart).toBeVisible();
      await chart.scrollIntoViewIfNeeded();
      await shoot(page, "reports-trend", vp.suffix);
    });

    test("contacts, a statement", async ({ page }) => {
      await page.goto("/contacts");
      await page.getByRole("button", { name: "Acme Kitchens Ltd" }).click();
      const panel = page.getByRole("complementary", { name: "Acme Kitchens Ltd: statement" });
      await expect(panel).toContainText("Customer");
      await expect(panel.getByRole("heading", { name: "Statement" })).toBeVisible();
      await shoot(page, "contacts-statement", vp.suffix);
    });

    test("contacts, duplicates", async ({ page }) => {
      await page.goto("/contacts");
      await expect(page.getByRole("button", { name: "Acme Kitchens Ltd" })).toBeVisible();
      await expect(page.getByText("Showing 4 of 4 contacts.")).toBeVisible();
      await shoot(page, "contacts-duplicates", vp.suffix);
    });

    test("invoices", async ({ page }) => {
      await page.goto("/invoices");
      await expect(page.getByText("The list below is a fictional sample.")).toBeVisible();
      await expect(page.getByText("INV-0006 · Acme Kitchens Ltd")).toBeVisible();
      await shoot(page, "invoices", vp.suffix);
    });

    test("bank", async ({ page }) => {
      await page.goto("/bank");
      await expect(page.getByText("to import bank statements.")).toBeVisible();
      await shoot(page, "bank", vp.suffix);
    });

    test("audit", async ({ page }) => {
      await page.goto("/audit");
      await expect(page.getByText(/Sample day at a fictional company/)).toBeVisible();
      await expect(page.getByRole("heading", { name: /^Wednesday,? 14 October 2026$/ })).toBeVisible();
      await shoot(page, "audit", vp.suffix);
    });

    test("ask, an answer with citations", async ({ page }) => {
      await page.goto("/ask");
      await expect(page.getByText("Why is my VAT higher than last quarter?")).toBeVisible();
      const answer = page.getByRole("article");
      await expect(answer).toContainText("Your Q3 bill is £2,140.00");
      await expect(answer.getByRole("list", { name: "Files used" })).toContainText("Books.xlsx");
      await answer.scrollIntoViewIfNeeded();
      await shoot(page, "ask-answer", vp.suffix);
    });

    test("settings, your data", async ({ page }) => {
      await page.goto("/settings");
      const panel = await settingsTab(page, "Your data");
      await expect(panel.getByRole("heading", { name: "Export your data", exact: true })).toBeVisible();
      await shoot(page, "settings-your-data", vp.suffix);
    });
  });
}
