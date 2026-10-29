/**
 * Silent, timed footage for the judges' video and the short feature clips, captured from the test-mode build against
 * the demo sandbox (the fictional Bramblewood Joinery Ltd, every document labelled "SAMPLE — FICTIONAL COMPANY").
 *
 *   node tools/video/capture.ts                       # build (submission mode), start servers, every shot
 *   node tools/video/capture.ts --skip-build          # reuse apps/web/out-e2e
 *   node tools/video/capture.ts --only judges-04,clip-review-01 --skip-build
 *   node tools/video/capture.ts --sequence judges     # or: clips
 *   node tools/video/capture.ts --plan                # print the shot → flow plan and exit
 *
 * Reads docs/video/JUDGES_VIDEO.md (else docs/submission/VIDEO_SCRIPT.md) and docs/video/CLIPS.md (else the built-in
 * DEFAULT_CLIPS below). Writes docs/video/raw/<shot-id>.webm (git-ignored), docs/video/manifest.json and
 * docs/video/contact-sheet-<sequence>.png. Judges' shots are 1920 × 1080 (a 1280 × 720 viewport at 1.5×); clips are
 * 1080 × 1920 (360 × 640 at 3×, phone emulation). Needs Node 22.18+ (runs TypeScript directly), ffmpeg, and the
 * runtime's Python (E2E_PYTHON or .venv/bin/python).
 */
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Browser, BrowserContext, Page } from "@playwright/test";
import { chooseFlow, FLOWS, SHOT_PLAN, type FlowCtx } from "./flows.ts";
import { CLEAN_CSS, CURSOR_SCRIPT, Human } from "./lib/human.ts";
import { Recorder } from "./lib/recorder.ts";
import { parseScript, type ScriptShot, type Sequence } from "./lib/script.ts";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "../..");
const WEB = path.join(ROOT, "apps/web");
const OUT = path.join(ROOT, "docs/video");
const RAW = path.join(OUT, "raw");
const require = createRequire(path.join(WEB, "package.json"));
const { chromium } = require("@playwright/test") as typeof import("@playwright/test");

const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 3100);
const RUNTIME_PORT = Number(process.env.E2E_RUNTIME_PORT ?? 8781);
const WEB_URL = `http://127.0.0.1:${WEB_PORT}`;
const RUNTIME_URL = `http://127.0.0.1:${RUNTIME_PORT}`;

export const FORMATS = {
  landscape: { width: 1920, height: 1080, viewport: { width: 1280, height: 720 }, scale: 1.5, phone: false },
  portrait: { width: 1080, height: 1920, viewport: { width: 360, height: 640 }, scale: 3, phone: true },
} as const;
type FormatName = keyof typeof FORMATS;

/**
 * Used until Muse's docs/video/CLIPS.md lands: short vertical clips, one feature each. Same table shape as the scripts
 * (see tools/video/lib/script.ts); captions and voice-over are placeholders for the real script.
 */
const DEFAULT_CLIPS: Sequence[] = [
  ["clip-review", "Review and approve", [["review-approve", 12, "AI proposes · code checks · you approve"], ["needs-a-look", 8, "Checks failed → Needs a look, nothing posted"]]],
  ["clip-vat", "VAT return by code", [["vat-return", 10, "9 VAT boxes, calculated by code"], ["hmrc-sim", 14, "Submit flow · simulated in the demo, HMRC sandbox for real"]]],
  ["clip-ask", "Ask your books", [["ask-vat", 14, "Every figure checked against your books"]]],
  ["clip-month-end", "Month-end close", [["month-end", 14, "One button runs the close · you approve each card"]]],
  ["clip-judges", "Try it with no sign-in", [["judges", 12, "accnomos.com/judges · fictional sample data"]]],
].map(([id, title, shots]) => ({
  id: id as string,
  title: title as string,
  shots: (shots as [string, number, string][]).map(([flow, duration, caption], i) => ({
    id: `${id}-${String(i + 1).padStart(2, "0")}`,
    sequence: id as string,
    index: i + 1,
    duration,
    what: FLOWS[flow]!.about,
    caption,
    vo: "",
    flow,
  })),
}));

interface Args {
  only: Set<string> | null;
  sequence: "judges" | "clips" | null;
  skipBuild: boolean;
  plan: boolean;
}

function args(): Args {
  const a = process.argv.slice(2);
  const val = (k: string) => {
    const i = a.indexOf(k);
    return i >= 0 ? a[i + 1] : undefined;
  };
  const only = val("--only");
  const seq = val("--sequence");
  return {
    only: only ? new Set(only.split(",").map((s) => s.trim())) : null,
    sequence: seq === "judges" || seq === "clips" ? seq : null,
    skipBuild: a.includes("--skip-build"),
    plan: a.includes("--plan"),
  };
}

/** The judges' script (one sequence, id "judges") and the clips (one sequence each, portrait). */
export function loadSequences(): { seq: Sequence; format: FormatName; source: string }[] {
  const out: { seq: Sequence; format: FormatName; source: string }[] = [];
  const judgesFile = [path.join(OUT, "JUDGES_VIDEO.md"), path.join(ROOT, "docs/submission/VIDEO_SCRIPT.md")].find(existsSync);
  if (judgesFile) {
    const first = parseScript(judgesFile, "judges")[0];
    if (first) {
      const shots = first.shots.map((s, i): ScriptShot => {
        const keep = !/^\d/.test(s.id) && !s.id.startsWith(`${first.id}-`);
        return { ...s, sequence: "judges", id: keep ? s.id : `judges-${String(i + 1).padStart(2, "0")}` };
      });
      out.push({ seq: { id: "judges", title: first.title, shots }, format: "landscape", source: path.relative(ROOT, judgesFile) });
    }
  }
  const clipsFile = path.join(OUT, "CLIPS.md");
  const clips = existsSync(clipsFile) ? parseScript(clipsFile, "clip") : DEFAULT_CLIPS;
  for (const seq of clips) {
    out.push({ seq, format: "portrait", source: existsSync(clipsFile) ? "docs/video/CLIPS.md" : "tools/video/capture.ts (DEFAULT_CLIPS)" });
  }
  return out;
}

async function up(url: string): Promise<boolean> {
  try {
    return (await fetch(url)).ok;
  } catch {
    return false;
  }
}

async function waitUp(url: string, ms: number): Promise<void> {
  const until = Date.now() + ms;
  while (Date.now() < until) {
    if (await up(url)) return;
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`${url} did not come up`);
}

/** The e2e runtime (test mode, DEMO_MODE=1) and the static server, unless they are already running. */
export async function servers(): Promise<ChildProcess[]> {
  const kids: ChildProcess[] = [];
  if (!(await up(`${RUNTIME_URL}/health`))) {
    const py = process.env.E2E_PYTHON ?? [path.join(ROOT, ".venv/bin/python"), path.join(ROOT, ".venv/Scripts/python.exe")].find(existsSync) ?? "python3";
    kids.push(
      spawn(py, ["-m", "uvicorn", "app.main:app", "--app-dir", "../../services/runtime", "--host", "127.0.0.1", "--port", String(RUNTIME_PORT), "--no-access-log"], {
        cwd: WEB,
        stdio: "ignore",
        env: {
          ...process.env,
          ACCNOMOS_TEST_MODE: "1",
          PORT: String(RUNTIME_PORT),
          CORS_ORIGINS: WEB_URL,
          RATE_LIMIT_PER_MIN: "0",
          DEMO_MODE: "1",
          DEMO_SECRET: "video-capture-only-demo-secret-not-for-production",
          DEMO_SESSIONS_PER_IP_PER_MIN: "0",
          DEMO_GRAPH_PER_MIN: "0",
          AI_PROVIDERS: "modal,meta,spark",
          PUBLIC_CHAT_PER_MIN: "0",
        },
      }),
    );
  }
  if (!(await up(WEB_URL))) kids.push(spawn("node", ["e2e/serve.mjs"], { cwd: WEB, stdio: "ignore" }));
  await waitUp(`${RUNTIME_URL}/health`, 120_000);
  await waitUp(WEB_URL, 60_000);
  // The demo's sample books are seeded in the background after the first /health: wait for them off camera.
  const until = Date.now() + 600_000;
  while (Date.now() < until) {
    const h = (await (await fetch(`${RUNTIME_URL}/health`)).json()) as { demo?: { ready?: boolean } };
    if (h.demo?.ready) break;
    await new Promise((r) => setTimeout(r, 1000));
  }
  return kids;
}

export async function launch(): Promise<Browser> {
  try {
    return await chromium.launch();
  } catch (e) {
    // Cloud containers ship one Chromium for any Playwright version.
    if (existsSync("/opt/pw-browsers/chromium")) return chromium.launch({ executablePath: "/opt/pw-browsers/chromium" });
    throw e;
  }
}

async function newContext(browser: Browser, format: FormatName): Promise<BrowserContext> {
  const f = FORMATS[format];
  const ctx = await browser.newContext({
    baseURL: WEB_URL,
    viewport: f.viewport,
    deviceScaleFactor: f.scale,
    isMobile: f.phone,
    hasTouch: f.phone,
    locale: "en-GB",
    timezoneId: "Europe/London",
    colorScheme: "light",
    reducedMotion: "no-preference",
  });
  await ctx.addInitScript(CURSOR_SCRIPT);
  await ctx.addInitScript(`(() => {
    const css = ${JSON.stringify(CLEAN_CSS + HIDE_TEST_ONLY)};
    const add = () => { const s = document.createElement("style"); s.textContent = css; (document.head || document.documentElement).appendChild(s); };
    if (document.documentElement) add(); else document.addEventListener("DOMContentLoaded", add);
  })();`);
  return ctx;
}

/**
 * Test-mode-only text hidden from captures: Home's summary card, which in test mode reads "Test stub summary … (accnomos-test-stub)"
 * because no model runs. Nothing a real user sees is hidden; docs/video/README.md lists this.
 */
const HIDE_TEST_ONLY = `section[aria-labelledby="home-summary"] { display: none !important; }`;

/** A fresh demo session for this context, off camera: /judges → Start the demo → Review. */
async function startDemo(page: Page): Promise<void> {
  await page.goto("/judges");
  await page.getByRole("button", { name: "Start the demo" }).click();
  await page.waitForURL(/\/review$/, { timeout: 300_000 });
  await page.getByRole("complementary", { name: "Demo sandbox" }).waitFor({ timeout: 60_000 });
}

export interface ManifestShot {
  id: string;
  sequence: string;
  index: number;
  duration: number;
  recorded: number | null;
  flow: string;
  kind: "app" | "card" | "camera";
  what: string;
  caption: string;
  vo: string;
  vo_wav: string;
  /** Card text (provenance, eval table) and an end card drawn over the shot's last seconds. */
  card?: string;
  end_card?: string;
  /** Why this shot must be re-filmed live; the footage, if any, is a test-mode stand-in. */
  live?: string;
  file: string | null;
  status: "ok" | "failed" | "card" | "skipped";
  error?: string;
}

async function captureShot(browser: Browser, format: FormatName, shot: ScriptShot): Promise<ManifestShot> {
  const flowName = chooseFlow(shot);
  const flow = FLOWS[flowName]!;
  const kind = flow.kind ?? "app";
  const base: ManifestShot = {
    id: shot.id,
    sequence: shot.sequence,
    index: shot.index,
    duration: shot.duration,
    recorded: null,
    flow: flowName,
    kind,
    what: shot.what,
    caption: shot.caption,
    vo: shot.vo,
    vo_wav: `docs/video/vo/${shot.id}.wav`,
    card: shot.card,
    end_card: shot.endCard,
    live: SHOT_PLAN[shot.id]?.live,
    file: null,
    status: kind === "app" ? "ok" : "card",
  };
  if (kind !== "app") return base;
  const f = FORMATS[format];
  const ctx = await newContext(browser, format);
  const page = await ctx.newPage();
  page.setDefaultTimeout(20_000);
  const h = new Human(page, f.phone);
  h.pace = SHOT_PLAN[shot.id]?.pace ?? 1;
  const c: FlowCtx = { page, h, phone: f.phone, receipt: path.join(WEB, "public/sample-receipt.png") };
  const rec = new Recorder(ctx, page, { width: f.width, height: f.height });
  const file = path.join(RAW, `${shot.id}.webm`);
  let recording = false;
  try {
    if (!flow.signedOut) await startDemo(page);
    await flow.setup?.(c);
    await h.park(f.viewport.width * 0.62, f.viewport.height * 0.55);
    await page.waitForTimeout(400); // fonts and late layout settle off camera
    await rec.start(path.join(RAW, `.frames-${shot.id}`));
    recording = true;
    const t0 = Date.now();
    await flow.run?.(c);
    const left = shot.duration * 1000 - (Date.now() - t0);
    if (left > 0) await page.waitForTimeout(Math.min(left, 400)); // the rest is held as the last frame
    recording = false;
    const recorded = await rec.stop(file, shot.duration);
    return { ...base, recorded: Math.round(recorded * 100) / 100, file: path.relative(ROOT, file) };
  } catch (e) {
    const msg = e instanceof Error ? e.message.split("\n").filter((l) => l.trim() && !/^Call log:/.test(l)).slice(0, 2).join(" ").replace(/\s+/g, " ").slice(0, 300) : String(e);
    if (recording) {
      try {
        const recorded = await rec.stop(file, shot.duration);
        return { ...base, recorded, file: path.relative(ROOT, file), status: "failed", error: msg };
      } catch {
        /* nothing usable */
      }
    }
    return { ...base, status: "failed", error: msg };
  } finally {
    await ctx.close();
  }
}

function contactSheet(seqId: string, shots: ManifestShot[], format: FormatName): void {
  const py = [path.join(ROOT, ".venv/bin/python"), path.join(ROOT, ".venv/Scripts/python.exe")].find(existsSync) ?? "python3";
  const r = spawnSync(py, [path.join(HERE, "contact_sheet.py"), "--sequence", seqId, "--format", format, "--manifest", path.join(OUT, "manifest.json")], {
    stdio: "inherit",
  });
  if (r.status !== 0) console.warn(`contact sheet for ${seqId} failed`);
}

async function main(): Promise<void> {
  const a = args();
  const plan = loadSequences().filter((s) => !a.sequence || (a.sequence === "judges" ? s.seq.id === "judges" : s.seq.id !== "judges"));
  if (a.plan) {
    for (const { seq, format, source } of plan) {
      console.log(`\n${seq.id} (${format}, ${seq.shots.reduce((t, s) => t + s.duration, 0)} s) from ${source}`);
      for (const s of seq.shots) console.log(`  ${s.id.padEnd(22)} ${String(s.duration).padStart(4)} s  ${chooseFlow(s).padEnd(16)} ${s.what.slice(0, 70)}`);
    }
    return;
  }
  mkdirSync(RAW, { recursive: true });
  if (!a.skipBuild) {
    const b = spawnSync("pnpm", ["run", "e2e:build"], { cwd: WEB, stdio: "inherit", env: { ...process.env, NEXT_PUBLIC_SUBMISSION_MODE: "1" }, shell: process.platform === "win32" });
    if (b.status !== 0) throw new Error("e2e:build failed");
  }
  const kids = await servers();
  const browser = await launch();
  const manifestPath = path.join(OUT, "manifest.json");
  const old = existsSync(manifestPath) ? (JSON.parse(readFileSync(manifestPath, "utf8")) as Manifest) : null;
  const manifest: Manifest = {
    note: "Silent footage from the test-mode build (NEXT_PUBLIC_SUBMISSION_MODE=1) on the demo sandbox's fictional sample books. AI readings in it come from the test-mode stub, not a live model. Regenerate: tools/video/regenerate.sh",
    generated: new Date().toISOString(),
    sequences: [],
  };
  try {
    for (const { seq, format, source } of plan) {
      const shots: ManifestShot[] = [];
      for (const s of seq.shots) {
        const prev = old?.sequences.find((q) => q.id === seq.id)?.shots.find((x) => x.id === s.id);
        if (a.only && !a.only.has(s.id) && !a.only.has(seq.id)) {
          // Not re-recorded this run: keep what the last run wrote, with this script's words and timing.
          shots.push(prev ? { ...prev, duration: s.duration, caption: s.caption, vo: s.vo, what: s.what, card: s.card, end_card: s.endCard, live: SHOT_PLAN[s.id]?.live } : { ...(await captureShot(browser, format, { ...s, flow: "card" })), status: "skipped" });
          continue;
        }
        process.stdout.write(`${s.id} … `);
        const m = await captureShot(browser, format, s);
        console.log(`${m.status}${m.recorded ? ` ${m.recorded.toFixed(1)} s / ${m.duration} s` : ""}${m.error ? ` (${m.error})` : ""}`);
        shots.push(m);
      }
      const f = FORMATS[format];
      manifest.sequences.push({ id: seq.id, title: seq.title, source, format, width: f.width, height: f.height, duration: shots.reduce((t, s) => t + s.duration, 0), shots });
    }
    // Keep sequences this run did not touch.
    for (const q of old?.sequences ?? []) if (!manifest.sequences.some((s) => s.id === q.id)) manifest.sequences.push(q);
    writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + "\n");
    for (const s of manifest.sequences) if (plan.some((p) => p.seq.id === s.id)) contactSheet(s.id, s.shots, s.format);
  } finally {
    await browser.close();
    for (const k of kids) k.kill();
  }
  const failed = manifest.sequences.flatMap((s) => s.shots).filter((s) => s.status === "failed");
  if (failed.length) {
    console.error(`\n${failed.length} shot(s) failed: ${failed.map((s) => `${s.id} (${s.error})`).join("; ")}`);
    process.exitCode = 1;
  }
}

export interface Manifest {
  note: string;
  generated: string;
  sequences: { id: string; title: string; source: string; format: FormatName; width: number; height: number; duration: number; shots: ManifestShot[] }[];
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((e) => {
    console.error(e);
    process.exit(1);
  });
}
