"use client";

import { useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import Modal, { fieldArea, fieldInput, fieldLabel, primaryButton, secondaryButton } from "@/components/invoices/Modal";
import { RuntimeErrorNote } from "@/components/States";
import LinesEditor, { blankLine, linesFromRt, linesToIn, type LineForm } from "@/components/trade/LinesEditor";
import PartyFields, { EMPTY_PARTY, cleanParty } from "@/components/trade/PartyFields";
import { useItems } from "@/components/trade/useItems";
import { todayIso } from "@/lib/invoices";
import { runtime, type RtInvoiceCustomer, type RtPurchaseOrder } from "@/lib/runtime";

/** Write a purchase order, or change a draft one. The runtime numbers (PO-0001) and prices it on save. */
export default function PurchaseOrderFormDialog({ account, order, onClose, onSaved }: { account: AccountInfo; order: RtPurchaseOrder | null; onClose: () => void; onSaved: (o: RtPurchaseOrder) => void }) {
  const items = useItems(account);
  const [suppliers, setSuppliers] = useState<RtInvoiceCustomer[]>([]);
  const [supplier, setSupplier] = useState<RtInvoiceCustomer>(order?.supplier ?? EMPTY_PARTY);
  const [issue, setIssue] = useState(order?.issue_date ?? todayIso());
  const [delivery, setDelivery] = useState(order?.delivery_date ?? "");
  const [deliverTo, setDeliverTo] = useState(order?.delivery_address ?? "");
  const [reference, setReference] = useState(order?.reference ?? "");
  const [account_, setAccount] = useState(order?.account ?? "");
  const [notes, setNotes] = useState(order?.notes ?? "");
  const [lines, setLines] = useState<LineForm[]>(() => (order ? linesFromRt(order.lines) : [blankLine()]));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    runtime.poSuppliers(account).then(setSuppliers).catch(() => setSuppliers([]));
  }, [account]);

  async function save() {
    if (!supplier.name.trim()) return setError("Add the supplier's name.");
    const out = linesToIn(lines);
    if (typeof out === "string") return setError(out);
    setBusy(true);
    setError(null);
    const draft = {
      supplier: cleanParty(supplier), issue_date: issue || null, delivery_date: delivery || null, delivery_address: deliverTo.trim() || null,
      lines: out, reference: reference.trim() || null, notes: notes.trim() || null, account: account_.trim() || null,
    };
    try {
      onSaved(order ? await runtime.updatePurchaseOrder(account, order.number, draft) : await runtime.createPurchaseOrder(account, draft));
    } catch (e) {
      const msg = (e as Error).message;
      setError(/"(?:detail|msg)":"([^"]+)"/.exec(msg)?.[1] ?? msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal id="po-form-title" title={order ? `Change order ${order.number}` : "New purchase order"} onClose={onClose} wide>
      <div className="mt-4 space-y-4">
        <section aria-labelledby="po-supplier"><h3 id="po-supplier" className="mb-2 text-[17px] font-extrabold">Supplier</h3>
          <PartyFields party={supplier} onChange={setSupplier} known={suppliers} noun="supplier" idPrefix="po-sup" emailLabel="Email (the order is sent here)" />
        </section>
        <section aria-labelledby="po-dates"><h3 id="po-dates" className="mb-2 text-[17px] font-extrabold">Delivery</h3>
          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <label className={fieldLabel} htmlFor="po-issue">Order date</label>
              <input id="po-issue" type="date" className={fieldInput} value={issue} onChange={(e) => setIssue(e.target.value)} />
            </div>
            <div>
              <label className={fieldLabel} htmlFor="po-delivery">Delivery wanted by</label>
              <input id="po-delivery" type="date" className={fieldInput} value={delivery} onChange={(e) => setDelivery(e.target.value)} />
            </div>
            <div>
              <label className={fieldLabel} htmlFor="po-ref">Your reference</label>
              <input id="po-ref" className={fieldInput} value={reference} onChange={(e) => setReference(e.target.value)} />
            </div>
            <div className="sm:col-span-2">
              <label className={fieldLabel} htmlFor="po-deliver-to">Deliver to (optional)</label>
              <textarea id="po-deliver-to" rows={2} className={fieldArea} value={deliverTo} onChange={(e) => setDeliverTo(e.target.value)} />
            </div>
            <div>
              <label className={fieldLabel} htmlFor="po-account">Expense account (optional)</label>
              <input id="po-account" className={fieldInput} value={account_} onChange={(e) => setAccount(e.target.value)} placeholder="5100 Tools & small equipment" />
            </div>
          </div>
        </section>
        <section aria-labelledby="po-lines"><h3 id="po-lines" className="mb-2 text-[17px] font-extrabold">Lines</h3>
          <LinesEditor account={account} lines={lines} onChange={setLines} items={items} side="purchase" idPrefix="po-ln" />
        </section>
        <div>
          <label className={fieldLabel} htmlFor="po-notes">Note to the supplier (optional)</label>
          <textarea id="po-notes" rows={2} className={fieldArea} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
        {error && <RuntimeErrorNote message={error} />}
        <div className="flex flex-wrap gap-3">
          <button type="button" onClick={save} disabled={busy} className={primaryButton}>{busy ? "Saving…" : "Save draft"}</button>
          <button type="button" onClick={onClose} className={secondaryButton}>Cancel</button>
        </div>
      </div>
    </Modal>
  );
}
