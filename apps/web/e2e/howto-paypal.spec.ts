import { statSync } from "node:fs";
import path from "node:path";
import type { Locator, Page } from "@playwright/test";
import { createBooksFolder, expect, signIn, test } from "./fixtures";

/**
 * Screenshots for the PayPal how-to guides (docs/howto/paypal-*.md, power-grid.md), at 1280 × 800 in the light theme.
 * Signed in to the test-mode runtime, whose PayPal is the stand-in in services/runtime/app/online_fakes.py (nothing
 * reaches PayPal) and whose books hold only fictional sample data. The disputes guide uses the company demo's sample
 * dispute (Bramblewood Joinery Ltd), like the other guides.
 *
 *   pnpm run e2e:build && HOWTO_SHOTS=1 pnpm exec playwright test e2e/howto-paypal.spec.ts --project=desktop --workers=1
 *
 * Skipped unless HOWTO_SHOTS=1, so `pnpm run e2e` never writes into docs/. PW_CHROMIUM: a Chromium to use instead of
 * Playwright's own download. No AI vendor or model name may appear in a picture: test-mode and model names are replaced
 * with "the AI" before each shot (as in e2e/help-shots.spec.ts).
 */

test.skip(process.env.HOWTO_SHOTS !== "1", "how-to shots run only with HOWTO_SHOTS=1");

test.use({
  viewport: { width: 1280, height: 800 },
  colorScheme: "light",
  actionTimeout: 10_000,
  launchOptions: { args: ["--lang=en-GB"], ...(process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {}) },
});

const OUT = path.resolve(__dirname, "../../../docs/howto/img");
const LIMIT = 450 * 1024;
const SEED_WAIT = 400_000;
const ONLY = process.env.HOWTO_ONLY ? new RegExp(process.env.HOWTO_ONLY) : null;

const SWAPS: [string, string][] = [
  ["\\s*\\(accnomos-test-stub\\)", ""],
  ["explanation by accnomos-test-stub", "explanation by the AI"],
  ["accnomos-test-stub", "the AI"],
  ["the test stub", "the AI"],
  ["Test stub judgement: no real model ran\\.?", ""],
  ["[:·]?\\s*Test stub coding: no real model ran\\.?", ""],
  ["Test stub", "The AI"],
  ["\\s\\(test\\)", ""],
  ["Test stub:\\s*", ""],
  ["\\(test mode\\)", ""],
  ["Your AI \\(local\\) returned HTTP \\d+\\.\\s*", ""],
  ["[Mm]use[- ][A-Za-z]+(?:[- ]\\d[\\w.-]*)?(?:-contributor)?", "the AI"],
  ["\\bMeta(?:'s)?\\s+(?:Model API|models?|AI)\\b", "the AI"],
  ["\\bMeta\\b", "the AI"],
  ["\\bGlimmer\\b", "the AI"],
];

async function tidy(page: Page): Promise<void> {
  await page.addInitScript((swaps: [string, string][]) => {
    const res = swaps.map(([re, to]) => [new RegExp(re, "g"), to] as const);
    const fix = (root: Node) => {
      const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      for (let n = walk.nextNode(); n; n = walk.nextNode()) {
        let t = n.nodeValue ?? "";
        for (const [re, to] of res) t = t.replace(re, to);
        if (t !== n.nodeValue) n.nodeValue = t;
      }
    };
    const start = () => {
      fix(document.body);
      new MutationObserver((ms) => {
        for (const m of ms) {
          if (m.type === "characterData" && m.target.parentNode) fix(m.target.parentNode);
          m.addedNodes.forEach((n) => fix(n));
        }
      }).observe(document.body, { subtree: true, childList: true, characterData: true });
    };
    if (document.body) start();
    else document.addEventListener("DOMContentLoaded", start);
  }, SWAPS);
}

async function mark(target: Locator): Promise<void> {
  await target.first().evaluate((el) => {
    el.setAttribute("data-howto-mark", "");
    (el as HTMLElement).style.outline = "3px solid #C8963E";
    (el as HTMLElement).style.outlineOffset = "3px";
    (el as HTMLElement).style.borderRadius ||= "8px";
  });
}

async function bring(page: Page, target: Locator, offset = 140): Promise<void> {
  await target.first().scrollIntoViewIfNeeded();
  await target.first().evaluate((el, off) => {
    window.scrollTo({ top: Math.max(0, el.getBoundingClientRect().top + window.scrollY - off), behavior: "instant" as ScrollBehavior });
  }, offset);
  await page.waitForTimeout(300);
}

async function shoot(page: Page, name: string): Promise<void> {
  if (ONLY && !ONLY.test(name)) return;
  await page.waitForTimeout(500);
  const file = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: file, scale: "css", animations: "disabled", caret: "hide" });
  expect(statSync(file).size, `${name}.png is over the size limit`).toBeLessThan(LIMIT);
  await page.evaluate(() =>
    document.querySelectorAll("[data-howto-mark]").forEach((el) => {
      el.removeAttribute("data-howto-mark");
      (el as HTMLElement).style.outline = "";
    }),
  );
}

async function openAssistant(page: Page): Promise<Locator> {
  await page.getByRole("button", { name: "Talk to Accnomos" }).click();
  const drawer = page.getByRole("dialog", { name: "Talk to Accnomos" });
  await expect(drawer).toBeVisible();
  return drawer;
}

test("signed in with the PayPal stand-in: pay links, Sync PayPal, bill pay, Ask, Power grid", async ({ page, runtime }) => {
  test.setTimeout(600_000);
  await tidy(page);
  await signIn(page);
  await createBooksFolder(page);

  // An approved bill on account, for bill pay: Novex Office Supplies (fictional), 90-day terms so it is not due yet.
  await runtime.dropInInbox("001_standard");
  const scan = await runtime.api<{ proposals: { id: string; status: string }[] }>("POST", "/books/scan");
  for (const p of scan.proposals) await runtime.api("POST", `/books/approve/${p.id}`, { edits: { payment_method: "unknown" } });
  const list = await runtime.api<{ contacts: { id: string; name: string }[] }>("POST", "/contacts/refresh");
  const oak = list.contacts.find((c) => /Novex/.test(c.name));
  if (oak) await runtime.api("PUT", `/contacts/${oak.id}`, { terms_days: 90 });

  // An invoice sent to a fictional customer (£372.00 = 6 h × £45 + 4 × £10, 20% VAT).
  await runtime.api("POST", "/invoices", {
    customer: { name: "Harbour Cafe Ltd", email: "accounts@harbourcafe.example" },
    lines: [
      { description: "Kitchen first fix", quantity: "6", unit: "hours", unit_price_pence: 4500, vat_code: "S" },
      { description: "Fixings", quantity: "4", unit: "boxes", unit_price_pence: 1000, vat_code: "S" },
    ],
  });
  await runtime.api("POST", "/invoices/INV-0001/send", { confirm: true });

  // ---- paypal-invoice-link: connect, add the link, the customer pays, approve
  await page.goto("/settings#settings-payments");
  const payments = page.getByRole("region", { name: "Online payments" });
  await bring(page, payments, 120);
  await mark(payments.getByRole("button", { name: /^Connect PayPal/ }));
  await shoot(page, "paypal-invoice-link-1");
  await payments.getByRole("button", { name: /^Connect PayPal/ }).click();
  await expect(page.getByRole("status")).toContainText("PayPal connected.");

  await page.goto("/invoices");
  const row = page.getByRole("listitem").filter({ hasText: "INV-0001 · Harbour Cafe Ltd" });
  await expect(row).toBeVisible({ timeout: 30_000 });
  await bring(page, row, 160);
  await mark(row.getByRole("button", { name: "Add payment link" }));
  await shoot(page, "paypal-invoice-link-2");
  await row.getByRole("button", { name: "Add payment link" }).click();
  const dialog = page.getByRole("dialog", { name: "Payment link for INV-0001" });
  await expect(dialog.getByRole("radio", { name: /PayPal/ })).toBeChecked({ timeout: 30_000 });
  await mark(dialog.getByRole("button", { name: "Make payment link" }));
  await shoot(page, "paypal-invoice-link-3");
  await dialog.getByRole("button", { name: "Make payment link" }).click();
  const url = await dialog.getByRole("textbox", { name: "Payment link" }).inputValue();
  await dialog.getByRole("button", { name: "Done" }).click();
  const pay = await page.request.post(url);
  expect(pay.ok()).toBeTruthy();
  await page.goto("/invoices");
  const paid = page.getByRole("region", { name: "Paid online" });
  await expect(paid).toContainText("INV-0001", { timeout: 30_000 });
  await bring(page, paid, 120);
  await mark(paid.getByRole("button", { name: /^Approve £372\.00/ }));
  await shoot(page, "paypal-invoice-link-4");
  await paid.getByRole("button", { name: /^Approve £372\.00/ }).click();
  await expect(paid).toBeHidden();

  // ---- paypal-sync: sync, the waiting list, a VAT choice, the tie-out
  await page.goto("/invoices");
  const panel = page.getByRole("region", { name: "PayPal", exact: true });
  await expect(panel.getByRole("button", { name: "Sync PayPal" })).toBeVisible({ timeout: 30_000 });
  await bring(page, panel, 120);
  await mark(panel.getByRole("button", { name: "Sync PayPal" }));
  await shoot(page, "paypal-sync-1");
  await panel.getByRole("button", { name: "Sync PayPal" }).click();
  const waiting = panel.getByRole("list", { name: "PayPal transactions waiting for approval" });
  await expect(waiting).toBeVisible({ timeout: 30_000 });
  await bring(page, waiting, 120);
  await shoot(page, "paypal-sync-2");
  const vatPick = panel.getByLabel("VAT on this sale (choose before approving)").first();
  if (await vatPick.count()) {
    const item = waiting.getByRole("listitem").filter({ has: page.getByLabel("VAT on this sale (choose before approving)") }).first();
    await bring(page, item, 160);
    await vatPick.selectOption("S");
    await mark(vatPick);
    await shoot(page, "paypal-sync-3");
    await item.getByRole("button", { name: /^Approve / }).click();
    await page.waitForTimeout(1500);
  } else {
    const first = waiting.getByRole("listitem").first();
    await bring(page, first, 160);
    await mark(first.getByRole("button", { name: /^Approve / }));
    await shoot(page, "paypal-sync-3");
    await first.getByRole("button", { name: /^Approve / }).click();
    await page.waitForTimeout(1500);
  }
  await page.goto("/invoices");
  const tie = page.getByLabel("PayPal and your books");
  await expect(tie).toBeVisible({ timeout: 30_000 });
  await bring(page, tie, 140);
  await mark(tie);
  await shoot(page, "paypal-sync-4");

  // ---- paypal-ask: questions and a card
  await page.goto("/invoices");
  const drawer = await openAssistant(page);
  await drawer.getByLabel("Your question").fill("How much is sitting in PayPal?");
  await drawer.getByRole("button", { name: "Send" }).click();
  await expect(drawer.getByRole("article").last()).toContainText(/PayPal/, { timeout: 30_000 });
  await page.waitForTimeout(1500);
  await shoot(page, "paypal-ask-1");
  await drawer.getByLabel("Your question").fill("What is waiting in Sync PayPal?");
  await drawer.getByRole("button", { name: "Send" }).click();
  await page.waitForTimeout(4000);
  await shoot(page, "paypal-ask-2");
  await page.keyboard.press("Escape");

  // ---- paypal-bill-pay: payee email, approve now / pay on due date, upcoming, calendar, kill switch
  await page.goto("/purchases");
  const bp = page.getByRole("heading", { name: "Pay bills with PayPal" });
  await expect(bp).toBeVisible({ timeout: 30_000 });
  const payees = page.getByRole("heading", { name: "Suppliers' PayPal emails" });
  await bring(page, payees, 120);
  const form = page.locator("form").filter({ hasText: "I typed this myself" });
  await form.getByLabel("Supplier").selectOption({ label: oak ? oak.name : "Novex Office Supplies Ltd" }).catch(() => undefined);
  await form.getByLabel("PayPal email").fill("accounts@novex-office.example");
  await form.getByLabel("I typed this myself and checked it with the supplier").check();
  await mark(form.getByRole("button", { name: "Save PayPal email" }));
  await shoot(page, "paypal-bill-pay-1");
  await form.getByRole("button", { name: "Save PayPal email" }).click();
  await expect(page.getByText("accounts@novex-office.example").first()).toBeVisible({ timeout: 15_000 });
  const ahead = page.getByRole("button", { name: "Approve now, pay on due date" }).first();
  await expect(ahead).toBeVisible({ timeout: 15_000 });
  await ahead.click();
  const confirmAhead = page.getByRole("button", { name: /^Approve £[\d,.]+ for / }).first();
  await bring(page, confirmAhead, 360);
  await mark(confirmAhead);
  await shoot(page, "paypal-bill-pay-2");
  await confirmAhead.click();
  const upcoming = page.getByRole("heading", { name: "Upcoming PayPal payments" }).first();
  await expect(page.getByText("Approved in advance").first()).toBeVisible({ timeout: 15_000 });
  await bring(page, upcoming, 120);
  await mark(page.getByRole("button", { name: /^Add to / }).first());
  await shoot(page, "paypal-bill-pay-3");
  const auto = page.getByRole("heading", { name: "Autopilot for bills" });
  await bring(page, auto, 120);
  await page.getByRole("checkbox", { name: /^Pay .* automatically$/ }).first().check().catch(() => undefined);
  const autoRow = page.getByRole("row").filter({ has: page.getByRole("checkbox", { name: /^Pay .* automatically$/ }) }).first();
  await autoRow.getByRole("textbox").nth(0).fill("100").catch(() => undefined);
  await autoRow.getByRole("textbox").nth(1).fill("500").catch(() => undefined);
  await page.getByLabel("Autopilot for bills is on").check().catch(() => undefined);
  await page.getByRole("button", { name: "Save", exact: true }).last().click().catch(() => undefined);
  const stop = page.getByRole("button", { name: "Stop all automatic payments now" });
  await stop.waitFor({ timeout: 10_000 }).catch(() => undefined);
  await bring(page, auto, 120);
  if (await stop.count()) await mark(stop);
  await shoot(page, "paypal-bill-pay-4");
  await page.goto("/");
  const homeUp = page.getByRole("heading", { name: "Upcoming PayPal payments" });
  await expect(homeUp).toBeVisible({ timeout: 30_000 });
  await bring(page, homeUp, 160);
  await shoot(page, "paypal-bill-pay-5");

  // ---- power-grid: the setting, the PayPal grid, the ledger explorer
  await page.goto("/settings#settings-power-grid");
  const setting = page.locator("#settings-power-grid");
  await bring(page, setting, 120);
  await page.getByLabel("Use the power grid").check();
  await mark(page.getByLabel("Use the power grid").locator(".."));
  await shoot(page, "power-grid-1");
  await page.goto("/invoices");
  const grid = page.getByTestId("paypal-grid");
  await expect(grid.locator(".ag-row").first()).toBeVisible({ timeout: 30_000 });
  await bring(page, grid, 120);
  await shoot(page, "power-grid-2");
  await page.goto("/reports/ledger-grid");
  const lg = page.getByTestId("ledger-grid");
  await expect(lg.getByText(/Total of \d+ lines shown/)).toBeVisible({ timeout: 30_000 });
  await page.getByLabel("Describe the lines you want to see").fill("Lines over £40, biggest first");
  await page.getByRole("button", { name: "Filter", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Lines matching your words.", { timeout: 30_000 });
  await mark(page.getByLabel("Describe the lines you want to see"));
  await shoot(page, "power-grid-3");
});

test("company demo: the sample PayPal dispute", async ({ page }) => {
  test.setTimeout(SEED_WAIT + 120_000);
  await tidy(page);
  await page.clock.install({ time: new Date("2026-10-27T09:00:00Z") });
  await page.goto("/demo");
  await page.getByRole("button", { name: "Start the demo" }).click();
  await expect(page.getByRole("complementary", { name: "Demo sandbox" })).toContainText("Demo sandbox with sample data", { timeout: SEED_WAIT });
  await page.goto("/invoices");
  const box = page.getByRole("region", { name: "PayPal disputes" });
  await expect(box).toBeVisible({ timeout: 30_000 });
  await bring(page, box, 120);
  await mark(box.getByRole("button", { name: "Build evidence" }));
  await shoot(page, "paypal-disputes-1");
  await box.getByRole("button", { name: "Build evidence" }).first().click();
  await expect(box.getByText("Response for PayPal (preview)")).toBeVisible({ timeout: 30_000 });
  await bring(page, box.getByText("Response for PayPal (preview)"), 200);
  await mark(box.getByRole("button", { name: /^Send to PayPal/ }));
  await shoot(page, "paypal-disputes-2");
  await box.getByRole("button", { name: /^Send to PayPal/ }).click();
  await expect(box.getByText(/Sent to PayPal|recorded as sent/).first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(800);
  await shoot(page, "paypal-disputes-3");
});
