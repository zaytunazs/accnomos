"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  INVOICE_DRAFT_KEY,
  pence,
  runtime,
  ukDate,
  type JobInvoiceDraft,
  type RtJobSummary,
  type RtStaff,
  type RtTimesheetEntry,
} from "@/lib/runtime";
import { errorText, todayIso, useAccount } from "./useAccount";
import { RuntimeErrorNote, isAuthError, isServerError } from "@/components/States";

const hrs = (h: number) => h.toLocaleString("en-GB", { maximumFractionDigits: 2 });
const card = "rounded-2xl border border-border bg-white p-4";
const heading = "text-[17px] font-extrabold text-ink";
const field = "h-10 rounded-xl border border-border px-2 text-sm";

/** /jobs/job?id=…: the job's summary, its timesheet (with a quick-add row) and "Invoice these hours". */
export default function JobDetail() {
  const router = useRouter();
  const id = useSearchParams().get("id") ?? "";
  const account = useAccount();
  const [summary, setSummary] = useState<RtJobSummary | null>(null);
  const [entries, setEntries] = useState<RtTimesheetEntry[]>([]);
  const [staff, setStaff] = useState<RtStaff[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [row, setRow] = useState({ staff_id: "", date: todayIso(), hours: "", note: "", billable: true });

  const fail = useCallback((err: unknown) => {
    const msg = errorText(err);
    if (isAuthError(msg) || isServerError(msg)) setError(msg);
    else setNote(msg);
  }, []);

  const load = useCallback(async () => {
    if (!account || !id) return;
    try {
      const [s, e, st] = await Promise.all([runtime.jobSummary(account, id), runtime.timesheets(account, id), runtime.staff(account)]);
      setSummary(s);
      setEntries(e);
      setStaff(st);
      setError(null);
      setRow((r) => (r.staff_id ? r : { ...r, staff_id: st.find((m) => m.active)?.id ?? "" }));
    } catch (err) {
      fail(err);
    }
  }, [account, id, fail]);

  useEffect(() => {
    queueMicrotask(load);
  }, [load]);

  async function act(label: string, fn: () => Promise<unknown>, done?: string) {
    setBusy(label);
    setNote(null);
    setError(null);
    try {
      await fn();
      if (done) setNote(done);
      await load();
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  function addRow(e: React.FormEvent) {
    e.preventDefault();
    if (!account) return;
    const hours = Number(row.hours);
    act("add", async () => {
      await runtime.addTimesheet(account, { ...row, job_id: id, hours, note: row.note.trim() });
      setRow((r) => ({ ...r, hours: "", note: "" }));
    });
  }

  /** Proposed lines from the unbilled hours, handed to the invoice form; sending that invoice marks the hours. */
  function invoiceHours() {
    if (!account || !summary) return;
    act("lines", async () => {
      const proposal = await runtime.jobInvoiceLines(account, id);
      if (!proposal.lines.length) throw new Error(proposal.warnings.join(" ") || "No unbilled billable hours on this job.");
      const draft: JobInvoiceDraft = { proposal, job_name: summary.job.name, customer_name: summary.customer_name };
      try {
        window.sessionStorage.setItem(INVOICE_DRAFT_KEY, JSON.stringify(draft));
      } catch {
        throw new Error("This browser blocked session storage, so the hours can't be passed to the invoice form.");
      }
      router.push("/invoices/new?from=job");
    });
  }

  if (!id) return <p className="text-sm text-muted">No job chosen. <Link href="/jobs" className="font-bold text-teal-dark underline">Back to jobs</Link></p>;
  if (account === null) return <p className="text-sm text-muted">Sign in to see this job.</p>;
  if (!summary) return <p className="text-sm text-muted">{note ?? "Loading…"}</p>;

  const job = summary.job;
  const names = Object.fromEntries(staff.map((s) => [s.id, s.role ? `${s.name} (${s.role})` : s.name]));
  const open = job.status === "open";
  const tiles = [
    ["Hours", `${hrs(summary.hours)} h`, `${hrs(summary.unbilled_hours)} h unbilled`],
    ["Labour cost", pence(summary.labour_cost_pence), "at hourly cost rates"],
    ["Materials", pence(summary.materials_pence), `${summary.purchases.length} tagged purchase${summary.purchases.length === 1 ? "" : "s"}, ex VAT`],
    ["Billable value", pence(summary.billable_value_pence), `${pence(summary.invoiced_value_pence)} invoiced`],
    ["Margin", pence(summary.margin_pence), "value − labour − materials"],
  ];

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link href="/jobs" className="text-sm font-bold text-teal-dark underline">
            ← Jobs
          </Link>
          <h1 className="mt-1 text-3xl font-extrabold tracking-tight">{job.name}</h1>
          <p className="mt-1 text-[15px] text-muted">
            {[summary.customer_name ?? job.customer_id, job.site_address].filter(Boolean).join(" · ") || "No customer or site yet"}
            {!open && " · Closed"}
          </p>
        </div>
        <button
          type="button"
          disabled={busy !== null || !account}
          onClick={() =>
            account &&
            act("status", () =>
              runtime.updateJob(account, id, {
                name: job.name, customer_id: job.customer_id, site_address: job.site_address, status: open ? "closed" : "open",
              }),
            )
          }
          className="h-10 rounded-xl border border-border bg-white px-4 text-sm font-bold text-ink disabled:opacity-60"
        >
          {open ? "Close job" : "Reopen job"}
        </button>
      </div>

      <div className="grid grid-cols-1 gap-3 min-[560px]:grid-cols-2 min-[1100px]:grid-cols-5">
        {tiles.map(([label, value, sub]) => (
          <div key={label} className={card}>
            <p className="text-sm font-semibold text-muted">{label}</p>
            <p className={`mt-1 text-2xl font-extrabold tracking-tight ${label === "Margin" && summary.margin_pence < 0 ? "text-warn-ink" : "text-ink"}`}>
              {value}
            </p>
            <p className="mt-1 text-[13px] font-semibold text-muted">{sub}</p>
          </div>
        ))}
      </div>
      {summary.warnings.length > 0 && (
        <ul className="rounded-2xl border border-warn-border bg-warn-bg p-4 text-sm font-semibold text-warn-ink">
          {summary.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}

      <section aria-labelledby="job-timesheet" className={card}>
        <h2 id="job-timesheet" className={heading}>
          Timesheet
        </h2>
        {staff.length === 0 && (
          <p className="mt-2 text-sm text-muted">
            Add your staff and their rates in <Link href="/settings" className="font-bold text-teal-dark underline">Settings</Link> first.
          </p>
        )}
        <form onSubmit={addRow} className="mt-3 overflow-x-auto" aria-label="Add hours">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="text-xs font-bold text-muted">
                <th scope="col" className="py-2 pr-3">Staff</th>
                <th scope="col" className="py-2 pr-3">Date</th>
                <th scope="col" className="py-2 pr-3 text-right">Hours</th>
                <th scope="col" className="py-2 pr-3">Note</th>
                <th scope="col" className="py-2 pr-3">Billable</th>
                <th scope="col" className="py-2"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {open && (
                <tr className="bg-ground/50">
                  <td className="py-2 pr-2">
                    <select
                      aria-label="Staff"
                      value={row.staff_id}
                      onChange={(e) => setRow({ ...row, staff_id: e.target.value })}
                      className={`${field} w-full min-w-36`}
                    >
                      {staff.filter((s) => s.active).map((s) => (
                        <option key={s.id} value={s.id}>{names[s.id]}</option>
                      ))}
                    </select>
                  </td>
                  <td className="py-2 pr-2">
                    <input aria-label="Date" type="date" value={row.date} onChange={(e) => setRow({ ...row, date: e.target.value })} className={field} />
                  </td>
                  <td className="py-2 pr-2">
                    <input
                      aria-label="Hours" type="number" min="0.25" max="24" step="0.25" inputMode="decimal" value={row.hours}
                      onChange={(e) => setRow({ ...row, hours: e.target.value })} className={`${field} w-20 text-right`}
                    />
                  </td>
                  <td className="py-2 pr-2">
                    <input aria-label="Note" value={row.note} maxLength={500} onChange={(e) => setRow({ ...row, note: e.target.value })} className={`${field} w-full min-w-40`} />
                  </td>
                  <td className="py-2 pr-2">
                    <input aria-label="Billable" type="checkbox" checked={row.billable} onChange={(e) => setRow({ ...row, billable: e.target.checked })} />
                  </td>
                  <td className="py-2 text-right">
                    <button
                      type="submit"
                      disabled={busy !== null || !row.staff_id || !(Number(row.hours) > 0)}
                      className="h-10 rounded-xl bg-teal px-4 text-sm font-extrabold text-white disabled:opacity-60"
                    >
                      {busy === "add" ? "Adding…" : "Add"}
                    </button>
                  </td>
                </tr>
              )}
              {[...entries].reverse().map((e) => (
                <tr key={e.id} className="text-ink">
                  <td className="py-2 pr-3 font-bold">{names[e.staff_id] ?? e.staff_id}</td>
                  <td className="py-2 pr-3 text-muted">{ukDate(e.date)}</td>
                  <td className="py-2 pr-3 text-right">{hrs(e.hours)}</td>
                  <td className="py-2 pr-3 text-muted">{e.note || "—"}</td>
                  <td className="py-2 pr-3 text-muted">{e.invoiced_in ? `Invoiced (${e.invoiced_in})` : e.billable ? "Yes" : "No"}</td>
                  <td className="py-2 text-right">
                    {!e.invoiced_in && open && (
                      <button
                        type="button"
                        disabled={busy !== null}
                        onClick={() => account && act(`del-${e.id}`, () => runtime.deleteTimesheet(account, e.id))}
                        className="h-9 rounded-xl border border-border bg-white px-3 text-[13px] font-bold text-ink disabled:opacity-60"
                      >
                        {busy === `del-${e.id}` ? "Removing…" : "Remove"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {entries.length === 0 && <p className="mt-2 text-sm text-muted">No hours yet.</p>}
        </form>
      </section>

      <section aria-labelledby="job-invoice" className={card}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="job-invoice" className={heading}>
            Invoice
          </h2>
          <button
            type="button"
            disabled={busy !== null || summary.unbilled_hours === 0}
            onClick={invoiceHours}
            className="h-11 rounded-xl bg-teal px-5 text-[15px] font-extrabold text-white disabled:opacity-60"
          >
            {busy === "lines" ? "Working out…" : "Invoice these hours"}
          </button>
        </div>
        <p className="mt-2 text-sm text-muted">
          Opens a new invoice with this job&apos;s customer and one line per person (unbilled hours × charge rate), for you
          to check and change. When that invoice is sent, these hours are marked invoiced with its number.
        </p>
      </section>

      {summary.purchases.length > 0 && (
        <section aria-labelledby="job-purchases" className={card}>
          <h2 id="job-purchases" className={heading}>
            Materials and costs
          </h2>
          <p className="mt-1 text-sm text-muted">Purchases tagged to this job when they were approved in Review (ex VAT).</p>
          <ul className="mt-2 divide-y divide-border text-sm">
            {summary.purchases.map((p) => (
              <li key={p.event_id} className="flex justify-between gap-3 py-2">
                <span>{ukDate(p.date)} · {p.supplier ?? "Unknown supplier"}</span>
                <span className="font-bold">{pence(p.net_pence)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {error && <RuntimeErrorNote message={error} />}
      {note && (
        <p role="status" className="text-sm font-bold text-teal-dark">
          {note}
        </p>
      )}
    </div>
  );
}
