"use client";

import { sentNote } from "@/lib/demo";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { PreviewSendDialog, ReminderDialog, StatusTimeline, VoidDialog } from "@/components/invoices/InvoiceDialogs";
import {
  CreditNoteDialog,
  CreditNoteViewDialog,
  PAYMENT_LABEL,
  PaymentsPanel,
  RecordPaymentDialog,
  StandaloneCreditNoteDialog,
  balanceOf,
} from "@/components/invoices/PaymentDialogs";
import { ApplyCreditDialog, RefundDialog } from "@/components/invoices/CreditDialogs";
import SignInCta from "@/components/SignInCta";
import { EmptyState, LoadingSkeleton, RuntimeErrorNote, SamplePill } from "@/components/States";
import PrintButton from "@/components/PrintButton";
import { csvFilename, downloadCsv, type CsvValue } from "@/lib/csv";
import { money, SAMPLE_INVOICES, STATUS_LABEL, useMsAccount } from "@/lib/invoices";
import { runtime, ukDate, type RtCreditNote, type RtCreditRow, type RtInvoice, type RtOpenItem } from "@/lib/runtime";

type Filter = "all" | "draft" | "sent" | "overdue" | "paid" | "void";
type Dialog =
  | { kind: "preview" | "paid" | "remind" | "void" | "credit"; invoice: RtInvoice }
  | { kind: "creditView"; note: RtCreditNote }
  | { kind: "applyCredit"; name: string; credits: RtCreditRow[]; documents: RtOpenItem[] }
  | { kind: "refund"; name: string; credits: RtCreditRow[] }
  | { kind: "standaloneCredit" }
  | null;

const sameName = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase();

/** A sent invoice as something a credit can go towards. */
function openItem(i: RtInvoice): RtOpenItem | null {
  const left = balanceOf(i);
  if (i.status !== "sent" || !i.event_id || left <= 0) return null;
  return { event_id: i.event_id, side: "sale", date: i.issue_date, due_date: i.due_date, reference: i.number, gross_pence: i.total_pence, outstanding_pence: left };
}

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "draft", label: "Drafts" },
  { value: "sent", label: "Awaiting payment" },
  { value: "overdue", label: "Overdue" },
  { value: "paid", label: "Paid" },
  { value: "void", label: "Void" },
];

const isOverdue = (i: Pick<RtInvoice, "status" | "days_overdue">) => i.status === "sent" && (i.days_overdue ?? 0) > 0;

function StatusChip({ invoice }: { invoice: Pick<RtInvoice, "status" | "days_overdue"> }) {
  if (isOverdue(invoice)) {
    const d = invoice.days_overdue!;
    return <span className="rounded-full bg-warn-bg px-2 py-0.5 text-[12px] font-extrabold text-warn-ink">{d} day{d === 1 ? "" : "s"} overdue</span>;
  }
  const tone = { draft: "bg-ground text-muted", sent: "bg-teal-tint text-teal-dark", paid: "bg-teal text-white", void: "bg-ground text-muted line-through" }[invoice.status];
  return <span className={`rounded-full px-2 py-0.5 text-[12px] font-extrabold ${tone}`}>{STATUS_LABEL[invoice.status]}</span>;
}

const action = "text-[13px] font-bold text-teal-dark hover:underline";

const CSV_HEAD = ["number", "customer", "issue_date", "due_date", "status", "net_pence", "vat_pence", "total_pence"];

/** The list exactly as the runtime gave it: pence stay pence (the signed-out sample has no net/VAT split). */
function invoiceRows(
  list: { number: string; customer: { name: string }; issue_date: string; due_date: string; status: string; net_pence?: number | null; vat_pence?: number | null; total_pence: number }[],
): CsvValue[][] {
  return [CSV_HEAD, ...list.map((i) => [i.number, i.customer.name, i.issue_date, i.due_date, i.status, i.net_pence ?? null, i.vat_pence ?? null, i.total_pence])];
}

const exportClass = "h-11 rounded-xl border border-border bg-white px-4 text-[15px] font-bold print:hidden";

export default function LiveInvoices() {
  const { account, ready } = useMsAccount();
  const [invoices, setInvoices] = useState<RtInvoice[] | null>(null);
  const [credits, setCredits] = useState<RtCreditNote[]>([]);
  const [onAccount, setOnAccount] = useState<RtCreditRow[]>([]); // customers' credits (GET /credits?side=sale)
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  // /invoices?q=INV-0007 (from the audit trail) starts with that search.
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("q");
    if (q) queueMicrotask(() => setQuery(q));
  }, []);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!account) return;
    try {
      // Together, so a row never shows Apply credit / Refund from an older list than its own figures.
      const [list, notes, onAcc] = await Promise.all([
        runtime.invoices(account),
        runtime.creditNotes(account).catch(() => []),
        runtime.credits(account, "sale").catch(() => []),
      ]);
      setInvoices(list);
      setCredits(notes);
      setOnAccount(onAcc);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [account]);

  useEffect(() => {
    queueMicrotask(load);
  }, [load]);

  function replace(updated: RtInvoice) {
    setInvoices((list) => list?.map((i) => (i.number === updated.number ? updated : i)) ?? null);
  }

  function done(updated: RtInvoice) {
    const was = dialog?.kind;
    setDialog(null);
    replace(updated);
    const left = balanceOf(updated);
    setNote({
      preview: sentNote(`${updated.number} sent to ${updated.sent_to ?? "the customer"} and recorded in your books.`),
      paid: left > 0
        ? `Payment recorded on ${updated.number}: ${money(left)} still owed.`
        : `${updated.number} is paid${updated.money?.overpaid_pence ? `; ${money(updated.money.overpaid_pence)} kept as a credit for ${updated.customer.name}` : ""}.`,
      remind: sentNote(`Reminder for ${updated.number} sent.`),
      void: `${updated.number} is void.`,
      credit: "",
      creditView: "",
      applyCredit: "",
      refund: "",
      standaloneCredit: "",
    }[was ?? "paid"]);
  }

  async function credited(cn: RtCreditNote) {
    setDialog(null);
    setNote(
      cn.invoice
        ? `Credit note ${cn.number} for ${money(cn.total_pence)} recorded against ${cn.invoice}.`
        : `Credit note ${cn.number} for ${money(cn.total_pence)} recorded for ${cn.customer.name}; ${money(cn.total_pence)} is on account for them.`,
    );
    await load();
  }

  if (ready && !account) {
    return (
      <div className="space-y-3">
        <p className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl bg-ground p-4 text-sm text-muted">
          <SignInCta />
          <SamplePill />
          <span>to write invoices; they are saved in your OneDrive under 03 Sales/invoices. The list below is a fictional sample.</span>
        </p>
        <div className="flex flex-wrap gap-2 print:hidden">
          <PrintButton />
          <button
            type="button"
            onClick={() => downloadCsv(csvFilename("invoices"), invoiceRows(SAMPLE_INVOICES), { sample: true })}
            className={exportClass}
          >
            Export CSV
          </button>
        </div>
        <ul className="divide-y divide-border rounded-2xl border border-border bg-white">
          {SAMPLE_INVOICES.map((i) => (
            <li key={i.number} className="flex items-center justify-between gap-3 px-4 py-3">
              <div>
                <p className="text-[15px] font-bold">{i.number} · {i.customer.name}</p>
                <p className="text-sm text-muted">{ukDate(i.issue_date)} · due {ukDate(i.due_date)}</p>
              </div>
              <div className="flex items-center gap-3">
                <StatusChip invoice={i} />
                <span className="text-[15px] font-extrabold tabular-nums">{money(i.total_pence)}</span>
              </div>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  const needle = query.trim().toLowerCase();
  const shown = (invoices ?? [])
    .filter((i) => filter === "all" || (filter === "overdue" ? isOverdue(i) : i.status === filter))
    .filter((i) => !needle || i.number.toLowerCase().includes(needle) || i.customer.name.toLowerCase().includes(needle))
    .sort((a, b) => Number(isOverdue(b)) - Number(isOverdue(a)) || a.due_date.localeCompare(b.due_date));
  const owed = (invoices ?? []).filter((i) => i.status === "sent").reduce((s, i) => s + balanceOf(i), 0);
  const overdue = (invoices ?? []).filter(isOverdue).reduce((s, i) => s + balanceOf(i), 0);
  const unpaidCount = (invoices ?? []).filter((i) => i.status === "sent").length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 print:hidden">
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="Show invoices">
          {FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              role="tab"
              aria-selected={filter === f.value}
              onClick={() => setFilter(f.value)}
              className={`h-9 rounded-full px-3 text-[13px] font-bold ${filter === f.value ? "bg-teal text-white" : "border border-border bg-white text-ink"}`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href="/invoices/new" className="inline-flex h-11 items-center rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark print:hidden">
            New invoice
          </Link>
          <button
            type="button"
            onClick={() => setDialog({ kind: "standaloneCredit" })}
            className="inline-flex h-11 items-center rounded-xl border border-border bg-white px-5 text-[15px] font-bold print:hidden"
          >
            New credit note
          </button>
        </div>
      </div>

      {invoices && invoices.length > 0 && (
        <div className="flex flex-wrap gap-2 print:hidden">
          <PrintButton />
          <button
            type="button"
            onClick={() => downloadCsv(csvFilename("invoices"), invoiceRows(shown))}
            className={exportClass}
          >
            Export CSV
          </button>
        </div>
      )}

      <div className="print:hidden">
        <label className="text-xs font-bold text-muted" htmlFor="inv-list-search">Search invoices</label>
        <input
          id="inv-list-search"
          className="mt-1 h-11 w-full rounded-xl border border-border bg-white px-3 text-[15px] text-ink"
          placeholder="Number or customer…"
          autoComplete="off"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      {invoices && invoices.length > 0 && (
        <div className="rounded-2xl border border-border bg-white p-4">
          <p className="text-sm text-muted">
            Awaiting payment <span className="font-extrabold text-ink">{money(owed)}</span>
            {unpaidCount > 0 && <> · {unpaidCount} unpaid</>}
            {overdue > 0 && <> · overdue <span className="font-extrabold text-warn-ink">{money(overdue)}</span></>}
          </p>
        </div>
      )}
      {note && <p role="status" className="rounded-xl bg-teal-tint px-4 py-3 text-sm font-bold text-teal-dark">{note}</p>}
      {error && <RuntimeErrorNote message={error} title="Could not load invoices" />}
      {!invoices && !error && <LoadingSkeleton lines={3} label="Loading your invoices…" />}
      {invoices && invoices.length === 0 && (
        <EmptyState
          title="No invoices yet"
          body="Sales invoices you write appear here, with who still owes you and what is overdue."
          action={
            <Link
              href="/invoices/new"
              className="inline-flex h-11 items-center whitespace-nowrap rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark"
            >
              New invoice
            </Link>
          }
        />
      )}
      {invoices && invoices.length > 0 && shown.length === 0 && (
        <p className="rounded-2xl border border-border bg-white p-4 text-sm text-muted">
          Nothing here.
        </p>
      )}

      {shown.length > 0 && account && (
        <ul className="divide-y divide-border rounded-2xl border border-border bg-white">
          {shown.map((i) => (
            <li key={i.number} className="px-4 py-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-[15px] font-bold">{i.number} · {i.customer.name}</p>
                  <p className="text-sm text-muted">
                    {ukDate(i.issue_date)} · due {ukDate(i.due_date)}
                    {i.status === "paid" && i.paid_at && ` · paid ${ukDate(i.paid_at)}`}
                    {i.money && i.money.payment_status !== "open" && i.money.payment_status !== "paid" && (
                      <> · <span className="font-bold text-ink">{PAYMENT_LABEL[i.money.payment_status]}</span></>
                    )}
                    {i.money && i.status === "sent" && (i.money.paid_pence > 0 || i.money.credited_pence > 0) && (
                      <> · balance <span className="font-bold text-ink tabular-nums">{money(i.money.balance_pence)}</span></>
                    )}
                    {i.reminders.length > 0 && i.status === "sent" && ` · ${i.reminders.length} reminder${i.reminders.length === 1 ? "" : "s"}`}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <StatusChip invoice={i} />
                  <span className="text-[15px] font-extrabold tabular-nums">{money(i.total_pence)}</span>
                </div>
              </div>
              <div className="mt-2 flex flex-wrap gap-4">
                {i.status === "draft" && (
                  <>
                    <Link href={`/invoices/new?id=${encodeURIComponent(i.number)}`} className={action}>Edit</Link>
                    <button type="button" className={action} onClick={() => setDialog({ kind: "preview", invoice: i })}>Preview and send</button>
                  </>
                )}
                {i.status !== "draft" && (
                  <button type="button" className={action} onClick={() => setDialog({ kind: "preview", invoice: i })}>View PDF</button>
                )}
                {i.status === "sent" && (
                  <>
                    <button type="button" className={action} onClick={() => setDialog({ kind: "remind", invoice: i })}>Draft a reminder</button>
                    <button type="button" className={action} onClick={() => setDialog({ kind: "paid", invoice: i })}>Record payment</button>
                  </>
                )}
                {(() => {
                  const item = openItem(i);
                  const theirs = onAccount.filter((c) => sameName(c.counterparty, i.customer.name));
                  return item && theirs.length > 0 ? (
                    <button type="button" className={action} onClick={() => setDialog({ kind: "applyCredit", name: i.customer.name, credits: theirs, documents: [item] })}>
                      Apply credit
                    </button>
                  ) : null;
                })()}
                {onAccount.some((c) => c.doc_event_id === i.event_id) && (
                  <button type="button" className={action} onClick={() => setDialog({ kind: "refund", name: i.customer.name, credits: onAccount.filter((c) => c.doc_event_id === i.event_id) })}>
                    Refund
                  </button>
                )}
                {(i.status === "sent" || i.status === "paid") && i.event_id && (
                  <button type="button" className={action} onClick={() => setDialog({ kind: "credit", invoice: i })}>Create credit note</button>
                )}
                {(i.status === "draft" || i.status === "sent" || i.status === "paid") && (
                  <button type="button" className="text-[13px] font-bold text-muted hover:underline" onClick={() => setDialog({ kind: "void", invoice: i })}>Void</button>
                )}
              </div>
              {i.status !== "draft" && (
                <details className="mt-2">
                  <summary className={`${action} cursor-pointer`}>{i.money ? "Payments and history" : "History"}</summary>
                  <PaymentsPanel account={account} invoice={i} onChanged={(inv, message) => { replace(inv); setNote(message); void load(); }} />
                  <StatusTimeline invoice={i} />
                </details>
              )}
            </li>
          ))}
        </ul>
      )}

      {credits.length > 0 && account && (
        <section aria-label="Credit notes" className="space-y-2">
          <h2 className="text-lg font-extrabold">Credit notes</h2>
          <ul className="divide-y divide-border rounded-2xl border border-border bg-white">
            {credits.map((c) => (
              <li key={c.number} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                <div className="min-w-0">
                  <p className={`truncate text-[15px] font-bold ${c.status === "void" ? "line-through text-muted" : ""}`}>
                    {c.number} · {c.customer.name}
                  </p>
                  <p className="text-sm text-muted">
                    {ukDate(c.issue_date)} · {c.invoice ? `against ${c.invoice}` : "stand-alone"} · {c.reason}
                    {c.sent_at && ` · emailed ${ukDate(c.sent_at)}`}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-[15px] font-extrabold tabular-nums">-{money(c.total_pence)}</span>
                  {(() => {
                    const left = onAccount.filter((x) => x.doc_event_id === c.event_id);
                    if (!left.length || c.status !== "issued") return null;
                    const docs = (invoices ?? []).filter((i) => sameName(i.customer.name, c.customer.name)).map(openItem).filter((x): x is RtOpenItem => x !== null);
                    return (
                      <>
                        <span className="text-[13px] font-semibold text-teal-dark">{money(left.reduce((n, x) => n + x.amount_pence, 0))} on account</span>
                        {docs.length > 0 && (
                          <button type="button" className={action} onClick={() => setDialog({ kind: "applyCredit", name: c.customer.name, credits: left, documents: docs })}>Apply credit</button>
                        )}
                        <button type="button" className={action} onClick={() => setDialog({ kind: "refund", name: c.customer.name, credits: left })}>Refund</button>
                      </>
                    );
                  })()}
                  <button type="button" className={action} onClick={() => setDialog({ kind: "creditView", note: c })}>View PDF</button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {dialog && account && (() => {
        if (dialog.kind === "applyCredit") {
          return (
            <ApplyCreditDialog
              account={account}
              name={dialog.name}
              credits={dialog.credits}
              documents={dialog.documents}
              onClose={() => setDialog(null)}
              onDone={(message) => { setDialog(null); setNote(message); void load(); }}
            />
          );
        }
        if (dialog.kind === "refund") {
          return (
            <RefundDialog
              account={account}
              name={dialog.name}
              credits={dialog.credits}
              onClose={() => setDialog(null)}
              onDone={(message) => { setDialog(null); setNote(message); void load(); }}
            />
          );
        }
        if (dialog.kind === "creditView") {
          return (
            <CreditNoteViewDialog
              account={account}
              note={dialog.note}
              onClose={() => setDialog(null)}
              onDone={(_cn, message) => { setDialog(null); setNote(message); void load(); }}
            />
          );
        }
        if (dialog.kind === "standaloneCredit") {
          return (
            <StandaloneCreditNoteDialog
              account={account}
              onClose={() => setDialog(null)}
              onDone={credited}
            />
          );
        }
        const props = { account, invoice: dialog.invoice, onClose: () => setDialog(null), onDone: done };
        switch (dialog.kind) {
          case "preview": return <PreviewSendDialog {...props} />;
          case "paid": return <RecordPaymentDialog {...props} />;
          case "remind": return <ReminderDialog {...props} />;
          case "void": return <VoidDialog {...props} />;
          case "credit": return <CreditNoteDialog account={account} invoice={dialog.invoice} onClose={() => setDialog(null)} onDone={credited} />;
        }
      })()}
    </div>
  );
}
