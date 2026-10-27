/** Runtime proposal → the Review card's display model: plain English only, never a raw check code. */
import { gbp, ukDate, type RtProposal } from "./runtime";
import type { Proposal as UiProposal } from "./sample-review";

const codeMeaning: Record<string, string> = {
  S: "standard-rated 20%",
  R: "reduced-rated 5%",
  Z: "zero-rated",
  E: "exempt",
  N: "no VAT reclaim (no VAT invoice)",
  O: "outside the scope of UK VAT",
};

const fieldLabel: Record<string, string> = {
  supplier_name: "Supplier",
  supplier_vat_number: "VAT number",
  date: "Date",
  net_total: "Net",
  vat_total: "VAT",
  gross_total: "Total",
};

const verifierName = (model: string) =>
  model.startsWith("baseten:") ? "Muse Spark Open" : model.startsWith("meta:") ? "Muse Spark" : model.replace(/^ollama:/, "");

const shown = (v: string | number | null) => (v === null || v === "" ? "none" : typeof v === "number" ? v.toFixed(2) : v);

/** Checker reasons arrive as "CODE: plain-English note" — show the note, never the raw code. */
export function plainReason(reason: string): string {
  return reason.replace(/^[A-Z][A-Z0-9_]*:\s*/, "");
}

/** The verifier chip, bound to the runtime's real second reading. Never claims agreement it did not see. */
function verifierView(p: RtProposal): Pick<UiProposal, "verifierNote" | "verifierTone" | "verifierDiffs"> {
  const v = p.verification;
  const passed = `Checks run by code: ${p.checks.filter((c) => c.ok).length} of ${p.checks.length} passed`;
  if (!v) {
    const why = p.status === "needs_a_look" ? "skipped, checks already flagged it" : "not run";
    return { verifierNote: `Second reading ${why} · ${passed}`, verifierTone: "none" };
  }
  if (v.error) return { verifierNote: `Second reading unavailable (${v.model}) · ${passed}`, verifierTone: "none" };
  const fields = Object.entries(v.fields);
  if (v.agree_all)
    return { verifierNote: `Verifier agrees · all ${fields.length} fields match — ${verifierName(v.model)} · ${passed}`, verifierTone: "agree" };
  const diffs = fields
    .filter(([, f]) => !f.agree)
    .map(([k, f]) => ({ field: fieldLabel[k] ?? k, extractor: shown(f.extractor), verifier: shown(f.verifier) }));
  return {
    verifierNote: `Verifier disagrees on ${diffs.length} of ${fields.length} fields — ${verifierName(v.model)}. Check the document before you approve; Edit highlights them.`,
    verifierTone: "differ",
    verifierDiffs: diffs,
  };
}

/** Append the model/timing/crop suffix to the verifier line so the card keeps showing how the reading was made. */
function withCrop<T extends { verifierNote: string }>(view: T, suffix: string): T {
  return { ...view, verifierNote: `${view.verifierNote} · ${suffix}` };
}

/** Map a runtime proposal onto the card's display model (strings only, plain English). */
export function toUi(p: RtProposal): UiProposal {
  const x = p.extracted;
  const local = p.model.startsWith("local:");
  const lines = p.journal_draft.map((l) => {
    const amt = gbp((l.debit_pence || l.credit_pence) / 100);
    const isVat = l.account.includes("2200");
    const isSettle = l.credit_pence > 0 && !isVat && x.doc_type !== "sales_invoice";
    const owed = isSettle && l.account.startsWith("2300"); // mileage allowance: the business owes you
    const label = isVat ? "VAT to reclaim" : owed ? "Owed to you" : isSettle ? `Paid from ${x.payment_method === "cash" ? "cash" : "business card"}` : l.account.replace(/^\d{4}\s/, "");
    const meaning = isVat ? "Goes to Box 4" : owed ? "You paid for the journeys; pay yourself back when you like" : isSettle ? "Will match a bank line" : `Expense, ${codeMeaning[l.vat_code ?? ""] ?? "VAT as shown"}`;
    return { account: `${label} ${amt}`, amount: amt, meaning };
  });
  const fails = p.checks.filter((c) => !c.ok);
  // One line per failed check; the verifier's own disagreement is shown by its table, not repeated here.
  const failedChecks = fails.filter((c) => c.code !== "VERIFIER_AGREES").map((c) => ({ text: c.message, warn: c.severity === "warn" }));
  const verified = p.checks.filter((c) => !["CROP", "VEHICLE", "MILEAGE"].includes(c.code)); // notes, not checks
  const cropped = p.crop && p.crop.method !== "none" ? ` · ${p.crop.note}` : "";
  const mileageNote = p.checks.find((c) => c.code === "MILEAGE");
  const why = fails.length
    ? "" // the failed checks are listed on the card, one line each
    : mileageNote
      ? `Why: ${mileageNote.message}. Your mileage log is the evidence; change it on Vehicles, not here.`
      : `Why: ${x.lines.length} line${x.lines.length === 1 ? "" : "s"}, totals add up (${x.net_total.toFixed(2)} + ${x.vat_total.toFixed(2)} = ${x.gross_total.toFixed(2)}); category "${x.category_guess}". — Checker, code`;
  return {
    id: p.id,
    supplier: x.supplier_name,
    total: gbp(x.gross_total),
    confidence: `Confidence ${Math.round(x.confidence * 100)}%`,
    source: p.mileage_claim ? "Calculated by code from your mileage log" : local ? "Read by Glimmer 30B on your machine" : "Read by Muse Spark",
    date: ukDate(x.date),
    vatNumber: x.supplier_vat_number ? `${x.supplier_vat_number} ✓` : "none shown",
    net: gbp(x.net_total),
    vat: gbp(x.vat_total),
    paidBy: x.card_last4 ? `Card ending ${x.card_last4}` : (x.payment_method ?? "—"),
    lines,
    reviewerNote: why,
    failedChecks,
    ...withCrop(verifierView(p), `checks by code: ${verified.filter((c) => c.ok).length} of ${verified.length} passed · ${p.model} · ${p.elapsed_s.toFixed(1)} s${cropped}`),
  };
}
