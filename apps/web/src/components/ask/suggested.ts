import { tileData, type RtDashboard } from "@/lib/runtime";

/** Starters when the dashboard cannot be read. */
export const FALLBACK_QUESTIONS = [
  "Why is my VAT different from last quarter?",
  "Who owes me the most?",
  "What needs my attention?",
];

const MAX_SUGGESTIONS = 4;

const gbp2 = (pounds: string) =>
  `£${Number(pounds).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/**
 * Suggested questions for an empty Ask thread, built from the dashboard
 * payload in code — never by a model. Each question mirrors a tile on Home,
 * so the answer is one the books can actually give.
 */
export function suggestedQuestions(d: RtDashboard | null): string[] {
  if (!d) return FALLBACK_QUESTIONS;
  const out: string[] = [];
  const vat = tileData(d.vat);
  const owedToYou = tileData(d.owed_to_you);
  const owedByYou = tileData(d.owed_by_you);
  const attention = tileData(d.attention);
  const cash = tileData(d.cash);
  if (vat) {
    const current = Number(vat.current.box5);
    const due = vat.due ? Number(vat.due.box5) : null;
    if (due !== null && due !== current) {
      out.push(`Why is Box 5 ${due > current ? "higher" : "lower"} this quarter?`);
    } else {
      out.push(`Why is my VAT ${gbp2(vat.current.box5)} for ${vat.current.label}?`);
    }
  }
  if ((owedToYou?.documents ?? 0) > 0) out.push("Who owes me the most?");
  if ((owedByYou?.documents ?? 0) > 0) out.push("What do I owe and when is it due?");
  if ((attention?.unmatched_bank_lines ?? 0) > 0) out.push("Which bank lines still need matching?");
  if ((attention?.proposed ?? 0) + (attention?.needs_a_look ?? 0) > 0) out.push("What is waiting in Review?");
  if (cash?.balance_pence !== null && cash?.balance_pence !== undefined) out.push("What is my cash balance?");
  const picked = out.slice(0, MAX_SUGGESTIONS);
  return picked.length > 0 ? picked : FALLBACK_QUESTIONS;
}
