"use client";

import { useEffect, useState, type ReactNode } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import Modal, { fieldArea, fieldInput, fieldLabel, primaryButton, secondaryButton } from "@/components/invoices/Modal";
import { money, todayIso } from "@/lib/invoices";
import { runtime, ukDate, type RtBankLine, type RtInvoice, type RtInvoicePdf, type RtReminderDraft } from "@/lib/runtime";

type Done = (inv: RtInvoice) => void;

function errorText(e: unknown): string | null {
  const msg = (e as Error).message;
  if (msg === "redirecting for consent") return null; // back from Microsoft, the user taps Send again
  const detail = /"detail":"([^"]+)"/.exec(msg)?.[1];
  return detail ?? msg;
}

function Confirm({ checked, onChange, children }: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode }) {
  return (
    <label className="mt-4 flex min-h-11 cursor-pointer items-start gap-3 text-[15px] font-semibold">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="mt-1 h-5 w-5 shrink-0 accent-teal" />
      <span>{children}</span>
    </label>
  );
}

function EmailFields({ email, onChange, idPrefix }: {
  email: { to: string; subject: string; body: string };
  onChange: (e: { to: string; subject: string; body: string }) => void;
  idPrefix: string;
}) {
  return (
    <div className="mt-4 space-y-3">
      <div>
        <label className={fieldLabel} htmlFor={`${idPrefix}-to`}>To</label>
        <input id={`${idPrefix}-to`} type="email" className={fieldInput} value={email.to} onChange={(e) => onChange({ ...email, to: e.target.value })} />
      </div>
      <div>
        <label className={fieldLabel} htmlFor={`${idPrefix}-subject`}>Subject</label>
        <input id={`${idPrefix}-subject`} className={fieldInput} value={email.subject} onChange={(e) => onChange({ ...email, subject: e.target.value })} />
      </div>
      <div>
        <label className={fieldLabel} htmlFor={`${idPrefix}-body`}>Message</label>
        <textarea id={`${idPrefix}-body`} rows={8} className={fieldArea} value={email.body} onChange={(e) => onChange({ ...email, body: e.target.value })} />
      </div>
    </div>
  );
}

/** Preview the PDF; for a draft, "Send via Outlook" behind a confirmation tick. */
export function PreviewSendDialog({ account, invoice, onClose, onDone }: { account: AccountInfo; invoice: RtInvoice; onClose: () => void; onDone: Done }) {
  const [pdf, setPdf] = useState<RtInvoicePdf | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [email, setEmail] = useState({ to: "", subject: "", body: "" });
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const draft = invoice.status === "draft";

  useEffect(() => {
    let blobUrl: string | null = null;
    (async () => {
      try {
        const r = await runtime.invoicePdf(account, invoice.number);
        // Browsers will not show a top-level data: PDF, so the runtime's data URL becomes a blob URL for the frame.
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
  }, [account, invoice.number]);

  async function send() {
    setBusy(true);
    setNote(null);
    try {
      onDone(await runtime.sendInvoice(account, invoice.number, email));
    } catch (e) {
      setNote(errorText(e) ?? "Microsoft asked for permission to send mail. Tap Send again when you are back.");
    } finally {
      setBusy(false);
    }
  }

  async function postOnly() {
    setBusy(true);
    try {
      onDone(await runtime.sendInvoice(account, invoice.number, { to: "", subject: "", body: "" }));
    } catch (e) {
      setNote(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const problems = pdf?.problems ?? [];
  return (
    <Modal id="invoice-preview-title" title={`${draft ? "Preview and send" : "Invoice"} ${invoice.number}`} onClose={onClose} wide>
      <p className="mt-1 text-sm text-muted">
        {invoice.customer.name} · {money(invoice.total_pence)} · due {ukDate(invoice.due_date)}
      </p>
      <div className="mt-4 h-[55vh] overflow-hidden rounded-xl border border-border bg-ground">
        {url ? (
          <iframe title={`PDF of ${invoice.number}`} src={url} className="h-full w-full" />
        ) : (
          <p className="p-4 text-sm text-muted">{note ? "Could not make the PDF." : "Making the PDF…"}</p>
        )}
      </div>
      {url && (
        <a href={url} download={`${invoice.number}.pdf`} className="mt-2 inline-block text-sm font-bold text-teal-dark hover:underline">
          Download PDF
        </a>
      )}
      {pdf && <p className="mt-1 text-xs text-muted">Saved in your OneDrive as {pdf.path}</p>}

      {invoice.status === "sent" && !invoice.event_id && (
        <div role="status" className="mt-4 rounded-xl border border-warn-border bg-warn-bg px-4 py-3 text-sm text-warn-ink">
          This invoice was emailed but is not in your books yet.
          <button type="button" onClick={postOnly} disabled={busy} className="ml-2 font-bold underline">Record it in the ledger now</button>
        </div>
      )}

      {draft && pdf && (
        <>
          {problems.length > 0 ? (
            <div role="alert" className="mt-4 rounded-xl border border-warn-border bg-warn-bg px-4 py-3 text-sm text-warn-ink">
              <p className="font-bold">Before you can send it:</p>
              <ul className="mt-1 list-disc pl-5">{problems.map((p) => <li key={p}>{p}</li>)}</ul>
            </div>
          ) : (
            <>
              <EmailFields email={email} onChange={setEmail} idPrefix="send" />
              <Confirm checked={confirmed} onChange={setConfirmed}>
                I have checked this invoice. Email it to {email.to || "the customer"} from my Outlook, and record the sale
                of {money(invoice.total_pence)} in my books.
              </Confirm>
            </>
          )}
          <div className="mt-4 flex flex-wrap gap-3">
            <button type="button" onClick={send} disabled={busy || !confirmed || problems.length > 0 || !email.to.trim()} className={primaryButton}>
              {busy ? "Sending…" : "Send via Outlook"}
            </button>
            <button type="button" onClick={onClose} className={secondaryButton}>Not now</button>
          </div>
        </>
      )}
      {note && <p role="alert" className="mt-3 text-sm font-bold text-warn-ink">{note}</p>}
    </Modal>
  );
}

export function MarkPaidDialog({ account, invoice, onClose, onDone }: { account: AccountInfo; invoice: RtInvoice; onClose: () => void; onDone: Done }) {
  const [paidOn, setPaidOn] = useState(todayIso());
  const [ref, setRef] = useState("");
  const [lines, setLines] = useState<RtBankLine[] | null>(null);
  const [lineId, setLineId] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    runtime.invoiceBankCandidates(account, invoice.number).then(setLines).catch(() => setLines([]));
  }, [account, invoice.number]);

  async function save() {
    setBusy(true);
    setNote(null);
    try {
      onDone(await runtime.markInvoicePaid(account, invoice.number, lineId
        ? { bank_line_id: lineId, payment_ref: ref || undefined }
        : { paid_on: paidOn, payment_ref: ref || undefined }));
    } catch (e) {
      setNote(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal id="invoice-paid-title" title={`Mark ${invoice.number} paid`} onClose={onClose}>
      <p className="mt-1 text-sm text-muted">{invoice.customer.name} · {money(invoice.total_pence)}</p>
      {lines && lines.length > 0 && (
        <fieldset className="mt-4">
          <legend className={fieldLabel}>Money in on your bank statement for exactly {money(invoice.total_pence)}</legend>
          <div className="mt-2 space-y-2">
            {[{ id: "", label: "None of these" }, ...lines.map((l) => ({ id: l.id, label: `${ukDate(l.date)} · ${l.description}` }))].map((o) => (
              <label key={o.id || "none"} className="flex min-h-11 cursor-pointer items-center gap-3 rounded-xl border border-border px-3 text-[15px]">
                <input type="radio" name="bank-line" checked={lineId === o.id} onChange={() => setLineId(o.id)} className="h-4 w-4 accent-teal" />
                {o.label}
              </label>
            ))}
          </div>
          <p className="mt-1 text-xs text-muted">Choosing a line also matches it on the bank page.</p>
        </fieldset>
      )}
      {!lineId && (
        <div className="mt-4">
          <label className={fieldLabel} htmlFor="paid-on">Paid on</label>
          <input id="paid-on" type="date" className={fieldInput} value={paidOn} onChange={(e) => setPaidOn(e.target.value)} />
        </div>
      )}
      <div className="mt-3">
        <label className={fieldLabel} htmlFor="paid-ref">Payment reference (optional)</label>
        <input id="paid-ref" className={fieldInput} value={ref} onChange={(e) => setRef(e.target.value)} placeholder="e.g. FPS ACME 0006" />
      </div>
      <div className="mt-4 flex flex-wrap gap-3">
        <button type="button" onClick={save} disabled={busy} className={primaryButton}>{busy ? "Saving…" : "Mark paid"}</button>
        <button type="button" onClick={onClose} className={secondaryButton}>Cancel</button>
      </div>
      {note && <p role="alert" className="mt-3 text-sm font-bold text-warn-ink">{note}</p>}
    </Modal>
  );
}

/** Muse drafts a chase email from facts the runtime supplies; the user edits, confirms and sends. */
export function ReminderDialog({ account, invoice, onClose, onDone }: { account: AccountInfo; invoice: RtInvoice; onClose: () => void; onDone: Done }) {
  const [draft, setDraft] = useState<RtReminderDraft | null>(null);
  const [email, setEmail] = useState({ to: "", subject: "", body: "" });
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    runtime.reminderDraft(account, invoice.number)
      .then((d) => {
        setDraft(d);
        setEmail({ to: d.to ?? "", subject: d.subject, body: d.body });
      })
      .catch((e) => setNote(errorText(e)));
  }, [account, invoice.number]);

  async function send() {
    setBusy(true);
    setNote(null);
    try {
      onDone(await runtime.reminderSend(account, invoice.number, email));
    } catch (e) {
      setNote(errorText(e) ?? "Microsoft asked for permission to send mail. Tap Send again when you are back.");
    } finally {
      setBusy(false);
    }
  }

  const days = invoice.days_overdue ?? 0;
  return (
    <Modal id="invoice-reminder-title" title={`Chase ${invoice.number}`} onClose={onClose}>
      <p className="mt-1 text-sm text-muted">
        {invoice.customer.name} · {money(invoice.total_pence)} · {days > 0 ? `${days} day${days === 1 ? "" : "s"} overdue` : `due ${ukDate(invoice.due_date)}`}
        {invoice.reminders.length > 0 && ` · ${invoice.reminders.length} reminder${invoice.reminders.length === 1 ? "" : "s"} sent`}
      </p>
      {!draft && !note && <p className="mt-4 text-sm text-muted">Your AI is drafting a polite reminder…</p>}
      {draft && (
        <>
          <p className="mt-3 rounded-xl bg-ground px-4 py-2 text-xs text-muted">
            {draft.fallback_reason
              ? `Written by Accnomos from the invoice (${draft.fallback_reason})`
              : `Drafted by ${draft.model}; every figure checked against the invoice.`}{" "}
            Nothing is sent until you confirm. The invoice PDF is attached.
          </p>
          <EmailFields email={email} onChange={setEmail} idPrefix="remind" />
          <Confirm checked={confirmed} onChange={setConfirmed}>
            I have read this reminder. Email it to {email.to || "the customer"} from my Outlook.
          </Confirm>
          <div className="mt-4 flex flex-wrap gap-3">
            <button type="button" onClick={send} disabled={busy || !confirmed || !email.to.trim()} className={primaryButton}>
              {busy ? "Sending…" : "Send via Outlook"}
            </button>
            <button type="button" onClick={onClose} className={secondaryButton}>Not now</button>
          </div>
        </>
      )}
      {note && <p role="alert" className="mt-3 text-sm font-bold text-warn-ink">{note}</p>}
    </Modal>
  );
}

export function VoidDialog({ account, invoice, onClose, onDone }: { account: AccountInfo; invoice: RtInvoice; onClose: () => void; onDone: Done }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    try {
      onDone(await runtime.voidInvoice(account, invoice.number, reason));
    } catch (e) {
      setNote(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal id="invoice-void-title" title={`Void ${invoice.number}`} onClose={onClose}>
      <p className="mt-2 text-[15px] leading-7">
        {invoice.status === "sent"
          ? "The invoice stays in your folder, marked void, and a reversing entry cancels the sale in your books. Tell the customer separately."
          : "The draft stays in your folder, marked void, so the number is not used again."}
      </p>
      <div className="mt-3">
        <label className={fieldLabel} htmlFor="void-reason">Why?</label>
        <input id="void-reason" className={fieldInput} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. raised in error" />
      </div>
      <div className="mt-4 flex flex-wrap gap-3">
        <button type="button" onClick={save} disabled={busy || !reason.trim()} className={primaryButton}>{busy ? "Voiding…" : "Void invoice"}</button>
        <button type="button" onClick={onClose} className={secondaryButton}>Cancel</button>
      </div>
      {note && <p role="alert" className="mt-3 text-sm font-bold text-warn-ink">{note}</p>}
    </Modal>
  );
}
