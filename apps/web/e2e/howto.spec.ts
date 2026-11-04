import { statSync } from "node:fs";
import path from "node:path";
import type { Locator, Page } from "@playwright/test";
import { expect, test, TODAY } from "./fixtures";

/**
 * Screenshots for the how-to guides (docs/howto/*.md), from the demo sandbox's fictional sample books: the company demo
 * (Bramblewood Joinery Ltd) and the personal demo (the Harrison household), at 1280 × 800 in the light theme.
 * Run: `HOWTO_SHOTS=1 pnpm exec playwright test e2e/howto.spec.ts --project=desktop` after `pnpm run e2e:build`.
 * Skipped unless HOWTO_SHOTS=1, so `pnpm run e2e` never writes into docs/.
 *
 * Each picture is `docs/howto/img/<guide>-<n>.png`; the control a step names gets a brass outline. Test mode answers with
 * a stub instead of a model, so its "test stub" labels are taken out of the frame before the picture is taken (the live
 * app names the Meta model there). A shot that cannot reach its state fails the test rather than saving the wrong screen.
 */

test.skip(process.env.HOWTO_SHOTS !== "1", "how-to shots run only with HOWTO_SHOTS=1");
test.describe.configure({ mode: "serial" });
test.use({ viewport: { width: 1280, height: 800 }, colorScheme: "light", actionTimeout: 10_000, launchOptions: { args: ["--lang=en-GB"] } });

const OUT = path.resolve(__dirname, "../../../docs/howto/img");
const LIMIT = 450 * 1024;
const SEED_WAIT = 400_000;
const ONLY = process.env.HOWTO_ONLY ? new RegExp(process.env.HOWTO_ONLY) : null;

const bar = (page: Page) => page.getByRole("complementary", { name: "Demo sandbox" });
const main = (page: Page) => page.getByRole("main");

/** Take test-mode wording out of the frame (the stub's name, its "Test stub:" prefixes and its failure notes). */
const SWAPS: [string, string][] = [
  ["\\s*\\(accnomos-test-stub\\)", ""],
  ["explanation by accnomos-test-stub", "explanation by your AI"],
  ["accnomos-test-stub", "your AI"],
  ["Test stub judgement: no real model ran\\.?", ""],
  ["Test stub:\\s*", ""],
  ["Your AI \\(local\\) could not write the note \\([A-Za-z]+\\)\\.?", ""],
  ["\\(test mode\\)", ""],
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

/** Outline the control the step names. */
async function mark(target: Locator): Promise<void> {
  await target.first().evaluate((el) => {
    el.setAttribute("data-howto-mark", "");
    (el as HTMLElement).style.outline = "3px solid #C8963E";
    (el as HTMLElement).style.outlineOffset = "3px";
    (el as HTMLElement).style.borderRadius ||= "8px";
  });
}

/** Scroll so `target` sits just under the demo bar. */
async function bring(page: Page, target: Locator, offset = 140): Promise<void> {
  await target.first().scrollIntoViewIfNeeded();
  await target.first().evaluate((el, off) => {
    const top = el.getBoundingClientRect().top + window.scrollY - off;
    window.scrollTo({ top: Math.max(0, top), behavior: "instant" as ScrollBehavior });
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

/** One shot that may not reach its state on these sample books: say so and go on. */
async function soft(name: string, body: () => Promise<void>): Promise<void> {
  try {
    await body();
  } catch (e) {
    console.log(`howto: ${name} skipped: ${String(e).split("\n")[0]}`);
  }
}

async function startDemo(page: Page, kind: "company" | "personal"): Promise<void> {
  await tidy(page);
  await page.clock.install({ time: TODAY });
  await page.goto("/judges");
  await page.getByRole("button", { name: kind === "personal" ? "Start the personal demo" : "Start the demo" }).click();
  await expect(bar(page)).toContainText("Demo sandbox with sample data", { timeout: SEED_WAIT });
}

async function openAssistant(page: Page): Promise<Locator> {
  await page.getByRole("button", { name: "Talk to Accnomos" }).click();
  const drawer = page.getByRole("dialog", { name: "Talk to Accnomos" });
  await expect(drawer).toBeVisible();
  return drawer;
}

async function settings(page: Page, tab: string): Promise<Locator> {
  await page.goto("/settings");
  await page.getByRole("tablist", { name: "Settings groups" }).getByRole("tab", { name: tab, exact: true }).click();
  const panel = page.getByRole("tabpanel", { name: tab });
  await expect(panel).toBeVisible();
  return panel;
}

test("signed out: Connect and the judges' guide", async ({ page }) => {
  await page.clock.install({ time: TODAY });
  await page.goto("/connect");
  await expect(page.getByRole("button", { name: "Sign in with Microsoft" })).toBeVisible();
  await mark(page.getByRole("button", { name: "Sign in with Microsoft" }));
  await shoot(page, "connect-books-1");

  await page.goto("/judges");
  await expect(page.getByRole("heading", { name: "Try Accnomos in one click" })).toBeVisible();
  await mark(page.getByRole("button", { name: "Start the demo" }));
  await shoot(page, "connect-books-2");
});

test("company demo", async ({ page }) => {
  test.setTimeout(SEED_WAIT + 900_000);
  await startDemo(page, "company");

  // ---- connect-books / home
  await page.goto("/");
  const summary = page.getByRole("region", { name: /^Your summary/ });
  await expect(summary).toBeVisible({ timeout: 30_000 });
  await expect(summary.getByRole("link").first()).toBeVisible({ timeout: 30_000 });
  await mark(summary);
  await shoot(page, "connect-books-3");
  await page.goto("/files");
  await expect(main(page).getByText("00 Inbox").first()).toBeVisible();
  await shoot(page, "connect-books-4");

  // ---- review-approve
  await page.goto("/review");
  await expect(page.getByText(/\d+ waiting for you/).first()).toBeVisible();
  await mark(page.getByText(/\d+ waiting for you/));
  await shoot(page, "review-approve-1");
  const openDoc = page.getByRole("button", { name: /^Open the document for / }).first();
  await openDoc.click();
  const viewer = page.getByRole("dialog", { name: /^Document: / });
  await expect(viewer).toBeVisible();
  await page.waitForTimeout(800);
  await shoot(page, "review-approve-2");
  await page.keyboard.press("Escape");
  const card = page.getByRole("button", { name: /^Approve / }).first();
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

  // ---- add-mailbox
  const automation = await settings(page, "Automation");
  const outlook = automation.getByRole("heading", { name: /Outlook/ }).first();
  await bring(page, outlook);
  await shoot(page, "add-mailbox-1");
  const email = automation.getByRole("heading", { name: /Email intake|Forward/i }).first();
  if (await email.count()) {
    await bring(page, email);
    await shoot(page, "add-mailbox-2");
  }
  await page.goto("/files");
  const sys = main(page).getByText("_System").first();
  await bring(page, sys, 300);
  await mark(sys);
  await shoot(page, "add-mailbox-3");

  // ---- reconcile-bank
  await page.goto("/bank");
  await expect(page.getByText("Reconciled to date").first()).toBeVisible();
  await shoot(page, "reconcile-bank-1");
  const reconcile = page.getByRole("tab", { name: "Reconcile" });
  await reconcile.click();
  const confirm = page.getByRole("button", { name: /^Confirm/ }).first();
  await expect(confirm).toBeVisible();
  await bring(page, confirm, 360);
  await mark(confirm);
  await shoot(page, "reconcile-bank-2");
  await page.getByRole("tab", { name: "Rules" }).click();
  await page.waitForTimeout(800);
  await shoot(page, "reconcile-bank-3");

  // ---- vat-return
  await page.goto("/vat");
  const group = page.getByRole("radiogroup", { name: "VAT period" });
  await group.getByRole("radio", { name: "Jul–Sep 2026" }).click();
  const ret = page.getByRole("region", { name: /Your return/ });
  await expect(ret).toContainText("Your return · Jul–Sep 2026");
  await bring(page, ret.getByText("Your return · Jul–Sep 2026"), 130);
  await shoot(page, "vat-return-1");
  await soft("vat-return-2", async () => {
    const row = ret.getByRole("row").filter({ hasText: "VAT reclaimed on purchases" });
    const open = row.getByRole("button").first();
    await open.click();
    await page.waitForTimeout(1000);
    await shoot(page, "vat-return-2");
    await page.keyboard.press("Escape");
  });
  if (!/\/vat$/.test(page.url())) await page.goto("/vat");
  const hmrc = page.getByRole("region", { name: "Connect to HMRC" });
  await bring(page, hmrc, 120);
  await mark(hmrc.getByRole("button", { name: "Connect to HMRC (simulated)" }));
  await shoot(page, "vat-return-3");
  await hmrc.getByRole("button", { name: "Connect to HMRC (simulated)" }).click();
  await hmrc.getByRole("button", { name: "Show obligations" }).click();
  await expect(hmrc.getByRole("radio", { name: "Choose period 26A3" })).toBeChecked();
  await bring(page, hmrc, 120);
  await shoot(page, "vat-return-4");
  await hmrc.getByRole("button", { name: "Prepare submission" }).click();
  await hmrc.getByLabel("I confirm the information is true and complete").check();
  const submit = hmrc.getByRole("button", { name: "Submit (demo — simulated)" });
  await bring(page, submit, 420);
  await mark(submit);
  await shoot(page, "vat-return-5");
  await submit.click();
  const done = hmrc.getByRole("heading", { name: /Demo — submission simulated/ });
  await expect(done).toBeVisible();
  await bring(page, done, 200);
  await shoot(page, "vat-return-6");

  // ---- income-tax-update
  const business = await settings(page, "Business");
  const se = business.getByText("I am self-employed").first();
  await bring(page, se, 260);
  await mark(se);
  await shoot(page, "income-tax-update-1");
  await soft("switches", async () => {
    await business.getByRole("switch", { name: "I am self-employed" }).click();
    await business.getByLabel("I let property (landlord mode)").check();
    await page.waitForTimeout(1000);
  });
  await page.goto("/property");
  await page.waitForTimeout(1500);
  await shoot(page, "income-tax-update-2");
  await page.goto("/self-employment");
  await expect(page.getByRole("heading", { name: /Self-employment/, level: 1 })).toBeVisible();
  await mark(page.getByRole("button", { name: /Connect to HMRC for Income Tax/ }));
  await shoot(page, "income-tax-update-3");

  // ---- payroll-paye
  await page.goto("/payroll");
  await expect(page.getByRole("heading", { name: "Payroll", level: 1 })).toBeVisible();
  await soft("payroll-1", async () => {
    await page.getByRole("button", { name: "Add employee" }).click();
    const emp = page.getByRole("form", { name: "New employee" });
    await emp.getByLabel("Payroll ID").fill("E001");
    await emp.getByLabel("Forenames").fill("Tom");
    await emp.getByLabel("Surname").fill("Ellis");
    await emp.getByLabel("NI number").fill("QQ123456C");
    await emp.getByLabel("Date of birth").fill("1994-05-12");
    await emp.getByLabel("Start date").fill("2026-04-06");
    await emp.getByLabel("Annual salary £").fill("24000");
    await bring(page, page.getByRole("heading", { name: "Employees", exact: true }), 130);
    await shoot(page, "payroll-paye-1");
    await emp.getByRole("button", { name: "Save employee" }).click();
    await page.waitForTimeout(2000);
  });
  await soft("payroll-2", async () => {
    await page.getByRole("button", { name: "Calculate pay run" }).click();
    await page.waitForTimeout(2500);
    const run = page.getByRole("region", { name: /^Pay run / });
    await bring(page, (await run.count()) ? run : page.getByRole("heading", { name: "Pay runs", exact: true }), 130);
    await shoot(page, "payroll-paye-2");
  });
  await soft("payroll-3", async () => {
    await bring(page, page.getByRole("heading", { name: "RTI files (FPS and EPS)" }), 130);
    await mark(page.getByRole("button", { name: /Download FPS/ }));
    await shoot(page, "payroll-paye-3");
  });

  // ---- invite-accountant
  const acct = await settings(page, "Your accountant");
  await shoot(page, "invite-accountant-1");
  const emailBox = acct.getByRole("textbox").first();
  await emailBox.fill("alex@harbourlane-accounts.example");
  await mark(emailBox);
  await shoot(page, "invite-accountant-2");


  // ---- export-accountant
  await page.goto("/reports/exports");
  await expect(page.getByRole("heading", { name: "Reports & exports", level: 1 })).toBeVisible();
  await shoot(page, "export-accountant-1");
  const taxes = page.getByRole("heading", { name: "Taxes and balances", level: 2 });
  await bring(page, taxes);
  await shoot(page, "export-accountant-2");
  const yourData = await settings(page, "Your data");
  await mark(yourData.getByRole("heading", { name: "Export your data", exact: true }));
  await shoot(page, "export-accountant-3");

  // ---- contacts (import-contacts)
  await page.goto("/contacts");
  await expect(page.getByText("Possible duplicates").first()).toBeVisible();
  await mark(page.getByRole("button", { name: "Import contacts" }).first());
  await shoot(page, "import-contacts-1");
  await page.getByRole("button", { name: "Import contacts" }).first().click();
  const panel = page.getByRole("region", { name: "Import contacts" });
  await expect(panel.getByRole("list", { name: "Contacts to import" }).getByRole("listitem").first()).toBeVisible();
  await bring(page, panel, 120);
  await shoot(page, "import-contacts-2");
  await panel.getByRole("button", { name: "Clear" }).click();
  const first = panel.getByRole("list", { name: "Contacts to import" }).getByRole("listitem").first();
  await first.getByRole("checkbox").check();
  await mark(panel.getByRole("button", { name: "Import 1" }));
  await shoot(page, "import-contacts-3");
  await panel.getByRole("tab", { name: "People who email you" }).click();
  await expect(panel.getByText(/emailed you in the last 180 days/)).toBeVisible();
  await shoot(page, "import-contacts-4");
  await panel.getByRole("button", { name: "Close" }).click();
  const dup = page.getByText("Possible duplicates").first();
  await bring(page, dup, 160);
  await shoot(page, "import-contacts-5");

  // ---- goals
  await page.goto("/goals");
  await expect(page.getByRole("heading", { name: "Goals & progress", level: 1 })).toBeVisible();
  await expect(page.getByRole("article").first()).toBeVisible();
  await shoot(page, "goals-1");
  await page.getByRole("button", { name: "+ Add a goal" }).click();
  const form = page.getByRole("form", { name: "Add a goal" });
  await form.getByRole("radio", { name: /Save for something/ }).check();
  await form.getByLabel("Name", { exact: true }).fill("New van deposit");
  await form.getByLabel("Amount to save (£)").fill("3,000");
  await form.getByLabel("By", { exact: true }).fill("2027-03-31");
  await bring(page, form, 120);
  await mark(form.getByRole("button", { name: "Add goal" }));
  await shoot(page, "goals-2");
  await form.getByRole("button", { name: "Add goal" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Goal added: New van deposit." })).toBeVisible();
  const note = page.locator("[data-goals-note]");
  await bring(page, note, 160);
  await page.waitForTimeout(1500);
  await shoot(page, "goals-3");
  const van = page.getByRole("article", { name: "New van deposit" });
  await van.getByRole("button", { name: "View details" }).click();
  const details = page.getByRole("region", { name: "New van deposit details" });
  await details.getByLabel("Record money put aside (£)").fill("250");
  await bring(page, details, 160);
  await mark(details.getByRole("button", { name: "Record" }));
  await shoot(page, "goals-4");
  await page.goto("/");
  const homeGoals = page.locator("[data-home-goals]");
  await expect(homeGoals.getByRole("article").first()).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(1500);
  await bring(page, homeGoals, 120);
  await shoot(page, "goals-5");

  // ---- calendar
  await page.goto("/");
  const deadlines = page.getByRole("region", { name: "Deadlines" });
  await bring(page, deadlines, 120);
  const addOne = deadlines.getByRole("button", { name: /^Add to calendar: / }).first();
  await mark(addOne);
  await shoot(page, "calendar-1");
  await page.goto("/calendar");
  await expect(page.getByRole("heading", { name: "Calendar", level: 1 })).toBeVisible();
  const sync = page.locator("[data-calendar-sync]");
  await mark(sync.getByRole("button", { name: "Add to calendar" }));
  await shoot(page, "calendar-2");
  await sync.getByRole("button", { name: "Add to calendar" }).click();
  await expect(sync).toContainText(/Done: \d+ added/);
  await mark(sync.getByRole("switch", { name: "Add all deadlines to my calendar automatically" }));
  await shoot(page, "calendar-3");
  await page.getByRole("button", { name: "+ Add an event" }).click();
  const ev = page.getByRole("form", { name: "Add an event" });
  await ev.getByLabel("Title").fill("Call with the accountant");
  await ev.getByLabel("Date").fill("2026-10-28");
  await ev.getByLabel("Time (leave empty for all day)").fill("09:30");
  await ev.getByRole("button", { name: "Add to calendar" }).click();
  const clash = ev.locator("[data-clash]");
  await expect(clash).toContainText("Clashes with");
  await bring(page, ev, 120);
  await mark(clash);
  await shoot(page, "calendar-4");
  await clash.getByRole("button", { name: "Cancel" }).click();

  // ---- notes and voice (voice-chat, notes-tasks)
  await page.goto("/");
  const drawer = await openAssistant(page);
  await mark(drawer.getByRole("button", { name: "Hands-free" }));
  await shoot(page, "voice-chat-1");
  await drawer.getByLabel("Your question").fill("How much VAT do I owe and why?");
  await drawer.getByRole("button", { name: "Send" }).click();
  await expect(drawer.getByRole("article").last()).toContainText(/Numbers by code|numbers by code/, { timeout: 30_000 });
  await shoot(page, "voice-chat-2");
  await drawer.getByLabel("Your question").fill("take a note: ring the scaffolder about Friday");
  await drawer.getByRole("button", { name: "Send" }).click();
  const noteCard = drawer.getByRole("article", { name: "Proposed: Note" });
  await expect(noteCard).toContainText("Ring the scaffolder about Friday", { timeout: 30_000 });
  await mark(noteCard.getByRole("button", { name: "Approve" }));
  await shoot(page, "notes-tasks-1");
  await noteCard.getByRole("button", { name: "Approve" }).click();
  await expect(noteCard.getByRole("status")).toContainText("Saved");
  await drawer.getByLabel("Your question").fill("add a meeting with Hartwell tomorrow at 10");
  await drawer.getByRole("button", { name: "Send" }).click();
  const evCard = drawer.getByRole("article", { name: "Proposed: Add to calendar" });
  await expect(evCard).toContainText("Meeting with Hartwell", { timeout: 30_000 });
  await shoot(page, "notes-tasks-2");
  await page.keyboard.press("Escape");
  await page.goto("/notes");
  await expect(page.getByRole("list", { name: "Your notes" })).toContainText("Ring the scaffolder about Friday");
  await shoot(page, "notes-tasks-3");
  await page.goto("/ask");
  await page.waitForTimeout(1500);
  await shoot(page, "voice-chat-3");
});

test("personal demo", async ({ page }) => {
  test.setTimeout(SEED_WAIT + 300_000);
  await startDemo(page, "personal");
  await expect(main(page).getByRole("heading", { name: /^This month/ })).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(1500);
  await shoot(page, "personal-finances-1");
  const budgets = page.getByRole("region", { name: "Budgets this month" });
  await bring(page, budgets, 120);
  await shoot(page, "personal-finances-2");
  await page.goto("/personal");
  await page.waitForTimeout(2000);
  await shoot(page, "personal-finances-4");
  await page.goto("/goals");
  await expect(page.getByRole("article").first()).toBeVisible();
  await shoot(page, "personal-finances-5");

});
