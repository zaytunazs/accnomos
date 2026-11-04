/**
 * Demo video v3 (v2 plus the in-app model switch and the Ask showcase): live footage of https://accnomos.com ("Try the demo": Bramblewood Joinery; personal demo: the
 * Harrison household), real Meta models answering. One WebM per shot (1920 x 1080, 30 fps, from Chromium's own
 * compositor) plus <shot>.marks.json: named moments in seconds from the start of the recording, which edit.py uses
 * to cut out the seconds a live model takes ("wait" .. "ready").
 *
 *   node capture_live.ts OUTDIR [shot,shot,...]
 * v3 shots: w-route (Settings › AI: Local model only → Ask → "explanation by Glimmer 30B"; then Meta Model API first →
 * the same question → "explanation by Muse Spark"), w-profit, w-timesheet, w-tiles (typed in Ask).
 * Env: PW_FROM (a folder whose node_modules has playwright or @playwright/test), FAKE_MIC (a WAV for the
 * voice shot), SITE (default https://accnomos.com), RECEIPT (the sample receipt PNG).
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
const API = process.env.API ?? "https://api.accnomos.com";
const OUT = path.resolve(process.argv[2] ?? "raw");
const ONLY = process.argv[3] ? new Set(process.argv[3].split(",")) : null;
const RECEIPT = process.env.RECEIPT ?? "sample-receipt.png";
mkdirSync(OUT, { recursive: true });

type Ctx = { page: any; h: Human; mark: (n: string) => void };
type Shot = { kind?: "company" | "personal" | "none"; setup?: (c: Ctx) => Promise<void>; run: (c: Ctx) => Promise<void>; mic?: boolean };

const vis = (l: any) => l.filter({ visible: true }).first();
async function settle(page: any, ms = 600) {
  await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => undefined);
  await page.waitForTimeout(ms);
}
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
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
/** Home's summary is written by the live model: wait (off camera) until it is in words. */
async function homeReady(page: any) {
  await vis(page.getByText("Your summary")).waitFor({ timeout: 60_000 });
  await page.getByText(/putting this into words/).first().waitFor({ state: "detached", timeout: 90_000 }).catch(() => undefined);
  await page.waitForTimeout(800);
  await unthrottled(page);
  await page.getByText(/putting this into words/).first().waitFor({ state: "detached", timeout: 90_000 }).catch(() => undefined);
}
async function sidebar(c: Ctx, name: string | RegExp) {
  await c.h.click(vis(c.page.getByRole("link", { name })), 900);
}
async function settingsTab(c: Ctx, name: string) {
  await c.h.click(vis(c.page.getByRole("button", { name, exact: true }).or(c.page.getByRole("tab", { name, exact: true }))), 1000);
}
/** Glide to a visible element without scrolling the page (for a screen that should stay put). */
async function point(c: Ctx, t: string | RegExp, dwell = 900) {
  const l = vis(c.page.getByText(t));
  const box = await l.boundingBox().catch(() => null);
  const vp = c.page.viewportSize();
  if (!box || box.y < 0 || box.y > vp.height - 20) return;
  await c.h.moveTo(box.x + Math.min(box.width * 0.5, 160), box.y + box.height / 2);
  await c.h.hold(dwell);
}
async function hoverText(c: Ctx, t: string | RegExp, dwell = 900) {
  const l = vis(c.page.getByText(t));
  if (await l.isVisible().catch(() => false)) await c.h.hover(l, dwell);
}

const SHOTS: Record<string, Shot> = {
  // s1/s3: Home, the AI summary in order, one button per item
  "w-home": {
    setup: async ({ page }) => { await go(page, "/"); await homeReady(page); },
    run: async (c) => {
      const { page, h } = c;
      await h.park(900, 140);
      await h.hold(1000);
      for (const t of [/^VAT return/, /invoices overdue/, /items waiting for your approval/, /Put aside for the VAT bill/, /bank lines to match/]) await point(c, t, 1100);
      await h.scrollBy(140, 900);
      await point(c, /worded by your AI/, 1800);
      await h.hold(600);
    },
  },
  "w-home-action": {
    setup: async ({ page }) => { await go(page, "/"); await homeReady(page); },
    run: async (c) => {
      const { page, h } = c;
      await h.park(700, 300);
      await point(c, /items waiting for your approval/, 900);
      c.mark("click");
      await h.click(vis(page.getByRole("link", { name: /^Review/ }).or(page.getByRole("button", { name: /^Review →|^Review$/ })).filter({ hasText: "→" })), 300);
      await vis(page.getByRole("heading", { level: 1, name: "Review" })).waitFor({ timeout: 30_000 });
      await settle(page, 300);
      await hoverText(c, /waiting for you/, 1500);
    },
  },
  // s2: goals with the AI note, then spending by category
  "w-goals": {
    setup: async ({ page }) => { await go(page, "/goals"); await page.waitForTimeout(12_000); },
    run: async (c) => {
      const { page, h } = c;
      await h.park(800, 200);
      await h.hold(800);
      for (const t of ["Put aside for the VAT bill", "Keep utilities in budget", "November sales"]) await hoverText(c, t, 1000);
      const note = vis(page.getByRole("heading", { name: "What your goals are telling you" }));
      await h.scrollIntoView(note, 900);
      await h.hover(note, 2500);
      await h.scrollBy(150, 700);
      await h.hold(1500);
    },
  },
  "w-spending": {
    // the sample books run to 30 Sep 2026, so this month's categories are empty: show the regular costs to trim
    setup: async ({ page }) => { await go(page, "/spending"); },
    run: async (c) => {
      const { page, h } = c;
      await h.park(800, 250);
      await h.hold(500);
      const reg = vis(page.getByRole("heading", { name: "Regular costs" }));
      await h.scrollIntoView(reg, 900);
      await h.hover(reg, 900);
      for (const t of [/Northgate Energy Solutions/, /Fictional Volt & Spark Energy/, /Zephyr Energy/]) await point(c, t, 900);
      await h.hold(1200);
    },
  },
  // s3: Talk, by voice (FAKE_MIC) or typed: add a calendar event, clash check, approve
  "w-talk": {
    mic: true,
    setup: async ({ page }) => { await go(page, "/"); await homeReady(page); },
    run: async (c) => {
      const { page, h } = c;
      await h.park(1000, 400);
      await h.click(vis(page.getByRole("button", { name: "Talk to Accnomos" })), 900);
      const dlg = page.getByRole("dialog");
      if (process.env.FAKE_MIC) {
        await h.moveToLocator(vis(dlg.getByRole("button", { name: "Ask by voice" })));
        await h.hold(300);
        c.mark("speak");
        await h.click(vis(dlg.getByRole("button", { name: "Ask by voice" })), 300);
      } else {
        await h.type(vis(dlg.getByLabel("Your question")), process.env.TALK_TEXT ?? "add a site visit tomorrow at 10", 300);
        await h.click(vis(dlg.getByRole("button", { name: "Send" })), 200);
      }
      c.mark("wait");
      const card = vis(dlg.getByText(/NEEDS YOUR OK|Needs your OK/i));
      await card.waitFor({ timeout: 150_000 });
      c.mark("ready");
      await h.hold(600);
      await hoverText(c, /Transcribed by/, 1200);
      await hoverText(c, /clash|free then|nothing else/i, 1200);
      await hoverText(c, /^When$/, 900);
      const approve = vis(dlg.getByRole("button", { name: "Approve" }));
      await h.hover(approve, 600);
      await h.click(approve, 300);
      c.mark("wait2");
      await vis(dlg.getByText(/Added|added to your calendar|Done/i)).waitFor({ timeout: 60_000 }).catch(() => undefined);
      c.mark("ready2");
      await h.hold(2200);
    },
  },
  // s4: Review → Add a receipt → (classify) Confirm → read by Muse Spark → Approve
  "w-receipt": {
    setup: async ({ page }) => { await go(page, "/review"); await vis(page.getByText(/waiting for you/)).waitFor({ timeout: 60_000 }); },
    run: async (c) => {
      const { page, h } = c;
      await h.park(700, 250);
      await h.hold(600);
      const add = vis(page.getByRole("button", { name: "Add a receipt" }));
      await h.moveToLocator(add);
      const fcP = page.waitForEvent("filechooser", { timeout: 10_000 }).catch(() => null);
      await h.click(add, 200);
      const fc = await fcP;
      if (fc) await fc.setFiles(RECEIPT);
      c.mark("wait");
      const confirm = vis(page.getByRole("button", { name: "Confirm" }));
      await confirm.waitFor({ timeout: 120_000 });
      c.mark("ready");
      await hoverText(c, /Looks like a receipt/, 1300);
      await h.click(confirm, 300);
      c.mark("wait2");
      const card = page.locator("section[aria-labelledby^=proposal-]").filter({ hasText: /NOVEX/i }).first();
      await card.waitFor({ timeout: 180_000 });
      await page.waitForTimeout(1500);
      c.mark("ready2");
      await h.scrollIntoView(card, 1100);
      await h.hover(vis(card.getByText(/Read by/)), 1500);
      await h.hover(vis(card.getByText(/^Net · VAT · Total/)), 1100);
      await h.hover(vis(card.getByText(/^Why:/)), 1500);
      await hoverText({ ...c, page: card } as any, /checks by code|Verifier agrees/, 1300);
      const approve = vis(card.getByRole("button", { name: /^Approve/ }));
      await h.click(approve, 400);
      await vis(page.getByText(/Approved · posted to your books|Approved/)).waitFor({ timeout: 30_000 }).catch(() => undefined);
      await h.hold(1800);
    },
  },
  // s4: typed request in Ask → priced invoice card → Approve
  "w-invoice": {
    setup: async ({ page }) => { await go(page, "/ask"); },
    run: async (c) => {
      const { page, h } = c;
      await h.park(700, 300);
      await h.hold(500);
      await h.type(vis(page.getByLabel(/Ask your books/)), "send a £450 invoice to Hartwell", 300);
      await h.click(vis(page.getByRole("button", { name: "Ask", exact: true })), 200);
      c.mark("wait");
      const card = vis(page.getByRole("article", { name: /^Proposed:/ }));
      await card.waitFor({ timeout: 150_000 });
      await page.waitForTimeout(800);
      c.mark("ready");
      await h.scrollIntoView(card, 900);
      await h.hover(card, 1600);
      const approve = vis(card.getByRole("button", { name: "Approve" }));
      await h.hover(approve, 700);
      await h.click(approve, 300);
      c.mark("wait2");
      await vis(page.getByText(/INV-|Invoice .* (created|sent)|Done/)).waitFor({ timeout: 60_000 }).catch(() => undefined);
      c.mark("ready2");
      await h.hold(2200);
    },
  },
  // s5: Reports, profit and loss, CSV export
  "w-reports": {
    setup: async ({ page }) => {
      await go(page, "/reports");
      await page.getByRole("radio", { name: /Jul.Sep 2026/ }).first().click().catch(() => undefined);
      await settle(page, 1500);
      await page.evaluate(() => window.scrollTo(0, 0));
    },
    run: async (c) => {
      const { page, h } = c;
      await h.park(800, 300);
      await point(c, /^Jul.Sep 2026$/, 700);
      const pl = vis(page.getByRole("heading", { name: /^Profit and loss/ }));
      await h.scrollIntoView(pl, 1200);
      await h.hover(pl, 1000);
      await h.scrollBy(260, 900);
      await h.hold(900);
      await h.scrollToTop(800);
      await h.click(vis(page.getByRole("button", { name: /Export to OneDrive/ })), 300);
      await vis(page.getByText(/Saved to 07 Reports/)).waitFor({ timeout: 20_000 }).catch(() => undefined);
      await hoverText(c, /Saved to 07 Reports/, 1800);
    },
  },
  // s5: VAT, nine boxes by code, Submit (simulated in the demo) → receipt
  "w-vat": {
    setup: async ({ page }) => {
      await go(page, "/vat");
      await page.getByRole("radiogroup", { name: "VAT period" }).getByRole("radio", { name: /Jul–Sep 2026/ }).click();
      await settle(page, 800);
    },
    run: async (c) => {
      const { page, h } = c;
      await h.park(700, 260);
      const ret = page.getByRole("region", { name: /Your return/ });
      await h.scrollIntoView(vis(ret.getByText("VAT due on sales")), 1000);
      for (const t of ["VAT due on sales", "VAT reclaimed on purchases", /Net VAT to pay HMRC/]) await h.hover(vis(ret.getByText(t)), 800);
      const hmrc = page.getByRole("region", { name: "Connect to HMRC" });
      await h.scrollIntoView(hmrc, 900);
      await h.click(hmrc.getByRole("button", { name: /Connect to HMRC/ }), 900);
      const obl = hmrc.getByRole("button", { name: "Show obligations" });
      if (await obl.isVisible({ timeout: 4000 }).catch(() => false)) await h.click(obl, 900);
      await h.click(vis(hmrc.getByRole("button", { name: "Prepare submission" })), 900);
      await h.click(vis(hmrc.getByLabel(/I confirm the information is true and complete/)), 700);
      await h.click(vis(hmrc.getByRole("button", { name: /^Submit/ })), 600);
      const receipt = vis(hmrc.getByText(/submission simulated|Form bundle|form bundle/i));
      await receipt.waitFor({ timeout: 30_000 });
      await h.scrollIntoView(receipt, 800);
      await hoverText(c, /bundle/i, 1400);
      await h.hold(1500);
    },
  },
  // s5 (after the 4 Nov ~06:45 deploy): the demo files to HMRC's REAL sandbox with a fresh test user
  "w-vat-hmrc": {
    setup: async ({ page }) => {
      await go(page, "/vat");
      await page.getByRole("radiogroup", { name: "VAT period" }).getByRole("radio", { name: /Jul–Sep 2026/ }).click();
      await settle(page, 800);
    },
    run: async (c) => {
      const { page, h } = c;
      await h.park(700, 260);
      const ret = page.getByRole("region", { name: /Your return/ });
      await h.scrollIntoView(vis(ret.getByText("VAT due on sales")), 1000);
      for (const t of ["VAT due on sales", "VAT reclaimed on purchases", /Net VAT to pay HMRC/]) await h.hover(vis(ret.getByText(t)), 700);
      const hmrc = page.getByRole("region", { name: "Connect to HMRC" });
      await h.scrollIntoView(hmrc, 900);
      await hoverText(c, /HMRC sandbox — real test service/, 1000);
      c.mark("user");
      await h.click(vis(hmrc.getByRole("button", { name: "Make an HMRC sandbox test user" })), 300);
      const user = hmrc.getByRole("group", { name: "HMRC sandbox test user" });
      await user.waitFor({ timeout: 60_000 });
      c.mark("userReady");
      await h.hover(user, 1400);
      const uid = (await user.getByTestId("sandbox-user-id").innerText()).trim();
      const pwd = (await user.getByTestId("sandbox-password").innerText()).trim();
      await h.click(vis(hmrc.getByRole("button", { name: "Connect to HMRC sandbox" })), 300);
      c.mark("hmrc");
      // HMRC's own sandbox pages: Continue → Sign in to the HMRC online service → User ID + password → Give permission
      for (let i = 0; i < 12 && !page.url().startsWith(SITE); i++) {
        await settle(page, 600);
        if (page.url().startsWith(SITE)) break;
        const idBox = page.getByLabel(/User ID/i).first();
        if (await idBox.isVisible().catch(() => false)) {
          await h.type(idBox, uid, 100);
          await h.type(page.getByLabel(/Password/i).first(), pwd, 100);
          await h.click(vis(page.getByRole("button", { name: /Sign in/i })), 300);
          continue;
        }
        for (const name of [/Give permission/i, /Sign in to the HMRC online service/i, /^Continue/i]) {
          const b = page.getByRole("button", { name }).or(page.getByRole("link", { name })).first();
          if (await b.isVisible().catch(() => false)) { await h.click(b, 300); break; }
        }
      }
      await page.waitForURL((u: URL) => u.href.startsWith(SITE), { timeout: 60_000 });
      c.mark("back");
      await settle(page, 1000);
      const hm = page.getByRole("region", { name: "Connect to HMRC" });
      await vis(hm.getByText(/Connected to HMRC.s sandbox as test user/)).waitFor({ timeout: 30_000 });
      await h.scrollIntoView(vis(hm.getByText(/Connected to HMRC.s sandbox as test user/)), 800);
      await hoverText(c, /Connected to HMRC.s sandbox as test user/, 900);
      await h.click(vis(hm.getByRole("button", { name: "Show obligations" })), 600);
      await vis(hm.getByRole("button", { name: "Prepare submission" })).waitFor({ timeout: 30_000 });
      await h.click(vis(hm.getByRole("button", { name: "Prepare submission" })), 700);
      await h.click(vis(hm.getByLabel(/I confirm the information is true and complete/)), 600);
      c.mark("submit");
      await h.click(vis(hm.getByRole("button", { name: /Submit to HMRC sandbox/ })), 300);
      const receipt = vis(hm.getByRole("heading", { name: /Submitted to HMRC sandbox/ }));
      await receipt.waitFor({ timeout: 60_000 });
      c.mark("receipt");
      await h.scrollIntoView(receipt, 800);
      await hoverText(c, /Form bundle number|form bundle/i, 1800);
      await hoverText(c, /HMRC.s own sandbox receipt/, 1500);
      await h.hold(800);
    },
  },
  // s6: sole trader and landlord pages (switched on in Settings off camera)
  "w-selfemp": {
    setup: async (c) => {
      await go(c.page, "/settings");
      await vis(c.page.getByRole("button", { name: "Business", exact: true }).or(c.page.getByRole("tab", { name: "Business", exact: true }))).click();
      await c.page.waitForTimeout(800);
      for (const n of [/I am self-employed/, /I let property/]) {
        const sw = c.page.getByRole("switch", { name: n }).or(c.page.getByRole("checkbox", { name: n })).first();
        if (await sw.isVisible({ timeout: 3000 }).catch(() => false) && !(await sw.isChecked().catch(() => false))) await sw.click();
        await c.page.waitForTimeout(1200);
      }
      await go(c.page, "/self-employment");
    },
    run: async (c) => {
      const { page, h } = c;
      await h.park(800, 250);
      await hoverText(c, /Quarterly updates for Making Tax Digital/, 1500);
      await hoverText(c, /Sandbox/, 1000);
      await h.scrollBy(320, 1000);
      await h.hold(1500);
      await go(page, "/property");
      await hoverText(c, /Rent and costs/, 1300);
      await h.scrollBy(320, 1000);
      await h.hold(1800);
    },
  },
  // s6: the Harrison household: summary, budget, savings goal
  "w-personal": {
    kind: "personal",
    setup: async ({ page }) => { await go(page, "/"); await homeReady(page); },
    run: async (c) => {
      const { page, h } = c;
      await h.park(800, 250);
      await h.hold(700);
      for (const t of [/Housing over budget/, /BT Broadband/, /savings|School fees/]) await hoverText(c, t, 1000);
      await h.click(vis(page.getByRole("link", { name: /See budget/ }).or(page.getByRole("button", { name: /See budget/ }))), 1200);
      await settle(page, 400);
      await hoverText(c, /^Housing$/, 900);
      await hoverText(c, /^Groceries$/, 900);
      await h.scrollBy(250, 900);
      await h.hold(1000);
    },
  },
  "w-personal-goals": {
    kind: "personal",
    setup: async ({ page }) => { await go(page, "/goals"); await page.waitForTimeout(8000); },
    run: async (c) => {
      await c.h.park(800, 250);
      for (const t of ["School fees", /behind plan to date/, "Spend less on coffee"]) await hoverText(c, t, 1100);
      await c.h.hold(900);
    },
  },
  "w-personal-cal": {
    kind: "personal",
    mic: true,
    setup: async ({ page }) => { await go(page, "/calendar"); },
    run: async (c) => {
      const { page, h } = c;
      await h.park(1000, 400);
      await h.click(vis(page.getByRole("button", { name: "Talk to Accnomos" })), 900);
      const dlg = page.getByRole("dialog");
      await h.type(vis(dlg.getByLabel("Your question")), process.env.BILL_TEXT ?? "put the BT Broadband bill in my calendar on 8 November, all day", 300);
      await h.click(vis(dlg.getByRole("button", { name: "Send" })), 200);
      c.mark("wait");
      await vis(dlg.getByText(/NEEDS YOUR OK/i)).waitFor({ timeout: 150_000 });
      c.mark("ready");
      await h.hold(1500);
      await h.click(vis(dlg.getByRole("button", { name: "Approve" })), 300);
      c.mark("wait2");
      await page.waitForTimeout(6000);
      c.mark("ready2");
      await page.keyboard.press("Escape");
      await settle(page, 1000);
      await hoverText(c, /BT Broadband/, 1800);
      await h.hold(1200);
    },
  },
  // s7: Settings › AI: the three choices and the local-only warning
  "w-ai": {
    setup: async ({ page }) => {
      await go(page, "/settings");
      await vis(page.getByRole("button", { name: "AI", exact: true }).or(page.getByRole("tab", { name: "AI", exact: true }))).click();
      await page.waitForTimeout(800);
      await page.getByText("Which AI answers first").first().evaluate((e: Element) => window.scrollTo(0, e.getBoundingClientRect().top + window.scrollY - 140));
      await page.waitForTimeout(500);
    },
    run: async (c) => {
      const { page, h } = c;
      await h.park(900, 200);
      await hoverText(c, "Which AI answers first", 900);
      await hoverText(c, /^Meta Model API first/, 1200);
      await hoverText(c, /^Local model first, Meta API when unsure/, 1200);
      const lo = vis(page.getByText(/^Local model only/));
      await h.click(lo, 900);
      const warn = vis(page.getByText("What local only means"));
      await h.scrollIntoView(warn, 900);
      await h.hover(warn, 1200);
      await hoverText(c, /No voice input/, 1500);
      await h.hold(800);
    },
  },
  // s7: Files › your OneDrive folder, Books.xlsx, backups and version history
  "w-files": {
    setup: async ({ page }) => { await go(page, "/files"); },
    run: async (c) => {
      const { page, h } = c;
      await h.park(800, 250);
      await hoverText(c, /A live view of your Accnomos folder in OneDrive/, 1300);
      await hoverText(c, /^00 Inbox$/, 800);
      const books = vis(page.getByRole("button", { name: /Books\.xlsx/ }).or(page.getByText(/^Books\.xlsx$/)));
      if (await books.isVisible({ timeout: 3000 }).catch(() => false)) { await h.scrollIntoView(books, 1200); await h.hover(books, 1300); }
      const bk = vis(page.getByRole("heading", { name: /^Backups$|version/i }));
      if (await bk.isVisible({ timeout: 3000 }).catch(() => false)) { await h.scrollIntoView(bk, 1200); await h.hover(bk, 1200); }
      await hoverText(c, /version history|versions/i, 1500);
      await h.hold(800);
    },
  },
  "w-backups": {
    setup: async ({ page }) => { await go(page, "/settings"); await vis(page.getByRole("button", { name: "Files & backups", exact: true }).or(page.getByRole("tab", { name: "Files & backups", exact: true }))).click(); await page.waitForTimeout(800); },
    run: async (c) => {
      await c.h.park(900, 250);
      await hoverText(c, "Full backups", 900);
      await hoverText(c, /Back up now writes a dated folder/, 1800);
      await hoverText(c, /version history|versions/i, 1300);
      await c.h.hold(800);
    },
  },
  // s7: the live record of AI calls (GET /ai/calls), drawn as a clean page
  "w-calls": {
    kind: "none",
    setup: async ({ page }) => {
      const calls = await (await fetch(`${API}/ai/calls`)).json();
      const pick = (p: (x: any) => boolean) => calls.find(p);
      const rows = [pick((x: any) => x.provider === "spark" && x.ok), pick((x: any) => x.provider === "meta" && x.ok)].filter(Boolean);
      const more = calls.filter((x: any) => !rows.includes(x)).slice(0, 4);
      const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");
      const show = (x: any, hi: boolean) => `<pre class="${hi ? "hi" : ""}">${esc(JSON.stringify({ at: x.at, task: x.task, provider: x.provider, model: x.model, latency_ms: x.latency_ms, ok: x.ok, fell_back_from: x.fell_back_from }, null, 2))}</pre>`;
      await page.setContent(`<!doctype html><html><head><style>
        @font-face{font-family:A;src:local("Segoe UI"),local("Arial")}
        body{margin:0;background:#F8F6F3;font-family:ui-sans-serif,system-ui,"Segoe UI",Arial;color:#2A1A0D}
        header{background:#5A2D00;color:#F8F6F3;padding:22px 40px;font-size:22px}
        header b{color:#C9A45C} .u{font-family:ui-monospace,Consolas,monospace;font-size:19px}
        main{padding:22px 40px;display:grid;grid-template-columns:1fr 1fr;gap:20px}
        pre{margin:0;background:#fff;border:1px solid #e3dcd2;border-radius:10px;padding:16px 20px;font:16px/1.45 ui-monospace,Consolas,monospace}
        pre.hi{border:2px solid #C9A45C;box-shadow:0 2px 10px rgba(90,45,0,.12)} p{grid-column:1/3;margin:0;color:#6b5a48;font-size:15px}
      </style></head><body><header><span class="u">GET ${API}/ai/calls</span> &nbsp; · &nbsp; <b>live record of the server's last AI calls</b></header>
      <main>${rows.map((r: any) => show(r, true)).join("")}${more.map((r: any) => show(r, false)).join("")}
      <p>Read ${new Date().toISOString().slice(0, 16).replace("T", " ")} UTC · provider "spark" = Muse Glimmer 30B (open weights) on our own server · "meta" = Muse Spark on the Meta Model API</p></main></body></html>`);
      await page.waitForTimeout(500);
    },
    run: async (c) => {
      const { page, h } = c;
      await h.park(500, 300);
      await h.hold(800);
      const pres = page.locator("pre.hi");
      for (let i = 0; i < (await pres.count()); i++) await h.hover(pres.nth(i), 1800);
      await h.hold(1000);
    },
  },
  // v3 s7: the model switch in the app itself. Settings › AI → Local model only → Ask → byline names Glimmer 30B;
  // then Meta Model API first → the same question → byline names Muse Spark.
  "w-route": {
    setup: async ({ page }) => { await openAiSettings(page); },
    run: async (c) => {
      const { page, h } = c;
      await h.park(900, 200);
      for (const [i, label] of [[1, /^Local model only/], [2, /^Meta Model API first/]] as const) {
        if (i === 2) { await openAiSettings(page); await h.park(900, 200); }
        c.mark(`set${i}`);
        await hoverText(c, "Which AI answers first", 600);
        await h.click(vis(page.getByText(label)), 900);
        c.mark(`picked${i}`);
        await h.hold(700);
        await go(page, "/ask");
        c.mark(`ask${i}`);
        await h.park(700, 300);
        const want = i === 1 ? /explanation by Glimmer/ : /explanation by Muse Spark/;
        await askTyped(c, ROUTE_Q, i, false, want);
        const by = vis(page.getByText(want));
        await h.scrollIntoView(by, 700);
        c.mark(`by${i}`);
        await h.hover(by, 2200);
        await h.hold(500);
      }
    },
  },
  // v3 s4b: the Ask showcase (typed)
  "w-profit": {
    setup: async ({ page }) => { await go(page, "/ask"); },
    run: async (c) => {
      await c.h.park(700, 300);
      await askTyped(c, process.env.PROFIT_Q ?? "How much profit did we make this quarter?", 1, false, ANSWERED);
      await hoverText(c, /explanation by|Worked out by code/, 1500);
      await c.h.hold(800);
    },
  },
  "w-timesheet": {
    setup: async ({ page }) => { await go(page, "/ask"); },
    run: async (c) => {
      const { page, h } = c;
      await h.park(700, 300);
      await askTyped(c, process.env.TIME_Q ?? "Add 2 hours for Ellie on the Kitchen fit-out, Harrogate job, including 1 hour overtime at double rate", 1, true);
      const card = vis(page.getByRole("article", { name: /^Proposed:/ }));
      await h.scrollIntoView(card, 900);
      await h.hover(card, 2200);
      const approve = vis(card.getByRole("button", { name: "Approve" }));
      await h.hover(approve, 700);
      c.mark("approve");
      await h.click(approve, 300);
      c.mark("wait2");
      await approve.waitFor({ state: "detached", timeout: 60_000 }).catch(() => undefined);
      await page.waitForTimeout(700);
      c.mark("ready2");
      await h.hold(2400);
    },
  },
  "w-tiles": {
    setup: async ({ page }) => { await go(page, "/ask"); },
    run: async (c) => {
      await c.h.park(700, 300);
      await askTyped(c, process.env.TILES_Q ?? "What tiles did we order for the Kitchen fit-out, Harrogate job?", 1, false, ANSWERED);
      await hoverText(c, /explanation by|Worked out by code/, 1500);
      await c.h.hold(800);
    },
  },
  // v3 s5a: the automatic bank feed (TrueLayer sandbox): Connect a bank → TrueLayer's mock bank → back → Fetch → lines matched
  "w-bankfeed": {
    setup: async ({ page }) => {
      await go(page, "/bank");
      const feed = page.getByRole("region", { name: "Bank feed" });
      await feed.waitFor({ timeout: 30_000 }).catch(() => undefined);
      await feed.evaluate((e: Element) => window.scrollTo(0, e.getBoundingClientRect().top + window.scrollY - 120)).catch(() => undefined);
      await page.waitForTimeout(600);
    },
    run: async (c) => {
      const { page, h } = c;
      await h.park(900, 250);
      const feed = page.getByRole("region", { name: "Bank feed" });
      await hoverText(c, /^Bank feed/, 800);
      const connect = vis(feed.getByRole("button", { name: /^Connect (a|the test) bank/ }).or(page.getByRole("button", { name: /^Connect the test bank/ })));
      if (await connect.isVisible({ timeout: 3000 }).catch(() => false)) {
        c.mark("connect");
        await h.click(connect, 300);
        await page.waitForURL((u: URL) => !u.href.startsWith(SITE), { timeout: 30_000 }).catch(() => undefined);
        c.mark("tl");
        // TrueLayer's sandbox: pick the mock bank, sign in with its public test login, allow
        for (let i = 0; i < 16 && !page.url().startsWith(SITE); i++) {
          await settle(page, 700);
          if (page.url().startsWith(SITE)) break;
          const user = page.getByLabel(/user ?name|user id/i).first();
          if (await user.isVisible().catch(() => false)) {
            await h.type(user, process.env.TL_USER ?? "john", 80);
            await h.type(page.getByLabel(/password/i).first(), process.env.TL_PASS ?? "doe", 80);
          }
          let clicked = false;
          for (const name of [/mock/i, /^Allow|^Approve|^Agree/i, /^Continue|^Submit|^Sign in|^Log in|^Confirm|^Next/i]) {
            const b = page.getByRole("button", { name }).or(page.getByRole("link", { name })).or(page.getByRole("option", { name })).first();
            if (await b.isVisible().catch(() => false)) { await h.click(b, 300); clicked = true; break; }
          }
          if (!clicked) {
            const tile = page.getByText(/^Mock/i).first();
            if (await tile.isVisible().catch(() => false)) await h.click(tile, 300);
            else await page.waitForTimeout(1500);
          }
          console.log("  tl page", i, page.url().slice(0, 80));
        }
        await page.waitForURL((u: URL) => u.href.startsWith(SITE), { timeout: 90_000 });
        c.mark("back");
        await settle(page, 1500);
      }
      const f2 = page.getByRole("region", { name: "Bank feed" });
      await h.scrollIntoView(f2, 700);
      const fetch = vis(f2.getByRole("button", { name: /^Fetch now|^Sync now/ }));
      await fetch.waitFor({ timeout: 60_000 });
      await h.hover(fetch, 600);
      c.mark("fetch");
      await h.click(fetch, 300);
      await vis(f2.getByRole("button", { name: /^Fetch now|^Sync now/ })).waitFor({ timeout: 90_000 }).catch(() => undefined);
      await page.waitForTimeout(800);
      c.mark("fetched");
      await hoverText(c, /new (bank )?lines?|fetched|Last fetched/i, 1400);
      await h.scrollBy(320, 900);
      await hoverText(c, /matched|Match/i, 1500);
      await h.hold(1200);
    },
  },
};

/** An Ask answer is in: worded by a model (checked) or worked out by code alone. */
const ANSWERED = /explanation by (Glimmer|Muse)|^Worked out by code/;
const ROUTE_Q = process.env.ROUTE_Q ?? "Who owes me the most?";
async function openAiSettings(page: any) {
  await go(page, "/settings");
  await vis(page.getByRole("button", { name: "AI", exact: true }).or(page.getByRole("tab", { name: "AI", exact: true }))).click();
  await page.waitForTimeout(800);
  await page.getByText("Which AI answers first").first().evaluate((e: Element) => window.scrollTo(0, e.getBoundingClientRect().top + window.scrollY - 140));
  await page.waitForTimeout(500);
}
/** Type a question in Ask, send it, mark wait<i>/ready<i> around the live model (a proposal card when `card`). */
async function askTyped(c: Ctx, q: string, i: number, card = false, want: RegExp = /explanation by (Glimmer|Muse)/) {
  const { page, h } = c;
  await h.type(vis(page.getByLabel(/Ask your books/)), q, 300);
  await h.click(vis(page.getByRole("button", { name: "Ask", exact: true })), 200);
  c.mark(`wait${i === 1 ? "" : i}`);
  const done = card ? vis(page.getByRole("article", { name: /^Proposed:/ })) : vis(page.getByText(want));
  await done.waitFor({ timeout: 180_000 });
  await page.waitForTimeout(600);
  c.mark(`ready${i === 1 ? "" : i}`);
}

/** Ask once each way so /ai/calls has a fresh Glimmer (local_only) and Muse Spark (meta_first) record. */
async function freshCalls() {
  const s = (await (await fetch(`${API}/demo/session?kind=company`, { method: "POST" })).json()).session;
  for (const route of ["local_only", "meta_first"]) {
    const r = await fetch(`${API}/books/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Demo-Session": s, "X-AI-Route": route },
      body: JSON.stringify({ question: "Who owes me the most?" }),
    }).catch((e) => ({ status: String(e) }) as any);
    console.log("ask", route, (r as any).status);
  }
}

async function demoSession(page: any, kind: "company" | "personal") {
  await page.goto(`${SITE}/judges`);
  await page.getByRole("button", { name: kind === "personal" ? "Start the personal demo" : "Start the demo" }).click();
  await page.waitForURL(/\/(review|$)/, { timeout: 120_000 }).catch(() => undefined);
  await page.waitForTimeout(Number(process.env.DEMO_WAIT_MS ?? 12_000)); // the demo books take ~10 s to build
}

const browserArgs = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required"];
let first = true;
for (const [id, shot] of Object.entries(SHOTS)) {
  if (ONLY && !ONLY.has(id)) continue;
  if (!first) await sleep(Number(process.env.GAP_MS ?? 25_000)); // stay under the live API's per-IP limits
  first = false;
  const args = [...browserArgs];
  if (shot.mic && process.env.FAKE_MIC) args.push(`--use-file-for-fake-audio-capture=${process.env.FAKE_MIC}%noloop`);
  const browser = await chromium.launch({ args });
  try {
    const context = await browser.newContext({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 2, permissions: ["microphone"], locale: "en-GB", timezoneId: "Europe/London", acceptDownloads: true });
    await context.addInitScript(CURSOR_SCRIPT);
    await context.addInitScript(`(() => { const s = document.createElement('style'); s.textContent = ${JSON.stringify(CLEAN_CSS)}; (document.head || document.documentElement).appendChild(s); })()`);
    const page = await context.newPage();
    const h = new Human(page);
    if (id === "w-calls") await freshCalls();
    if (shot.kind !== "none") await demoSession(page, shot.kind ?? "company");
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
