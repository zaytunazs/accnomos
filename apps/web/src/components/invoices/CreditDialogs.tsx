"use client";

import { useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import Modal, { fieldInput, fieldLabel, primaryButton, secondaryButton } from "@/components/invoices/Modal";
import { RuntimeErrorNote, isAuthError, isServerError } from "@/components/States";
import { money, parsePounds, poundsInput, todayIso } from "@/lib/invoices";
import { runtime, ukDate, type RtCredit, type RtOpenItem } from "@/lib/runtime";

/**
 * Credits on a contact (services/runtime/app/credits.py) and payments against bills (app/payments.py). The runtime
 * checks every amount against what is left and posts by code; these dialogs only collect what the user chose.
 */

export function errorText(e: unknown): string | null {
  const msg = (e as Error).message;
  if (msg === "redirecting for consent") return null;
  const detail = /"detail":"([^"]+)"/.exec(msg)?.[1];
  return detail ?? msg;
}

function Note({ note }: { note: string }) {
  if (isAuthError(note) || isServerError(note)) return <RuntimeErrorNote message={note} />;
  return <p role="alert" className="mt-3 text-sm font-bold text-warn-ink">{note}</p>;
}

const docLabel = (d: RtOpenItem) =>
  `${d.reference ?? (d.side === "sale" ? "Invoice" : "Bill")} · ${ukDate(d.date)} · ${money(d.outstanding_pence)} left`;
const creditLabel = (c: RtCredit & { reference?: string | null }) =>
  `${money(c.amount_pence)} from ${c.source === "payment" ? "an overpayment" : "a credit note"}${c.reference ? ` (${c.reference})` : ""} · ${ukDate(c.date)}`;

/** Apply credit: put a credit on the account towards one open document of the same contact. Nothing is posted. */
export function ApplyCreditDialog({ account, name, credits, documents, onClose, onDone }: {
  account: AccountInfo;
  name: string;
  credits: (RtCredit & { reference?: string | null })[];
  documents: RtOpenItem[];
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const [creditId, setCreditId] = useState(credits[0]?.id ?? "");
  const credit = credits.find((c) => c.id === creditId);
  const docs = documents.filter((d) => d.side === credit?.side && d.outstanding_pence > 0);
  const [docId, setDocId] = useState(docs[0]?.event_id ?? "");
  const doc = docs.find((d) => d.event_id === docId);
  const most = credit && doc ? Math.min(credit.amount_pence, doc.outstanding_pence) : 0;
  const [amount, setAmount] = useState(poundsInput(most));
  const [day, setDay] = useState(todayIso());
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const pence = parsePounds(amount);
  const valid = !!credit && !!doc && pence !== null && pence > 0 && pence <= most;

  async function save() {
    if (!valid) return;
    setBusy(true);
    setNote(null);
    try {
      await runtime.applyCredit(account, { credit: credit!.id, event_id: doc!.event_id, amount_pence: pence!, date: day });
      onDone(`${money(pence!)} of ${name}'s credit applied to ${doc!.reference ?? "the document"}.`);
    } catch (e) {
      setNote(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal id="apply-credit-title" title={`Apply credit for ${name}`} onClose={onClose}>
      <p className="mt-1 text-sm text-muted">Money already on {name}&apos;s account goes towards another of their documents.</p>
      <div className="mt-4 space-y-3">
        <div>
          <label className={fieldLabel} htmlFor="apply-credit">Credit</label>
          <select id="apply-credit" className={fieldInput} value={creditId} onChange={(e) => { setCreditId(e.target.value); setDocId(""); setAmount(""); }}>
            {credits.map((c) => <option key={c.id} value={c.id}>{creditLabel(c)}</option>)}
          </select>
        </div>
        <div>
          <label className={fieldLabel} htmlFor="apply-doc">{credit?.side === "purchase" ? "Bill" : "Invoice"}</label>
          {docs.length ? (
            <select
              id="apply-doc"
              className={fieldInput}
              value={docId}
              onChange={(e) => {
                setDocId(e.target.value);
                const d = docs.find((x) => x.event_id === e.target.value);
                if (d && credit) setAmount(poundsInput(Math.min(credit.amount_pence, d.outstanding_pence)));
              }}
            >
              <option value="">Choose…</option>
              {docs.map((d) => <option key={d.event_id} value={d.event_id}>{docLabel(d)}</option>)}
            </select>
          ) : (
            <p className="mt-1 text-sm font-semibold text-muted">Nothing of {name}&apos;s is waiting to be paid. Refund the credit instead.</p>
          )}
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className={fieldLabel} htmlFor="apply-amount">Amount (£)</label>
            <input id="apply-amount" inputMode="decimal" className={fieldInput} value={amount} onChange={(e) => setAmount(e.target.value)} />
          </div>
          <div>
            <label className={fieldLabel} htmlFor="apply-date">Date</label>
            <input id="apply-date" type="date" className={fieldInput} value={day} onChange={(e) => setDay(e.target.value)} />
          </div>
        </div>
      </div>
      <p className="mt-3 rounded-xl bg-ground px-4 py-2 text-xs text-muted">
        No money moves and nothing new is posted: the credit is already in{" "}
        {credit?.side === "purchase" ? "2100 Creditors" : "1100 Debtors"}. {most > 0 ? `Up to ${money(most)}.` : ""}
      </p>
      <div className="mt-4 flex flex-wrap gap-3">
        <button type="button" onClick={save} disabled={busy || !valid} className={primaryButton}>{busy ? "Saving…" : "Apply credit"}</button>
        <button type="button" onClick={onClose} className={secondaryButton}>Cancel</button>
      </div>
      {note && <Note note={note} />}
    </Modal>
  );
}

/** Refund: pay a customer's credit back, or record a supplier paying theirs back. Posted by the runtime. */
export function RefundDialog({ account, name, credits, onClose, onDone }: {
  account: AccountInfo;
  name: string;
  credits: (RtCredit & { reference?: string | null })[];
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const [creditId, setCreditId] = useState(credits[0]?.id ?? "");
  const credit = credits.find((c) => c.id === creditId);
  const [amount, setAmount] = useState(poundsInput(credit?.amount_pence ?? 0));
  const [day, setDay] = useState(todayIso());
  const [from, setFrom] = useState<"1200 Bank" | "1210 Cash">("1200 Bank");
  const [ref, setRef] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const pence = parsePounds(amount);
  const valid = !!credit && pence !== null && pence > 0 && pence <= credit.amount_pence;
  const customer = credit?.side !== "purchase";

  async function save() {
    if (!valid) return;
    setBusy(true);
    setNote(null);
    try {
      await runtime.refundCredit(account, { credit: credit!.id, amount_pence: pence!, date: day, account: from, reference: ref || undefined });
      onDone(customer ? `Refund of ${money(pence!)} to ${name} recorded.` : `${name}'s refund of ${money(pence!)} recorded.`);
    } catch (e) {
      setNote(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal id="refund-credit-title" title={customer ? `Refund ${name}` : `Refund from ${name}`} onClose={onClose}>
      <p className="mt-1 text-sm text-muted">
        {customer ? `Money you paid back to ${name} from their credit.` : `Money ${name} paid you back for the credit they owe you.`}{" "}
        If it is on a bank statement, match the line on the Bank page instead: it offers the refund there.
      </p>
      <div className="mt-4 space-y-3">
        <div>
          <label className={fieldLabel} htmlFor="refund-credit">Credit</label>
          <select id="refund-credit" className={fieldInput} value={creditId} onChange={(e) => { setCreditId(e.target.value); setAmount(poundsInput(credits.find((c) => c.id === e.target.value)?.amount_pence ?? 0)); }}>
            {credits.map((c) => <option key={c.id} value={c.id}>{creditLabel(c)}</option>)}
          </select>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className={fieldLabel} htmlFor="refund-amount">Amount (£)</label>
            <input id="refund-amount" inputMode="decimal" className={fieldInput} value={amount} onChange={(e) => setAmount(e.target.value)} />
          </div>
          <div>
            <label className={fieldLabel} htmlFor="refund-date">Date</label>
            <input id="refund-date" type="date" className={fieldInput} value={day} onChange={(e) => setDay(e.target.value)} />
          </div>
          <div className="sm:col-span-2">
            <label className={fieldLabel} htmlFor="refund-from">{customer ? "Paid from" : "Paid into"}</label>
            <select id="refund-from" className={fieldInput} value={from} onChange={(e) => setFrom(e.target.value as "1200 Bank" | "1210 Cash")}>
              <option value="1200 Bank">Bank (1200)</option>
              <option value="1210 Cash">Cash (1210)</option>
            </select>
          </div>
        </div>
        <div>
          <label className={fieldLabel} htmlFor="refund-ref">Reference (optional)</label>
          <input id="refund-ref" className={fieldInput} value={ref} onChange={(e) => setRef(e.target.value)} />
        </div>
      </div>
      <p className="mt-3 rounded-xl bg-ground px-4 py-2 text-xs text-muted">
        {valid ? `${money(pence!)} ` : ""}is recorded in your books as{" "}
        {customer ? `Dr 1100 Debtors / Cr ${from}` : `Dr ${from} / Cr 2100 Creditors`}, with no VAT.
      </p>
      <div className="mt-4 flex flex-wrap gap-3">
        <button type="button" onClick={save} disabled={busy || !valid} className={primaryButton}>{busy ? "Saving…" : "Record refund"}</button>
        <button type="button" onClick={onClose} className={secondaryButton}>Cancel</button>
      </div>
      {note && <Note note={note} />}
    </Modal>
  );
}

/** Record payment on a bill: amount (default what is left), date, bank or cash. Posted Dr 2100 Creditors / Cr Bank. */
export function BillPaymentDialog({ account, name, bill, onClose, onDone }: {
  account: AccountInfo;
  name: string;
  bill: RtOpenItem;
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const [amount, setAmount] = useState(poundsInput(bill.outstanding_pence));
  const [day, setDay] = useState(todayIso());
  const [from, setFrom] = useState<"1200 Bank" | "1210 Cash">("1200 Bank");
  const [ref, setRef] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const pence = parsePounds(amount);
  const valid = pence !== null && pence > 0;
  const over = valid && pence! > bill.outstanding_pence ? pence! - bill.outstanding_pence : 0;
  const label = bill.reference ?? `the bill of ${ukDate(bill.date)}`;

  async function save() {
    if (!valid) return;
    setBusy(true);
    setNote(null);
    try {
      await runtime.recordPayment(account, {
        side: "purchase",
        date: day,
        amount_pence: pence!,
        account: from,
        reference: ref || undefined,
        allocations: [{ event_id: bill.event_id, amount_pence: Math.min(pence!, bill.outstanding_pence) }],
      });
      const left = bill.outstanding_pence - Math.min(pence!, bill.outstanding_pence);
      onDone(left > 0 ? `Payment recorded on ${label}: ${money(left)} still to pay.` : `${label} is paid.`);
    } catch (e) {
      setNote(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal id="bill-payment-title" title={`Record payment on ${label}`} onClose={onClose}>
      <p className="mt-1 text-sm text-muted">
        {name} · bill {money(bill.gross_pence)} · paid {money(bill.gross_pence - bill.outstanding_pence)} · balance{" "}
        <strong className="text-ink">{money(bill.outstanding_pence)}</strong>
      </p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div>
          <label className={fieldLabel} htmlFor="bill-amount">Amount (£)</label>
          <input id="bill-amount" inputMode="decimal" className={fieldInput} value={amount} onChange={(e) => setAmount(e.target.value)} />
        </div>
        <div>
          <label className={fieldLabel} htmlFor="bill-date">Paid on</label>
          <input id="bill-date" type="date" className={fieldInput} value={day} onChange={(e) => setDay(e.target.value)} />
        </div>
        <div className="sm:col-span-2">
          <label className={fieldLabel} htmlFor="bill-from">Paid from</label>
          <select id="bill-from" className={fieldInput} value={from} onChange={(e) => setFrom(e.target.value as "1200 Bank" | "1210 Cash")}>
            <option value="1200 Bank">Bank (1200)</option>
            <option value="1210 Cash">Cash (1210)</option>
          </select>
        </div>
        <div className="sm:col-span-2">
          <label className={fieldLabel} htmlFor="bill-ref">Payment reference (optional)</label>
          <input id="bill-ref" className={fieldInput} value={ref} onChange={(e) => setRef(e.target.value)} />
        </div>
      </div>
      <p className="mt-3 rounded-xl bg-ground px-4 py-2 text-xs text-muted">
        {valid ? `${money(pence!)} ` : ""}is recorded in your books as money out ({from}) against 2100 Creditors.{" "}
        {over > 0 ? `${money(over)} more than the balance is kept as a credit ${name} owes you.` : valid && pence! < bill.outstanding_pence ? `${money(bill.outstanding_pence - pence!)} stays to pay.` : ""}
        {" "}When the payment shows on a bank statement, the Bank page suggests linking the line to it.
      </p>
      <div className="mt-4 flex flex-wrap gap-3">
        <button type="button" onClick={save} disabled={busy || !valid} className={primaryButton}>{busy ? "Saving…" : "Record payment"}</button>
        <button type="button" onClick={onClose} className={secondaryButton}>Cancel</button>
      </div>
      {note && <Note note={note} />}
    </Modal>
  );
}
