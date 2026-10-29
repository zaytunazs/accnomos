/**
 * One scripted flow per thing a shot can show, run against the demo sandbox (DEMO_MODE=1 runtime, the fictional
 * Bramblewood Joinery Ltd books, every document labelled "SAMPLE — FICTIONAL COMPANY").
 *
 * `setup` runs off camera (navigate, wait until ready); `run` is what is recorded. A flow should take a little less
 * than a typical shot; capture.ts holds the last frame to the shot's length, and assemble.sh speeds up (and says so)
 * a recording that runs over.
 *
 * Choosing a flow for a shot: the script's `flow` column if it has one, else the first rule in RULES whose pattern
 * matches the shot's description. `card` means no app footage (title, provenance and end cards are drawn by
 * assemble.sh); `camera` marks a shot only a real camera can film (hand-held phone, shoebox).
 */
import type { Locator, Page } from "@playwright/test";
import type { Human } from "./lib/human.ts";

export interface FlowCtx {
  page: Page;
  h: Human;
  phone: boolean;
  /** Absolute path of apps/web/public/sample-receipt.png (fictional, stamped SAMPLE). */
  receipt: string;
}

export interface Flow {
  /** What the flow shows, for the manifest and README. */
  about: string;
  /** Starts signed out (no demo session): the landing page and /judges. */
  signedOut?: boolean;
  setup?: (c: FlowCtx) => Promise<void>;
  run?: (c: FlowCtx) => Promise<void>;
  /** No app footage: assemble.sh draws a card. `camera`: footage only a real camera can shoot. */
  kind?: "app" | "card" | "camera";
}

const main = (p: Page) => p.getByRole("main");

async function open(c: FlowCtx, path: string, ready: (p: Page) => Locator): Promise<void> {
  await c.page.goto(path);
  await ready(c.page).first().waitFor({ state: "visible", timeout: 60_000 });
  await c.page.waitForLoadState("networkidle").catch(() => undefined);
  await c.page.evaluate(() => window.scrollTo(0, 0));
  await c.page.waitForTimeout(300);
}

const h1 = (name: string | RegExp) => (p: Page) => p.getByRole("heading", { level: 1, name });

/** Phone: open the site menu; desktop: the top bar. Then click a link by name (shows how you get there). */
async function navTo(c: FlowCtx, group: string, link: string | RegExp): Promise<void> {
  const { page, h } = c;
  if (c.phone) {
    const menu = page.getByRole("button", { name: /^Menu$/ }).first();
    if (await menu.isVisible().catch(() => false)) {
      await h.click(menu, 500);
      await h.click(page.getByRole("link", { name: link }).first(), 900);
      return;
    }
  } else {
    const btn = page.getByRole("button", { name: new RegExp(`^${group}`) }).first();
    if (await btn.isVisible().catch(() => false)) {
      await h.click(btn, 500);
      await h.click(page.getByRole("link", { name: link }).first(), 900);
      return;
    }
  }
  throw new Error(`no menu route to ${String(link)}`);
}

/** A slow look down a page: scroll in a few steps, pausing on each screenful. */
async function browse(c: FlowCtx, screens = 2, pause = 1400): Promise<void> {
  const vp = c.page.viewportSize()!;
  for (let i = 0; i < screens; i++) {
    await c.h.hold(pause);
    await c.h.scrollBy(vp.height * 0.6, 1100);
  }
  await c.h.hold(pause);
}

export const FLOWS: Record<string, Flow> = {
  card: { about: "No app footage: a title, provenance, eval or end card drawn by assemble.sh", kind: "card" },
  camera: { about: "Needs a real camera (hand-held phone, shoebox of receipts): a placeholder card until filmed", kind: "camera" },

  landing: {
    about: "The public landing page, signed out, down to “Try the demo”",
    signedOut: true,
    setup: (c) => open(c, "/", (p) => main(p).getByRole("link", { name: "Try the demo", exact: true })),
    run: async (c) => {
      await c.h.park(c.page.viewportSize()!.width * 0.7, 300);
      await c.h.hold(1200);
      await browse(c, 2, 1300);
      await c.h.scrollToTop(900);
      await c.h.hover(main(c.page).getByRole("link", { name: "Try the demo", exact: true }).first(), 900);
    },
  },

  judges: {
    about: "/judges with no sign-in: the guide, then “Start the demo” opens Review on the sample books",
    signedOut: true,
    setup: (c) => open(c, "/judges", h1("Try Accnomos in one click")),
    run: async (c) => {
      const { page, h } = c;
      await h.park(page.viewportSize()!.width * 0.6, 260);
      await h.hold(1500);
      await h.hover(page.getByRole("region", { name: "What to try, in this order" }), 1200);
      await h.scrollToTop(700);
      await h.click(page.getByRole("button", { name: "Start the demo" }), 300);
      await page.waitForURL(/\/review$/, { timeout: 300_000 });
      await page.getByRole("complementary", { name: "Demo sandbox" }).waitFor();
      await h.hold(1800);
    },
  },

  home: {
    about: "Home on the sample books: cash, owed to you, VAT estimate, what needs attention",
    setup: (c) => open(c, "/", (p) => p.getByRole("heading", { level: 1, name: /^Good (morning|afternoon|evening)/ })),
    run: async (c) => {
      const { page, h } = c;
      await h.park(page.viewportSize()!.width * 0.55, 240);
      await h.hold(900);
      const today = page.getByRole("heading", { level: 1, name: /^Good / });
      await h.hover(today, 900);
      await h.scrollIntoView(today);
      await h.hover(page.getByText("VAT estimate").first(), 1200);
      await browse(c, 1, 1200);
    },
  },

  "receipt-upload": {
    about: "Review → Add a receipt: the sample receipt goes to 00 Inbox (the reading itself must be filmed live: the stub cannot read it)",
    setup: (c) => open(c, "/review", h1("Review")),
    run: async (c) => {
      const { page, h } = c;
      await h.park(page.viewportSize()!.width * 0.5, 200);
      await h.hold(700);
      const add = page.getByRole("button", { name: "Add a receipt" }).first();
      await h.moveToLocator(add);
      await h.hold(300);
      const chooser = page.waitForEvent("filechooser", { timeout: 10_000 }).catch(() => null);
      await h.click(add, 200);
      const fc = await chooser;
      if (fc) await fc.setFiles(c.receipt);
      else await page.locator('input[type="file"]').first().setInputFiles(c.receipt);
      const added = page.getByText(/file added to 00 Inbox/).first();
      await added.waitFor({ timeout: 30_000 });
      await h.hover(added, 1600);
      // Not scanned on camera: the test-mode stub reads only the gold receipts, and the demo's 00 Inbox holds sample
      // files it cannot read. Film the reading itself live (docs/video/README.md).
      await h.hover(page.getByRole("button", { name: "Scan 00 Inbox now" }).first(), 1400);
    },
  },

  "review-approve": {
    about: "Review: open the first waiting receipt (what was read, code checks, journal) and Approve it",
    setup: (c) => open(c, "/review", (p) => p.getByText(/\d+ waiting for you/)),
    run: async (c) => {
      const { page, h } = c;
      await h.park(page.viewportSize()!.width * 0.5, 220);
      const waiting = page.getByText(/\d+ waiting for you/).first();
      await h.scrollIntoView(waiting, 1000);
      await h.hold(600);
      const approve = page.getByRole("button", { name: /^Approve/ }).first();
      const card = page.getByRole("article").filter({ has: approve }).first();
      const why = card.getByText(/^Why:/).first();
      if (await why.isVisible().catch(() => false)) await h.hover(why, 1400);
      const checks = card.getByText(/checks by code/).first();
      if (await checks.isVisible().catch(() => false)) await h.hover(checks, 1200);
      await h.click(approve, 400);
      await page.getByText(/Approved · posted to your books/).first().waitFor({ timeout: 20_000 });
      await h.hold(1600);
    },
  },

  "needs-a-look": {
    about: "Review → Needs a look: a reading the checks flagged (foreign VAT number, euros), nothing posted",
    setup: (c) => open(c, "/review", (p) => p.getByText(/\d+ waiting for you/)),
    run: async (c) => {
      const { page, h } = c;
      await h.park(page.viewportSize()!.width * 0.5, 220);
      const flag = page.getByText("Needs a look.").first();
      await h.scrollIntoView(flag, 1600);
      await h.hover(flag, 1200);
      const why = page.getByText(/not a UK format|needs converting/).first();
      if (await why.isVisible().catch(() => false)) await h.hover(why, 1800);
      await h.hold(800);
    },
  },

  "files-ledger": {
    about: "Files: the folders in OneDrive, then _System → Ledger → events (one immutable file per approval)",
    setup: (c) => open(c, "/files", h1("Files")),
    run: async (c) => {
      const { page, h } = c;
      await h.park(page.viewportSize()!.width * 0.5, 220);
      await h.hold(900);
      const sys = page.getByRole("button", { name: /^_System/ }).first();
      await h.click(sys, 900);
      for (const name of [/^Ledger/, /^events/]) {
        const b = page.getByRole("button", { name }).first();
        if (await b.isVisible().catch(() => false)) await h.click(b, 900);
      }
      const ev = page.getByRole("button", { name: /^› 2026-0[89]/ }).first();
      if (await ev.isVisible().catch(() => false)) await h.click(ev, 1200);
      await h.hold(800);
    },
  },

  "files-books": {
    about: "Files: Books.xlsx and the numbered folders, all in the user's own OneDrive (no Accnomos database)",
    setup: (c) => open(c, "/files", h1("Files")),
    run: async (c) => {
      const { page, h } = c;
      await h.park(page.viewportSize()!.width * 0.5, 220);
      await h.hold(1200);
      const books = page.getByRole("button", { name: "Books.xlsx" }).first();
      if (await books.isVisible().catch(() => false)) await h.hover(books, 1800);
      else await browse(c, 1, 1400);
      await h.hold(800);
    },
  },

  "vat-return": {
    about: "VAT return for Jul–Sep 2026: the nine boxes worked out by code from approved entries",
    setup: (c) => open(c, "/vat", h1("VAT return")),
    run: async (c) => {
      const { page, h } = c;
      await h.park(page.viewportSize()!.width * 0.4, 260);
      await h.hold(700);
      await h.click(page.getByRole("radiogroup", { name: "VAT period" }).getByRole("radio", { name: /Jul–Sep 2026/ }), 900);
      const ret = page.getByRole("region", { name: /Your return/ });
      await h.scrollIntoView(ret.getByText("VAT reclaimed on purchases").first(), 1100);
      await h.hover(ret.getByText("VAT due on sales").first(), 900);
      await h.hover(ret.getByText("VAT reclaimed on purchases").first(), 900);
      await h.hover(ret.getByText(/Net VAT to pay HMRC/).first(), 1100);
      await h.hover(ret.getByText("Total purchases excluding VAT").first(), 1000);
    },
  },

  "hmrc-sim": {
    about: "VAT → Connect to HMRC (simulated in the demo) → obligations → declaration → simulated receipt",
    setup: async (c) => {
      await open(c, "/vat", h1("VAT return"));
      await c.page.getByRole("radiogroup", { name: "VAT period" }).getByRole("radio", { name: /Jul–Sep 2026/ }).click();
      await c.page.getByRole("region", { name: "Connect to HMRC" }).scrollIntoViewIfNeeded();
      await c.page.evaluate(() => window.scrollBy(0, -120));
    },
    run: async (c) => {
      const { page, h } = c;
      const hmrc = page.getByRole("region", { name: "Connect to HMRC" });
      await h.park(page.viewportSize()!.width * 0.5, 300);
      await h.hover(hmrc.getByText("Demo · HMRC simulated").first(), 1000);
      await h.click(hmrc.getByRole("button", { name: "Connect to HMRC (simulated)" }), 900);
      await h.click(hmrc.getByRole("button", { name: "Show obligations" }), 1000);
      await h.click(hmrc.getByRole("button", { name: "Prepare submission" }), 900);
      await h.click(hmrc.getByLabel("I confirm the information is true and complete"), 700);
      await h.click(hmrc.getByRole("button", { name: /Submit \(demo — simulated\)/ }), 600);
      const receipt = hmrc.getByRole("heading", { name: /Demo — submission simulated/ });
      await receipt.waitFor({ timeout: 20_000 });
      await h.scrollIntoView(receipt, 800);
      await h.hover(hmrc.getByText("HMRC was not contacted").first(), 1600);
    },
  },

  "ask-vat": {
    about: "Ask: “How much VAT do I owe for Jul–Sep 2026?”, figures from code and the files used",
    setup: (c) => open(c, "/ask", (p) => p.getByLabel("Ask your books")),
    run: async (c) => {
      const { page, h } = c;
      await h.park(page.viewportSize()!.width * 0.5, 240);
      await h.hold(600);
      // The sample books' open quarter with figures is Jul–Sep 2026 (the demo's "today" is in Oct–Dec, still empty).
      await h.type(page.getByLabel("Ask your books").first(), "How much VAT do I owe for Jul–Sep 2026?", 300);
      await h.click(page.getByRole("button", { name: "Ask", exact: true }).first(), 300);
      const answer = page.getByRole("article").last();
      await answer.waitFor({ timeout: 30_000 });
      await h.hold(900);
      const key = answer.getByRole("table", { name: "Key numbers" });
      if (await key.isVisible().catch(() => false)) await h.hover(key, 1600);
      const files = answer.getByRole("list", { name: "Files used" });
      if (await files.isVisible().catch(() => false)) await h.hover(files, 1400);
    },
  },

  "ask-invoice": {
    about: "Ask with an action: “Send a £100 invoice to Hartwell Property Maintenance” → a priced card waiting for Approve",
    setup: (c) => open(c, "/ask", (p) => p.getByLabel("Ask your books")),
    run: async (c) => {
      const { page, h } = c;
      await h.park(page.viewportSize()!.width * 0.5, 240);
      await h.type(page.getByLabel("Ask your books").first(), "Send a £100 invoice to Hartwell Property Maintenance", 300);
      await h.click(page.getByRole("button", { name: "Ask", exact: true }).first(), 300);
      const card = page.getByRole("article", { name: /^Proposed:/ }).first();
      await card.waitFor({ timeout: 30_000 });
      await h.scrollIntoView(card, 900);
      await h.hover(card, 1400);
      await h.hover(card.getByRole("button", { name: "Approve" }), 1400);
    },
  },

  "month-end": {
    about: "Month-end: one button runs the close checklist; code does the checks, cards wait for approval",
    setup: (c) => open(c, "/month-end", h1("Month-end")),
    run: async (c) => {
      const { page, h } = c;
      await h.park(page.viewportSize()!.width * 0.5, 260);
      await h.hold(600);
      await h.click(page.getByRole("button", { name: /^Close / }).first(), 600);
      const list = page.getByRole("list", { name: /^Close checklist for/ });
      await list.waitFor({ timeout: 60_000 });
      await h.hold(1000);
      await h.scrollIntoView(list.getByRole("listitem").nth(1), 1200);
      await browse(c, 1, 1400);
    },
  },

  profiles: {
    about: "The profile switcher (top left): company, sole trader and personal books",
    setup: (c) => open(c, "/", (p) => p.getByRole("heading", { level: 1 })),
    run: async (c) => {
      const { page, h } = c;
      await h.park(page.viewportSize()!.width * 0.4, 300);
      const sw = page.getByRole("button", { name: /Demo visitor|profile/i }).first();
      await h.click(sw, 1800);
      await h.press("Escape", 600);
    },
  },

  models: {
    about: "Meta models at work: the provider chain (Muse Glimmer first) and the measured eval figures",
    setup: (c) => open(c, "/models", h1("Meta models at work")),
    run: async (c) => {
      const { page, h } = c;
      await h.park(page.viewportSize()!.width * 0.5, 260);
      await h.hold(800);
      const chain = page.getByRole("list", { name: "Provider chain" });
      if (await chain.isVisible().catch(() => false)) await h.hover(chain.getByRole("listitem").first(), 1400);
      const report = page.getByRole("link", { name: /Report: evals\/runs\/spark_open_200/ }).first();
      if (await report.count()) await h.hover(report, 1600);
      await browse(c, 1, 1200);
    },
  },

  "connect-ai": {
    about: "Connect → Choose your AI",
    setup: (c) => open(c, "/connect/ai", (p) => p.getByRole("heading", { level: 1 })),
    run: async (c) => browse(c, 1, 1500),
  },

  reports: {
    about: "Reports: profit and loss, aged debtors and creditors, VAT summary, over six months of sample books",
    setup: (c) => open(c, "/reports", (p) => p.getByRole("heading", { name: /Profit and loss/ })),
    run: async (c) => {
      await c.h.park(c.page.viewportSize()!.width * 0.5, 260);
      await c.h.hover(c.page.getByRole("heading", { name: /Profit and loss/ }).first(), 1000);
      await browse(c, 2, 1300);
    },
  },

  contacts: {
    about: "Contacts built from the ledger: who owes what, suppliers not VAT-registered",
    setup: (c) => open(c, "/contacts", (p) => p.getByRole("heading", { level: 1 })),
    run: async (c) => {
      await c.h.park(c.page.viewportSize()!.width * 0.5, 260);
      await browse(c, 2, 1300);
    },
  },

  bank: {
    about: "Bank: imported statements reconciled against the books, bank rules, what is still to match",
    setup: (c) => open(c, "/bank", (p) => p.getByRole("heading", { level: 1 })),
    run: async (c) => {
      await c.h.park(c.page.viewportSize()!.width * 0.5, 260);
      await browse(c, 2, 1300);
    },
  },

  invoices: {
    about: "Invoices: the list, then one invoice with its payments",
    setup: (c) => open(c, "/invoices", (p) => p.getByRole("heading", { level: 1 })),
    run: async (c) => {
      const { page, h } = c;
      await h.park(page.viewportSize()!.width * 0.5, 260);
      await h.hold(1000);
      const first = main(page).getByRole("link", { name: /^INV-/ }).first();
      if (await first.isVisible().catch(() => false)) {
        await h.click(first, 1500);
        await browse(c, 1, 1300);
      } else await browse(c, 2, 1300);
    },
  },

  "new-invoice": {
    about: "Sales → New invoice: pick a customer, add a line, totals by code",
    setup: (c) => open(c, "/invoices/new", (p) => p.getByRole("heading", { level: 1 })),
    run: async (c) => browse(c, 1, 1600),
  },

  settings: {
    about: "Settings: business details, VAT stagger, Autopilot level, Outlook intake",
    setup: (c) => open(c, "/settings", (p) => p.getByRole("heading", { level: 1 })),
    run: async (c) => browse(c, 2, 1300),
  },

  outlook: {
    about: "Settings → Connections (Outlook intake is read-only Mail.Read; the demo has no mailbox, so this shows the settings)",
    setup: (c) => open(c, "/settings", h1("Settings")),
    run: async (c) => {
      const { page, h } = c;
      await h.park(page.viewportSize()!.width * 0.5, 300);
      const conn = page.getByRole("heading", { name: "Connections" }).first();
      await h.hover(conn, 1200);
      const outlook = page.getByText(/Outlook/).first();
      if (await outlook.isVisible().catch(() => false)) await h.hover(outlook, 1500);
      await browse(c, 1, 1400);
    },
  },

  "how-it-works": {
    about: "Help (How it works): what AI does, what code does and the known gaps, per feature",
    setup: (c) => open(c, "/how-it-works", (p) => p.getByRole("heading", { level: 1 })),
    run: async (c) => browse(c, 2, 1400),
  },

  property: {
    about: "Property: rental income and costs per property",
    setup: (c) => open(c, "/property", (p) => p.getByRole("heading", { level: 1 })),
    run: async (c) => browse(c, 1, 1500),
  },

  payroll: {
    about: "Payroll: a prepared pay run waiting for confirmation (estimates by code)",
    setup: (c) => open(c, "/payroll", (p) => p.getByRole("heading", { level: 1 })),
    run: async (c) => browse(c, 1, 1500),
  },

  "self-employment": {
    about: "Self-employment: MTD Income Tax quarterly figures",
    setup: (c) => open(c, "/self-employment", (p) => p.getByRole("heading", { level: 1 })),
    run: async (c) => browse(c, 1, 1500),
  },

  cis: {
    about: "Construction Industry Scheme: deductions on labour, statements",
    setup: (c) => open(c, "/cis", (p) => p.getByRole("heading", { level: 1 })),
    run: async (c) => browse(c, 1, 1500),
  },

  personal: {
    about: "Personal finances",
    setup: (c) => open(c, "/personal", (p) => p.getByRole("heading", { level: 1 })),
    run: async (c) => browse(c, 1, 1500),
  },

  spending: {
    about: "Spending and cheaper options",
    setup: (c) => open(c, "/spending", (p) => p.getByRole("heading", { level: 1 })),
    run: async (c) => browse(c, 1, 1500),
  },

  accountant: {
    about: "Your accountant: invite by email, the books folder is shared in OneDrive",
    setup: (c) => open(c, "/settings", (p) => p.getByRole("heading", { level: 1 })),
    run: async (c) => {
      const t = c.page.getByText(/Your accountant/).first();
      if (await t.isVisible().catch(() => false)) await c.h.hover(t, 1500);
      await browse(c, 1, 1400);
    },
  },

  "nav-tour": {
    about: "A walk through the top menus",
    setup: (c) => open(c, "/", (p) => p.getByRole("heading", { level: 1 })),
    run: async (c) => {
      for (const g of ["Sales", "Purchases", "Reporting", "Tax"]) {
        const b = c.page.getByRole("button", { name: new RegExp(`^${g}`) }).first();
        if (!(await b.isVisible().catch(() => false))) continue;
        await c.h.click(b, 1000);
        await c.h.press("Escape", 300);
      }
    },
  },
};

/** First match wins; tested against a shot's description (`what`), then its caption. */
export const RULES: [RegExp, string][] = [
  [/provenance|black card|title card|end card|eval card|full-screen card|plain card|\bcard\b.*(text|white)/i, "card"],
  [/shoebox|hand-held|handheld|phone in hand|filmed with a camera/i, "camera"],
  [/\/judges|no sign-in|private window/i, "judges"],
  [/landing|public site|homepage/i, "landing"],
  [/needs a look|disagree/i, "needs-a-look"],
  [/profile/i, "profiles"],
  [/hmrc|submit|declaration|obligation/i, "hmrc-sim"],
  [/photograph|take a photo|snap|upload|add a receipt|capture/i, "receipt-upload"],
  [/ledger|_system/i, "files-ledger"],
  [/books\.xlsx|onedrive|files/i, "files-books"],
  [/vat return|box \d|nine boxes|9 boxes/i, "vat-return"],
  [/invoice.*(ask|chat)|(ask|chat).*invoice/i, "ask-invoice"],
  [/\bask\b|question|chat/i, "ask-vat"],
  [/month.?end|close/i, "month-end"],
  [/meta models|models panel|glimmer|choose your ai|provider/i, "models"],
  [/outlook|email|inbox intake|mail/i, "outlook"],
  [/review|approve/i, "review-approve"],
  [/report|profit|p&l|aged/i, "reports"],
  [/contact|customer|supplier/i, "contacts"],
  [/bank|reconcil/i, "bank"],
  [/new invoice/i, "new-invoice"],
  [/invoice|payment|credit note/i, "invoices"],
  [/property|landlord|letting/i, "property"],
  [/payroll|pay run/i, "payroll"],
  [/self.?employ|income tax|itsa/i, "self-employment"],
  [/\bcis\b|construction/i, "cis"],
  [/personal/i, "personal"],
  [/accountant/i, "accountant"],
  [/help|how it works/i, "how-it-works"],
  [/settings|autopilot/i, "settings"],
  [/home|dashboard/i, "home"],
];

export function chooseFlow(shot: { flow?: string; what: string; caption: string }): string {
  if (shot.flow && FLOWS[shot.flow]) return shot.flow;
  for (const text of [shot.what, shot.caption]) {
    for (const [re, name] of RULES) if (re.test(text)) return name;
  }
  return "home";
}
