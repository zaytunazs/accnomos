"use client";

import { useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { fieldInput, fieldLabel } from "@/components/invoices/Modal";
import { linePence, liveTotals, money, parsePounds, poundsInput, thousandths, VAT_CODES } from "@/lib/invoices";
import { runtime, type RtInvoiceLine, type RtInvoiceLineIn, type RtItem, type RtSalesVatCode } from "@/lib/runtime";

/** A line as typed: pounds and quantity stay strings until saved; the runtime does the pricing. */
export interface LineForm {
  key: number;
  description: string;
  quantity: string;
  unit: string;
  price: string; // pounds as typed
  vat_code: RtSalesVatCode;
  item_code: string | null;
}

let nextKey = 1;
export const blankLine = (): LineForm => ({ key: nextKey++, description: "", quantity: "1", unit: "", price: "", vat_code: "S", item_code: null });

export function linesFromRt(lines: (RtInvoiceLine | RtInvoiceLineIn)[]): LineForm[] {
  return lines.map((l) => ({
    key: nextKey++,
    description: l.description,
    quantity: String(l.quantity),
    unit: l.unit ?? "",
    price: poundsInput(l.unit_price_pence),
    vat_code: l.vat_code,
    item_code: l.item_code ?? null,
  }));
}

/** The lines as the runtime takes them, or the sentence saying what is wrong. Blank lines are dropped. */
export function linesToIn(lines: LineForm[]): RtInvoiceLineIn[] | string {
  const out: RtInvoiceLineIn[] = [];
  for (const [n, l] of lines.entries()) {
    if (!l.description.trim() && !l.price.trim()) continue;
    if (!l.description.trim()) return `Line ${n + 1}: add a description.`;
    const q = thousandths(l.quantity);
    if (q === null || q === 0) return `Line ${n + 1}: quantity must be a number above 0 (up to 3 decimals).`;
    const p = parsePounds(l.price);
    if (p === null) return `Line ${n + 1}: unit price must be pounds and pence, e.g. 45.00.`;
    out.push({
      description: l.description.trim(),
      quantity: l.quantity.trim(),
      unit: l.unit.trim() || null,
      unit_price_pence: p,
      vat_code: l.vat_code,
      item_code: l.item_code,
    });
  }
  return out.length ? out : "Add at least one line.";
}

/** Pick a product or service: the runtime fills the description, unit, price and VAT from the catalogue. */
export function ItemPicker({
  account, items, side, quantity, idPrefix, value, onFill,
}: {
  account: AccountInfo;
  items: RtItem[];
  side: "sale" | "purchase";
  quantity: string;
  idPrefix: string;
  value: string | null;
  onFill: (patch: Partial<LineForm>) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  if (items.length === 0 && !value) return null;

  async function pick(code: string) {
    if (!code) return onFill({ item_code: null });
    setBusy(true);
    setNote(null);
    try {
      const f = await runtime.itemLine(account, code, side, thousandths(quantity) ? quantity.trim() : "1");
      onFill({
        item_code: f.item_code,
        description: f.description,
        unit: f.unit ?? "",
        vat_code: f.vat_code,
        ...(f.unit_price_pence !== null ? { price: poundsInput(f.unit_price_pence) } : {}),
      });
      if (f.unit_price_pence === null) setNote(`This item has no ${side === "sale" ? "sale" : "purchase"} price: type one in.`);
    } catch (e) {
      setNote((e as Error).message.replace(/ \(status \d+[^)]*\)$/, ""));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-2">
      <label className={fieldLabel} htmlFor={`${idPrefix}-item`}>Product or service (optional)</label>
      <select id={`${idPrefix}-item`} className={fieldInput} value={value ?? ""} disabled={busy} onChange={(e) => void pick(e.target.value)}>
        <option value="">Type it in myself</option>
        {value && !items.some((i) => i.code === value) && <option value={value}>{value} (archived)</option>}
        {items.map((i) => <option key={i.code} value={i.code}>{i.code} · {i.name}</option>)}
      </select>
      {note && <p role="status" className="mt-1 text-xs font-semibold text-warn-ink">{note}</p>}
    </div>
  );
}

/** The lines of a quote, order or repeating template: same fields and rounding preview as an invoice. */
export default function LinesEditor({
  account, lines, onChange, items, side, idPrefix, priceLabel = "Unit price (£, ex VAT)",
}: {
  account: AccountInfo;
  lines: LineForm[];
  onChange: (next: LineForm[]) => void;
  items: RtItem[];
  side: "sale" | "purchase";
  idPrefix: string;
  priceLabel?: string;
}) {
  const set = (key: number, patch: Partial<LineForm>) => onChange(lines.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  const priced = lines.filter((l) => parsePounds(l.price) !== null).map((l) => ({ quantity: l.quantity, unit_price_pence: parsePounds(l.price)!, vat_code: l.vat_code }));
  const totals = liveTotals(priced);

  return (
    <div>
      <div className="space-y-3">
        {lines.map((l, n) => {
          const p = linePence({ quantity: l.quantity, unit_price_pence: parsePounds(l.price) ?? 0, vat_code: l.vat_code });
          const priceOk = l.price.trim() === "" || parsePounds(l.price) !== null;
          const id = `${idPrefix}-${l.key}`;
          return (
            <div key={l.key} className="rounded-xl border border-border p-3">
              <ItemPicker account={account} items={items} side={side} quantity={l.quantity} idPrefix={id} value={l.item_code} onFill={(patch) => set(l.key, patch)} />
              <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
                <div>
                  <label className={fieldLabel} htmlFor={`${id}-desc`}>Description</label>
                  <input id={`${id}-desc`} className={fieldInput} value={l.description} onChange={(e) => set(l.key, { description: e.target.value })} />
                </div>
                <p className="self-end pb-2 text-right text-[15px] font-extrabold tabular-nums">{p && parsePounds(l.price) !== null ? money(p.net) : "—"}</p>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <div>
                  <label className={fieldLabel} htmlFor={`${id}-qty`}>Qty</label>
                  <input id={`${id}-qty`} inputMode="decimal" className={fieldInput} value={l.quantity} onChange={(e) => set(l.key, { quantity: e.target.value })} />
                </div>
                <div>
                  <label className={fieldLabel} htmlFor={`${id}-unit`}>Unit</label>
                  <input id={`${id}-unit`} className={fieldInput} placeholder="hours, days, each" value={l.unit} onChange={(e) => set(l.key, { unit: e.target.value })} />
                </div>
                <div>
                  <label className={fieldLabel} htmlFor={`${id}-price`}>{priceLabel}</label>
                  <input id={`${id}-price`} inputMode="decimal" className={`${fieldInput} ${priceOk ? "" : "border-warn-border"}`} placeholder="45.00" value={l.price} onChange={(e) => set(l.key, { price: e.target.value })} />
                </div>
                <div>
                  <label className={fieldLabel} htmlFor={`${id}-vat`}>VAT</label>
                  <select id={`${id}-vat`} className={fieldInput} value={l.vat_code} onChange={(e) => set(l.key, { vat_code: e.target.value as RtSalesVatCode })}>
                    {VAT_CODES.map((c) => <option key={c.code} value={c.code}>{c.label}</option>)}
                  </select>
                </div>
              </div>
              {lines.length > 1 && (
                <button type="button" onClick={() => onChange(lines.filter((x) => x.key !== l.key))} aria-label={`Remove line ${n + 1}`} className="mt-2 text-[13px] font-bold text-muted hover:underline">
                  Remove line
                </button>
              )}
            </div>
          );
        })}
      </div>
      <button type="button" onClick={() => onChange([...lines, blankLine()])} className="mt-3 text-sm font-bold text-teal-dark hover:underline">
        + Add a line
      </button>
      <dl className="mt-4 space-y-1 border-t border-border pt-3 text-sm italic" aria-live="polite">
        <div className="flex justify-between"><dt className="font-bold">Net</dt><dd className="tabular-nums">{money(totals.net)}</dd></div>
        <div className="flex justify-between"><dt className="font-bold">VAT</dt><dd className="tabular-nums">{money(totals.vat)}</dd></div>
        <div className="flex justify-between text-[17px]"><dt className="font-extrabold">Total</dt><dd className="font-extrabold tabular-nums">{money(totals.total)}</dd></div>
      </dl>
      <p className="mt-2 text-xs text-muted">A preview while you type; Accnomos works out the sums again when you save.</p>
    </div>
  );
}
