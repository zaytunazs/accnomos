"use client";

import { useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import Modal, { fieldArea, fieldInput, fieldLabel, primaryButton, secondaryButton } from "@/components/invoices/Modal";
import { RuntimeErrorNote, isAuthError, isServerError, parseRuntimeError } from "@/components/States";
import { liveTotals, money, parsePounds, poundsInput, thousandths, todayIso, VAT_CODES } from "@/lib/invoices";
import {
  runtime,
  ukDate,
  type RtBankLine,
  type RtCreditNote,
  type RtCreditNotePdf,
  type RtInvoice,
  type RtPaymentStatus,
  type RtSalesVatCode,
} from "@/lib/runtime";

/**
 * Payments and credit notes on an invoice (services/runtime/app/payments.py, credit_notes.py). Every figure that is
 * posted is worked out by the runtime; the previews here only add up what the user typed.
 */

function errorText(e: unknown): string | null {
  const msg = (e as Error).message;
  if (msg === "redirecting for consent") return null;
  const detail = /"detail":"([^"]+)"/.exec(msg)?.[1];
  return detail ?? msg;
}

function Note({ note }: { note: string }) {
  if (isAuthError(note) || isServerError(note)) return <RuntimeErrorNote message={note} />;
  return <p role="alert" className="mt-3 text-sm font-bold text-warn-ink">{parseRuntimeError(note).detail || note}</p>;
}

/** What is still owed (the runtime's figure when it has one). */
export function balanceOf(i: RtInvoice): number {
  if (i.money) return i.money.balance_pence;
  if (i.status === "paid") return 0;
  return i.balance_pence ?? i.total_pence;
}

export const PAYMENT_LABEL: Record<RtPaymentStatus, string> = {
  open: "Unpaid",
  part_paid: "Part paid",
  paid: "Paid",
  overpaid: "Overpaid",
};

/** Paid / credited / balance and each payment, with Remove. */
export function PaymentsPanel({ account, invoice, onChanged }: {
  account: AccountInfo;
  invoice: RtInvoice;
  onChanged: (inv: RtInvoice, message: string) => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const m = invoice.money;
  if (!m) return null;

  async function act(id: string, run: () => Promise<RtInvoice>, message: string) {
    setBusy(id);
    setNote(null);
    try {
      onChanged(await run(), message);
    } catch (e) {
      setNote(errorText(e));
    } finally {
      setBusy(null);
    }
  }
  const remove = (id: string) =>
    act(id, () => runtime.removeInvoicePayment(account, invoice.number, id), `Payment removed from ${invoice.number}.`);
  /** A Bank-page match posts nothing: turn it into a recorded payment so the money reaches 1200 Bank once. */
  const postAsPayment = (lineId: string) =>
    act(`post:${lineId}`, async () => {
      await runtime.paymentFromBankLine(account, lineId);
      return runtime.invoice(account, invoice.number);
    }, `The bank line is now a recorded payment on ${invoice.number}, in your books once.`);
  const removeUse = (useId: string) =>
    act(useId, async () => {
      await runtime.removeCreditUse(account, useId);
      return runtime.invoice(account, invoice.number);
    }, `Credit removed from ${invoice.number}.`);

  return (
    <section aria-label={`Payments on ${invoice.number}`} className="mt-3 rounded-xl border border-border bg-ground/50 p-3 text-sm">
      <dl className="grid grid-cols-3 gap-2 tabular-nums">
        <div><dt className="text-xs font-bold text-muted">Paid</dt><dd className="font-bold">{money(m.paid_pence)}</dd></div>
        <div><dt className="text-xs font-bold text-muted">Credited</dt><dd className="font-bold">{money(m.credited_pence)}</dd></div>
        <div><dt className="text-xs font-bold text-muted">Balance</dt><dd className="font-extrabold">{money(m.balance_pence)}</dd></div>
      </dl>
      {m.overpaid_pence > 0 && (
        <p className="mt-2 font-semibold text-teal-dark">{money(m.overpaid_pence)} overpaid: kept as a credit for {invoice.customer.name}.</p>
      )}
      {m.payments.length > 0 && (
        <ul className="mt-2 divide-y divide-border">
          {m.payments.map((p) => (
            <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span>
                {p.date ? ukDate(p.date) : "—"} · {p.description}
                {p.reference && <span className="text-muted"> · {p.reference}</span>}
                <span className="ml-1 font-bold tabular-nums">{money(p.applied_pence)}</span>
                {p.amount_pence !== p.applied_pence && <span className="text-muted"> of {money(p.amount_pence)}</span>}
              </span>
              <span className="flex gap-3">
                {p.source === "bank_line" && (
                  <button
                    type="button"
                    onClick={() => postAsPayment(p.id)}
                    disabled={busy !== null}
                    className="text-[13px] font-bold text-teal-dark hover:underline"
                    title="Matched on the Bank page, so nothing is in your books yet: record it as a payment from this line"
                    aria-label={`Post the bank line of ${money(p.amount_pence)} as a payment on ${invoice.number}`}
                  >
                    {busy === `post:${p.id}` ? "Posting…" : "Post as payment"}
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => remove(p.id)}
                  disabled={busy !== null}
                  className="text-[13px] font-bold text-muted hover:underline"
                  aria-label={`Remove payment of ${money(p.applied_pence)} on ${invoice.number}`}
                >
                  {busy === p.id ? "Removing…" : p.source === "bank_line" ? "Unmatch" : "Remove"}
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
      {m.credit_notes.length > 0 && (
        <ul className="mt-2 text-muted">
          {m.credit_notes.map((c) => (
            <li key={c.use_id ?? c.event_id} className="flex flex-wrap items-center justify-between gap-2">
              <span>
                Credit note {c.number ?? ""} · {money(c.applied_pence)}
                {c.use_id && " (credit applied from another invoice)"}
              </span>
              {c.use_id && (
                <button
                  type="button"
                  onClick={() => removeUse(c.use_id!)}
                  disabled={busy !== null}
                  className="text-[13px] font-bold text-muted hover:underline"
                  aria-label={`Remove credit of ${money(c.applied_pence)} applied to ${invoice.number}`}
                >
                  {busy === c.use_id ? "Removing…" : "Remove"}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-xs text-muted">Removing a payment reverses its entry in your books; nothing is deleted.</p>
      {note && <Note note={note} />}
    </section>
  );
}

/** Record payment: amount (default the balance), date, bank or cash, optional bank statement line. */
export function RecordPaymentDialog({ account, invoice, onClose, onDone }: {
  account: AccountInfo;
  invoice: RtInvoice;
  onClose: () => void;
  onDone: (inv: RtInvoice) => void;
}) {
  const owed = balanceOf(invoice);
  const [amount, setAmount] = useState(poundsInput(owed));
  const [paidOn, setPaidOn] = useState(todayIso());
  const [into, setInto] = useState<"1200 Bank" | "1210 Cash">("1200 Bank");
  const [ref, setRef] = useState("");
  const [lines, setLines] = useState<RtBankLine[] | null>(null);
  const [lineId, setLineId] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    runtime.invoiceBankCandidates(account, invoice.number).then(setLines).catch(() => setLines([]));
  }, [account, invoice.number]);

  const line = lines?.find((l) => l.id === lineId);
  const pence = line ? line.amount_pence : parsePounds(amount);
  const valid = pence !== null && pence > 0;
  const over = valid && pence! > owed ? pence! - owed : 0;

  async function save() {
    if (!valid) return;
    setBusy(true);
    setNote(null);
    try {
      onDone(await runtime.recordInvoicePayment(account, invoice.number, lineId
        ? { bank_line_id: lineId, payment_ref: ref || undefined }
        : { amount_pence: pence!, paid_on: paidOn, account: into, payment_ref: ref || undefined }));
    } catch (e) {
      setNote(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal id="invoice-payment-title" title={`Record payment on ${invoice.number}`} onClose={onClose}>
      <p className="mt-1 text-sm text-muted">
        {invoice.customer.name} · total {money(invoice.total_pence)} · balance <strong className="text-ink">{money(owed)}</strong>
      </p>
      {lines && lines.length > 0 && (
        <fieldset className="mt-4">
          <legend className={fieldLabel}>Money in on your bank statement</legend>
          <div className="mt-2 space-y-2">
            {[{ id: "", label: "Not on a statement yet" }, ...lines.map((l) => ({ id: l.id, label: `${ukDate(l.date)} · ${l.description} · ${money(l.amount_pence)}` }))].map((o) => (
              <label key={o.id || "none"} className="flex min-h-11 cursor-pointer items-center gap-3 rounded-xl border border-border px-3 text-[15px]">
                <input type="radio" name="bank-line" checked={lineId === o.id} onChange={() => setLineId(o.id)} className="h-4 w-4 accent-teal" />
                {o.label}
              </label>
            ))}
          </div>
          <p className="mt-1 text-xs text-muted">Choosing a line records its amount and matches it on the bank page.</p>
        </fieldset>
      )}
      {!lineId && (
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <div>
            <label className={fieldLabel} htmlFor="pay-amount">Amount (£)</label>
            <input id="pay-amount" inputMode="decimal" className={fieldInput} value={amount} onChange={(e) => setAmount(e.target.value)} />
          </div>
          <div>
            <label className={fieldLabel} htmlFor="pay-date">Paid on</label>
            <input id="pay-date" type="date" className={fieldInput} value={paidOn} onChange={(e) => setPaidOn(e.target.value)} />
          </div>
          <div className="sm:col-span-2">
            <label className={fieldLabel} htmlFor="pay-into">Paid into</label>
            <select id="pay-into" className={fieldInput} value={into} onChange={(e) => setInto(e.target.value as "1200 Bank" | "1210 Cash")}>
              <option value="1200 Bank">Bank (1200)</option>
              <option value="1210 Cash">Cash (1210)</option>
            </select>
          </div>
        </div>
      )}
      <div className="mt-3">
        <label className={fieldLabel} htmlFor="pay-ref">Payment reference (optional)</label>
        <input id="pay-ref" className={fieldInput} value={ref} onChange={(e) => setRef(e.target.value)} placeholder="e.g. FPS ACME 0006" />
      </div>
      <p className="mt-3 rounded-xl bg-ground px-4 py-2 text-xs text-muted">
        {valid ? `${money(pence!)} ` : ""}is recorded in your books as money in ({lineId || into === "1200 Bank" ? "1200 Bank" : "1210 Cash"}) against
        1100 Debtors. {over > 0 ? `${money(over)} more than the balance is kept as a credit for ${invoice.customer.name}.` : valid && pence! < owed ? `${money(owed - pence!)} stays owed.` : ""}
      </p>
      <div className="mt-4 flex flex-wrap gap-3">
        <button type="button" onClick={save} disabled={busy || !valid} className={primaryButton}>{busy ? "Saving…" : "Record payment"}</button>
        <button type="button" onClick={onClose} className={secondaryButton}>Cancel</button>
      </div>
      {note && <div className="mt-3"><Note note={note} /></div>}
    </Modal>
  );
}

/** Create credit note: the whole invoice or chosen lines and quantities, a date and a reason, behind a tick. */
export function CreditNoteDialog({ account, invoice, onClose, onDone }: {
  account: AccountInfo;
  invoice: RtInvoice;
  onClose: () => void;
  onDone: (cn: RtCreditNote) => void;
}) {
  const [whole, setWhole] = useState(true);
  const [picked, setPicked] = useState<Record<number, string>>({});
  const [day, setDay] = useState(todayIso());
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const chosen = whole
    ? invoice.lines.map((l, i) => ({ i, quantity: String(l.quantity) }))
    : Object.entries(picked).map(([i, quantity]) => ({ i: Number(i), quantity }));
  const okQty = chosen.every((c) => thousandths(c.quantity) !== null && thousandths(c.quantity)! > 0);
  const preview = liveTotals(chosen.filter(() => okQty).map((c) => ({ ...invoice.lines[c.i], quantity: c.quantity })));
  const ready = chosen.length > 0 && okQty && reason.trim() !== "" && confirmed;

  async function save() {
    setBusy(true);
    setNote(null);
    try {
      onDone(await runtime.createCreditNote(account, invoice.number, {
        reason: reason.trim(),
        issue_date: day,
        lines: whole ? null : chosen.map((c) => ({ line: c.i, quantity: c.quantity })),
      }));
    } catch (e) {
      setNote(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal id="credit-note-title" title={`Credit note for ${invoice.number}`} onClose={onClose} wide>
      <p className="mt-1 text-sm text-muted">{invoice.customer.name} · invoice total {money(invoice.total_pence)}</p>
      <fieldset className="mt-4">
        <legend className={fieldLabel}>What to credit</legend>
        <div className="mt-2 flex flex-wrap gap-3">
          {[{ v: true, label: "The whole invoice" }, { v: false, label: "Chosen lines" }].map((o) => (
            <label key={o.label} className="flex min-h-11 cursor-pointer items-center gap-2 rounded-xl border border-border px-3 text-[15px]">
              <input type="radio" name="cn-whole" checked={whole === o.v} onChange={() => { setWhole(o.v); setConfirmed(false); }} className="h-4 w-4 accent-teal" />
              {o.label}
            </label>
          ))}
        </div>
      </fieldset>
      {!whole && (
        <ul className="mt-3 space-y-2">
          {invoice.lines.map((l, i) => {
            const on = picked[i] !== undefined;
            return (
              <li key={i} className="flex flex-wrap items-center gap-3 rounded-xl border border-border px-3 py-2 text-[15px]">
                <label className="flex min-h-11 flex-1 cursor-pointer items-center gap-2">
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={(e) => {
                      setConfirmed(false);
                      setPicked((p) => {
                        const next = { ...p };
                        if (e.target.checked) next[i] = String(l.quantity);
                        else delete next[i];
                        return next;
                      });
                    }}
                    className="h-5 w-5 accent-teal"
                  />
                  {l.description} · {money(l.unit_price_pence)} {l.vat_code === "S" || l.vat_code === "R" ? `+ ${l.vat_rate}% VAT` : ""}
                </label>
                {on && (
                  <span className="flex items-center gap-2">
                    <label className="text-xs font-bold text-muted" htmlFor={`cn-qty-${i}`}>Qty (of {String(l.quantity)})</label>
                    <input
                      id={`cn-qty-${i}`}
                      className="h-11 w-24 rounded-xl border border-border px-3 text-[15px]"
                      value={picked[i]}
                      onChange={(e) => { setConfirmed(false); setPicked((p) => ({ ...p, [i]: e.target.value })); }}
                    />
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div>
          <label className={fieldLabel} htmlFor="cn-date">Credit note date</label>
          <input id="cn-date" type="date" className={fieldInput} value={day} onChange={(e) => { setDay(e.target.value); setConfirmed(false); }} />
        </div>
        <div>
          <label className={fieldLabel} htmlFor="cn-reason">Reason</label>
          <textarea id="cn-reason" rows={1} className={fieldArea} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. 2 hours not worked" />
        </div>
      </div>
      <p className="mt-3 text-sm tabular-nums">
        Credit about <strong>{money(preview.total)}</strong> (net {money(preview.net)}, VAT {money(preview.vat)}); your books work out the
        exact figures.
      </p>
      <label className="mt-4 flex min-h-11 cursor-pointer items-start gap-3 text-[15px] font-semibold">
        <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} className="mt-1 h-5 w-5 shrink-0 accent-teal" />
        <span>
          Record this credit note in my books now. It reverses that part of the sale with the same VAT rates, in the VAT period of
          {" "}{day ? ukDate(day) : "its date"}. I can email it afterwards.
        </span>
      </label>
      <div className="mt-4 flex flex-wrap gap-3">
        <button type="button" onClick={save} disabled={busy || !ready} className={primaryButton}>{busy ? "Saving…" : "Create credit note"}</button>
        <button type="button" onClick={onClose} className={secondaryButton}>Cancel</button>
      </div>
      {note && <div className="mt-3"><Note note={note} /></div>}
    </Modal>
  );
}

interface StandaloneLine {
  key: number;
  description: string;
  quantity: string;
  price: string; // unit price in pounds as typed
  vat_code: RtSalesVatCode;
}

let nextStandaloneKey = 1;

/** A credit note against no invoice: its own customer, lines and descriptions. Posted at once behind a tick. */
export function StandaloneCreditNoteDialog({ account, onClose, onDone }: {
  account: AccountInfo;
  onClose: () => void;
  onDone: (cn: RtCreditNote) => void;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [lines, setLines] = useState<StandaloneLine[]>([{ key: nextStandaloneKey++, description: "", quantity: "1", price: "", vat_code: "S" }]);
  const [day, setDay] = useState(todayIso());
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const setLine = (key: number, patch: Partial<StandaloneLine>) =>
    setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l)));

  const priced = lines.map((l) => ({ quantity: l.quantity, unit_price_pence: parsePounds(l.price) ?? 0, vat_code: l.vat_code }));
  const preview = liveTotals(priced.filter((l) => thousandths(l.quantity) !== null));
  const emailOk = !email.trim() || /.+@.+\..+/.test(email.trim());
  const ready =
    name.trim() !== "" &&
    emailOk &&
    lines.length > 0 &&
    lines.every((l) => l.description.trim() !== "" && thousandths(l.quantity) !== null && parsePounds(l.price) !== null) &&
    preview.total > 0 &&
    reason.trim() !== "" &&
    confirmed;

  async function save() {
    setBusy(true);
    setNote(null);
    try {
      onDone(await runtime.createStandaloneCreditNote(account, {
        customer: { name: name.trim(), email: email.trim() || null },
        issue_date: day,
        lines: lines.map((l) => ({
          description: l.description.trim(),
          quantity: l.quantity.trim(),
          unit_price_pence: parsePounds(l.price)!,
          vat_code: l.vat_code,
        })),
        reason: reason.trim(),
      }));
    } catch (e) {
      setNote(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal id="standalone-credit-note-title" title="New credit note" onClose={onClose} wide>
      <p className="mt-1 text-sm text-muted">Against no invoice: the amount is left as a credit for the customer, to apply or refund.</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div>
          <label className={fieldLabel} htmlFor="scn-name">Customer</label>
          <input id="scn-name" className={fieldInput} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Acme Kitchens Ltd" />
        </div>
        <div>
          <label className={fieldLabel} htmlFor="scn-email">Customer email (optional)</label>
          <input id="scn-email" type="email" className={fieldInput} value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
      </div>
      {!emailOk && <p role="alert" className="mt-1 text-sm font-semibold text-warn-ink">That email address does not look right.</p>}
      <fieldset className="mt-4">
        <legend className={fieldLabel}>Lines</legend>
        <ul className="mt-2 space-y-2">
          {lines.map((l, n) => (
            <li key={l.key} className="grid gap-2 rounded-xl border border-border p-3 sm:grid-cols-[1fr_5rem_6rem_7rem_auto]">
              <div>
                <label className={fieldLabel} htmlFor={`scn-desc-${l.key}`}>Description</label>
                <input id={`scn-desc-${l.key}`} className={fieldInput} value={l.description} onChange={(e) => setLine(l.key, { description: e.target.value })} placeholder={`Line ${n + 1}`} />
              </div>
              <div>
                <label className={fieldLabel} htmlFor={`scn-qty-${l.key}`}>Qty</label>
                <input id={`scn-qty-${l.key}`} className={fieldInput} value={l.quantity} onChange={(e) => setLine(l.key, { quantity: e.target.value })} inputMode="decimal" />
              </div>
              <div>
                <label className={fieldLabel} htmlFor={`scn-price-${l.key}`}>Unit price (£)</label>
                <input id={`scn-price-${l.key}`} className={fieldInput} value={l.price} onChange={(e) => setLine(l.key, { price: e.target.value })} inputMode="decimal" />
              </div>
              <div>
                <label className={fieldLabel} htmlFor={`scn-vat-${l.key}`}>VAT</label>
                <select id={`scn-vat-${l.key}`} className={fieldInput} value={l.vat_code} onChange={(e) => setLine(l.key, { vat_code: e.target.value as RtSalesVatCode })}>
                  {VAT_CODES.map((c) => <option key={c.code} value={c.code}>{c.label}</option>)}
                </select>
              </div>
              <div className="flex items-end">
                {lines.length > 1 && (
                  <button
                    type="button"
                    onClick={() => setLines((ls) => ls.filter((x) => x.key !== l.key))}
                    className="text-[13px] font-bold text-muted hover:underline"
                    aria-label={`Remove line ${n + 1}`}
                  >
                    Remove
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
        <button
          type="button"
          onClick={() => setLines((ls) => [...ls, { key: nextStandaloneKey++, description: "", quantity: "1", price: "", vat_code: "S" }])}
          className="mt-2 text-[13px] font-bold text-teal-dark hover:underline"
        >
          Add another line
        </button>
      </fieldset>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div>
          <label className={fieldLabel} htmlFor="scn-date">Credit note date</label>
          <input id="scn-date" type="date" className={fieldInput} value={day} onChange={(e) => { setDay(e.target.value); setConfirmed(false); }} />
        </div>
        <div>
          <label className={fieldLabel} htmlFor="scn-reason">Reason</label>
          <textarea id="scn-reason" rows={1} className={fieldArea} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. goodwill gesture" />
        </div>
      </div>
      <p className="mt-3 text-sm tabular-nums">
        Credit about <strong>{money(preview.total)}</strong> (net {money(preview.net)}, VAT {money(preview.vat)}); your books work out the
        exact figures.
      </p>
      <label className="mt-4 flex min-h-11 cursor-pointer items-start gap-3 text-[15px] font-semibold">
        <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} className="mt-1 h-5 w-5 shrink-0 accent-teal" />
        <span>
          Record this credit note in my books now. It reverses that amount of the sale with the same VAT rates, in the VAT period of
          {" "}{day ? ukDate(day) : "its date"}. I can email it afterwards.
        </span>
      </label>
      <div className="mt-4 flex flex-wrap gap-3">
        <button type="button" onClick={save} disabled={busy || !ready} className={primaryButton}>{busy ? "Saving…" : "Create credit note"}</button>
        <button type="button" onClick={onClose} className={secondaryButton}>Cancel</button>
      </div>
      {note && <div className="mt-3"><Note note={note} /></div>}
    </Modal>
  );
}

/** The credit note's PDF; email it behind a tick, or void it. */
export function CreditNoteViewDialog({ account, note: cn, onClose, onDone }: {
  account: AccountInfo;
  note: RtCreditNote;
  onClose: () => void;
  onDone: (cn: RtCreditNote, message: string) => void;
}) {
  const [pdf, setPdf] = useState<RtCreditNotePdf | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [email, setEmail] = useState({ to: "", subject: "", body: "" });
  const [confirmed, setConfirmed] = useState(false);
  const [voiding, setVoiding] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    let blobUrl: string | null = null;
    (async () => {
      try {
        const r = await runtime.creditNotePdf(account, cn.number);
        blobUrl = URL.createObjectURL(await (await fetch(r.data_url)).blob());
        setPdf(r);
        setUrl(blobUrl);
        setEmail({ to: r.email.to ?? "", subject: r.email.subject, body: r.email.body });
      } catch (e) {
        setNote(errorText(e));
      }
    })();
    return () => {
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [account, cn.number]);

  async function send() {
    setBusy(true);
    setNote(null);
    try {
      const sent = await runtime.sendCreditNote(account, cn.number, email);
      onDone(sent, `${sent.number} emailed to ${sent.sent_to ?? "the customer"}.`);
    } catch (e) {
      setNote(errorText(e) ?? "Microsoft asked for permission to send mail. Tap Send again when you are back.");
    } finally {
      setBusy(false);
    }
  }

  async function voidIt() {
    setBusy(true);
    setNote(null);
    try {
      const v = await runtime.voidCreditNote(account, cn.number, reason.trim());
      onDone(v, `${v.number} is void; its entry was reversed.`);
    } catch (e) {
      setNote(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const issued = cn.status === "issued";
  return (
    <Modal id="credit-note-view-title" title={`Credit note ${cn.number}`} onClose={onClose} wide>
      <p className="mt-1 text-sm text-muted">
        {cn.customer.name} · {money(cn.total_pence)} · {ukDate(cn.issue_date)} · {cn.invoice ? `against ${cn.invoice}` : "stand-alone"}
      </p>
      <div className="mt-4 h-[45vh] overflow-hidden rounded-xl border border-border bg-ground">
        {url ? <iframe title={`PDF of ${cn.number}`} src={url} className="h-full w-full" /> : <p className="p-4 text-sm text-muted">Making the PDF…</p>}
      </div>
      {url && (
        <a href={url} download={`${cn.number}.pdf`} className="mt-2 inline-block text-sm font-bold text-teal-dark hover:underline">Download PDF</a>
      )}
      {pdf && <p className="mt-1 text-xs text-muted">Saved in your OneDrive as {pdf.path}</p>}
      {issued && pdf && !voiding && (
        <>
          <div className="mt-4 space-y-3">
            <div>
              <label className={fieldLabel} htmlFor="cn-to">To</label>
              <input id="cn-to" type="email" className={fieldInput} value={email.to} onChange={(e) => { setEmail({ ...email, to: e.target.value }); setConfirmed(false); }} />
            </div>
            <div>
              <label className={fieldLabel} htmlFor="cn-subject">Subject</label>
              <input id="cn-subject" className={fieldInput} value={email.subject} onChange={(e) => { setEmail({ ...email, subject: e.target.value }); setConfirmed(false); }} />
            </div>
          </div>
          <label className="mt-4 flex min-h-11 cursor-pointer items-start gap-3 text-[15px] font-semibold">
            <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} className="mt-1 h-5 w-5 shrink-0 accent-teal" />
            <span>Email {cn.number} to {email.to || "the customer"} from my Outlook.</span>
          </label>
          <div className="mt-4 flex flex-wrap gap-3">
            <button type="button" onClick={send} disabled={busy || !confirmed || !email.to.trim()} className={primaryButton}>
              {busy ? "Sending…" : cn.sent_at ? "Send again via Outlook" : "Send via Outlook"}
            </button>
            <button type="button" onClick={() => setVoiding(true)} className={secondaryButton}>Void…</button>
          </div>
        </>
      )}
      {issued && voiding && (
        <div className="mt-4">
          <label className={fieldLabel} htmlFor="cn-void-reason">Why is it void?</label>
          <input id="cn-void-reason" className={fieldInput} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. raised in error" />
          <p className="mt-2 text-xs text-muted">A reversing entry on the credit note&apos;s own date puts the sale and its VAT back.</p>
          <div className="mt-3 flex flex-wrap gap-3">
            <button type="button" onClick={voidIt} disabled={busy || !reason.trim()} className={primaryButton}>{busy ? "Voiding…" : "Void credit note"}</button>
            <button type="button" onClick={() => setVoiding(false)} className={secondaryButton}>Back</button>
          </div>
        </div>
      )}
      {!issued && <p className="mt-4 text-sm text-muted">Void{cn.void_reason ? `: ${cn.void_reason}` : ""}.</p>}
      {note && <div className="mt-3"><Note note={note} /></div>}
    </Modal>
  );
}
