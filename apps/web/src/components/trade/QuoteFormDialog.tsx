"use client";

import { useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import Modal, { fieldArea, fieldInput, fieldLabel, primaryButton, secondaryButton } from "@/components/invoices/Modal";
import { RuntimeErrorNote } from "@/components/States";
import LinesEditor, { blankLine, linesFromRt, linesToIn, type LineForm } from "@/components/trade/LinesEditor";
import PartyFields, { EMPTY_PARTY, cleanParty } from "@/components/trade/PartyFields";
import { useItems } from "@/components/trade/useItems";
import { todayIso } from "@/lib/invoices";
import { runtime, type RtInvoiceCustomer, type RtQuote } from "@/lib/runtime";

/** Write a quote, or change a draft one. The runtime numbers (QU-0001) and prices it on save. */
export default function QuoteFormDialog({ account, quote, onClose, onSaved }: { account: AccountInfo; quote: RtQuote | null; onClose: () => void; onSaved: (q: RtQuote) => void }) {
  const items = useItems(account);
  const [customers, setCustomers] = useState<RtInvoiceCustomer[]>([]);
  const [customer, setCustomer] = useState<RtInvoiceCustomer>(quote?.customer ?? EMPTY_PARTY);
  const [issue, setIssue] = useState(quote?.issue_date ?? todayIso());
  const [expiry, setExpiry] = useState(quote?.expiry_date ?? "");
  const [reference, setReference] = useState(quote?.reference ?? "");
  const [notes, setNotes] = useState(quote?.notes ?? "");
  const [lines, setLines] = useState<LineForm[]>(() => (quote ? linesFromRt(quote.lines) : [blankLine()]));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    runtime.invoiceCustomers(account).then(setCustomers).catch(() => setCustomers([]));
  }, [account]);

  async function save() {
    if (!customer.name.trim()) return setError("Add the customer's name.");
    const out = linesToIn(lines);
    if (typeof out === "string") return setError(out);
    setBusy(true);
    setError(null);
    const draft = { customer: cleanParty(customer), issue_date: issue || null, expiry_date: expiry || null, lines: out, reference: reference.trim() || null, notes: notes.trim() || null };
    try {
      onSaved(quote ? await runtime.updateQuote(account, quote.number, draft) : await runtime.createQuote(account, draft));
    } catch (e) {
      const msg = (e as Error).message;
      setError(/"(?:detail|msg)":"([^"]+)"/.exec(msg)?.[1] ?? msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal id="quote-form-title" title={quote ? `Change quote ${quote.number}` : "New quote"} onClose={onClose} wide>
      <div className="mt-4 space-y-4">
        <section aria-labelledby="quote-customer"><h3 id="quote-customer" className="mb-2 text-[17px] font-extrabold">Customer</h3>
          <PartyFields party={customer} onChange={setCustomer} known={customers} noun="customer" idPrefix="quote-cust" emailLabel="Email (the quote is sent here)" />
        </section>
        <section aria-labelledby="quote-dates"><h3 id="quote-dates" className="mb-2 text-[17px] font-extrabold">Dates</h3>
          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <label className={fieldLabel} htmlFor="quote-issue">Quote date</label>
              <input id="quote-issue" type="date" className={fieldInput} value={issue} onChange={(e) => setIssue(e.target.value)} />
            </div>
            <div>
              <label className={fieldLabel} htmlFor="quote-expiry">Valid until</label>
              <input id="quote-expiry" type="date" className={fieldInput} value={expiry} onChange={(e) => setExpiry(e.target.value)} />
              {!expiry && <p className="mt-1 text-xs text-muted">Blank: 30 days after the quote date</p>}
            </div>
            <div>
              <label className={fieldLabel} htmlFor="quote-ref">Your reference</label>
              <input id="quote-ref" className={fieldInput} value={reference} onChange={(e) => setReference(e.target.value)} />
            </div>
          </div>
        </section>
        <section aria-labelledby="quote-lines"><h3 id="quote-lines" className="mb-2 text-[17px] font-extrabold">Lines</h3>
          <LinesEditor account={account} lines={lines} onChange={setLines} items={items} side="sale" idPrefix="quote-ln" />
        </section>
        <div>
          <label className={fieldLabel} htmlFor="quote-notes">Note on the quote (optional)</label>
          <textarea id="quote-notes" rows={2} className={fieldArea} value={notes} onChange={(e) => setNotes(e.target.value)} />
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
