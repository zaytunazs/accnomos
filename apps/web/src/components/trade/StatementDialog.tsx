"use client";

import { useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import Modal, { fieldInput, fieldLabel, secondaryButton } from "@/components/invoices/Modal";
import SendDialog from "@/components/trade/SendDialog";
import { money, todayIso } from "@/lib/invoices";
import { runtime, ukDate, type RtCustomerStatement } from "@/lib/runtime";

/** A customer's statement for a period: activity, running balance and what is still owed. PDF and email from here. */
export default function StatementDialog({ account, contactId, name, onClose, onSent }: { account: AccountInfo; contactId: string; name: string; onClose: () => void; onSent: (message: string) => void }) {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState(todayIso());
  const [st, setSt] = useState<RtCustomerStatement | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [pdf, setPdf] = useState(false);

  useEffect(() => {
    let live = true;
    runtime.customerStatement(account, contactId, start || undefined, end || undefined)
      .then((r) => { if (live) { setSt(r); setErr(null); } })
      .catch((e) => live && setErr((e as Error).message));
    return () => {
      live = false;
    };
  }, [account, contactId, start, end]);

  if (pdf) {
    return (
      <SendDialog
        id="statement-send-title"
        title={`Statement for ${name}`}
        summary={st ? `Up to ${ukDate(st.end)} · ${money(st.shows_outstanding ? st.owed_pence : st.closing_balance_pence)} due` : ""}
        attachName={`Statement ${end}.pdf`}
        canSend
        load={() => runtime.customerStatementPdf(account, contactId, start || undefined, end || undefined)}
        send={async (email) => { await runtime.sendCustomerStatement(account, contactId, email, start || undefined, end || undefined); }}
        confirmText={(to) => `I have checked this statement. Email it to ${to} from my Outlook.`}
        onClose={() => setPdf(false)}
        onDone={() => onSent(`Statement sent to ${name} and recorded.`)}
      />
    );
  }

  return (
    <Modal id="statement-title" title={`Statement for ${name}`} onClose={onClose} wide>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <label className={fieldLabel} htmlFor="st-start">From (blank: the beginning)</label>
          <input id="st-start" type="date" className={fieldInput} value={start} onChange={(e) => setStart(e.target.value)} />
        </div>
        <div>
          <label className={fieldLabel} htmlFor="st-end">To</label>
          <input id="st-end" type="date" className={fieldInput} value={end} onChange={(e) => setEnd(e.target.value)} />
        </div>
      </div>
      {err && <p role="alert" className="mt-3 text-sm font-bold text-warn-ink">{err}</p>}
      {st && (
        <div className="mt-4">
          <p className="text-sm text-muted">
            Opening balance {money(st.opening_balance_pence)} · closing balance <strong className="text-ink">{money(st.closing_balance_pence)}</strong>
            {st.credit_pence > 0 && ` · ${money(st.credit_pence)} on account for them`}
          </p>
          {st.lines.length === 0 ? <p className="mt-3 text-sm">Nothing happened in this period.</p> : (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[34rem] text-left text-sm">
                <caption className="sr-only">Activity</caption>
                <thead><tr className="text-xs text-muted"><th scope="col" className="py-1">Date</th><th scope="col">Details</th><th scope="col" className="text-right">Charged</th><th scope="col" className="text-right">Paid or credited</th><th scope="col" className="text-right">Balance</th></tr></thead>
                <tbody className="divide-y divide-border">
                  {st.lines.map((l, i) => (
                    <tr key={i}>
                      <td className="py-1 pr-2 whitespace-nowrap">{ukDate(l.date)}</td>
                      <td className="pr-2">{l.details}{l.reference ? ` ${l.reference}` : ""}</td>
                      <td className="text-right tabular-nums">{l.amount_pence > 0 ? money(l.amount_pence) : ""}</td>
                      <td className="text-right tabular-nums">{l.paid_pence < 0 || l.amount_pence < 0 ? money(Math.abs(Math.min(l.paid_pence, 0)) + Math.abs(Math.min(l.amount_pence, 0))) : ""}</td>
                      <td className="text-right font-bold tabular-nums">{money(l.balance_pence)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {st.shows_outstanding && st.open_documents.length > 0 && (
            <p className="mt-3 text-sm">Still owed on {st.open_documents.length} invoice{st.open_documents.length === 1 ? "" : "s"}: <strong>{money(st.owed_pence)}</strong>.</p>
          )}
          {!st.shows_outstanding && <p className="mt-3 text-xs text-muted">The list of unpaid invoices is only shown for statements that run to today.</p>}
        </div>
      )}
      <div className="mt-4 flex flex-wrap gap-3">
        <button type="button" disabled={!st} onClick={() => setPdf(true)} className="h-11 rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-60">Preview PDF and email</button>
        <button type="button" onClick={onClose} className={secondaryButton}>Close</button>
      </div>
    </Modal>
  );
}
