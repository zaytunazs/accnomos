/**
 * Pure helpers behind the Review edit sheet (same rules as apps/mobile/lib/services/proposal_editing.dart).
 *
 * Runtime contract: there is no edit endpoint. Edits travel inside `POST /books/proposals/{id}/approve` as `edits`,
 * whose keys are limited to `DOC_EDITS` in services/runtime/app/approve.py. Only changed fields are sent. The VAT
 * code and the supplier's VAT number are checked here but cannot be sent: the runtime keeps them as read.
 * All money maths is in integer pence.
 */
import type { RtProposal } from "./runtime";

/** services/runtime/app/schemas.py CATEGORIES (anything else is refused at approve). */
export const CATEGORIES = [
  "Tools & small equipment", "Materials", "Office supplies", "Motor expenses", "Travel", "Subsistence",
  "Software & subscriptions", "Telephone & internet", "Rent", "Utilities", "Insurance", "Professional fees",
  "Advertising", "Postage", "Bank charges", "Sales", "Sundry",
];

const RATE: Record<string, number> = { S: 0.2, R: 0.05 };
const RATE_LABEL: Record<string, string> = {
  S: "standard 20%", R: "reduced 5%", Z: "zero-rated", E: "exempt", O: "outside the scope of VAT", N: "no VAT invoice",
};
const VAT_CONTROL = "2200";

export interface EditForm {
  supplier: string;
  date: string; // YYYY-MM-DD
  net: string;
  vat: string;
  gross: string;
  category: string;
  vrn: string;
}

/** "£1,234.50" / " 7 " → pence; null when it is not a non-negative amount with at most 2 decimals. */
export function parsePence(text: string): number | null {
  const s = text.replace(/[£,\s]/g, "");
  if (!/^\d+(\.\d{1,2})?$/.test(s)) return null;
  return Math.round(Number(s) * 100);
}

export const poundsText = (pence: number) => (pence / 100).toFixed(2);
const gbp = (pence: number) => `£${(pence / 100).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** VAT codes on the expense lines (or the sales lines), e.g. ["S"] or ["S", "Z"]. */
export function vatCodesOf(p: RtProposal): string[] {
  const sale = p.extracted.doc_type === "sales_invoice";
  const codes = p.journal_draft
    .filter((j) => (sale ? j.credit_pence : j.debit_pence) && !j.account.startsWith(VAT_CONTROL) && j.vat_code)
    .map((j) => j.vat_code as string);
  return [...new Set(codes)].sort();
}

export const vatCodeLabel = (code: string) => `${code} (${RATE_LABEL[code] ?? "as read"})`;

/** UK VAT number shapes the runtime accepts (services/runtime/app/checks.py). Empty = none printed, allowed. */
export function normaliseVrn(raw: string | null | undefined): string | null {
  if (!raw) return null;
  let s = raw.toUpperCase().replace(/[\s.-]/g, "").replace(/^VAT(REG)?(NO|NUMBER)?:?/, "");
  if (!s) return null;
  if (/^\d+$/.test(s) && (s.length === 9 || s.length === 12)) s = `GB${s}`;
  return s;
}
export function vrnLooksValid(raw: string): boolean {
  const s = normaliseVrn(raw);
  return s === null || /^(GB|XI)(\d{9}|\d{12}|(GD|HA)\d{3})$/.test(s);
}

const todayIso = (now: Date) =>
  `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;

export function initialForm(p: RtProposal): EditForm {
  const x = p.extracted;
  return {
    supplier: x.supplier_name,
    date: x.date,
    net: x.net_total.toFixed(2),
    vat: x.vat_total.toFixed(2),
    gross: x.gross_total.toFixed(2),
    category: x.category_guess,
    vrn: x.supplier_vat_number ?? "",
  };
}

export type EditField = keyof EditForm;
export interface EditProblem {
  field: EditField;
  message: string;
}

/** Every reason the form cannot be saved, in plain English, first problem first. */
export function validate(p: RtProposal, f: EditForm, now = new Date()): EditProblem[] {
  const out: EditProblem[] = [];
  if (!f.supplier.trim()) out.push({ field: "supplier", message: "Enter the supplier's name." });
  if (!/^\d{4}-\d{2}-\d{2}$/.test(f.date) || Number.isNaN(Date.parse(f.date)))
    out.push({ field: "date", message: "Enter the date on the document." });
  else if (f.date > todayIso(now)) out.push({ field: "date", message: "The date is in the future. Use the date printed on the document." });
  const net = parsePence(f.net), vat = parsePence(f.vat), gross = parsePence(f.gross);
  if (net === null) out.push({ field: "net", message: "Net must be an amount, e.g. 32.06." });
  if (vat === null) out.push({ field: "vat", message: "VAT must be an amount, e.g. 6.41 (0 if none)." });
  if (gross === null) out.push({ field: "gross", message: "Total must be an amount, e.g. 38.47." });
  if (net !== null && vat !== null && gross !== null) {
    const diff = net + vat - gross;
    if (diff !== 0)
      out.push({
        field: "gross",
        message: `Net + VAT is ${gbp(net + vat)} but the total is ${gbp(gross)} (${gbp(Math.abs(diff))} ${diff > 0 ? "over" : "short"}).`,
      });
    const codes = vatCodesOf(p);
    if (codes.length === 1) {
      const code = codes[0];
      const expected = Math.round(net * (RATE[code] ?? 0));
      if (Math.abs(vat - expected) > 2 + p.extracted.lines.length) // the runtime's VAT_MATH tolerance
        out.push({
          field: "vat",
          message: `VAT code ${vatCodeLabel(code)} expects about ${gbp(expected)} VAT on ${gbp(net)}, not ${gbp(vat)}.`,
        });
    }
  }
  if (!f.category) out.push({ field: "category", message: "Choose a category." });
  if (!vrnLooksValid(f.vrn))
    out.push({ field: "vrn", message: "That is not a UK VAT number: GB and 9 digits, e.g. GB 123 4567 89." });
  else if (normaliseVrn(f.vrn) !== normaliseVrn(p.extracted.supplier_vat_number))
    out.push({
      field: "vrn",
      message: "The VAT number can't be corrected on approval yet; the runtime keeps it as read. Put it back, or Reject and rescan a clearer copy.",
    });
  return out;
}

/** The `edits` for approve: only the fields that changed (keys from the runtime's DOC_EDITS). */
export function buildEdits(p: RtProposal, f: EditForm): Record<string, string | number> {
  const x = p.extracted;
  const edits: Record<string, string | number> = {};
  const supplier = f.supplier.trim();
  if (supplier && supplier !== x.supplier_name) edits.supplier_name = supplier;
  if (f.date !== x.date) edits.date = f.date;
  const money: [keyof EditForm, "net_total" | "vat_total" | "gross_total"][] = [["net", "net_total"], ["vat", "vat_total"], ["gross", "gross_total"]];
  for (const [field, key] of money) {
    const pence = parsePence(f[field]);
    if (pence !== null && pence !== Math.round(x[key] * 100)) edits[key] = pence / 100;
  }
  if (f.category && f.category !== x.category_guess) edits.category = f.category;
  return edits;
}

/** Edit-sheet field → the verifier's field key (services/runtime/app/ai/verify.py). */
export const VERIFIER_FIELD: Partial<Record<EditField, string>> = {
  supplier: "supplier_name",
  vrn: "supplier_vat_number",
  date: "date",
  net: "net_total",
  vat: "vat_total",
  gross: "gross_total",
};
