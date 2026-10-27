"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { MarkPaidDialog, PreviewSendDialog, ReminderDialog, StatusTimeline, VoidDialog } from "@/components/invoices/InvoiceDialogs";
import SignInCta from "@/components/SignInCta";
import { EmptyState, RuntimeErrorNote } from "@/components/States";
import PrintButton from "@/components/PrintButton";
import { csvFilename, downloadCsv, type CsvValue } from "@/lib/csv";
import { money, SAMPLE_INVOICES, STATUS_LABEL, useMsAccount } from "@/lib/invoices";
import { runtime, ukDate, type RtInvoice } from "@/lib/runtime";

type Filter = "all" | "draft" | "sent" | "overdue" | "paid" | "void";
type Dialog = { kind: "preview" | "paid" | "remind" | "void"; invoice: RtInvoice } | null;

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
      setInvoices(await runtime.invoices(account));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [account]);

  useEffect(() => {
    queueMicrotask(load);
  }, [load]);

  function done(updated: RtInvoice) {
    const was = dialog?.kind;
    setDialog(null);
    setInvoices((list) => list?.map((i) => (i.number === updated.number ? updated : i)) ?? null);
    setNote({
      preview: `${updated.number} sent to ${updated.sent_to ?? "the customer"} and recorded in your books.`,
      paid: `${updated.number} marked paid.`,
      remind: `Reminder for ${updated.number} sent.`,
      void: `${updated.number} is void.`,
    }[was ?? "paid"]);
  }

  if (ready && !account) {
    return (
      <div className="space-y-3">
        <p className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl bg-ground p-4 text-sm text-muted">
          <SignInCta />
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
  const owed = (invoices ?? []).filter((i) => i.status === "sent").reduce((s, i) => s + i.total_pence, 0);
  const overdue = (invoices ?? []).filter(isOverdue).reduce((s, i) => s + i.total_pence, 0);
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
        <Link href="/invoices/new" className="inline-flex h-11 items-center rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark print:hidden">
          New invoice
        </Link>
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
      {!invoices && !error && <p className="text-sm text-muted">Loading invoices…</p>}
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
                    <button type="button" className={action} onClick={() => setDialog({ kind: "paid", invoice: i })}>Mark paid</button>
                  </>
                )}
                {(i.status === "draft" || i.status === "sent") && (
                  <button type="button" className="text-[13px] font-bold text-muted hover:underline" onClick={() => setDialog({ kind: "void", invoice: i })}>Void</button>
                )}
              </div>
              {i.status !== "draft" && (
                <details className="mt-2">
                  <summary className={`${action} cursor-pointer`}>History</summary>
                  <StatusTimeline invoice={i} />
                </details>
              )}
            </li>
          ))}
        </ul>
      )}

      {dialog && account && (() => {
        const props = { account, invoice: dialog.invoice, onClose: () => setDialog(null), onDone: done };
        switch (dialog.kind) {
          case "preview": return <PreviewSendDialog {...props} />;
          case "paid": return <MarkPaidDialog {...props} />;
          case "remind": return <ReminderDialog {...props} />;
          case "void": return <VoidDialog {...props} />;
        }
      })()}
    </div>
  );
}
