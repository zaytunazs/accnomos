"use client";

import { useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import Modal, { fieldArea, fieldInput, fieldLabel, primaryButton, secondaryButton } from "@/components/invoices/Modal";
import { RuntimeErrorNote } from "@/components/States";
import LinesEditor, { blankLine, linesFromRt, linesToIn, type LineForm } from "@/components/trade/LinesEditor";
import PartyFields, { EMPTY_PARTY, cleanParty } from "@/components/trade/PartyFields";
import { useItems } from "@/components/trade/useItems";
import { todayIso } from "@/lib/invoices";
import { runtime, ukDate, type RtFrequency, type RtInvoiceCustomer, type RtRepeating } from "@/lib/runtime";

const FREQ: { value: RtFrequency; label: string; unit: string }[] = [
  { value: "weekly", label: "Weekly", unit: "week" },
  { value: "monthly", label: "Monthly", unit: "month" },
  { value: "quarterly", label: "Quarterly", unit: "quarter" },
  { value: "yearly", label: "Yearly", unit: "year" },
];

/** Set up a repeating invoice or bill. The runtime shows the next dates before anything is saved. */
export default function RepeatingFormDialog({ account, template, onClose, onSaved }: { account: AccountInfo; template: RtRepeating | null; onClose: () => void; onSaved: (t: RtRepeating) => void }) {
  const items = useItems(account);
  const [kind, setKind] = useState<"invoice" | "bill">(template?.kind ?? "invoice");
  const [name, setName] = useState(template?.name ?? "");
  const [frequency, setFrequency] = useState<RtFrequency>(template?.frequency ?? "monthly");
  const [every, setEvery] = useState(String(template?.every ?? 1));
  const [start, setStart] = useState(template?.start_date ?? todayIso());
  const [end, setEnd] = useState(template?.end_date ?? "");
  const [auto, setAuto] = useState(template?.approve_automatically ?? false);
  const [paused, setPaused] = useState(template?.paused ?? false);
  const [party, setParty] = useState<RtInvoiceCustomer>(template?.party ?? EMPTY_PARTY);
  const [known, setKnown] = useState<RtInvoiceCustomer[]>([]);
  const [reference, setReference] = useState(template?.reference ?? "");
  const [notes, setNotes] = useState(template?.notes ?? "");
  const [dueDays, setDueDays] = useState(template?.due_days != null ? String(template.due_days) : "");
  const [expense, setExpense] = useState(template?.account ?? "");
  const [lines, setLines] = useState<LineForm[]>(() => (template ? linesFromRt(template.lines) : [blankLine()]));
  const [dates, setDates] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (kind === "invoice" ? runtime.invoiceCustomers(account) : runtime.poSuppliers(account)).then(setKnown).catch(() => setKnown([]));
  }, [account, kind]);

  const n = Number(every);
  const everyOk = Number.isInteger(n) && n >= 1 && n <= 52;
  useEffect(() => {
    if (!start || !everyOk) return;
    let live = true;
    runtime.repeatingDates(account, { frequency, start, every: n, end: end || null }).then((d) => live && setDates(d)).catch(() => live && setDates(null));
    return () => {
      live = false;
    };
  }, [account, frequency, start, n, everyOk, end]);

  async function save() {
    if (!party.name.trim()) return setError(kind === "invoice" ? "Add the customer's name." : "Add the supplier's name.");
    if (!everyOk) return setError("Repeat every must be a whole number from 1 to 52.");
    if (!start) return setError("Add a first date.");
    const out = linesToIn(lines);
    if (typeof out === "string") return setError(out);
    const dd = dueDays.trim() ? Number(dueDays) : null;
    if (dd !== null && (!Number.isInteger(dd) || dd < 0 || dd > 365)) return setError("Days to pay must be a whole number from 0 to 365.");
    setBusy(true);
    setError(null);
    const body = {
      kind, name: name.trim() || null, frequency, every: n, start_date: start, end_date: end || null, approve_automatically: auto,
      party: cleanParty(party), lines: out, reference: reference.trim() || null, notes: notes.trim() || null, due_days: dd,
      account: kind === "bill" ? expense.trim() || null : null, paused,
    };
    try {
      onSaved(template ? await runtime.updateRepeating(account, template.id, body) : await runtime.createRepeating(account, body));
    } catch (e) {
      const msg = (e as Error).message;
      setError(/"(?:detail|msg)":"([^"]+)"/.exec(msg)?.[1] ?? msg);
    } finally {
      setBusy(false);
    }
  }

  const unit = FREQ.find((f) => f.value === frequency)!.unit;
  return (
    <Modal id="repeat-form-title" title={template ? `Change ${template.id}` : "New repeating invoice or bill"} onClose={onClose} wide>
      <div className="mt-4 space-y-4">
        <fieldset disabled={template !== null}>
          <legend className="text-[17px] font-extrabold">What repeats</legend>
          <div className="mt-2 flex flex-wrap gap-4">
            {(["invoice", "bill"] as const).map((k) => (
              <label key={k} className="flex min-h-11 items-center gap-2 text-[15px] font-semibold">
                <input type="radio" name="repeat-kind" className="h-5 w-5 accent-teal" checked={kind === k} onChange={() => { setKind(k); setParty(EMPTY_PARTY); }} />
                {k === "invoice" ? "An invoice I send" : "A bill I receive"}
              </label>
            ))}
          </div>
        </fieldset>
        <section aria-labelledby="repeat-party">
          <h3 id="repeat-party" className="mb-2 text-[17px] font-extrabold">{kind === "invoice" ? "Customer" : "Supplier"}</h3>
          <PartyFields party={party} onChange={setParty} known={known} noun={kind === "invoice" ? "customer" : "supplier"} idPrefix="repeat-party"
            emailLabel={kind === "invoice" ? "Email (invoices are sent here)" : "Email (optional)"} />
        </section>
        <section aria-labelledby="repeat-when">
          <h3 id="repeat-when" className="mb-2 text-[17px] font-extrabold">Schedule</h3>
          <div className="grid gap-3 sm:grid-cols-4">
            <div className="sm:col-span-2">
              <label className={fieldLabel} htmlFor="repeat-name">Name (optional)</label>
              <input id="repeat-name" className={fieldInput} value={name} onChange={(e) => setName(e.target.value)} placeholder="Monthly retainer" />
            </div>
            <div>
              <label className={fieldLabel} htmlFor="repeat-freq">Repeats</label>
              <select id="repeat-freq" className={fieldInput} value={frequency} onChange={(e) => setFrequency(e.target.value as RtFrequency)}>
                {FREQ.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
              </select>
            </div>
            <div>
              <label className={fieldLabel} htmlFor="repeat-every">Every how many {unit}s</label>
              <input id="repeat-every" inputMode="numeric" className={fieldInput} value={every} onChange={(e) => setEvery(e.target.value)} />
            </div>
            <div>
              <label className={fieldLabel} htmlFor="repeat-start">First date</label>
              <input id="repeat-start" type="date" className={fieldInput} value={start} onChange={(e) => setStart(e.target.value)} />
            </div>
            <div>
              <label className={fieldLabel} htmlFor="repeat-end">Last date (optional)</label>
              <input id="repeat-end" type="date" className={fieldInput} value={end} onChange={(e) => setEnd(e.target.value)} />
            </div>
            <div>
              <label className={fieldLabel} htmlFor="repeat-due">{kind === "invoice" ? "Days to pay" : "Days to pay (optional)"}</label>
              <input id="repeat-due" inputMode="numeric" className={fieldInput} value={dueDays} onChange={(e) => setDueDays(e.target.value)} placeholder={kind === "invoice" ? "your usual terms" : "30"} />
            </div>
            {kind === "bill" && (
              <div>
                <label className={fieldLabel} htmlFor="repeat-account">Expense account (optional)</label>
                <input id="repeat-account" className={fieldInput} value={expense} onChange={(e) => setExpense(e.target.value)} placeholder="7000 Rent" />
              </div>
            )}
          </div>
          <p className="mt-2 text-sm text-muted" aria-live="polite">
            {dates && dates.length > 0 ? <>Next dates: <strong className="text-ink">{dates.map(ukDate).join(", ")}</strong>. Months are counted from the first date, so the 31st becomes the last day of a shorter month.</> : dates ? "No dates fall before the last date." : ""}
          </p>
        </section>
        <section aria-labelledby="repeat-lines"><h3 id="repeat-lines" className="mb-2 text-[17px] font-extrabold">Lines</h3>
          <LinesEditor account={account} lines={lines} onChange={setLines} items={items} side={kind === "invoice" ? "sale" : "purchase"} idPrefix="repeat-ln" />
        </section>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className={fieldLabel} htmlFor="repeat-ref">Reference (optional)</label>
            <input id="repeat-ref" className={fieldInput} value={reference} onChange={(e) => setReference(e.target.value)} />
          </div>
          <div>
            <label className={fieldLabel} htmlFor="repeat-notes">Note on each one (optional)</label>
            <textarea id="repeat-notes" rows={2} className={fieldArea} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>
        </div>
        <fieldset className="rounded-xl border border-border p-3">
          <legend className="px-1 text-[15px] font-extrabold">Approval</legend>
          <label className="flex min-h-11 cursor-pointer items-start gap-3 text-[15px] font-semibold">
            <input type="checkbox" className="mt-1 h-5 w-5 shrink-0 accent-teal" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
            <span>
              {kind === "invoice"
                ? "Approve automatically: when each invoice is due, email it to the customer from my Outlook and post it to my books, without asking me again."
                : "Approve automatically: when each bill is due, approve it and post it to my books, without asking me again."}
            </span>
          </label>
          <p className="mt-1 text-sm text-muted">
            {auto
              ? kind === "invoice"
                ? "This is your standing approval: an email to your customer cannot be taken back. If an invoice cannot be sent (no customer email, or Outlook is not connected) it stays a draft and tells you why."
                : "This is your standing approval. A bill with a failed check still waits in Review for you."
              : kind === "invoice"
                ? "Left unticked, each one is made as a draft invoice for you to check and send."
                : "Left unticked, each one waits in Review for you to approve."}
          </p>
        </fieldset>
        {template && (
          <label className="flex min-h-11 items-center gap-2 text-[15px] font-semibold">
            <input type="checkbox" className="h-5 w-5 accent-teal" checked={paused} onChange={(e) => setPaused(e.target.checked)} />
            Pause this schedule (nothing is made until you untick this)
          </label>
        )}
        {error && <RuntimeErrorNote message={error} />}
        <div className="flex flex-wrap gap-3">
          <button type="button" onClick={save} disabled={busy} className={primaryButton}>{busy ? "Saving…" : "Save"}</button>
          <button type="button" onClick={onClose} className={secondaryButton}>Cancel</button>
        </div>
      </div>
    </Modal>
  );
}
