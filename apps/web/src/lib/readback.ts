/**
 * Read-back for spoken requests: the figure a card will act on, in words, so a mis-heard number ("fourteen" for
 * "forty") is caught before Approve. Speech-to-text gets numbers wrong more often than words (the voice eval scores
 * them separately), and a digit on a card is easy to skim past; "forty pounds" next to it is not.
 */

const ONES = [
  "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
  "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
];
const TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"];

function under1000(n: number): string {
  const h = Math.floor(n / 100);
  const r = n % 100;
  const rest = r < 20 ? ONES[r] : TENS[Math.floor(r / 10)] + (r % 10 ? `-${ONES[r % 10]}` : "");
  if (!h) return rest;
  return `${ONES[h]} hundred${r ? ` and ${rest}` : ""}`;
}

/** A whole number in British English words: 1405 -> "one thousand, four hundred and five". */
export function wholeInWords(n: number): string {
  if (!Number.isFinite(n)) return String(n);
  if (n < 0) return `minus ${wholeInWords(-n)}`;
  n = Math.floor(n);
  if (n < 1000) return under1000(n);
  const parts: string[] = [];
  for (const [size, name] of [[1e9, "billion"], [1e6, "million"], [1e3, "thousand"]] as const) {
    if (n >= size) {
      parts.push(`${under1000(Math.floor(n / size) % 1000)} ${name}`);
      n %= size;
    }
  }
  if (n) parts.push(n < 100 ? `and ${under1000(n)}` : under1000(n));
  return parts.join(", ").replace(", and ", " and ");
}

/** 4050 -> "forty pounds and fifty pence"; 100 -> "one pound"; 5 -> "five pence". */
export function penceInWords(pence: number): string {
  const sign = pence < 0 ? "minus " : "";
  const abs = Math.abs(Math.round(pence));
  const pounds = Math.floor(abs / 100);
  const p = abs % 100;
  const lb = pounds ? `${wholeInWords(pounds)} pound${pounds === 1 ? "" : "s"}` : "";
  const pc = p ? `${wholeInWords(p)} pence` : "";
  return sign + (lb && pc ? `${lb} and ${pc}` : lb || pc || "zero pounds");
}

/** "12.5" -> "twelve point five"; "3" -> "three". A quantity as typed by the runtime (a decimal string). */
export function quantityInWords(q: string | number): string {
  const s = String(q).trim();
  const m = s.match(/^(-?)(\d+)(?:\.(\d+))?$/);
  if (!m) return s;
  const whole = `${m[1] ? "minus " : ""}${wholeInWords(Number(m[2]))}`;
  const frac = (m[3] ?? "").replace(/0+$/, "");
  return frac ? `${whole} point ${[...frac].map((d) => ONES[Number(d)]).join(" ")}` : whole;
}

export interface ReadBackLine {
  label: string;
  figure: string; // as the card shows it: "£40.00", "12.5 miles"
  words: string; // "forty pounds", "twelve point five miles"
}

const gbp = (pence: number) =>
  `${pence < 0 ? "-" : ""}£${(Math.abs(pence) / 100).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function money(label: string, pence: unknown): ReadBackLine[] {
  return typeof pence === "number" && Number.isFinite(pence) ? [{ label, figure: gbp(pence), words: penceInWords(pence) }] : [];
}

function qty(label: string, value: unknown, unit: string): ReadBackLine[] {
  if (typeof value !== "string" && typeof value !== "number") return [];
  const n = Number(value);
  if (!Number.isFinite(n)) return [];
  const one = n === 1;
  return [{ label, figure: `${value} ${one ? unit : `${unit}s`}`, words: `${quantityInWords(value)} ${one ? unit : `${unit}s`}` }];
}

/** The figures to read back for one proposed action; empty when the card carries no figure a voice could mis-hear. */
export function readBack(kind: string, preview: Record<string, unknown>): ReadBackLine[] {
  switch (kind) {
    case "create_invoice":
    case "create_quote":
    case "convert_quote_to_invoice": {
      const lines = Array.isArray(preview.lines) ? (preview.lines as Record<string, unknown>[]) : [];
      const out = lines.length === 1 ? money("Price each", lines[0].unit_price_pence) : [];
      return [...out, ...money("Total", preview.total_pence)];
    }
    case "chase_invoice":
      return money("Owed", preview.total_pence);
    case "remind_unpaid":
      return money("Owed in all", preview.total_pence);
    case "payment_link_message":
      return money("Owed", preview.balance_pence);
    case "match_bank_line":
      return money("Amount", preview.amount_pence);
    case "log_mileage":
      return qty("Distance", preview.miles, "mile");
    case "log_timesheet":
      return [...qty("Time", preview.hours, "hour"), ...qty("Overtime", preview.overtime_hours, "hour"), ...money("Pay", preview.cost_pence)];
    case "pay_overtime":
      return [...qty("Time", preview.hours, "hour"), ...money("Extra pay", preview.extra_pence)];
    default:
      return [];
  }
}
