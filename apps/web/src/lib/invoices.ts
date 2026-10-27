"use client";

import { useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { getMsal, msalConfigured } from "./msal";
import type { RtInvoice, RtInvoiceLineIn, RtSalesVatCode } from "./runtime";

/**
 * Sales invoice helpers for the web app. The runtime prices every invoice when it is saved
 * (services/runtime/app/invoicing.py); the live totals here only preview that sum while typing and
 * round the same way: per line, half away from zero, in whole pence.
 */

export const VAT_CODES: { code: RtSalesVatCode; rate: number; label: string }[] = [
  { code: "S", rate: 20, label: "20% standard" },
  { code: "R", rate: 5, label: "5% reduced" },
  { code: "Z", rate: 0, label: "0% zero rated" },
  { code: "E", rate: 0, label: "Exempt" },
  { code: "O", rate: 0, label: "Outside the scope" },
];
const RATE: Record<RtSalesVatCode, number> = { S: 20, R: 5, Z: 0, E: 0, O: 0 };

/** n / d rounded half away from zero, for integers (as Decimal ROUND_HALF_UP in the runtime). */
function divRound(n: number, d: number): number {
  const q = Math.floor((Math.abs(n) * 2 + d) / (2 * d));
  return n < 0 ? -q : q;
}

/** Quantity in thousandths, or null when it is not a number with up to 3 decimal places. */
export function thousandths(qty: string | number): number | null {
  const s = String(qty).trim();
  if (!/^\d+(\.\d{1,3})?$/.test(s)) return null;
  const [whole, frac = ""] = s.split(".");
  return Number(whole) * 1000 + Number(frac.padEnd(3, "0"));
}

/** "£1,234.50" or "1234.5" -> 123450 pence; null when it is not money. Negative for a discount. */
export function parsePounds(raw: string): number | null {
  const s = raw.replace(/[£,\s]/g, "");
  if (!/^-?\d+(\.\d{1,2})?$/.test(s)) return null;
  const neg = s.startsWith("-");
  const [whole, frac = ""] = s.replace("-", "").split(".");
  const p = Number(whole) * 100 + Number(frac.padEnd(2, "0"));
  return neg ? -p : p;
}

export function linePence(line: Pick<RtInvoiceLineIn, "quantity" | "unit_price_pence" | "vat_code">): { net: number; vat: number } | null {
  const q = thousandths(line.quantity);
  if (q === null) return null;
  const net = divRound(q * line.unit_price_pence, 1000);
  return { net, vat: divRound(net * RATE[line.vat_code], 100) };
}

export interface LiveTotals {
  byCode: { code: RtSalesVatCode; rate: number; net: number; vat: number }[];
  net: number;
  vat: number;
  total: number;
}

export function liveTotals(lines: Pick<RtInvoiceLineIn, "quantity" | "unit_price_pence" | "vat_code">[]): LiveTotals {
  const groups = new Map<RtSalesVatCode, { net: number; vat: number }>();
  for (const ln of lines) {
    const p = linePence(ln);
    if (!p) continue;
    const g = groups.get(ln.vat_code) ?? { net: 0, vat: 0 };
    groups.set(ln.vat_code, { net: g.net + p.net, vat: g.vat + p.vat });
  }
  const byCode = VAT_CODES.filter((c) => groups.has(c.code)).map((c) => ({ code: c.code, rate: c.rate, ...groups.get(c.code)! }));
  const net = byCode.reduce((s, g) => s + g.net, 0);
  const vat = byCode.reduce((s, g) => s + g.vat, 0);
  return { byCode, net, vat, total: net + vat };
}

/** Exact pounds from pence (no floats): 123450 -> "£1,234.50". */
export function money(pence: number): string {
  const sign = pence < 0 ? "-" : "";
  const abs = Math.abs(pence);
  return `${sign}£${Math.floor(abs / 100).toLocaleString("en-GB")}.${String(abs % 100).padStart(2, "0")}`;
}

/** Pence as an editable pounds string: 4500 -> "45.00". */
export function poundsInput(pence: number): string {
  const sign = pence < 0 ? "-" : "";
  const abs = Math.abs(pence);
  return `${sign}${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, "0")}`;
}

export function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export const STATUS_LABEL: Record<RtInvoice["status"], string> = { draft: "Draft", sent: "Sent", paid: "Paid", void: "Void" };

/** The signed-in Microsoft account, or null (also while loading: check `ready`). */
export function useMsAccount(): { account: AccountInfo | null; ready: boolean } {
  const [state, setState] = useState<{ account: AccountInfo | null; ready: boolean }>({ account: null, ready: false });
  useEffect(() => {
    (async () => {
      if (!msalConfigured()) return queueMicrotask(() => setState({ account: null, ready: true }));
      try {
        const msal = await getMsal();
        await msal.handleRedirectPromise().catch(() => null);
        setState({ account: msal.getActiveAccount() ?? msal.getAllAccounts()[0] ?? null, ready: true });
      } catch {
        setState({ account: null, ready: true });
      }
    })();
  }, []);
  return state;
}

/** Shown signed out. SAMPLE — FICTIONAL COMPANY. */
export const SAMPLE_INVOICES: Pick<RtInvoice, "number" | "status" | "customer" | "issue_date" | "due_date" | "total_pence" | "days_overdue">[] = [
  { number: "INV-0007", status: "draft", customer: { contact_id: null, name: "Harrogate Dental Ltd", email: null, address: null, vrn: null }, issue_date: "2026-10-27", due_date: "2026-11-26", total_pence: 186000, days_overdue: null },
  { number: "INV-0006", status: "sent", customer: { contact_id: null, name: "Acme Kitchens Ltd", email: null, address: null, vrn: null }, issue_date: "2026-09-01", due_date: "2026-10-01", total_pence: 40500, days_overdue: 26 },
  { number: "INV-0005", status: "paid", customer: { contact_id: null, name: "Leeds Lettings", email: null, address: null, vrn: null }, issue_date: "2026-08-14", due_date: "2026-09-13", total_pence: 96000, days_overdue: null },
];
