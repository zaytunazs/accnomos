/**
 * Screenshots for the how-to guides (docs/howto/*.md): every screenshot placeholder becomes
 * docs/howto/img/<guide>-<N>.png (1440 × 900, cropped round the control the step talks about, with a highlight box
 * on it) and the placeholder is replaced by the image, so the guide renders on GitHub and in the app's Help page.
 *
 *   node tools/video/howto.ts                 # every guide (reuses apps/web/out-e2e; starts the servers as capture.ts does)
 *   node tools/video/howto.ts --only vat-return --dry-run
 *
 * Placeholders it understands (one per line; N counts placeholders in the guide, from 1):
 *   ![Screenshot: what it shows](img/<guide>-<N>.png)        an image link whose file does not exist yet
 *   <!-- screenshot: what it shows -->                      also [screenshot: …], [Screenshot placeholder: …],
 *   > 📸 Screenshot: what it shows                          [SCREENSHOT: …], ![screenshot: …]() and TODO screenshot lines
 * Optional hints inside the text: `page=/vat` picks the page; `target="Approve (post to books)"` the control to box;
 * `crop=full` keeps the whole viewport. Without hints the page comes from ROUTES (keywords in the step and the guide
 * title) and the control from the step's **bold**, “quoted” or `code` words, tried as button, link, tab, field, text.
 * Runs against the demo sandbox (the fictional sample books), like capture.ts.
 */
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Browser, Locator, Page } from "@playwright/test";
import { launch, servers } from "./capture.ts";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "../..");
const HOWTO = path.join(ROOT, "docs/howto");
const IMG = path.join(HOWTO, "img");
const WEB_URL = `http://127.0.0.1:${process.env.E2E_WEB_PORT ?? 3100}`;

/** Keyword → page, first match wins (tested against the step text, then the guide's title and file name). */
export const ROUTES: [RegExp, string][] = [
  [/judges|no sign-in|try the demo/i, "/judges"],
  [/month.?end|close the month|close checklist/i, "/month-end"],
  [/hmrc|submit|obligation|declaration|vat return|nine boxes|9 boxes|box \d|vat period/i, "/vat"],
  [/needs a look|review|approve|scan 00 inbox|add a receipt|upload|receipt/i, "/review"],
  [/\bask\b|question/i, "/ask"],
  [/new invoice|create an invoice/i, "/invoices/new"],
  [/invoice|payment|credit note/i, "/invoices"],
  [/quote/i, "/sales/quotes"],
  [/bank rule|reconcil|bank/i, "/bank"],
  [/contact|customer|supplier/i, "/contacts"],
  [/report|profit|aged|balance sheet/i, "/reports"],
  [/files|onedrive|books\.xlsx|ledger|folder/i, "/files"],
  [/payroll|pay run/i, "/payroll"],
  [/mileage|vehicle/i, "/vehicles"],
  [/property|landlord|letting|rent/i, "/property"],
  [/self.?employ|income tax/i, "/self-employment"],
  [/\bcis\b|construction/i, "/cis"],
  [/accountant/i, "/settings"],
  [/import|switch from|xero|quickbooks|sage|freeagent/i, "/import"],
  [/models|meta ai|glimmer/i, "/models"],
  [/choose your ai|connect/i, "/connect/ai"],
  [/journal|chart of accounts/i, "/accounting/journals"],
  [/spending|cheaper|shopping/i, "/spending"],
  [/personal/i, "/personal"],
  [/jobs|timesheet/i, "/jobs"],
  [/settings|autopilot|outlook|stagger|vat scheme/i, "/settings"],
  [/help|how it works/i, "/how-it-works"],
  [/home|dashboard|summary/i, "/"],
];

export interface Placeholder {
  guide: string;
  n: number;
  line: number;
  raw: string;
  alt: string;
  step: string;
  page?: string;
  target?: string;
  full: boolean;
}

const PATTERNS: RegExp[] = [
  /^!\[(?<alt>[^\]]*)\]\((?<src>img\/[^)\s]+\.png)\)\s*$/,
  /^<!--\s*screenshot\s*:?\s*(?<alt>.*?)\s*-->\s*$/i,
  /^!?\[\s*screenshot(?:\s+placeholder)?\s*:\s*(?<alt>[^\]]*)\](?:\(\s*\))?\s*$/i,
  /^>\s*(?:📸|🖼️|\[!NOTE\])?\s*\**screenshot\**\s*:\s*(?<alt>.+)$/i,
  /^(?:TODO|TBD)\s*:?\s*screenshot\s*:?\s*(?<alt>.+)$/i,
];

function hint(text: string, key: string): string | undefined {
  const m = new RegExp(`${key}=(?:"([^"]+)"|“([^”]+)”|(\\S+))`).exec(text);
  return m ? (m[1] ?? m[2] ?? m[3]) : undefined;
}

/** The nearest preceding non-blank lines that are not placeholders: the step the picture belongs to. */
function stepText(lines: string[], i: number): string {
  const out: string[] = [];
  for (let j = i - 1; j >= 0 && out.length < 3; j--) {
    const l = lines[j]!.trim();
    if (!l) {
      if (out.length) break;
      continue;
    }
    if (PATTERNS.some((p) => p.test(l))) break;
    out.unshift(l);
    if (/^(\d+\.|[-*])\s/.test(l) || /^#/.test(l)) break;
  }
  return out.join(" ");
}

export function findPlaceholders(file: string): Placeholder[] {
  const guide = path.basename(file, ".md");
  const lines = readFileSync(file, "utf8").split(/\r?\n/);
  const out: Placeholder[] = [];
  lines.forEach((line, i) => {
    const t = line.trim().replace(/^(\d+\.|[-*])\s+/, "");
    for (const p of PATTERNS) {
      const m = p.exec(t);
      if (!m) continue;
      const alt = (m.groups?.alt ?? "").trim();
      const text = alt.replace(/\s*(page|target|crop)=(?:"[^"]*"|“[^”]*”|\S+)/g, "").trim();
      out.push({
        guide,
        n: out.length + 1,
        line: i,
        raw: line,
        alt: text || `Step ${out.length + 1}`,
        step: stepText(lines, i),
        page: hint(alt, "page"),
        target: hint(alt, "target"),
        full: hint(alt, "crop") === "full",
      });
      break;
    }
  });
  return out;
}

function pickPage(p: Placeholder, title: string): string {
  if (p.page) return p.page;
  for (const text of [`${p.alt} ${p.step}`, `${title} ${p.guide}`]) for (const [re, route] of ROUTES) if (re.test(text)) return route;
  return "/";
}

/** Control names the step mentions: **bold**, “quoted”, "quoted", `code`, longest first. */
export function candidates(p: Placeholder): string[] {
  if (p.target) return [p.target];
  const text = `${p.step} ${p.alt}`;
  const found = new Set<string>();
  for (const re of [/\*\*([^*]{2,60})\*\*/g, /“([^”]{2,60})”/g, /"([^"]{2,60})"/g, /`([^`]{2,60})`/g, /‘([^’]{2,60})’/g]) {
    for (const m of text.matchAll(re)) found.add(m[1]!.trim().replace(/[.,:;]$/, ""));
  }
  return [...found].filter((s) => !/^(page|target|crop)=/.test(s)).sort((a, b) => b.length - a.length);
}

async function locate(page: Page, names: string[]): Promise<Locator | null> {
  for (const name of names) {
    const exact = { name, exact: true };
    const tries: Locator[] = [
      page.getByRole("button", exact),
      page.getByRole("link", exact),
      page.getByRole("tab", exact),
      page.getByRole("radio", { name }),
      page.getByRole("checkbox", { name }),
      page.getByLabel(name, { exact: true }),
      page.getByRole("heading", { name }),
      page.getByRole("button", { name }),
      page.getByRole("link", { name }),
      page.getByRole("region", { name }),
      page.getByText(name, { exact: true }),
      page.getByText(name),
    ];
    for (const l of tries) {
      const first = l.first();
      if ((await first.count()) && (await first.isVisible().catch(() => false))) return first;
    }
  }
  return null;
}

async function shoot(page: Page, p: Placeholder, title: string, out: string): Promise<{ route: string; target: string | null }> {
  const route = pickPage(p, title);
  await page.goto(route);
  await page.getByRole("heading", { level: 1 }).first().waitFor({ timeout: 60_000 }).catch(() => undefined);
  await page.waitForLoadState("networkidle").catch(() => undefined);
  if (route === "/vat") {
    const jul = page.getByRole("radiogroup", { name: "VAT period" }).getByRole("radio", { name: /Jul–Sep 2026/ });
    if (await jul.count()) await jul.click();
  }
  const names = candidates(p);
  const target = names.length ? await locate(page, names) : null;
  const vp = page.viewportSize()!;
  let clip = { x: 0, y: 0, width: vp.width, height: vp.height };
  if (target) {
    await target.evaluate((el) => el.scrollIntoView({ block: "center", inline: "nearest" }));
    await page.waitForTimeout(300);
    const box = (await target.boundingBox())!;
    // The highlight: a teal box drawn over the page (pointer-events off), removed after the shot.
    await page.evaluate((b) => {
      const d = document.createElement("div");
      d.id = "__howto_hl";
      const pad = 6;
      Object.assign(d.style, {
        position: "fixed", left: `${b.x - pad}px`, top: `${b.y - pad}px`, width: `${b.width + 2 * pad}px`, height: `${b.height + 2 * pad}px`,
        border: "4px solid #E8A33D", borderRadius: "10px", boxShadow: "0 0 0 4px rgba(232,163,61,.25)", zIndex: "2147483647", pointerEvents: "none",
      });
      document.documentElement.appendChild(d);
    }, box);
    if (!p.full) {
      // Crop to two thirds of the viewport round the control (keeps the 16:10 shape), unless the control is bigger.
      const w = Math.max(Math.round(vp.width * 0.667), Math.min(vp.width, box.width + 160));
      const h = Math.round((w * vp.height) / vp.width);
      const x = Math.min(Math.max(0, box.x + box.width / 2 - w / 2), vp.width - w);
      const y = Math.min(Math.max(0, box.y + box.height / 2 - h / 2), vp.height - h);
      clip = { x, y, width: w, height: h };
    }
  }
  const tmp = `${out}.tmp.png`;
  await page.screenshot({ path: tmp, clip, animations: "disabled", caret: "hide" });
  await page.evaluate(() => document.getElementById("__howto_hl")?.remove());
  // Every image is exactly 1440 × 900 (the crop is taken at 2× and scaled).
  await new Promise<void>((resolve, reject) => {
    const ff = spawn("ffmpeg", ["-y", "-loglevel", "error", "-i", tmp, "-vf", "scale=1440:900:flags=lanczos", "-pred", "mixed", out], { stdio: "inherit" });
    ff.on("exit", (c) => (c === 0 ? resolve() : reject(new Error(`ffmpeg ${c}`))));
  });
  rmSync(tmp, { force: true });
  return { route, target: target ? names.join(" | ") : null };
}

async function main(): Promise<void> {
  const argv = process.argv.slice(2);
  const only = argv.includes("--only") ? argv[argv.indexOf("--only") + 1]!.split(",") : null;
  const dry = argv.includes("--dry-run");
  if (!existsSync(HOWTO)) {
    console.log("no docs/howto yet");
    return;
  }
  const guides = readdirSync(HOWTO).filter((f) => f.endsWith(".md") && f !== "README.md" && (!only || only.includes(f.replace(/\.md$/, ""))));
  const plan = guides.map((f) => ({ file: path.join(HOWTO, f), ph: findPlaceholders(path.join(HOWTO, f)) }));
  for (const g of plan) {
    const title = /^#\s+(.*)$/m.exec(readFileSync(g.file, "utf8"))?.[1] ?? g.file;
    for (const p of g.ph) console.log(`${p.guide}-${p.n}  ${pickPage(p, title).padEnd(16)} [${candidates(p).join(" | ")}]  ${p.alt.slice(0, 60)}`);
  }
  if (dry) return;
  mkdirSync(IMG, { recursive: true });
  const kids = await servers();
  const browser: Browser = await launch();
  const ctx = await browser.newContext({ baseURL: WEB_URL, viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, locale: "en-GB", timezoneId: "Europe/London", colorScheme: "light" });
  await ctx.addInitScript(`(() => { const add = () => { const s = document.createElement("style"); s.textContent = "nextjs-portal{display:none!important} ::-webkit-scrollbar{width:0!important;height:0!important} section[aria-labelledby=home-summary]{display:none!important}"; (document.head||document.documentElement).appendChild(s); }; if (document.documentElement) add(); else document.addEventListener("DOMContentLoaded", add); })();`);
  const page = await ctx.newPage();
  page.setDefaultTimeout(20_000);
  const report: string[] = [];
  try {
    for (const g of plan) {
      if (!g.ph.length) continue;
      const text = readFileSync(g.file, "utf8");
      const title = /^#\s+(.*)$/m.exec(text)?.[1] ?? g.file;
      // A fresh demo per guide, so one guide's approvals do not change the next one's screens.
      const judges = /judges|no sign-in/i.test(`${title} ${g.ph[0]!.guide}`);
      if (!judges) {
        await page.goto("/judges");
        await page.getByRole("button", { name: "Start the demo" }).click();
        await page.waitForURL(/\/review$/, { timeout: 300_000 });
      }
      const lines = text.split(/\r?\n/);
      for (const p of g.ph) {
        const name = `${p.guide}-${p.n}.png`;
        try {
          const r = await shoot(page, p, title, path.join(IMG, name));
          report.push(`${name}  ${r.route}  ${r.target ?? "(no control found: whole view)"}`);
        } catch (e) {
          report.push(`${name}  FAILED ${e instanceof Error ? e.message.split("\n")[0] : e}`);
          continue;
        }
        const indent = /^(\s*(?:\d+\.|[-*])?\s*)/.exec(p.raw)![1]!;
        lines[p.line] = `${indent}![${p.alt.replace(/[[\]]/g, "")}](img/${name})`;
      }
      writeFileSync(g.file, lines.join("\n"));
    }
  } finally {
    await browser.close();
    for (const k of kids) k.kill();
  }
  console.log(report.join("\n"));
  if (report.some((r) => r.includes("FAILED"))) process.exitCode = 1;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((e) => {
    console.error(e);
    process.exit(1);
  });
}
