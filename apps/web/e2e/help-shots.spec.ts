import { mkdirSync, statSync } from "node:fs";
import path from "node:path";
import type { Locator, Page } from "@playwright/test";
import { expect, signIn, test, TODAY } from "./fixtures";

/**
 * Screenshots for the help centre (src/content/help/articles.json → public/help/<name>.webp), from the demo sandbox's
 * fictional sample books and the test-mode Support page, at 1280 × 800 in the light theme. Skipped unless
 * HELP_SHOTS=1. PNGs go to test-results/help-shots/; `python tools/help_shots_webp.py` (repo root) turns them into
 * public/help/*.webp and refuses any whose text (OCR) names an AI vendor or model.
 *
 *   pnpm run e2e:build && HELP_SHOTS=1 pnpm exec playwright test e2e/help-shots.spec.ts --project=desktop --workers=1
 *
 * PW_CHROMIUM: a Chromium to use instead of Playwright's own download (an environment without `playwright install`).
 * No AI vendor or model name may appear in a help picture: model names are replaced with "the AI" before each shot, and
 * the footer's model-page links are hidden. Settings › AI is never photographed.
 */

test.skip(process.env.HELP_SHOTS !== "1", "help shots run only with HELP_SHOTS=1");
test.describe.configure({ mode: "serial" });
test.use({ viewport: { width: 1280, height: 800 }, colorScheme: "light", actionTimeout: 10_000, launchOptions: { args: ["--lang=en-GB"], ...(process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {}) } });

const OUT = path.resolve(__dirname, "../test-results/help-shots");
const SEED_WAIT = 400_000;
const bar = (page: Page) => page.getByRole("complementary", { name: "Demo sandbox" });

const SWAPS: [string, string][] = [
  ["\\s*\\(accnomos-test-stub\\)", ""],
  ["explanation by accnomos-test-stub", "explanation by the AI"],
  ["accnomos-test-stub", "the AI"],
  ["Test stub judgement: no real model ran\\.?", ""],
  ["Test stub:\\s*", ""],
  ["\\(test mode\\)", ""],
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
      const style = document.createElement("style");
      style.textContent = 'a[href="/models"], a[href="/meta-models"] { display: none !important; }';
      document.head.appendChild(style);
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
    el.setAttribute("data-help-mark", "");
    (el as HTMLElement).style.outline = "3px solid #C8963E";
    (el as HTMLElement).style.outlineOffset = "3px";
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
  mkdirSync(OUT, { recursive: true });
  await page.waitForTimeout(500);
  const file = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: file, scale: "css", animations: "disabled", caret: "hide" });
  expect(statSync(file).size).toBeGreaterThan(1000);
  await page.evaluate(() =>
    document.querySelectorAll("[data-help-mark]").forEach((el) => {
      el.removeAttribute("data-help-mark");
      (el as HTMLElement).style.outline = "";
    }),
  );
}

/** One shot that may not reach its state on these sample books: say so and go on. */
async function soft(name: string, body: () => Promise<void>): Promise<void> {
  try {
    await body();
  } catch (e) {
    console.log(`help-shots: ${name} skipped: ${String(e).split("\n")[0]}`);
  }
}

test("signed in: the Support page, the assistant's answer and its ticket card", async ({ page }) => {
  await tidy(page);
  await signIn(page, TODAY);
  await page.goto("/support");
  const ask = page.getByRole("textbox", { name: "Your question" });
  await expect(ask).toBeVisible();
  await ask.fill("The PayPal sync is not working, I get an error");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const ticket = page.getByRole("article", { name: "Proposed: Support ticket" });
  await expect(ticket).toBeVisible({ timeout: 30_000 });
  await shoot(page, "support-1");
  await bring(page, ticket, 120);
  await mark(ticket.getByRole("button", { name: "Create ticket" }));
  await shoot(page, "support-ticket-card");
  await ticket.getByRole("button", { name: "Create ticket" }).click();
  await expect(ticket.getByRole("status")).toContainText("ticket", { timeout: 15_000 });
  await page.goto(await ticket.getByRole("link", { name: "Open it on Support" }).getAttribute("href").then((h) => h ?? "/support"));
  await expect(page.locator("[data-ticket-thread]")).toBeVisible({ timeout: 15_000 });
  await shoot(page, "support-2");
});

test("company demo: review, the assistant, invoices and PayPal, purchases, month-end", async ({ page }) => {
  test.setTimeout(SEED_WAIT + 600_000);
  await tidy(page);
  await page.clock.install({ time: TODAY });
  await page.goto("/demo");
  await page.getByRole("button", { name: "Start the demo" }).click();
  await expect(bar(page)).toContainText("Demo sandbox with sample data", { timeout: SEED_WAIT });

  await soft("review", async () => {
    await page.goto("/review");
    const card = page.getByRole("button", { name: /^Approve / }).first();
    await expect(card).toBeVisible({ timeout: 30_000 });
    await bring(page, card, 420);
    await mark(card);
    await shoot(page, "review-approve-3");
    await card.click();
    await expect(page.locator('p[role="status"][aria-live="polite"]')).toContainText("Approved");
    await shoot(page, "review-approve-4");
    const autopilot = page.getByRole("heading", { name: /Approved by Autopilot/ });
    await bring(page, autopilot);
    await mark(page.getByRole("button", { name: "Undo" }).first());
    await shoot(page, "review-approve-5");
  });

  await soft("assistant", async () => {
    await page.goto("/");
    await page.getByRole("button", { name: "Talk to Accnomos" }).click();
    const drawer = page.getByRole("dialog", { name: "Talk to Accnomos" });
    await expect(drawer).toBeVisible();
    await mark(drawer.getByRole("button", { name: "Hands-free" }));
    await shoot(page, "voice-chat-1");
    await drawer.getByLabel("Your question").fill("How much VAT do I owe and why?");
    await drawer.getByRole("button", { name: "Send" }).click();
    await expect(drawer.getByRole("article").last()).toContainText(/Numbers by code|numbers by code/, { timeout: 30_000 });
    await shoot(page, "voice-chat-2");
    await drawer.getByLabel("Your question").fill("How do I connect my bank feed?");
    await drawer.getByRole("button", { name: "Send" }).click();
    await expect(drawer.getByRole("link", { name: /Help · Connect a bank feed/ }).first()).toBeVisible({ timeout: 30_000 });
    await shoot(page, "voice-chat-help");
    await page.keyboard.press("Escape");
  });

  await soft("invoices", async () => {
    await page.goto("/invoices");
    await expect(page.getByRole("main")).toContainText(/INV-/, { timeout: 30_000 });
    await shoot(page, "invoices-1");
    const sync = page.getByRole("button", { name: "Sync PayPal" });
    await bring(page, sync, 260);
    await mark(sync);
    await shoot(page, "paypal-sync-1");
    const disputes = page.getByRole("heading", { name: "PayPal disputes" });
    await bring(page, disputes, 160);
    await shoot(page, "paypal-disputes-1");
  });

  await soft("billpay", async () => {
    await page.goto("/purchases");
    const pay = page.getByRole("heading", { name: /Pay bills with PayPal/ });
    await expect(pay).toBeVisible({ timeout: 30_000 });
    await bring(page, pay, 160);
    await shoot(page, "billpay-1");
  });

  await soft("online payments", async () => {
    await page.goto("/settings");
    await page.getByRole("tablist", { name: "Settings groups" }).getByRole("tab", { name: "Business", exact: true }).click();
    const online = page.getByRole("heading", { name: "Online payments" });
    await expect(online).toBeVisible({ timeout: 15_000 });
    await bring(page, online, 160);
    await shoot(page, "paypal-connect-1");
  });

  await soft("month-end", async () => {
    await page.goto("/month-end");
    await expect(page.getByRole("heading", { level: 1, name: "Month-end" })).toBeVisible();
    await page.waitForTimeout(1500);
    await shoot(page, "month-end-1");
  });

  await soft("help centre", async () => {
    await page.goto("/help");
    await expect(page.getByRole("heading", { level: 1, name: "Help centre" })).toBeVisible();
    await shoot(page, "help-centre-1");
  });
});
