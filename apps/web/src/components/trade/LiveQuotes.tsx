"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import type { AccountInfo } from "@azure/msal-browser";
import { errorText } from "@/components/invoices/InvoiceDialogs";
import { primaryButton } from "@/components/invoices/Modal";
import SignInCta from "@/components/SignInCta";
import { EmptyState, LoadingSkeleton, RuntimeErrorNote } from "@/components/States";
import QuoteFormDialog from "@/components/trade/QuoteFormDialog";
import SendDialog from "@/components/trade/SendDialog";
import { money, useMsAccount } from "@/lib/invoices";
import { runtime, ukDate, type RtQuote, type RtQuoteStatus } from "@/lib/runtime";

type Filter = "all" | RtQuoteStatus;
const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "draft", label: "Drafts" },
  { value: "sent", label: "Sent" },
  { value: "accepted", label: "Accepted" },
  { value: "declined", label: "Declined" },
  { value: "expired", label: "Expired" },
];
const LABEL: Record<RtQuoteStatus, string> = { draft: "Draft", sent: "Sent", accepted: "Accepted", declined: "Declined", expired: "Expired" };
const TONE: Record<RtQuoteStatus, string> = {
  draft: "bg-ground text-muted",
  sent: "bg-teal-tint text-teal-dark",
  accepted: "bg-teal text-white",
  declined: "bg-ground text-muted line-through",
  expired: "bg-warn-bg text-warn-ink",
};
const action = "text-[13px] font-bold text-teal-dark hover:underline";

type Dialog = { kind: "form"; quote: RtQuote | null } | { kind: "pdf"; quote: RtQuote } | null;

export default function LiveQuotes() {
  const { account, ready } = useMsAccount();
  const [quotes, setQuotes] = useState<RtQuote[] | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [dialog, setDialog] = useState<Dialog>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!account) return;
    try {
      setQuotes(await runtime.quotes(account));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [account]);
  useEffect(() => {
    queueMicrotask(load);
  }, [load]);

  const replace = (q: RtQuote) => setQuotes((l) => l?.map((x) => (x.number === q.number ? q : x)) ?? null);

  async function act(q: RtQuote, run: (a: AccountInfo) => Promise<RtQuote>, message: string) {
    if (!account) return;
    setBusy(q.number);
    setNote(null);
    try {
      replace(await run(account));
      setNote(message);
    } catch (e) {
      setError(errorText(e) ?? "Something went wrong.");
    } finally {
      setBusy(null);
    }
  }

  async function convert(q: RtQuote) {
    if (!account) return;
    setBusy(q.number);
    setNote(null);
    try {
      const r = await runtime.convertQuote(account, q.number);
      replace(r.quote);
      setNote(`${r.invoice.number} is a draft invoice with the same lines and totals as ${q.number}. Open it on the Invoices page to check it and send it.`);
    } catch (e) {
      setError(errorText(e) ?? "Something went wrong.");
    } finally {
      setBusy(null);
    }
  }

  if (ready && !account) {
    return (
      <p className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl bg-ground p-4 text-sm text-muted">
        <SignInCta />
        <span>to write quotes; each one is saved in your OneDrive under 03 Sales/quotes.</span>
      </p>
    );
  }

  const needle = query.trim().toLowerCase();
  const shown = (quotes ?? [])
    .filter((q) => filter === "all" || q.status === filter)
    .filter((q) => !needle || q.number.toLowerCase().includes(needle) || q.customer.name.toLowerCase().includes(needle));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="Show quotes">
          {FILTERS.map((f) => (
            <button key={f.value} type="button" role="tab" aria-selected={filter === f.value} onClick={() => setFilter(f.value)}
              className={`h-9 rounded-full px-3 text-[13px] font-bold ${filter === f.value ? "bg-teal text-white" : "border border-border bg-white text-ink"}`}>
              {f.label}
            </button>
          ))}
        </div>
        <button type="button" className={primaryButton} onClick={() => setDialog({ kind: "form", quote: null })}>New quote</button>
      </div>
      <div>
        <label className="text-xs font-bold text-muted" htmlFor="quote-search">Search quotes</label>
        <input id="quote-search" className="mt-1 h-11 w-full rounded-xl border border-border bg-white px-3 text-[15px] text-ink" placeholder="Number or customer…" autoComplete="off" value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>
      {note && <p role="status" className="rounded-xl bg-teal-tint px-4 py-3 text-sm font-bold text-teal-dark">{note}</p>}
      {error && <RuntimeErrorNote message={error} title="Could not complete that" />}
      {!quotes && !error && <LoadingSkeleton lines={3} label="Loading your quotes…" />}
      {quotes && quotes.length === 0 && (
        <EmptyState title="No quotes yet" body="Write a quote, send it from your Outlook, and turn it into an invoice when the customer says yes." />
      )}
      {quotes && quotes.length > 0 && shown.length === 0 && <p className="rounded-2xl border border-border bg-white p-4 text-sm text-muted">Nothing here.</p>}
      {shown.length > 0 && account && (
        <ul className="divide-y divide-border rounded-2xl border border-border bg-white">
          {shown.map((q) => (
            <li key={q.number} className="px-4 py-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-[15px] font-bold">{q.number} · {q.customer.name}</p>
                  <p className="text-sm text-muted">
                    {ukDate(q.issue_date)} · valid until {ukDate(q.expiry_date)}
                    {q.invoice_number && <> · invoiced as <Link href={`/invoices?q=${encodeURIComponent(q.invoice_number)}`} className="font-bold text-teal-dark">{q.invoice_number}</Link></>}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`rounded-full px-2 py-0.5 text-[12px] font-extrabold ${TONE[q.status]}`}>{LABEL[q.status]}</span>
                  <span className="text-[15px] font-extrabold tabular-nums">{money(q.total_pence)}</span>
                </div>
              </div>
              <div className="mt-2 flex flex-wrap gap-4">
                {q.status === "draft" && (
                  <>
                    <button type="button" className={action} onClick={() => setDialog({ kind: "form", quote: q })}>Edit</button>
                    <button type="button" className={action} onClick={() => setDialog({ kind: "pdf", quote: q })}>Preview and send</button>
                    <button type="button" className={action} disabled={busy === q.number} onClick={() => act(q, (a) => runtime.markQuoteSent(a, q.number), `${q.number} is marked as sent.`)}>Mark as sent</button>
                  </>
                )}
                {q.status !== "draft" && <button type="button" className={action} onClick={() => setDialog({ kind: "pdf", quote: q })}>View PDF</button>}
                {(q.status === "sent" || q.status === "expired") && !q.invoice_number && (
                  <>
                    <button type="button" className={action} disabled={busy === q.number} onClick={() => act(q, (a) => runtime.acceptQuote(a, q.number), `${q.number} is accepted.`)}>Accepted</button>
                    <button type="button" className={action} disabled={busy === q.number} onClick={() => act(q, (a) => runtime.declineQuote(a, q.number), `${q.number} is declined.`)}>Declined</button>
                  </>
                )}
                {(q.status === "sent" || q.status === "accepted") && !q.invoice_number && (
                  <button type="button" className={action} disabled={busy === q.number} onClick={() => convert(q)}>Convert to invoice</button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {dialog?.kind === "form" && account && (
        <QuoteFormDialog account={account} quote={dialog.quote} onClose={() => setDialog(null)}
          onSaved={(q) => { setDialog(null); setNote(`Draft ${q.number} saved in your OneDrive (03 Sales/quotes).`); void load(); }} />
      )}
      {dialog?.kind === "pdf" && account && (
        <SendDialog
          id="quote-send-title"
          title={`${dialog.quote.status === "draft" ? "Preview and send" : "Quote"} ${dialog.quote.number}`}
          summary={`${dialog.quote.customer.name} · ${money(dialog.quote.total_pence)} · valid until ${ukDate(dialog.quote.expiry_date)}`}
          attachName={`${dialog.quote.number}.pdf`}
          canSend={dialog.quote.status === "draft"}
          load={() => runtime.quotePdf(account, dialog.quote.number)}
          send={async (email) => { replace(await runtime.sendQuote(account, dialog.quote.number, email)); }}
          confirmText={(to) => `I have checked this quote. Email it to ${to} from my Outlook.`}
          onClose={() => setDialog(null)}
          onDone={() => { setDialog(null); setNote(`${dialog.quote.number} sent and recorded.`); void load(); }}
        />
      )}
    </div>
  );
}
