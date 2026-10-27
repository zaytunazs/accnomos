/**
 * Which waiting proposals a saved Autopilot rule matches, decided in the browser with the same conditions
 * services/runtime/app/autopilot.py uses before it would post (supplier key, purchase, every check passed,
 * same VAT number and VAT treatment, gross within 2x the usual). At L1 nothing is posted on its own: Review
 * offers these to the user, and each approval is a normal `POST …/approve`.
 */
import { normaliseVrn, vatCodesOf } from "./review-edit";
import type { RtProposal, RtRule } from "./runtime";

const TRAILING = new Set(["ltd", "limited", "plc", "llp", "uk", "co"]);
const MAX_TIMES_TYPICAL = 2;

/** 'Screwfix Direct Ltd.' → 'screwfix-direct'; "Sainsbury's" → 'sainsburys'; 'B&Q' → 'b-and-q' (autopilot.supplier_key). */
export function supplierKey(name: string): string {
  const s = name.toLowerCase().replace(/&/g, " and ").replace(/['’]/g, "");
  const words = s.replace(/[^a-z0-9]+/g, " ").trim().split(/\s+/).filter(Boolean);
  while (words.length > 1 && TRAILING.has(words[words.length - 1])) words.pop();
  if (words.length > 1 && words[0] === "the") words.shift();
  return words.join("-");
}

/** The rule this proposal fully matches, or null. */
export function matchingRule(p: RtProposal, rules: RtRule[]): RtRule | null {
  const x = p.extracted;
  const key = supplierKey(x.supplier_name);
  const rule = key ? [...rules].reverse().find((r) => r.supplier_key === key) : undefined;
  if (!rule || rule.side !== "purchase" || x.doc_type === "sales_invoice" || p.mileage_claim) return null;
  if (p.status !== "proposed" || p.checks.some((c) => !c.ok)) return null;
  if (normaliseVrn(x.supplier_vat_number) !== rule.vrn) return null;
  if ((vatCodesOf(p).join(",") || null) !== rule.vat_code) return null;
  const gross = Math.round(x.gross_total * 100);
  if (gross <= 0 || gross > MAX_TIMES_TYPICAL * rule.typical_gross_pence) return null;
  return rule;
}

/** "Do the same as the approval that made the rule" (autopilot.edits_for), sending only what differs. */
export function ruleEdits(p: RtProposal, rule: RtRule): Record<string, string> | undefined {
  const edits: Record<string, string> = {};
  if (rule.category !== p.extracted.category_guess) edits.category = rule.category;
  const expense = p.journal_draft.find((j) => j.debit_pence && !j.account.startsWith("2200"))?.account;
  if (rule.account && rule.account !== expense) edits.account = rule.account;
  return Object.keys(edits).length ? edits : undefined;
}
