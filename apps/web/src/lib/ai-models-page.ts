/**
 * The public /ai-models page: which AI model does which job in Accnomos, how it is called, what code checks
 * after it, and what the committed eval runs measured. Server-only (app/ai-models/page.tsx): the figures are read
 * from evals/runs/<run>/summary.json (or result.json) when the site is built, so they cannot drift from the runs.
 *
 * Built from the code (checked 29 Oct 2026): services/runtime/app/ai/{config,providers,chain,extract,verify,ask,
 * cis_read,property_read,home_summary,close_summary,spending,triage,remind,plan,items,duplicates,stt,voice,crop}.py,
 * app/{actions,bank_reconcile,cashflow,public_chat}.py and tools/brand_muse.py. docs/AI_MODELS.md
 * carries the same facts; keep the two in step.
 *
 * Wording rules for this page: models are named by what they are ("the hosted model", "the local open-weights
 * model"), never by vendor or product name. No hardware, and no other company's tools or engines. The submission
 * build's rule (no launch or "coming soon" words) applies too (e2e/ai-models-page.spec.ts checks both).
 */
import { readRun, REPO } from "./evals";

type Json = Record<string, unknown>;

export interface Result {
  /** What was measured, in plain words. */
  label: string;
  /** The headline figure(s). */
  value: string;
  /** "27 Oct 2026 · 200 documents" */
  basis: string;
  /** A few words for the overview table, or null when nothing was measured. */
  short?: string | null;
  /** The committed report, or null when nothing has been run yet. */
  report: string | null;
}

export interface AiModel {
  id: string; // anchor and test id
  name: string;
  modelId: string;
  what: string;
  /** One line each for the overview table. */
  uses: string;
  via: string;
  jobs: { job: string; screen: string }[];
  called: string[];
  checks: string[];
  results: Result[];
}

const pct = (x: unknown) => (typeof x === "number" ? `${Math.round(x * 100)} %` : "n/a");
const pct1 = (x: unknown) => (typeof x === "number" ? `${x} %` : "n/a");
const num = (x: unknown) => (typeof x === "number" ? String(x) : "n/a");
const report = (run: string) => `${REPO}/evals/runs/${run}/report.md`;

/** "2026-10-28T13:10:49+00:00" -> "28 Oct 2026". */
function day(iso: unknown): string | null {
  if (typeof iso !== "string" || !/^\d{4}-\d{2}-\d{2}/.test(iso)) return null;
  const d = new Date(`${iso.slice(0, 10)}T12:00:00Z`);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

/**
 * The extraction, Ask and Autopilot summaries carry no date of their own: these are the dates of the commits that
 * added them (git log -1 --format=%cs -- evals/runs/<run>).
 */
const COMMITTED: Record<string, string> = {
  spark_open_200: "27 Oct 2026",
  spark_open_messy_200: "27 Oct 2026",
  glimmer_200_v2: "27 Oct 2026",
  glimmer_messy_200_v2: "27 Oct 2026",
  ask_40: "27 Oct 2026",
  autopilot_l2: "27 Oct 2026",
  mail_intake: "27 Oct 2026",
  spark13_200: "4 Nov 2026",
  spark13_messy_200: "4 Nov 2026",
};

/** Live checks against the live API in a demo session (evals/harness/live_checks.py), and the live crop run. */
const LIVE_CHECKS = report("live_checks_2026-11-04");
const SAM_LIVE = report("sam_crop_live");

function extraction(run: string, label: string): Result | null {
  const s = readRun(run, "summary.json");
  if (!s) return null;
  const v = (s.verification ?? {}) as Json;
  const o = (v.doc_outcomes ?? {}) as Json;
  const checker =
    typeof v.verifier === "string"
      ? `; second reading caught ${num(o.disagreed_and_extractor_wrong)} wrong reading(s), missed ${num(o.agreed_but_extractor_wrong)}, raised ${num(o.disagreed_but_extractor_right)} false alarm(s)`
      : "";
  return {
    label,
    value: `every field right ${pct(s.all_fields_correct)}${checker}`,
    short: `${label.toLowerCase().includes("messy") ? "messy" : "clean"} documents ${pct(s.all_fields_correct)}`,
    basis: `${COMMITTED[run] ?? "date not recorded"} · ${num(s.n)} documents`,
    report: report(run),
  };
}

/** A reader run with its own `generated` date and `all_exact_pct` (CIS, property). */
function reader(run: string, label: string, unit: string): Result | null {
  const s = readRun(run, "summary.json");
  if (!s || s.stub === true) return null;
  return {
    label,
    value: `every figure exact ${pct1(s.all_exact_pct)}`,
    short: `${label.split(" ")[0] === "CIS" ? "CIS" : "property"} ${pct1(s.all_exact_pct)}`,
    basis: `${day(s.generated) ?? "date not recorded"} · ${num(s.docs)} ${unit}`,
    report: report(run),
  };
}

function ask(): Result | null {
  const g = ((readRun("ask_40", "result.json")?.glimmer as Json | undefined)?.summary ?? null) as Json | null;
  if (!g) return null;
  return {
    label: "Ask: figures in the answer",
    short: `Ask figures ${num(g.numbers_exact)}/${num(g.with_gold)}`,
    value: `${num(g.numbers_exact)}/${num(g.with_gold)} exact; ${num(g.shipped_invented)} invented figures reached the user; ${num(g.cards_right_kind)}/${num(g.instructions)} instructions became the right action card`,
    basis: `${COMMITTED.ask_40} · ${num(g.questions)} questions and ${num(g.instructions)} instructions`,
    report: report("ask_40"),
  };
}

function autopilot(): Result | null {
  const all = (((readRun("autopilot_l2", "summary.json")?.on as Json | undefined)?.all ?? null) as Json | null);
  if (!all) return null;
  return {
    label: "Autopilot: posted without a person",
    value: `${num(all.false_posts)} false posts in ${num(all.docs)} (${pct1(Math.round(Number(all.false_post_rate) * 1000) / 10)}), all of them documents already in the books fed again`,
    basis: `${COMMITTED.autopilot_l2} · ${num(all.docs)} documents`,
    report: report("autopilot_l2"),
  };
}

function triage(): Result | null {
  const t = (readRun("mail_intake", "result.json")?.triage ?? null) as Json | null;
  if (!t) return null;
  return {
    label: "Inbox triage: category of each thread",
    value: `${num(t.category_ok)}/${num(t.category_scored)} right; ${num(t.model_failures)} model failures`,
    basis: `${COMMITTED.mail_intake} · ${num(t.threads)} threads`,
    report: report("mail_intake"),
  };
}

/** evals/harness/bank_ai.py writes evals/runs/bank_ai/; until it has been run against a real model, say so. */
function bankCoding(): Result {
  const s = readRun("bank_ai", "summary.json");
  if (s && s.stub !== true) {
    return {
      label: "Bank line coding suggestions",
      value: `right account ${pct1(s.accuracy_pct)}; no suggestion ${pct1(s.refusal_pct)}`,
      short: `bank coding ${pct1(s.accuracy_pct)}`,
      basis: `${day(s.generated) ?? "date not recorded"} · ${num(s.scored_lines)} bank lines`,
      report: report("bank_ai"),
    };
  }
  return {
    label: "Bank line coding suggestions",
    value: "Not measured yet: the eval (evals/harness/bank_ai.py) is written and stub-tested, not yet run on a model.",
    basis: "no run committed",
    report: null,
  };
}

/** evals/harness/stt.py writes evals/runs/stt/ (synthetic speech clips, through the hosted speech-to-text model). */
function speech(): Result {
  const s = readRun("stt", "summary.json");
  const muse = ((s?.providers as Json | undefined)?.muse ?? null) as Json | null;
  if (s && muse) {
    const wer = typeof muse.corpus_wer === "number" ? `${Math.round(muse.corpus_wer * 1000) / 10} %` : "n/a";
    return {
      label: "Spoken questions to text",
      short: `word error rate ${wer}`,
      value: `word error rate ${wer}; ${
        typeof muse.amounts_accuracy_pct === "number"
          ? `amounts heard right ${pct1(muse.amounts_accuracy_pct)}`
          : `spoken numbers heard right ${pct1(muse.numbers_accuracy_pct)}, so a spoken card reads its figures back in words before you approve`
      }; ${num(muse.failures)} failures`,
      basis: `${day(s.at) ?? "date not recorded"} · ${num(muse.clips)} recordings`,
      report: report("stt"),
    };
  }
  return {
    label: "Spoken questions to text",
    value:
      "Not measured yet: the comparison eval (evals/harness/stt.py) has no committed run.",
    basis: "no run committed",
    report: null,
  };
}

/**
 * evals/harness/classify.py writes evals/runs/classify/: the upload flow's first step (what kind of document is this?)
 * through the live provider chain, so the hosted model first. Shown under the hosted model only when it answered.
 */
function classifier(): Result | null {
  const s = readRun("classify", "summary.json");
  if (!s || s.stub === true || typeof s.model !== "string" || !s.model.startsWith("muse-spark")) return null;
  return {
    label: "What kind of document is this (the upload flow's first step: receipt, bill, sales invoice, statement…)",
    value: `right type ${pct1(s.accuracy_pct)}; ${pct1(s.by_ai_pct)} answered by the model, the rest by code (bank CSVs)`,
    short: `document type ${pct1(s.accuracy_pct)}`,
    basis: `${day(s.generated) ?? "date not recorded"} · ${num(s.docs)} documents`,
    report: report("classify"),
  };
}

/** evals/harness/sam_crop_live.py writes evals/runs/sam_crop_live/: the crop model live against known boxes, then read. */
function samLive(): Result | null {
  const s = readRun("sam_crop_live", "summary.json");
  if (!s) return null;
  const sam = (s.sam ?? {}) as Json;
  const code = (s.code ?? {}) as Json;
  const rs = (s.read_sam ?? {}) as Json;
  const rc = (s.read_code ?? {}) as Json;
  const lat = (s.sam_call_latency_s ?? {}) as Json;
  return {
    label: "Crop, live on the hosted model's API",
    short: `crop overlap ${num(sam.mean_iou)}`,
    value: `a box for ${num(s.sam_box_returned)} of ${num(s.n)} photos; mean overlap ${num(sam.mean_iou)} against ${num(code.mean_iou)} for the plain-code crop; every field read right ${num(rs.all_fields_correct)}/${num(s.n)} after the model crop and ${num(rc.all_fields_correct)}/${num(s.n)} after the code crop; median ${num(lat.median)} s a call`,
    basis: "4 Nov 2026 · 20 synthetic scenes",
    report: SAM_LIVE,
  };
}

const present = (xs: (Result | null)[]) => xs.filter((x): x is Result => x !== null);

/**
 * The live server's order: AI_PROVIDERS=meta,spark from 29 Oct 2026, spark,anthropic since 11 Nov 2026 (owner's
 * decisions). The hosted GPU provider is supported by the code (app/ai/providers.py) but not deployed, so it is
 * mentioned only as an optional extra provider.
 */
const CHAIN =
  "On our live server, with no AI chosen, calls go in this order since 11 November 2026: 1st the local open-weights model on our own server; last, a backup AI provider when our server cannot answer. From 29 October to 11 November the order was: 1st the hosted model (Contributor mode for the demo and testing), last the local open-weights model. A timeout, outage or rate limit moves the call to the next; a provider that keeps failing is skipped for a while.";
const MODAL_NOTE =
  "The code also supports the local open-weights model on a hosted GPU as an optional extra provider in that order; it is not what runs live.";

/**
 * Owner's correction (29 Oct 2026): the live server ran the hosted model's Contributor tier (MODEL_API_MODEL) for the
 * demo and testers until 11 Nov 2026. The app's own key mode asks for the standard tier (lib/ai-config.ts DEFAULT_KEY).
 */
export const CONTRIBUTOR_NOTE =
  "Until 11 November 2026 our live server used the hosted model in Contributor mode for the demo and testing. In Contributor mode the model's provider may use the content sent to it to improve its models. The demo uses only fictional sample data; anyone who tried it with their own books was served the same way. Since 11 November 2026 our server sends nothing to the hosted model. With your own API key (key mode) the app asks for the hosted model's standard mode.";

const TEXT_CHECKS = [
  "AI proposes, you approve, code calculates: the model returns strict JSON or words only; every amount is worked out in pence by code, and nothing is posted, sent or kept until you approve it.",
  "Readings are checked by code: lines and totals add up, VAT maths and rates, VAT number shape, duplicates, dates. Anything that fails waits in Needs a look.",
  "Summaries and answers are checked figure by figure against facts code built from your books (the KnownNumbers check). An invented figure, or one from the wrong period, means code's own wording is shown instead, with the reason.",
];

/** The overview table's "Measured" cell: the short figures, or that nothing has been measured. */
export function measured(m: AiModel): string {
  const xs = m.results.map((r) => r.short).filter((x): x is string => !!x);
  return xs.length ? xs.join("; ") : "Not measured yet";
}

export function aiModels(): AiModel[] {
  return [
    {
      id: "hosted-model",
      name: "Hosted model",
      modelId: "hosted · Contributor mode on our server until 11 Nov 2026 · standard mode with your own key",
      uses: "Reads documents and CIS and property paperwork; answers Ask; words the summaries; bank, inbox, reminder and duplicate suggestions",
      via: "A hosted model API: 1st on our live server until 11 Nov 2026 (Contributor mode, demo and testing), or standard with your own key",
      what: "A hosted model on its provider's API: it reads images and text and replies in strict JSON. It was the first choice on our live server, in Contributor mode for the demo and testing, until 11 November 2026.",
      jobs: [
        { job: "Says what kind of document each upload is (receipt, bill, sales invoice, credit note, statement) before it is read; you confirm or change it", screen: "Upload" },
        { job: "Reads receipts, invoices, credit notes and emailed bills into a strict list (supplier, VAT number, date, lines, net, VAT, total) and suggests the category", screen: "Review" },
        { job: "The Verifier's second reading in key mode and on the server chain", screen: "Review card: “Verifier agrees”" },
        { job: "Reads CIS payment and deduction statements and reverse-charge invoices", screen: "CIS" },
        { job: "Reads letting agents' statements, property bills, insurance schedules and mortgage statements", screen: "Property" },
        { job: "Answers questions about your books, and turns typed or spoken instructions into an action card", screen: "Ask" },
        { job: "Words the summaries: Home, month-end close, spending, cash flow and the day plan", screen: "Home, Month end, Spending, Reports › Cash flow, Jobs" },
        { job: "Suggests an account and VAT code for a bank line no rule matched", screen: "Bank › Reconcile" },
        { job: "Sorts email threads and drafts a reply and to-dos; drafts payment reminders", screen: "Home inbox, Invoices" },
        { job: "Gives a view on possible duplicate contacts and on differently named items that may be the same product", screen: "Contacts, Prices" },
        { job: "Answers the website's “Ask about Accnomos” chat from our public notes only", screen: "Public website" },
      ],
      called: [
        CHAIN,
        "Key mode: the hosted model's API (/chat/completions) with your own API key, which stays on your device and is never logged.",
        CONTRIBUTOR_NOTE,
      ],
      checks: TEXT_CHECKS,
      results: present([
        classifier(),
        extraction("spark13_200", "Receipts and invoices, clean (reader and Verifier)"),
        extraction("spark13_messy_200", "Receipts and invoices, messy photos (reader and Verifier)"),
        {
          label: "Every other job",
          value: "Run live on our server, not scored against an answer key: Ask (typed and spoken), the Home summary, the goals note and the upload's document type and reading were each answered by the hosted model in a demo session. CIS, property, bank, inbox and reminder jobs are measured on the local open-weights model below.",
          basis: "4 Nov 2026 · live checks on the live server",
          report: LIVE_CHECKS,
        },
      ]),
    },
    {
      id: "local-model",
      name: "Local open-weights model",
      modelId: "open weights · on our own server or your computer",
      uses: "The same jobs as the hosted model: first on our live server since 11 Nov 2026, or for everything in local mode; most of our measured results",
      via: "Our own server, 1st on our live server since 11 Nov 2026 (last before that); or your own machine",
      what: "An open-weights model: it reads images and text and replies in strict JSON. We run the weights ourselves.",
      jobs: [
        { job: "Every hosted-model job above, when the hosted model is not used or cannot answer: reading documents, CIS and property paperwork, Ask and action cards, the summaries, bank suggestions, inbox triage, reminders, duplicates and item matches", screen: "Review, CIS, Property, Ask, Home, Month end, Spending, Bank, Invoices, Contacts, Prices" },
        { job: "All of them, when you choose local mode in Settings, including the Verifier's second reading", screen: "the same screens" },
      ],
      called: [
        CHAIN,
        MODAL_NOTE,
        "Local mode: your own machine running the local open-weights model, chosen in Settings. Documents then go only there.",
      ],
      checks: TEXT_CHECKS,
      results: present([
        extraction("glimmer_200_v2", "Receipts and invoices, clean"),
        extraction("glimmer_messy_200_v2", "Receipts and invoices, messy photos"),
        reader("cis_read", "CIS statements and reverse-charge invoices", "documents"),
        reader("property_docs", "Letting paperwork", "documents"),
        ask(),
        autopilot(),
        triage(),
        bankCoding(),
      ]),
    },
    {
      id: "verifier-model",
      name: "Open-weights verifier model",
      modelId: "open weights · hosted",
      uses: "The Verifier: an independent second reading of each document",
      via: "Hosted open weights; switched off on the live server for now",
      what: "An open-weights model on a hosted endpoint the server owner can switch on. A different model from the first reader, so the second reading is independent. It is off on the live server for now: the Verifier runs on the same chain as the reader. The results below are from earlier runs when it was on.",
      jobs: [
        { job: "The Verifier: a second reading of each document with a different prompt and schema that never sees the first answer", screen: "Review card: “Verifier agrees” or “Needs a look”" },
      ],
      called: [
        "Key mode and the server chain: only when the server owner switches it on (off for now); otherwise the chain's providers in order.",
        "Local mode never uses it: your documents stay on your machine.",
      ],
      checks: [
        "The model never merges or picks values: code compares six fields (supplier, VAT number, date, net, VAT, gross). A disagreement sends the card to Needs a look; it never changes a figure.",
      ],
      results: present([
        extraction("spark_open_200", "Receipts and invoices, clean (reader and Verifier; earlier run)"),
        extraction("spark_open_messy_200", "Receipts and invoices, messy photos (reader and Verifier; earlier run)"),
      ]),
    },
    {
      id: "speech-to-text",
      name: "Speech-to-text model",
      modelId: "hosted speech-to-text · a local speech-to-text model on our own server",
      uses: "Speech to text for spoken questions and instructions on Ask",
      via: "Our own server since 11 Nov 2026; the hosted speech-to-text model with your own key, or first before that date",
      what: "A hosted speech-to-text model, with a local speech-to-text model on our own server.",
      jobs: [
        { job: "Turns a spoken question or instruction (overtime, a quote, a shopping list) into text for Ask and action cards", screen: "Ask: the microphone button, on the web and Android" },
      ],
      called: [
        "Since 11 Nov 2026: the local speech-to-text model on our own server; the hosted speech-to-text model (/asr/transcribe) only with your own key in key mode, or when the server owner switches it on.",
        "Before that: the hosted speech-to-text model first, then a local fallback model if it failed. If both fail you see why, and can type the question instead.",
        "The audio is converted in a temporary folder that is deleted at once; it is not kept.",
      ],
      checks: [
        "The text goes through the same path as a typed question: figures checked against your books, action cards priced in pence by code and waiting for Approve.",
        "The answer, the action card and the audit log say which service heard you (“Transcribed by the speech-to-text model”).",
      ],
      results: [
        speech(),
        {
          label: "Used live",
          value: "Used from the Android app on a real phone by the owner, and in our live checks: two spoken questions (synthetic speech) transcribed by the hosted speech-to-text model on the live server, then answered by the hosted model.",
          basis: "4 Nov 2026 · live server",
          report: LIVE_CHECKS,
        },
      ],
    },
    {
      id: "receipt-crop",
      name: "Receipt-crop image model",
      modelId: "hosted image segmentation",
      uses: "Finds and crops the receipt in a phone photo before it is read",
      via: "The hosted model's API (/responses), when the server owner switches it on (off since 11 Nov 2026)",
      what: "An image segmentation model: finds an object in a photo from a word.",
      jobs: [
        { job: "Finds and crops the receipt or invoice in a messy phone photo before it is read", screen: "Review (photo uploads)" },
      ],
      called: [
        "The hosted model's API (/responses), only when the server owner switches it on: with your own API key in key mode, else the server's. Not when you choose a local model first or local only in Settings › AI.",
        "Otherwise, and whenever it is unsure, errors or times out, a plain-code crop runs instead (no AI).",
      ],
      checks: [
        "Code accepts the crop only with a confident box (score at least 0.5) covering enough of the photo; any doubt or error keeps the original photo.",
      ],
      results: [
        samLive() ?? {
          label: "Crop",
          value: "Not measured yet on the crop model.",
          basis: "no run committed",
          report: null,
        },
        {
          label: "Plain-code crop (the fallback)",
          value: "mean overlap 0.88 against 0.48 for the uncropped photo",
          basis: "27 Oct 2026 · 20 synthetic scenes",
          report: `${REPO}/evals/REPORT_crop_code_20_2026-10-27.md`,
        },
      ],
    },
    {
      id: "image-model",
      name: "Image-generation model",
      modelId: "hosted image generation · build time only",
      uses: "Made the brand artwork and the demo video title art; not in the running app",
      via: "A hosted image API, from a build script",
      what: "An image-generation model. Used once, at build time, not by the running app.",
      jobs: [
        { job: "Made the brand artwork: the hero illustration, the app icon and the store graphic, also used for the demo video's title art and thumbnail", screen: "Website, Android icon, demo video" },
      ],
      called: ["A hosted image API, from a build script (tools/brand_muse.py). The app never calls it."],
      checks: ["No figures involved; the images were chosen by a person."],
      results: [
        {
          label: "Images made",
          value: "12 images, USD 0.12 in all (USD 0.01 each)",
          basis: "build time · 12 images",
          report: null,
        },
      ],
    },
  ];
}
