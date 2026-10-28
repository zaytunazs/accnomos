"use client";

import { useEffect, useState } from "react";
import Modal, { primaryButton, secondaryButton } from "@/components/invoices/Modal";
import { Confirm, EmailFields, Note, errorText } from "@/components/invoices/InvoiceDialogs";
import type { RtTradePdf } from "@/lib/runtime";

/**
 * Preview a PDF (a quote, purchase order or statement) and, when `canSend`, email it from the user's Outlook behind a
 * ticked confirmation. Nothing is sent until the tick; the runtime refuses a send without `confirm: true`.
 */
export default function SendDialog({
  id, title, summary, attachName, confirmText, canSend, load, send, onClose, onDone, afterPdf,
}: {
  id: string;
  title: string;
  summary: string;
  attachName: string;
  confirmText: (to: string) => string;
  canSend: boolean;
  load: () => Promise<RtTradePdf>;
  send: (email: { to: string; subject: string; body: string }) => Promise<void>;
  onClose: () => void;
  onDone: () => void;
  afterPdf?: React.ReactNode;
}) {
  const [pdf, setPdf] = useState<RtTradePdf | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [email, setEmail] = useState({ to: "", subject: "", body: "" });
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    let blobUrl: string | null = null;
    (async () => {
      try {
        const r = await load();
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
    // load is a fresh closure on each render of the parent; the dialog loads once, when it opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function doSend() {
    setBusy(true);
    setNote(null);
    try {
      await send(email);
      onDone();
    } catch (e) {
      setNote(errorText(e) ?? "Microsoft asked for permission to send mail. Tap Send again when you are back.");
    } finally {
      setBusy(false);
    }
  }

  const problems = pdf?.problems ?? [];
  return (
    <Modal id={id} title={title} onClose={onClose} wide>
      <p className="mt-1 text-sm text-muted">{summary}</p>
      <div className="mt-4 h-[50vh] overflow-hidden rounded-xl border border-border bg-ground">
        {url ? <iframe title={`PDF: ${title}`} src={url} className="h-full w-full" /> : <p className="p-4 text-sm text-muted">{note ? "Could not make the PDF." : "Making the PDF…"}</p>}
      </div>
      {url && <a href={url} download={attachName} className="mt-2 inline-block text-sm font-bold text-teal-dark hover:underline">Download PDF</a>}
      {afterPdf}
      {canSend && pdf && (
        problems.length > 0 ? (
          <div role="alert" className="mt-4 rounded-xl border border-warn-border bg-warn-bg px-4 py-3 text-sm text-warn-ink">
            <p className="font-bold">Before you can send it:</p>
            <ul className="mt-1 list-disc pl-5">{problems.map((p) => <li key={p}>{p}</li>)}</ul>
          </div>
        ) : (
          <>
            <EmailFields email={email} onChange={(e) => { setEmail(e); setConfirmed(false); }} idPrefix={`${id}-mail`} />
            <p className="mt-2 text-sm text-muted">It goes as an attachment named <strong className="text-ink">{attachName}</strong>.</p>
            <Confirm checked={confirmed} onChange={setConfirmed}>{confirmText(email.to || "the recipient")}</Confirm>
            <div className="mt-4 flex flex-wrap gap-3">
              <button type="button" onClick={doSend} disabled={busy || !confirmed || !email.to.trim()} className={primaryButton}>
                {busy ? "Sending…" : "Send via Outlook"}
              </button>
              <button type="button" onClick={onClose} className={secondaryButton}>Not now</button>
            </div>
          </>
        )
      )}
      {!canSend && <div className="mt-4"><button type="button" onClick={onClose} className={secondaryButton}>Close</button></div>}
      {note && <div className="mt-3"><Note note={note} /></div>}
    </Modal>
  );
}
