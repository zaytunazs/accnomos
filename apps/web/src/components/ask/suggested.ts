import type { RtDashboard } from "@/lib/runtime";

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
  if (d.vat) {
    const current = Number(d.vat.current.box5);
    const due = d.vat.due ? Number(d.vat.due.box5) : null;
    if (due !== null && due !== current) {
      out.push(`Why is Box 5 ${due > current ? "higher" : "lower"} this quarter?`);
    } else {
      out.push(`Why is my VAT ${gbp2(d.vat.current.box5)} for ${d.vat.current.label}?`);
    }
  }
  if ((d.owed_to_you?.documents ?? 0) > 0) out.push("Who owes me the most?");
  if ((d.owed_by_you?.documents ?? 0) > 0) out.push("What do I owe and when is it due?");
  if ((d.attention?.unmatched_bank_lines ?? 0) > 0) out.push("Which bank lines still need matching?");
  if ((d.attention?.proposed ?? 0) + (d.attention?.needs_a_look ?? 0) > 0) out.push("What is waiting in Review?");
  if (d.cash?.balance_pence !== null && d.cash?.balance_pence !== undefined) out.push("What is my cash balance?");
  const picked = out.slice(0, MAX_SUGGESTIONS);
  return picked.length > 0 ? picked : FALLBACK_QUESTIONS;
}
