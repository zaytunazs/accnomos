/** Formatting and period helpers for Spending, Cheaper options and the shopping list. Figures come from the runtime. */

/** "1234.5" -> "£1,234.50" (pounds as the runtime sends them, never re-calculated here). */
export function money(pounds: string | null | undefined, dp = 2): string {
  if (pounds === null || pounds === undefined || pounds === "") return "–";
  const n = Number(pounds);
  if (!Number.isFinite(n)) return pounds;
  const s = Math.abs(n).toLocaleString("en-GB", { minimumFractionDigits: dp, maximumFractionDigits: dp });
  return `${n < 0 ? "-" : ""}£${s}`;
}

/** A change vs the previous period, signed: "+£53.60" / "-£12.00" / "no change". */
export function change(pounds: string, pct?: string | null): string {
  const n = Number(pounds);
  if (n === 0) return "no change";
  const text = `${n > 0 ? "+" : "-"}${money(String(Math.abs(n)))}`;
  return pct ? `${text} (${n > 0 ? "+" : ""}${pct}%)` : text;
}

/** Per metre / kg / litre / item at 4 dp, as code worked it out: "£0.0250 per metre". */
export const perMeasure = (pounds: string, word: string) => `${money(pounds, 4)} per ${word}`;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-09-08" -> "8 Sep 2026", the way the runtime writes dates (browsers differ on "Sep"/"Sept"). */
export function ukDay(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

export type PeriodChoice = "month" | "last_month" | "quarter" | "custom";
export interface Span {
  start: string;
  end: string;
}

const iso = (d: Date) => d.toISOString().slice(0, 10);
const utc = (y: number, m: number, day: number) => new Date(Date.UTC(y, m, day));

/** The span for a choice, from London's today (YYYY-MM-DD). Calendar months and quarters, whole. */
export function spanFor(choice: Exclude<PeriodChoice, "custom">, today: string): Span {
  const [y, m] = today.split("-").map(Number);
  if (choice === "month") return { start: iso(utc(y, m - 1, 1)), end: iso(utc(y, m, 0)) };
  if (choice === "last_month") return { start: iso(utc(y, m - 2, 1)), end: iso(utc(y, m - 1, 0)) };
  const q = Math.floor((m - 1) / 3) * 3;
  return { start: iso(utc(y, q, 1)), end: iso(utc(y, q + 3, 0)) };
}
