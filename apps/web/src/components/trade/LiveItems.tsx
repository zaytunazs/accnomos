"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import Modal, { fieldArea, fieldInput, fieldLabel, primaryButton, secondaryButton } from "@/components/invoices/Modal";
import SignInCta from "@/components/SignInCta";
import { EmptyState, LoadingSkeleton, RuntimeErrorNote } from "@/components/States";
import { money, parsePounds, poundsInput, useMsAccount, VAT_CODES } from "@/lib/invoices";
import { runtime, type RtItem, type RtItemImport, type RtItemIn, type RtSalesVatCode } from "@/lib/runtime";

const action = "text-[13px] font-bold text-teal-dark hover:underline";
const exportClass = "h-11 rounded-xl border border-border bg-white px-4 text-[15px] font-bold";

function ItemFormDialog({ account, item, onClose, onSaved }: { account: AccountInfo; item: RtItem | null; onClose: () => void; onSaved: (i: RtItem) => void }) {
  const [code, setCode] = useState(item?.code ?? "");
  const [name, setName] = useState(item?.name ?? "");
  const [description, setDescription] = useState(item?.description ?? "");
  const [unit, setUnit] = useState(item?.unit ?? "");
  const [sale, setSale] = useState(item?.sale_price_pence != null ? poundsInput(item.sale_price_pence) : "");
  const [purchase, setPurchase] = useState(item?.purchase_price_pence != null ? poundsInput(item.purchase_price_pence) : "");
  const [vat, setVat] = useState<RtSalesVatCode>(item?.vat_code ?? "S");
  const [income, setIncome] = useState(item?.income_account ?? "4000 Sales");
  const [expense, setExpense] = useState(item?.expense_account ?? "7999 Sundry expenses");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    if (!code.trim()) return setError("Add a code, e.g. LAB-1.");
    if (!name.trim()) return setError("Add a name.");
    const s = sale.trim() ? parsePounds(sale) : null;
    const p = purchase.trim() ? parsePounds(purchase) : null;
    if (sale.trim() && s === null) return setError("Sale price must be pounds and pence, e.g. 45.00.");
    if (purchase.trim() && p === null) return setError("Purchase price must be pounds and pence, e.g. 30.00.");
    const body: RtItemIn = {
      code: code.trim(), name: name.trim(), description: description.trim() || null, unit: unit.trim() || null,
      sale_price_pence: s, purchase_price_pence: p, vat_code: vat, income_account: income.trim(), expense_account: expense.trim(), archived: false,
    };
    setBusy(true);
    setError(null);
    try {
      onSaved(item ? await runtime.updateItem(account, item.code, body) : await runtime.createItem(account, body));
    } catch (e) {
      const msg = (e as Error).message;
      setError(/"(?:detail|msg)":"([^"]+)"/.exec(msg)?.[1] ?? msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal id="item-form-title" title={item ? `Change ${item.code}` : "New product or service"} onClose={onClose}>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div>
          <label className={fieldLabel} htmlFor="item-code">Code</label>
          <input id="item-code" className={fieldInput} value={code} disabled={item !== null} onChange={(e) => setCode(e.target.value)} placeholder="LAB-1" />
        </div>
        <div>
          <label className={fieldLabel} htmlFor="item-name">Name</label>
          <input id="item-name" className={fieldInput} value={name} onChange={(e) => setName(e.target.value)} placeholder="Labour" />
        </div>
        <div className="sm:col-span-2">
          <label className={fieldLabel} htmlFor="item-desc">Description on documents (optional)</label>
          <textarea id="item-desc" rows={2} className={fieldArea} value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        <div>
          <label className={fieldLabel} htmlFor="item-unit">Unit</label>
          <input id="item-unit" className={fieldInput} value={unit} onChange={(e) => setUnit(e.target.value)} placeholder="hours, each" />
        </div>
        <div>
          <label className={fieldLabel} htmlFor="item-vat">VAT</label>
          <select id="item-vat" className={fieldInput} value={vat} onChange={(e) => setVat(e.target.value as RtSalesVatCode)}>
            {VAT_CODES.map((c) => <option key={c.code} value={c.code}>{c.label}</option>)}
          </select>
        </div>
        <div>
          <label className={fieldLabel} htmlFor="item-sale">Sale price (£, ex VAT)</label>
          <input id="item-sale" inputMode="decimal" className={fieldInput} value={sale} onChange={(e) => setSale(e.target.value)} placeholder="45.00" />
        </div>
        <div>
          <label className={fieldLabel} htmlFor="item-purchase">Purchase price (£, ex VAT)</label>
          <input id="item-purchase" inputMode="decimal" className={fieldInput} value={purchase} onChange={(e) => setPurchase(e.target.value)} placeholder="30.00" />
        </div>
        <div>
          <label className={fieldLabel} htmlFor="item-income">Income account</label>
          <input id="item-income" className={fieldInput} value={income} onChange={(e) => setIncome(e.target.value)} />
        </div>
        <div>
          <label className={fieldLabel} htmlFor="item-expense">Expense account</label>
          <input id="item-expense" className={fieldInput} value={expense} onChange={(e) => setExpense(e.target.value)} />
        </div>
      </div>
      <p className="mt-3 text-xs text-muted">
        Invoices still post their sales to 4000 Sales whatever the income account says; bills and purchase orders use the expense account.
      </p>
      {error && <p role="alert" className="mt-3 text-sm font-bold text-warn-ink">{error}</p>}
      <div className="mt-4 flex flex-wrap gap-3">
        <button type="button" onClick={save} disabled={busy} className={primaryButton}>{busy ? "Saving…" : "Save"}</button>
        <button type="button" onClick={onClose} className={secondaryButton}>Cancel</button>
      </div>
    </Modal>
  );
}

export default function LiveItems() {
  const { account, ready } = useMsAccount();
  const [items, setItems] = useState<RtItem[] | null>(null);
  const [archived, setArchived] = useState(false);
  const [dialog, setDialog] = useState<{ item: RtItem | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [result, setResult] = useState<RtItemImport | null>(null);
  const [update, setUpdate] = useState(true);
  const file = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    if (!account) return;
    try {
      setItems(await runtime.items(account, archived));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [account, archived]);
  useEffect(() => {
    queueMicrotask(load);
  }, [load]);

  async function exportCsv() {
    if (!account) return;
    try {
      const r = await runtime.exportItems(account);
      const url = URL.createObjectURL(new Blob([`﻿${r.csv}`], { type: "text/csv;charset=utf-8" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = r.filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function importCsv(f: File | undefined) {
    if (!account || !f) return;
    setResult(null);
    try {
      const r = await runtime.importItems(account, await f.text(), update);
      setResult(r);
      setNote(`${r.created} added, ${r.updated} updated, ${r.skipped} skipped.`);
      await load();
    } catch (e) {
      const msg = (e as Error).message;
      setError(/"detail":"([^"]+)"/.exec(msg)?.[1] ?? msg);
    } finally {
      if (file.current) file.current.value = "";
    }
  }

  async function archive(i: RtItem) {
    if (!account) return;
    try {
      await runtime.archiveItem(account, i.code);
      setNote(`${i.code} is archived. Old documents keep their lines; it no longer appears in the pickers.`);
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function restore(i: RtItem) {
    if (!account) return;
    try {
      await runtime.updateItem(account, i.code, { ...i, archived: false });
      setNote(`${i.code} is back in the pickers.`);
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (ready && !account) {
    return (
      <p className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl bg-ground p-4 text-sm text-muted">
        <SignInCta />
        <span>to keep a list of what you sell and buy; it is saved in your OneDrive under _System/Items.</span>
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="flex min-h-11 items-center gap-2 text-[15px] font-semibold">
          <input type="checkbox" className="h-5 w-5 accent-teal" checked={archived} onChange={(e) => setArchived(e.target.checked)} />
          Show archived
        </label>
        <div className="flex flex-wrap gap-2">
          <button type="button" className={exportClass} onClick={exportCsv}>Export CSV</button>
          <button type="button" className={primaryButton} onClick={() => setDialog({ item: null })}>New item</button>
        </div>
      </div>

      <details className="rounded-2xl border border-border bg-white p-4">
        <summary className="cursor-pointer text-[15px] font-bold">Import from a CSV file</summary>
        <p className="mt-2 text-sm text-muted">
          Use the file from Export CSV, or a Xero inventory export. Rows that cannot be read are skipped and listed below; nothing else changes.
        </p>
        <label className="mt-3 flex min-h-11 items-center gap-2 text-[15px] font-semibold">
          <input type="checkbox" className="h-5 w-5 accent-teal" checked={update} onChange={(e) => setUpdate(e.target.checked)} />
          Update items that already have the same code
        </label>
        <label className={`${fieldLabel} mt-2 block`} htmlFor="items-csv">CSV file</label>
        <input id="items-csv" ref={file} type="file" accept=".csv,text/csv" className="mt-1 block w-full text-[15px]" onChange={(e) => void importCsv(e.target.files?.[0])} />
        {result && result.errors.length > 0 && (
          <ul aria-label="Rows not imported" className="mt-3 list-disc pl-5 text-sm text-warn-ink">
            {result.errors.map((r) => <li key={`${r.line}-${r.message}`}>Line {r.line}{r.code ? ` (${r.code})` : ""}: {r.message}</li>)}
          </ul>
        )}
      </details>

      {note && <p role="status" className="rounded-xl bg-teal-tint px-4 py-3 text-sm font-bold text-teal-dark">{note}</p>}
      {error && <RuntimeErrorNote message={error} title="Could not complete that" />}
      {!items && !error && <LoadingSkeleton lines={3} label="Loading your items…" />}
      {items && items.length === 0 && (
        <EmptyState title="No products or services yet" body="Add what you sell and buy once, then pick it on an invoice, quote or purchase order to fill the line." />
      )}
      {items && items.length > 0 && (
        <ul className="divide-y divide-border rounded-2xl border border-border bg-white">
          {items.map((i) => (
            <li key={i.code} className="px-4 py-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className={`truncate text-[15px] font-bold ${i.archived ? "text-muted" : ""}`}>{i.code} · {i.name}{i.archived && " (archived)"}</p>
                  <p className="text-sm text-muted">
                    Sell {i.sale_price_pence !== null ? money(i.sale_price_pence) : "no price"} · buy {i.purchase_price_pence !== null ? money(i.purchase_price_pence) : "no price"}
                    {i.unit && ` per ${i.unit}`} · VAT {VAT_CODES.find((c) => c.code === i.vat_code)?.label}
                  </p>
                </div>
                <div className="flex gap-4">
                  <button type="button" className={action} onClick={() => setDialog({ item: i })}>Edit</button>
                  {i.archived
                    ? <button type="button" className={action} onClick={() => restore(i)}>Restore</button>
                    : <button type="button" className="text-[13px] font-bold text-muted hover:underline" onClick={() => archive(i)}>Archive</button>}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
      {dialog && account && (
        <ItemFormDialog account={account} item={dialog.item} onClose={() => setDialog(null)}
          onSaved={(i) => { setDialog(null); setNote(`${i.code} saved.`); void load(); }} />
      )}
    </div>
  );
}
