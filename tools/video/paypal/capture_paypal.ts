/**
 * PayPal hackathon video: live footage of https://accnomos.com in "Try the demo" (fictional books), one WebM per shot
 * (1920 x 1080, 30 fps, Chromium's own compositor) plus <shot>.marks.json (named moments in seconds, for the edit).
 * Same helpers as tools/video/v3/capture_live.ts. Script and click paths: docs/submission/paypal/VIDEO_SCRIPT.md and
 * SHOT_LIST.md. Nothing is faked: a screen that is not there ends the shot with an error in its marks file.
 *
 *   PW_FROM=apps/web node tools/video/paypal/capture_paypal.ts OUTDIR [shot,shot,...]
 * Hero shots: pp-sync, pp-grid (Power grid; GRID_APPROVE=1 really approves the ticked rows), pp-ask, pp-billpay,
 * pp-disputes (pp-invoice, pp-vat as inserts). Montage: m-review, m-bank, m-quotes, m-vat, m-reports, m-jobs, m-payroll,
 * m-upcoming, m-support (files, voice, day plan and Android are filmed by hand). Blur model bylines in the edit (docs/submission/paypal/SHOT_LIST.md).
 * Env: PW_FROM (a folder whose node_modules has playwright or @playwright/test), SITE (default https://accnomos.com),
 * PAYPAL_CONNECT=1 (connect PayPal in test mode in the demo copy first: needs PAYPAL_DIRECT=1 on the server),
 * PAY=1 (pp-billpay presses "Pay £…": a real sandbox payout; without it the shot ends on the confirmation),
 * GAP_MS (pause between shots for the live API's per-IP limit, default 25 s), DEMO_WAIT_MS (default 12 s),
 * CHROME (a Chromium binary, if Playwright's own is missing), HTTPS_PROXY (passed to Chromium when set, for a sandboxed
 * agent), CALLBACK_HOST (e.g. https://api.accnomos.com: if the server's PayPal connect sends the browser to its internal
 * http://127.0.0.1:8780 address, the browser is sent to this host instead; seen on the live server 11 Nov 2026),
 * SYNC_FIRST=1 (press Sync PayPal off camera before the shot: pp-tieout, pp-grid).
 * The PayPal checkout (scene p3) and the signed-in sandbox scenes (p4 with real payments, p5 tie-out, p8) are filmed by
 * hand: they need the owner's sign-in and the sandbox buyer, whose credentials never go in the repo.
 */
import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { CURSOR_SCRIPT, CLEAN_CSS, Human } from "../lib/human.ts";
import { Recorder } from "../lib/recorder.ts";

const req = createRequire(path.join(process.env.PW_FROM ?? process.cwd(), "package.json"));
let pw: any;
try { pw = req("@playwright/test"); } catch { pw = req("playwright"); }
const { chromium } = pw;

const SITE = process.env.SITE ?? "https://accnomos.com";
const OUT = path.resolve(process.argv[2] ?? "raw-paypal");
const ONLY = process.argv[3] ? new Set(process.argv[3].split(",")) : null;
mkdirSync(OUT, { recursive: true });

type Ctx = { page: any; h: Human; mark: (n: string) => void };
type Shot = { setup?: (c: Ctx) => Promise<void>; run: (c: Ctx) => Promise<void> };

const vis = (l: any) => l.filter({ visible: true }).first();
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
async function settle(page: any, ms = 600) {
  await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => undefined);
  await page.waitForTimeout(ms);
}
/** The live API rate-limits per IP: if a page says so, wait and load it again (off camera). */
async function unthrottled(page: any) {
  for (let i = 0; i < 6; i++) {
    const busy = await page.getByText(/Too many requests|Couldn.t (finish|load)/).first().isVisible().catch(() => false);
    if (!busy) return;
    console.log("  rate-limited, waiting");
    await sleep(20_000);
    await page.reload();
    await settle(page, 1500);
  }
}
async function go(page: any, p: string) {
  await page.goto(SITE + p);
  await settle(page, 1200);
  await unthrottled(page);
  await page.evaluate(() => window.scrollTo(0, 0));
}
async function hoverText(c: Ctx, t: string | RegExp, dwell = 900, within?: any) {
  const l = vis((within ?? c.page).getByText(t));
  if (await l.isVisible().catch(() => false)) await c.h.hover(l, dwell);
}
/** Scroll a region to ~120 px below the top, off camera. */
async function toRegion(page: any, name: string) {
  const r = page.getByRole("region", { name, exact: true }).first();
  await r.waitFor({ timeout: 30_000 });
  await r.evaluate((e: Element) => window.scrollTo(0, e.getBoundingClientRect().top + window.scrollY - 120));
  await page.waitForTimeout(500);
  return r;
}

/** The live server's connect callback can point at its internal address (PAYPAL_RETURN_URL unset): follow it on the public host. */
async function fixCallback(page: any) {
  const host = process.env.CALLBACK_HOST;
  if (!host) return;
  await page.route(/^http:\/\/127\.0\.0\.1:8780\//, (r: any) =>
    r.fulfill({ status: 302, headers: { location: r.request().url().replace("http://127.0.0.1:8780", host) } }));
}
/** Press Sync PayPal off camera, so a shot opens on the synced panel. */
async function syncOffCamera(page: any) {
  await go(page, "/invoices");
  const panel = page.locator('section[aria-label="PayPal"]').first();
  await panel.getByRole("button", { name: "Sync PayPal" }).first().click();
  await panel.getByRole("status").first().waitFor({ timeout: 90_000 }).catch(() => undefined);
  await settle(page, 1500);
}

/** Settings › Online payments → "Connect PayPal (test mode)": in direct mode the server sends the browser straight back. */
async function connectPayPal(page: any) {
  await go(page, "/settings#settings-payments");
  const btn = page.getByRole("button", { name: /^Connect PayPal/ }).first();
  if (!(await btn.isVisible({ timeout: 8000 }).catch(() => false))) {
    console.log("  PayPal: no Connect button (already connected, or PayPal not set up on the server)");
    return;
  }
  await btn.click();
  // The page is already on /settings, so wait for the round trip's result rather than the URL.
  await page.getByText(/^Connected:/).first().waitFor({ timeout: 60_000 }).catch(() => undefined);
  await settle(page, 1500);
  console.log("  PayPal connected:", await page.getByText(/^Connected:/).first().isVisible().catch(() => false));
}

const SHOTS: Record<string, Shot> = {
  // p2: Add payment link → Paid into PayPal → Make payment link → the link
  "pp-invoice": {
    setup: async ({ page }) => { await go(page, "/invoices"); },
    run: async (c) => {
      const { page, h } = c;
      await h.park(800, 250);
      const add = vis(page.getByRole("button", { name: "Add payment link" }));
      await h.scrollIntoView(add, 900);
      await h.click(add, 600);
      const dlg = page.getByRole("dialog");
      const paypal = vis(dlg.getByRole("radio", { name: /^PayPal$/ }).or(dlg.getByLabel(/^PayPal$/)));
      if (await paypal.isVisible({ timeout: 5000 }).catch(() => false)) await h.click(paypal, 500);
      const make = vis(dlg.getByRole("button", { name: "Make payment link" }));
      c.mark("make");
      await h.click(make, 300);
      c.mark("wait");
      await vis(dlg.getByLabel("Payment link", { exact: true })).waitFor({ timeout: 60_000 });
      c.mark("ready");
      await h.hover(vis(dlg.getByLabel("Payment link", { exact: true })), 1800);
      await h.hold(800);
    },
  },
  // p4 (demo fallback, or the shared sandbox with PAYPAL_CONNECT=1): Sync PayPal → proposals → VAT on a sale → Approve
  "pp-sync": {
    setup: async ({ page }) => { await go(page, "/invoices"); await toRegion(page, "PayPal"); },
    run: async (c) => {
      const { page, h } = c;
      const panel = page.locator('section[aria-label="PayPal"]').first();
      await h.park(900, 220);
      await hoverText(c, /waits for your approval/, 1000, panel);
      await hoverText(c, /Sample PayPal history/, 1200, panel);
      c.mark("sync");
      await h.click(vis(panel.getByRole("button", { name: "Sync PayPal" })), 300);
      c.mark("wait");
      await vis(panel.getByRole("status")).waitFor({ timeout: 90_000 });
      c.mark("ready");
      await h.hover(vis(panel.getByRole("status")), 1500);
      const list = panel.getByRole("list", { name: "PayPal transactions waiting for approval" });
      const inv = vis(list.getByRole("listitem").filter({ hasText: /^Invoice payment/ }));
      if (await inv.isVisible({ timeout: 5000 }).catch(() => false)) {
        await h.scrollIntoView(inv, 900);
        await hoverText(c, /PayPal fee/, 1500, inv);
        await hoverText(c, /^Pays invoice/, 1200, inv);
      }
      // The sale with no invoice in the books (SALE_MATCH picks one, e.g. "DEMO-1002"): choose its VAT
      const sale = vis(list.getByRole("listitem").filter({ hasText: /^Sale/ }).filter({ hasText: process.env.SALE_MATCH ?? /./ }));
      const vatSel = vis(sale.getByLabel(/VAT on this sale/).or(panel.getByLabel(/VAT on this sale/)));
      if (await vatSel.isVisible({ timeout: 3000 }).catch(() => false)) {
        await h.scrollIntoView(sale, 900);
        await hoverText(c, /PayPal fee/, 1400, sale);
        await hoverText(c, /choose its VAT/, 1200, sale);
        await h.scrollIntoView(vatSel, 700);
        await h.hover(vatSel, 600);
        await vatSel.selectOption("S");
        c.mark("vat");
        await h.hold(1200);
      }
      const target = (await inv.isVisible().catch(() => false)) ? inv : sale;
      if (await target.isVisible().catch(() => false)) {
        const approve = vis(target.getByRole("button", { name: /^Approve £/ }));
        await h.scrollIntoView(approve, 800);
        c.mark("approve");
        await h.click(approve, 300);
        await vis(panel.getByText(/is in your books/)).waitFor({ timeout: 60_000 }).catch(() => undefined);
        c.mark("approved");
      }
      await hoverText(c, /PayPal says/, 2000, panel); // the tie-out, only when PayPal is really connected
      await h.hold(1500);
    },
  },
  // p6: Purchases → Pay bills with PayPal → Due today → Approve payment → confirmation (→ Pay with PAY=1)
  "pp-billpay": {
    setup: async ({ page }) => {
      await go(page, "/purchases");
      const hd = page.getByRole("heading", { name: "Pay bills with PayPal" }).first();
      await hd.waitFor({ timeout: 30_000 });
      await hd.evaluate((e: Element) => window.scrollTo(0, e.getBoundingClientRect().top + window.scrollY - 100));
      await page.waitForTimeout(600);
    },
    run: async (c) => {
      const { page, h } = c;
      await h.park(900, 200);
      await hoverText(c, /^Due today$/, 1000);
      const approve = vis(page.getByRole("button", { name: /^Approve payment$|^Try again$/ }));
      if (!(await approve.isVisible({ timeout: 5000 }).catch(() => false))) {
        await hoverText(c, /No bill is due for PayPal today|Connect PayPal in Settings/, 2000);
        c.mark("empty"); // no bill due today with a PayPal email: see SHOT_LIST.md, Bill pay (re-shoot)
        await hoverText(c, /^Upcoming PayPal payments$/, 1500);
        await h.scrollBy(260, 1200);
        await h.hold(1500);
        throw new Error("no bill due today with a PayPal email: see SHOT_LIST.md, Bill pay");
      }
      await h.click(approve, 600);
      await hoverText(c, /from your PayPal account now\?/, 1800);
      const pay = vis(page.getByRole("button", { name: /^Pay £/ }));
      await h.hover(pay, 800);
      if (process.env.PAY === "1") {
        c.mark("pay");
        await h.click(pay, 300);
        c.mark("wait");
        await vis(page.getByText(/Paid and posted|PayPal is processing it|Waiting for the supplier to claim it|Not paid/)).waitFor({ timeout: 90_000 }).catch(() => undefined);
        c.mark("ready");
        // PayPal answered SUCCESS in about 30 s in the sandbox (11 Nov 2026); Accnomos checks again when Purchases opens
        for (let i = 0; i < 4 && !(await page.getByText("Paid and posted").first().isVisible().catch(() => false)); i++) {
          await sleep(15_000);
          await page.reload();
          await settle(page, 1500);
          await page.getByRole("heading", { name: "Pay bills with PayPal" }).first().scrollIntoViewIfNeeded().catch(() => undefined);
        }
        c.mark("paid");
        await hoverText(c, /Paid and posted|PayPal is processing it|Waiting for the supplier to claim it/, 2000);
      }
      await hoverText(c, /Upcoming|Add to calendar/, 1500); // the schedule, where deployed
      await h.hold(1200);
    },
  },
  // p7: PayPal disputes (the demo's SAMPLE dispute) → Build evidence → preview → Send to PayPal (demo)
  "pp-disputes": {
    setup: async ({ page }) => { await go(page, "/invoices"); await toRegion(page, "PayPal disputes"); },
    run: async (c) => {
      const { page, h } = c;
      const panel = page.locator('section[aria-label="PayPal disputes"]').first();
      await h.park(900, 220);
      await hoverText(c, /Waiting for your answer/, 1000, panel);
      await hoverText(c, /answer by/, 1000, panel);
      c.mark("build");
      await h.click(vis(panel.getByRole("button", { name: "Build evidence" })), 300);
      c.mark("wait");
      const preview = vis(panel.getByText("Response for PayPal (preview)"));
      await preview.waitFor({ timeout: 180_000 });
      c.mark("ready"); // the byline under this heading may name a model: blur it in the edit
      await h.scrollIntoView(preview, 900);
      await h.hover(preview, 1200);
      await h.scrollBy(260, 1400);
      await h.hold(1200);
      const send = vis(panel.getByRole("button", { name: "Send to PayPal (demo)" }));
      await h.scrollIntoView(send, 800);
      await h.click(send, 300);
      await vis(page.getByText(/Nothing was sent to PayPal/)).waitFor({ timeout: 60_000 }).catch(() => undefined);
      c.mark("sent");
      await hoverText(c, /Nothing was sent to PayPal/, 2200);
    },
  },
  // ag: the Power grid (AG Grid Community): tick waiting PayPal rows, totals, Approve selected; then a plain-words filter
  "pp-grid": {
    setup: async ({ page }) => {
      await page.evaluate(() => window.localStorage.setItem("accnomos.powergrid.show", "1")); // Settings › Business › Power grid
      await go(page, "/invoices");
      await toRegion(page, "PayPal");
    },
    run: async (c) => {
      const { page, h } = c;
      const grid = vis(page.getByRole("grid").or(page.locator(".ag-root")));
      await grid.waitFor({ timeout: 30_000 });
      await h.park(900, 240);
      // Tick up to three waiting rows that can be approved as they are (not a sale still waiting for its VAT choice)
      // (AG Grid 34 puts body rows in .ag-grid-scrolling-container; the totals row is row-index "b-0")
      const rows = page.locator(".ag-row[row-index]");
      const picks: any[] = [];
      const seen = new Set<string>();
      for (let i = 0; i < (await rows.count()) && picks.length < 3; i++) {
        const row = rows.nth(i);
        const idx = (await row.getAttribute("row-index")) ?? "";
        if (idx.startsWith("b") || seen.has(idx)) continue;
        seen.add(idx);
        if (/Choose the VAT/.test(await row.innerText().catch(() => ""))) continue;
        if (!(await row.locator(".ag-checkbox-input:not([disabled])").count())) continue;
        picks.push(row.locator(".ag-selection-checkbox").first());
      }
      await h.scrollIntoView(grid, 800);
      for (const box of picks) await h.click(box, 350);
      const n = picks.length;
      await hoverText(c, /^Total of \d+ shown/, 1200);
      const approve = vis(page.getByRole("button", { name: /^Approve selected/ }));
      if (n > 0 && process.env.GRID_APPROVE === "1") {
        page.once("dialog", (d: any) => d.accept());
        c.mark("approve");
        await h.click(approve, 300);
        const confirm = vis(page.getByRole("dialog").getByRole("button", { name: /^Approve/ }));
        if (await confirm.isVisible({ timeout: 2000 }).catch(() => false)) await h.click(confirm, 300);
        await page.waitForTimeout(5000);
        c.mark("approved");
        await h.hold(1500);
      } else {
        await h.hover(approve, 1200);
      }
      await go(page, "/reports/ledger-grid");
      await page.getByText("Opening the ledger explorer").first().waitFor({ state: "detached", timeout: 30_000 }).catch(() => undefined);
      c.mark("explorer");
      const box = vis(page.getByLabel(/Describe the lines you want to see/).or(page.getByPlaceholder(/Describe the lines/)));
      await h.type(box, process.env.GRID_Q ?? "PayPal fees over £5", 300);
      await h.click(vis(page.getByRole("button", { name: "Filter", exact: true })), 300);
      c.mark("wait");
      await page.getByText("Working it out…").first().waitFor({ state: "detached", timeout: 90_000 }).catch(() => undefined);
      c.mark("ready");
      await h.hold(900);
      await h.scrollBy(280, 1000);
      await h.hold(2500);
    },
  },
  // h2: Ask the PayPal questions (answered by code from the books' PayPal entries; blur the byline in the edit)
  "pp-ask": {
    setup: async ({ page }) => { await go(page, "/ask"); },
    run: async (c) => {
      const { page, h } = c;
      await h.park(700, 300);
      // v4 (checked live 11 Nov 2026 on a demo WITHOUT PayPal connected: the sample history answers £492.00 / £97.79)
      const qs = [
        process.env.ASK_Q1 ?? "Did that client pay all the arrears? They had around £500 overdue — check PayPal.",
        process.env.ASK_Q2 ?? "There was a payment via PayPal last month, probably around £100 for stationery — how much exactly was it?",
      ];
      for (const [i, q] of qs.entries()) {
        await h.type(vis(page.getByLabel(/Ask your books/)), q, 300);
        await h.click(vis(page.getByRole("button", { name: "Ask", exact: true })), 200);
        c.mark(`wait${i + 1}`);
        await page.getByText(ANSWERED).nth(i).waitFor({ timeout: 180_000 });
        await page.waitForTimeout(600);
        c.mark(`ready${i + 1}`);
        const ans = page.getByText(ANSWERED).nth(i);
        await ans.evaluate((e: Element) => e.closest("li,article,section,div")?.scrollIntoView({ block: "end", behavior: "smooth" })).catch(() => undefined);
        await h.hold(3200);
      }
    },
  },
  // h3: the tie-out at the top of the PayPal panel (only when PayPal is really connected: PAYPAL_CONNECT=1 SYNC_FIRST=1)
  "pp-tieout": {
    setup: async ({ page }) => { await go(page, "/invoices"); await toRegion(page, "PayPal"); await page.evaluate(() => window.scrollBy(0, -140)); },
    run: async (c) => {
      const { page, h } = c;
      await h.park(700, 200);
      await h.hold(600);
      const says = vis(page.getByText(/^PayPal says/));
      await says.waitFor({ timeout: 20_000 });
      await h.hover(says, 1600);
      await hoverText(c, /\(as of/, 1800);
      await hoverText(c, /^Difference/, 2600);
      await hoverText(c, /refreshes this balance/, 1800);
      await h.hold(800);
    },
  },
  ...montage(),
  // p8: the VAT return's Box 1 and Box 6
  "pp-vat": {
    setup: async ({ page }) => { await go(page, "/vat"); await page.waitForTimeout(3000); },
    run: async (c) => {
      await c.h.park(900, 250);
      await hoverText(c, /^Box 1\b/, 1500);
      await hoverText(c, /^Box 6\b/, 1800);
      await c.h.hold(1000);
    },
  },
};

/** An Ask answer is in: worded by a model (checked) or worked out by code alone. */
const ANSWERED = /explanation by |^Worked out by code/;

/** Montage: about 3 s of footage per screen (the edit trims), each a plain look at a page that exists. */
function montage(): Record<string, Shot> {
  const look = (route: string, focus: (string | RegExp)[] = [], scroll = 0): Shot => ({
    setup: async ({ page }) => { await go(page, route); await page.waitForTimeout(2500); },
    run: async (c) => {
      await c.h.park(800, 260);
      await c.h.hold(700);
      for (const t of focus) await hoverText(c, t, 900);
      if (scroll) await c.h.scrollBy(scroll, 900);
      await c.h.hold(1200);
    },
  });
  return {
    "m-files": look("/files", [/Books\.xlsx/]),
    "m-home": look("/", [/^Upcoming PayPal payments$/]),
    "m-talk": {
      setup: async ({ page }) => { await go(page, "/review"); await page.waitForTimeout(1500); },
      run: async (c) => {
        await c.h.park(800, 300);
        await c.h.click(vis(c.page.getByRole("button", { name: "Talk to Accnomos" })), 700);
        await hoverText(c, /Ask by voice/, 1500);
        const mic = vis(c.page.getByRole("button", { name: "Ask by voice" }));
        if (await mic.isVisible().catch(() => false)) await c.h.hover(mic, 1500);
        await c.h.hold(800);
      },
    },
    "m-review": look("/review", [/waiting for you/]),
    "m-bank": look("/bank", [/^Bank feed/, /matched/i], 250),
    "m-quotes": look("/sales/quotes", [], 150),
    "m-vat": look("/vat", [/^Box 1\b/, /^Box 6\b/]),
    "m-reports": look("/reports/profit-and-loss", [], 200),
    "m-jobs": look("/jobs", [], 150),
    "m-payroll": look("/payroll", [], 150),
    "m-upcoming": look("/purchases", [/^Upcoming PayPal payments$/, /Download all \(\.ics\)|^Calendar$/]),
    "m-support": look("/support", [], 150),
  };
}

async function demoSession(page: any) {
  await page.goto(`${SITE}/judges`);
  await page.getByRole("button", { name: "Start the demo" }).click();
  await page.waitForURL(/\/(review|$)/, { timeout: 120_000 }).catch(() => undefined);
  await page.waitForTimeout(Number(process.env.DEMO_WAIT_MS ?? 12_000)); // the demo books take ~10 s to build
}

let first = true;
for (const [id, shot] of Object.entries(SHOTS)) {
  if (ONLY && !ONLY.has(id)) continue;
  if (!first) await sleep(Number(process.env.GAP_MS ?? 25_000));
  first = false;
  const browser = await chromium.launch({
    ...(process.env.CHROME ? { executablePath: process.env.CHROME } : {}),
    ...(process.env.HTTPS_PROXY ? { proxy: { server: process.env.HTTPS_PROXY } } : {}),
  });
  try {
    const context = await browser.newContext({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 2, locale: "en-GB", timezoneId: "Europe/London" });
    await context.addInitScript(CURSOR_SCRIPT);
    await context.addInitScript(`(() => { const s = document.createElement('style'); s.textContent = ${JSON.stringify(CLEAN_CSS)}; (document.head || document.documentElement).appendChild(s); })()`);
    const page = await context.newPage();
    const h = new Human(page);
    await fixCallback(page);
    await demoSession(page);
    if (process.env.PAYPAL_CONNECT === "1") await connectPayPal(page);
    if (process.env.SYNC_FIRST === "1") await syncOffCamera(page);
    const marks: Record<string, number> = {};
    let t0 = 0;
    const ctx: Ctx = { page, h, mark: (n) => { marks[n] = Date.now() / 1000 - t0; } };
    await shot.setup?.(ctx);
    const rec = new Recorder(context, page, { width: 1920, height: 1080 });
    await rec.start(path.join(OUT, `.frames-${id}`));
    t0 = Date.now() / 1000;
    let err = "";
    try { await shot.run(ctx); } catch (e) { err = String(e).slice(0, 400); console.log(id, "RUN ERROR", err); }
    const secs = await rec.stop(path.join(OUT, `${id}.webm`));
    writeFileSync(path.join(OUT, `${id}.marks.json`), JSON.stringify({ secs, marks, err }, null, 1));
    console.log(id, secs.toFixed(1), "s", JSON.stringify(marks), err ? "ERR" : "ok");
  } catch (e) {
    console.log(id, "FAILED", String(e).slice(0, 400));
  } finally {
    await browser.close();
  }
}
console.log("CAPTURE_DONE");
