/**
 * Headline numbers of the committed eval runs (evals/runs/*), read from their summary files at build time, so the
 * /models page cannot drift from what the runs recorded. Server-only: imported by app/models/page.tsx alone.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

export const REPO = "https://github.com/zaytunazs/accnomos/blob/main";
const RUNS = join(process.cwd(), "..", "..", "evals", "runs");

export interface EvalHeadline {
  run: string;
  title: string;
  model: string;
  where: string;
  numbers: { label: string; value: string }[];
  report: string; // link to the committed report
}

type Json = Record<string, unknown>;

/** One committed run file, parsed; null when this checkout lacks it. */
export function readRun(run: string, file: string): Json | null {
  try {
    return JSON.parse(readFileSync(join(RUNS, run, file), "utf8")) as Json;
  } catch {
    return null; // a run missing from this checkout is left off the page, never invented
  }
}

const pct = (x: unknown) => (typeof x === "number" ? `${Math.round(x * 100)} %` : "n/a");
const num = (x: unknown) => (typeof x === "number" ? String(x) : "n/a");

function where(cfg: unknown): string {
  const url = typeof cfg === "object" && cfg && "base_url" in cfg ? String((cfg as Json).base_url) : "";
  if (url.includes("modal.run")) return "Modal";
  if (url.includes("baseten")) return "hosted open weights";
  if (url.includes("localhost") || url.includes("127.0.0.1")) return "our own server";
  return "Meta Model API";
}

function extraction(run: string, title: string): EvalHeadline | null {
  const s = readRun(run, "summary.json");
  if (!s) return null;
  const cfg = s.config as Json | undefined;
  const fields = (s.field_accuracy ?? {}) as Json;
  return {
    run,
    title,
    model: String(cfg?.model ?? "").includes("glimmer") ? "Muse Glimmer 30B" : "Muse Spark Open",
    where: where(cfg),
    numbers: [
      { label: "Documents", value: num(s.n) },
      { label: "Every field right", value: pct(s.all_fields_correct) },
      { label: "Proposed vs Needs a look right", value: pct(fields.status) },
      { label: "Mean per document", value: typeof s.mean_elapsed_s === "number" ? `${s.mean_elapsed_s} s` : "n/a" },
    ],
    report: `${REPO}/evals/runs/${run}/report.md`,
  };
}

function ask(): EvalHeadline | null {
  const r = readRun("ask_40", "result.json");
  const g = (r?.glimmer as Json | undefined)?.summary as Json | undefined;
  if (!g) return null;
  return {
    run: "ask_40",
    title: "Ask: 35 questions over the seeded books",
    model: "Muse Glimmer 30B",
    where: "host not recorded in the run",
    numbers: [
      { label: "Numbers exact", value: `${num(g.numbers_exact)}/${num(g.with_gold)}` },
      { label: "Invented figures shown", value: num(g.shipped_invented) },
      { label: "Citations present", value: `${num(g.citation_present)}/${num(g.with_gold)}` },
      { label: "Median per question", value: `${num(g.median_seconds)} s` },
    ],
    report: `${REPO}/evals/runs/ask_40/report.md`,
  };
}

function autopilot(): EvalHeadline | null {
  const s = readRun("autopilot_l2", "summary.json");
  const on = s?.on as Json | undefined;
  const all = on?.all as Json | undefined;
  const clean = on?.without_seeded_copies as Json | undefined;
  if (!all) return null;
  return {
    run: "autopilot_l2",
    title: "Autopilot: documents posted without a person",
    model: "Muse Glimmer 30B",
    where: where((on?.meta as Json | undefined)?.config),
    numbers: [
      { label: "Documents", value: num(all.docs) },
      { label: "Posted", value: num(all.would_post) },
      { label: "False posts", value: `${num(all.false_posts)} (${pct(all.false_post_rate)})` },
      { label: "Without the seeded copies", value: `${num(clean?.false_posts)} (${pct(clean?.false_post_rate)})` },
    ],
    report: `${REPO}/evals/runs/autopilot_l2/report.md`,
  };
}

/** Every headline we can read, in the order the page shows them. */
export function evalHeadlines(): EvalHeadline[] {
  return [
    extraction("spark_open_200", "Receipts and invoices, 200 clean"),
    extraction("spark_open_messy_200", "Receipts and invoices, 200 messy"),
    extraction("glimmer_200_v2", "Receipts and invoices, 200 clean"),
    extraction("glimmer_messy_200_v2", "Receipts and invoices, 200 messy"),
    ask(),
    autopilot(),
  ].filter((e): e is EvalHeadline => e !== null);
}
