import { mkdirSync } from "node:fs";
import path from "node:path";
import type { Page } from "@playwright/test";
import { confirmScan, createBooksFolder, DEMO_DAY, expect, GOLD, signIn, test } from "./fixtures";

/**
 * Presentation-review screenshots (docs/reviews/ui-polish-4nov/REVIEW.md): the key pages at 320–1440 px, signed in
 * with seeded books and on the /try demo, with long names, large values, empty, loading and error states, an open
 * dialog and keyboard focus. Not part of the suite: runs only with UI_POLISH_SHOTS=1 and writes into UI_POLISH_OUT
 * (default /tmp/ui-polish-shots/<tag>), never into the repo.
 */
test.skip(process.env.UI_POLISH_SHOTS !== "1", "ui-polish shots run only with UI_POLISH_SHOTS=1");

const TAG = process.env.UI_POLISH_TAG ?? "before";
const OUT = process.env.UI_POLISH_OUT ?? `/tmp/ui-polish-shots/${TAG}`;
mkdirSync(OUT, { recursive: true });

const WIDTHS = (process.env.UI_POLISH_WIDTHS ?? "320,390,768,900,1024,1279,1280,1440").split(",").map(Number);
const HEIGHT: Record<number, number> = { 320: 568, 390: 844, 768: 1024, 900: 900, 1024: 768, 1279: 800, 1280: 800, 1440: 900 };

async function shootAll(page: Page, slug: string, opts: { full?: boolean; settle?: () => Promise<void> } = {}): Promise<void> {
  for (const w of WIDTHS) {
    await page.setViewportSize({ width: w, height: HEIGHT[w] ?? 800 });
    await page.waitForTimeout(250);
    if (opts.settle) await opts.settle();
    await page.screenshot({
      path: path.join(OUT, `${slug}-${w}.png`),
      fullPage: opts.full ?? true,
      scale: "css",
      animations: "disabled",
      caret: "hide",
    });
  }
}

const LONG_GOAL = "Keep the Harbour Lane refit materials under a very long limit name that wraps";

async function seedGoals(runtime: { api: <T>(m: "POST", p: string, d?: unknown) => Promise<T> }) {
  await runtime.api("POST", "/books/goals", {
    name: "New van deposit", kind: "save", start: "2026-06-01", end: "2027-03-31", target_pence: 1250000, saved_pence: 487500,
  });
  await runtime.api("POST", "/books/goals", {
    name: LONG_GOAL, kind: "spend_cap", start: "2026-10-01", end: "2026-10-31", target_pence: 40000, focus: "Materials",
  });
  await runtime.api("POST", "/books/goals", {
    name: "Sales this quarter", kind: "earn", start: "2026-10-01", end: "2026-12-31", target_pence: 9876543200,
  });
}

async function seedInvoices(runtime: { api: <T>(m: "POST", p: string, d?: unknown) => Promise<T> }) {
  const line = (d: string, pence: number) => ({ description: d, quantity: "1", unit: "each", unit_price_pence: pence, vat_code: "S" });
  // Draft
  await runtime.api("POST", "/invoices", { customer: { name: "Harbour Cafe Ltd", email: "accounts@harbourcafe.example" }, lines: [line("Kitchen first fix", 45000)] });
  // Sent, awaiting payment
  await runtime.api("POST", "/invoices", { customer: { name: "The Old Vicarage Bed and Breakfast (Lymington) Limited", email: "a@b.example" }, lines: [line("Oak staircase, balustrade and landing, supply and fit", 98765432)] });
  await runtime.api("POST", "/invoices/INV-0002/send", { confirm: true });
  // Overdue
  await runtime.api("POST", "/invoices", { customer: { name: "Acme Kitchens Ltd", email: "ap@acme.example" }, lines: [line("Worktops", 82000)], issue_date: "2026-08-01", due_date: "2026-08-31" });
  await runtime.api("POST", "/invoices/INV-0003/send", { confirm: true });
  // Paid
  await runtime.api("POST", "/invoices", { customer: { name: "Jo Bloggs", email: "jo@bloggs.example" }, lines: [line("Shelving", 12000)] });
  await runtime.api("POST", "/invoices/INV-0004/send", { confirm: true });
  await runtime.api("POST", "/invoices/INV-0004/mark-paid", { paid_on: "2026-10-27" });
}

test.describe("ui-polish shots", () => {
  test.setTimeout(120_000);
  test.beforeEach(({}, info) => test.skip(info.project.name !== "desktop", "viewports are set per test"));

  test("home /try (demo)", async ({ page }) => {
    await page.goto("/try");
    await expect(page.getByRole("region", { name: /^Your summary/ })).toContainText("£");
    await page.waitForLoadState("networkidle");
    await shootAll(page, "home-try");
  });

  test("home signed in, books with figures, goals and invoices", async ({ page, runtime }) => {
    await runtime.reset("bank");
    await signIn(page);
    await createBooksFolder(page);
    await runtime.postGold();
    await seedGoals(runtime);
    await seedInvoices(runtime);
    await page.goto("/");
    await expect(page.getByRole("region", { name: "Business snapshot" })).toBeVisible();
    await expect(page.locator("[data-home-goals]").getByRole("article")).toHaveCount(3);
    await page.waitForLoadState("networkidle");
    await shootAll(page, "home-signed");
  });

  test("home signed in, empty books (empty states)", async ({ page }) => {
    await signIn(page);
    await createBooksFolder(page);
    await page.goto("/");
    await expect(page.getByRole("region", { name: /^Your summary/ })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await shootAll(page, "home-empty");
  });

  test("home signed in, runtime error", async ({ page }) => {
    await signIn(page);
    await createBooksFolder(page);
    await page.route(/\/books\/(home|dashboard|goals)\b/, (route) => route.fulfill({ status: 503, body: JSON.stringify({ detail: "The runtime is restarting (ref e2e-503)" }), contentType: "application/json" }));
    await page.goto("/");
    await page.waitForTimeout(1500);
    await shootAll(page, "home-error");
  });

  test("home signed in, held loading", async ({ page, runtime }) => {
    await runtime.reset("bank");
    await signIn(page);
    await createBooksFolder(page);
    await seedGoals(runtime);
    let release = () => {};
    const held = new Promise<void>((r) => (release = r));
    await page.route(/\/books\/(home|goals)\b/, async (route) => {
      await held;
      await route.continue();
    });
    await page.goto("/");
    await page.waitForTimeout(800);
    await shootAll(page, "home-loading");
    release();
  });

  test("goals page signed in", async ({ page, runtime }) => {
    await runtime.reset("bank");
    await signIn(page);
    await createBooksFolder(page);
    await seedGoals(runtime);
    await page.goto("/goals");
    await expect(page.getByRole("article")).toHaveCount(3);
    await page.waitForLoadState("networkidle");
    await shootAll(page, "goals");
    // keyboard focus on a card's View details
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.getByRole("button", { name: "View details" }).first().focus();
    await page.screenshot({ path: path.join(OUT, "goals-focus-1280.png"), scale: "css", animations: "disabled" });
  });

  test("goals page signed in, none yet", async ({ page }) => {
    await signIn(page);
    await createBooksFolder(page);
    await page.goto("/goals");
    await expect(page.getByText("No goals yet")).toBeVisible();
    await shootAll(page, "goals-empty");
  });

  test("goals signed out sample", async ({ page }) => {
    await page.goto("/goals");
    await expect(page.getByRole("article")).toHaveCount(3);
    await shootAll(page, "goals-try");
  });

  test("review signed out sample", async ({ page }) => {
    await page.goto("/review");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await shootAll(page, "review-try");
  });

  test("review signed in, scan done and a card", async ({ page, runtime }) => {
    await signIn(page);
    await createBooksFolder(page);
    await page.goto("/review");
    await page.locator('input[type="file"]').first().setInputFiles({ name: `${GOLD}.png`, mimeType: "image/png", buffer: await runtime.goldPng() });
    await expect(page.getByText("1 file added to 00 Inbox")).toBeVisible();
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator('[data-scan-file][data-stage="confirm"]').first()).toBeVisible({ timeout: 30_000 });
    await page.screenshot({ path: path.join(OUT, "review-scan-confirm-390.png"), fullPage: true, scale: "css", animations: "disabled" });
    await confirmScan(page);
    await expect(page.getByRole("region", { name: "Novex Office Supplies Ltd · £51.90" })).toBeVisible();
    await expect(page.getByText(/^Done · /)).toBeVisible();
    await page.waitForLoadState("networkidle");
    await shootAll(page, "review-signed");
    // keyboard focus: the card and a button
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("button", { name: /^Approve/ }).first().focus();
    await page.screenshot({ path: path.join(OUT, "review-focus-390.png"), scale: "css", animations: "disabled" });
  });

  test("invoices signed in, every status, and the record payment dialog", async ({ page, runtime }) => {
    await signIn(page);
    await createBooksFolder(page);
    await seedInvoices(runtime);
    await page.goto("/invoices");
    await expect(page.getByText("INV-0004 · Jo Bloggs")).toBeVisible();
    await page.waitForLoadState("networkidle");
    await shootAll(page, "invoices");
    await page.getByRole("button", { name: "Record payment" }).first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    for (const w of [320, 390, 1280]) {
      await page.setViewportSize({ width: w, height: HEIGHT[w] });
      await page.waitForTimeout(200);
      await page.screenshot({ path: path.join(OUT, `invoices-dialog-${w}.png`), scale: "css", animations: "disabled" });
    }
  });

  test("invoices signed out sample", async ({ page }) => {
    await page.goto("/invoices");
    await expect(page.getByText("INV-0006 · Acme Kitchens Ltd")).toBeVisible();
    await shootAll(page, "invoices-try");
  });

  test("bank signed in with the gold statement", async ({ page, runtime }) => {
    await runtime.reset("bank");
    await signIn(page);
    await createBooksFolder(page);
    await page.goto("/bank");
    await page.locator('input[type="file"]').setInputFiles(path.join(__dirname, "../../../evals/gold/bank/barclays.csv"));
    await expect(page.getByRole("status").filter({ hasText: "barclays.csv" })).toContainText("6 new lines");
    await page.getByRole("button", { name: /04 Bank statements\/.*barclays\.csv/ }).click();
    await page.waitForLoadState("networkidle");
    await shootAll(page, "bank");
    await page.goto("/bank/reconcile");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await shootAll(page, "bank-reconcile");
  });

  test("nav: VAT page (Reporting and Tax both hold it), customers (Sales and Contacts), menu drawer and sidebar", async ({ page, runtime }) => {
    await runtime.reset("bank");
    await signIn(page);
    await createBooksFolder(page);
    await page.goto("/vat");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.waitForLoadState("networkidle");
    for (const w of [1024, 1280, 1440]) {
      await page.setViewportSize({ width: w, height: HEIGHT[w] });
      await page.waitForTimeout(200);
      if (w < 1280) {
        await page.getByRole("navigation", { name: "Main" }).getByRole("button", { name: "Reporting" }).click();
      } else {
        const nav = page.getByRole("navigation", { name: "Main" });
        await nav.getByRole("button", { name: "Reporting" }).click();
        await nav.getByRole("button", { name: "Tax" }).click();
      }
      await page.waitForTimeout(150);
      await page.screenshot({ path: path.join(OUT, `nav-vat-${w}.png`), scale: "css", animations: "disabled" });
      await page.keyboard.press("Escape");
    }
    await page.goto("/contacts/customers");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    for (const w of [1024, 1280]) {
      await page.setViewportSize({ width: w, height: HEIGHT[w] });
      await page.waitForTimeout(200);
      const nav = page.getByRole("navigation", { name: "Main" });
      await nav.getByRole("button", { name: "Sales" }).click();
      if (w >= 1280) await nav.getByRole("button", { name: "More" }).click();
      await page.waitForTimeout(150);
      await page.screenshot({ path: path.join(OUT, `nav-customers-${w}.png`), fullPage: w >= 1280, scale: "css", animations: "disabled" });
      await page.keyboard.press("Escape");
    }
    // the phone drawer on /vat, and keyboard focus on the first drawer link
    await page.goto("/vat");
    for (const w of [320, 390]) {
      await page.setViewportSize({ width: w, height: HEIGHT[w] });
      await page.waitForTimeout(200);
      await page.screenshot({ path: path.join(OUT, `nav-topbar-${w}.png`), scale: "css", animations: "disabled" });
      await page.getByRole("button", { name: "Menu" }).click();
      await page.waitForTimeout(150);
      await page.keyboard.press("Tab");
      await page.keyboard.press("Tab");
      await page.screenshot({ path: path.join(OUT, `nav-drawer-${w}.png`), scale: "css", animations: "disabled" });
      await page.keyboard.press("Escape");
    }
  });

  test("phone: review with the assistant and tab bar over the form (keyboard open simulated by a short viewport)", async ({ page, runtime }) => {
    await signIn(page);
    await createBooksFolder(page);
    await runtime.dropInInbox();
    await page.goto("/review");
    await page.getByRole("button", { name: "Scan 00 Inbox now" }).click();
    await confirmScan(page);
    await expect(page.getByRole("region", { name: "Novex Office Supplies Ltd · £51.90" })).toBeVisible();
    for (const [w, h] of [[320, 568], [390, 844], [390, 420]] as const) {
      await page.setViewportSize({ width: w, height: h });
      await page.waitForTimeout(200);
      const approve = page.getByRole("button", { name: /^Approve/ }).first();
      await approve.scrollIntoViewIfNeeded();
      await approve.focus();
      await page.screenshot({ path: path.join(OUT, `phone-review-actions-${w}x${h}.png`), scale: "css", animations: "disabled" });
    }
    // a form with its last field focused at a keyboard-height viewport
    await page.goto("/invoices/new");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    for (const [w, h] of [[320, 568], [390, 420]] as const) {
      await page.setViewportSize({ width: w, height: h });
      await page.waitForTimeout(200);
      const submit = page.getByRole("button", { name: /Save|Send|Preview/ }).last();
      await submit.scrollIntoViewIfNeeded();
      await page.keyboard.press("Shift+Tab");
      await page.screenshot({ path: path.join(OUT, `phone-form-end-${w}x${h}.png`), scale: "css", animations: "disabled" });
    }
  });

  test("home signed in at DEMO_DAY: profile menu and account menu at 320/390", async ({ page, runtime }) => {
    await runtime.reset("demo");
    await signIn(page, DEMO_DAY);
    await createBooksFolder(page);
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    for (const w of [320, 390]) {
      await page.setViewportSize({ width: w, height: HEIGHT[w] });
      await page.waitForTimeout(200);
      await page.screenshot({ path: path.join(OUT, `profile-bar-${w}.png`), scale: "css", animations: "disabled" });
      await page.getByRole("button", { name: /^Profile: / }).click();
      await page.waitForTimeout(150);
      await page.screenshot({ path: path.join(OUT, `profile-menu-${w}.png`), scale: "css", animations: "disabled" });
      await page.keyboard.press("Escape");
    }
  });
});
