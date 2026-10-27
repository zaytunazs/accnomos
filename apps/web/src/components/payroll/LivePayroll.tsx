"use client";

import { useCallback, useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { errorText, todayIso, useAccount } from "@/components/jobs/useAccount";
import { gbp, runtime, ukDate, type RtPayRun, type RtPayRunList, type RtStaff } from "@/lib/runtime";

export const ESTIMATE = "Estimate — your payroll provider calculates the actual tax and NI";

const pounds = (pence: number) => gbp(pence / 100);
/** "12.34" -> 1234; null when it isn't a non-negative amount. */
const toPence = (s: string): number | null => {
  const n = Number(s.trim().replace(/^£/, ""));
  return s.trim() !== "" && Number.isFinite(n) && n >= 0 ? Math.round(n * 100) : null;
};
const periodOf = (iso: string) => iso.slice(0, 7);
const monthName = (period: string) =>
  new Date(`${period}-01T12:00:00`).toLocaleDateString("en-GB", { month: "long", year: "numeric" });

const input = "h-11 rounded-xl border border-border bg-white px-3 text-[15px]";
const button = "h-11 rounded-xl bg-teal px-5 text-[15px] font-bold text-white disabled:opacity-60";
const quiet = "h-11 rounded-xl border border-border bg-white px-4 text-[15px] font-bold disabled:opacity-60";

type Row = { staff_id: string; hours: string; rate: string; notes: string };
const rowsOf = (run: RtPayRun): Row[] =>
  run.lines.map((l) => ({ staff_id: l.staff_id, hours: String(l.hours), rate: (l.rate_pence / 100).toFixed(2), notes: l.notes }));

/** The "Estimate" badge: on every figure the runtime estimates. */
export function EstimateBadge({ full = false }: { full?: boolean }) {
  return (
    <span className="inline-flex items-center rounded-full bg-warn-bg px-2.5 py-0.5 text-[12px] font-bold text-warn-ink ring-1 ring-warn-border">
      {full ? ESTIMATE : "Estimate"}
    </span>
  );
}

export default function LivePayroll() {
  const account = useAccount();
  const [period, setPeriod] = useState(periodOf(todayIso()));
  const [list, setList] = useState<RtPayRunList | null>(null);
  const [staff, setStaff] = useState<RtStaff[]>([]);
  const [rows, setRows] = useState<Row[]>([]);
  const [payDate, setPayDate] = useState("");
  const [dirty, setDirty] = useState(false);
  const [actual, setActual] = useState({ gross: "", erNi: "" });
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const run = list?.runs.find((r) => periodOf(r.period_start) === period) ?? null;

  const load = useCallback(async (acct: AccountInfo) => {
    const [l, s] = await Promise.all([runtime.payrollRuns(acct), runtime.staff(acct)]);
    setList(l);
    setStaff(s);
  }, []);

  useEffect(() => {
    if (account) queueMicrotask(() => load(account).catch((e) => setNote(errorText(e))));
  }, [account, load]);

  // Editable rows start from the saved run, and start again whenever another run (month, reload) is shown.
  const [shown, setShown] = useState<RtPayRun | null>(null);
  if (run !== shown) {
    setShown(run);
    setRows(run ? rowsOf(run) : []);
    setPayDate(run?.pay_date ?? "");
    setDirty(false);
  }

  async function act(key: string, fn: (a: AccountInfo) => Promise<unknown>, done?: string) {
    if (!account) return;
    setBusy(key);
    try {
      await fn(account);
      if (done) setNote(done);
      await load(account);
    } catch (e) {
      setNote(errorText(e));
    } finally {
      setBusy(null);
    }
  }

  if (account === undefined) return <p className="text-sm text-muted">Loading pay runs…</p>;
  if (account === null)
    return (
      <p className="rounded-2xl border border-border bg-white p-6 text-[15px] leading-7 text-muted">
        Sign in with Microsoft to prepare pay runs from your timesheets. Accnomos adds up the hours and estimates tax and
        NI so you can hand clean numbers to your payroll provider. It does not run payroll or send anything to HMRC.
      </p>
    );

  const names = new Map(staff.map((s) => [s.id, s]));
  const draft = run?.status === "draft";
  const edits = rows.map((r) => ({ staff_id: r.staff_id, hours: Number(r.hours), rate_pence: toPence(r.rate), notes: r.notes }));
  const editsValid = edits.every((e) => Number.isFinite(e.hours) && e.hours >= 0 && e.hours <= 744 && e.rate_pence !== null);
  const total = (f: "gross_pence" | "est_paye_pence" | "est_ee_ni_pence" | "est_net_pence" | "est_er_ni_pence") =>
    run ? run.lines.reduce((n, l) => n + l[f], 0) : 0;
  const grossP = toPence(actual.gross);
  const erNiP = toPence(actual.erNi);
  const notOnRun = staff.filter((s) => s.active && !rows.some((r) => r.staff_id === s.id));

  async function download() {
    if (!account || !run) return;
    setBusy("export");
    try {
      const r = await runtime.exportPayRun(account, period);
      const url = URL.createObjectURL(new Blob(["\uFEFF", r.csv], { type: "text/csv;charset=utf-8" }));
      const a = Object.assign(document.createElement("a"), { href: url, download: `payroll-${period}.csv` });
      a.click();
      URL.revokeObjectURL(url);
      setNote(`Saved to ${r.path} in your OneDrive and downloaded. ${ESTIMATE}.`);
    } catch (e) {
      setNote(errorText(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <p role="note" className="rounded-2xl border border-warn-border bg-warn-bg px-4 py-3 text-[15px] font-semibold leading-6 text-warn-ink">
        {ESTIMATE}. Accnomos prepares the numbers; it does not run payroll or file RTI with HMRC.
      </p>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
          Month
          <input type="month" value={period} max={periodOf(todayIso())} onChange={(e) => e.target.value && setPeriod(e.target.value)} className={input} />
        </label>
        {(!run || draft) && (
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => {
              if (run && !window.confirm("Prepare again from timesheets? Your edits to this draft will be replaced.")) return;
              act("prepare", (a) => runtime.preparePayRun(a, period), `Pay run for ${monthName(period)} prepared from timesheets.`);
            }}
            className={run ? quiet : button}
          >
            {busy === "prepare" ? "Adding up hours…" : run ? "Prepare again from timesheets" : `Prepare ${monthName(period)} pay run`}
          </button>
        )}
        {run && (
          <button type="button" disabled={busy !== null || dirty} onClick={download} className={quiet} title={dirty ? "Save your changes first" : undefined}>
            {busy === "export" ? "Exporting…" : "Export CSV"}
          </button>
        )}
      </div>

      {note && (
        <p role="status" className="rounded-xl bg-teal-tint px-4 py-2 text-sm text-teal-dark">
          {note}
        </p>
      )}

      {!run && (
        <p className="rounded-2xl border border-border bg-white p-6 text-[15px] leading-7 text-muted">
          No pay run for {monthName(period)} yet. Preparing one adds up everyone&apos;s timesheet hours for the month at
          their hourly rate (set on the Jobs page) and estimates the deductions. You can change hours and rates before
          exporting.
        </p>
      )}

      {run && (
        <section aria-labelledby="pay-run" className="rounded-2xl border border-border bg-white p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 id="pay-run" className="text-[17px] font-extrabold">
              {monthName(period)} pay run{" "}
              <span className={`ml-1 rounded-full px-2.5 py-0.5 text-[12px] font-bold ${draft ? "bg-ground text-muted" : "bg-teal-tint text-teal-dark"}`}>
                {draft ? "Draft" : "Confirmed and posted"}
              </span>
            </h2>
            <EstimateBadge full />
          </div>
          <div className="mt-2 flex flex-wrap items-end gap-3 text-sm text-muted">
            <span>{ukDate(run.period_start)} – {ukDate(run.period_end)}</span>
            {draft ? (
              <label className="flex items-center gap-2 font-bold">
                Pay date
                <input type="date" value={payDate} onChange={(e) => { setPayDate(e.target.value); setDirty(true); }} className={`${input} h-9`} />
              </label>
            ) : (
              <span>Paid {ukDate(run.pay_date)}</span>
            )}
          </div>
          {run.warnings.map((w) => (
            <p key={w} className="mt-2 text-sm font-semibold text-warn-ink">{w}</p>
          ))}

          {rows.length > 0 && (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-left text-[15px]">
                <thead>
                  <tr className="border-b border-border text-[13px] font-bold text-muted">
                    <th scope="col" className="py-2 pr-3">Employee</th>
                    <th scope="col" className="py-2 pr-3 text-right">Hours</th>
                    <th scope="col" className="py-2 pr-3 text-right">Rate £/hr</th>
                    <th scope="col" className="py-2 pr-3 text-right">Gross</th>
                    <th scope="col" className="py-2 pr-3 text-right">Est. PAYE</th>
                    <th scope="col" className="py-2 pr-3 text-right">Est. employee NI</th>
                    <th scope="col" className="py-2 pr-3 text-right">Est. net pay</th>
                    <th scope="col" className="py-2 pr-3 text-right">Est. employer NI</th>
                    <th scope="col" className="py-2">Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => {
                    const line = run.lines.find((l) => l.staff_id === r.staff_id);
                    const who = names.get(r.staff_id);
                    const set = (patch: Partial<Row>) => {
                      setRows(rows.map((x, j) => (j === i ? { ...x, ...patch } : x)));
                      setDirty(true);
                    };
                    const stale = dirty || !line;
                    const cell = (p: number | undefined) => (stale || p === undefined ? "—" : pounds(p));
                    return (
                      <tr key={r.staff_id} className="border-t border-border">
                        <th scope="row" className="py-2 pr-3 font-bold">
                          {who?.name ?? r.staff_id}
                          {who?.role && <span className="block text-[13px] font-normal text-muted">{who.role}</span>}
                        </th>
                        <td className="py-2 pr-3 text-right">
                          {draft ? (
                            <input aria-label={`Hours for ${who?.name ?? r.staff_id}`} type="number" min="0" max="744" step="0.25" inputMode="decimal" value={r.hours} onChange={(e) => set({ hours: e.target.value })} className={`${input} h-9 w-24 text-right`} />
                          ) : (
                            <span className="tabular-nums">{r.hours}</span>
                          )}
                        </td>
                        <td className="py-2 pr-3 text-right">
                          {draft ? (
                            <input aria-label={`Hourly rate for ${who?.name ?? r.staff_id}`} type="number" min="0" step="0.01" inputMode="decimal" value={r.rate} onChange={(e) => set({ rate: e.target.value })} className={`${input} h-9 w-24 text-right`} />
                          ) : (
                            <span className="tabular-nums">{r.rate}</span>
                          )}
                        </td>
                        <td className="py-2 pr-3 text-right font-bold tabular-nums">{cell(line?.gross_pence)}</td>
                        <td className="py-2 pr-3 text-right tabular-nums text-muted">{cell(line?.est_paye_pence)}</td>
                        <td className="py-2 pr-3 text-right tabular-nums text-muted">{cell(line?.est_ee_ni_pence)}</td>
                        <td className="py-2 pr-3 text-right tabular-nums text-muted">{cell(line?.est_net_pence)}</td>
                        <td className="py-2 pr-3 text-right tabular-nums text-muted">{cell(line?.est_er_ni_pence)}</td>
                        <td className="py-2">
                          {draft ? (
                            <div className="flex items-center gap-2">
                              <input aria-label={`Notes for ${who?.name ?? r.staff_id}`} maxLength={300} value={r.notes} onChange={(e) => set({ notes: e.target.value })} className={`${input} h-9 w-40`} />
                              <button type="button" onClick={() => { setRows(rows.filter((_, j) => j !== i)); setDirty(true); }} className="text-sm font-bold text-muted underline underline-offset-2">
                                Remove
                              </button>
                            </div>
                          ) : (
                            <span className="text-sm text-muted">{r.notes}</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                  {!dirty && (
                    <tr className="border-t-2 border-border font-bold">
                      <th scope="row" className="py-2 pr-3">Total</th>
                      <td className="py-2 pr-3 text-right tabular-nums">{run.lines.reduce((n, l) => n + l.hours, 0)}</td>
                      <td />
                      <td className="py-2 pr-3 text-right tabular-nums">{pounds(total("gross_pence"))}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{pounds(total("est_paye_pence"))}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{pounds(total("est_ee_ni_pence"))}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{pounds(total("est_net_pence"))}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{pounds(total("est_er_ni_pence"))}</td>
                      <td className="py-2"><EstimateBadge /></td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}

          {draft && (
            <div className="mt-3 flex flex-wrap items-center gap-3">
              {notOnRun.length > 0 && (
                <select
                  aria-label="Add someone to this pay run"
                  value=""
                  onChange={(e) => {
                    const s = names.get(e.target.value);
                    if (!s) return;
                    setRows([...rows, { staff_id: s.id, hours: "0", rate: (s.hourly_rate_pence / 100).toFixed(2), notes: "" }]);
                    setDirty(true);
                  }}
                  className={input}
                >
                  <option value="">Add someone…</option>
                  {notOnRun.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
              )}
              <button
                type="button"
                disabled={busy !== null || !dirty || !editsValid}
                onClick={() =>
                  act("save", (a) => runtime.editPayRun(a, period, edits.map((e) => ({ ...e, rate_pence: e.rate_pence ?? 0 })), payDate || null), "Changes saved; estimates worked out again.")
                }
                className={button}
              >
                {busy === "save" ? "Saving…" : "Save changes"}
              </button>
              {dirty && <span className="text-sm text-muted">Save to see the new gross and estimates.</span>}
              {!editsValid && <span className="text-sm font-semibold text-warn-ink">Hours must be 0–744 and rates a £ amount.</span>}
            </div>
          )}
        </section>
      )}

      {run && draft && (
        <section aria-labelledby="confirm" className="rounded-2xl border border-border bg-white p-5">
          <h2 id="confirm" className="text-[17px] font-extrabold">Confirm what was actually paid</h2>
          <p className="mt-1 text-sm leading-6 text-muted">
            When your payroll provider has run payroll, type in <strong>their</strong> totals (not the estimates above).
            Accnomos then records the staff costs in your books on the pay date: gross wages to <em>7000 Gross wages</em>,
            employer NI to <em>7010 Employer&apos;s NI</em>, both owed via <em>2210 Payroll liabilities</em> until paid.
          </p>
          <form
            className="mt-3 flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (grossP === null || grossP <= 0 || erNiP === null) return;
              if (!window.confirm(`Post ${pounds(grossP)} gross wages and ${pounds(erNiP)} employer NI to your books for ${monthName(period)}?`)) return;
              act("confirm", (a) => runtime.confirmPayRun(a, period, grossP, erNiP), `${monthName(period)} staff costs posted to your books.`).then(() =>
                setActual({ gross: "", erNi: "" }),
              );
            }}
          >
            <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
              Actual gross pay £ (provider)
              <input required inputMode="decimal" value={actual.gross} onChange={(e) => setActual({ ...actual, gross: e.target.value })} placeholder={`estimate ${(total("gross_pence") / 100).toFixed(2)}`} className={`${input} w-48`} />
            </label>
            <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
              Actual employer NI £ (provider)
              <input required inputMode="decimal" value={actual.erNi} onChange={(e) => setActual({ ...actual, erNi: e.target.value })} placeholder={`estimate ${(total("est_er_ni_pence") / 100).toFixed(2)}`} className={`${input} w-48`} />
            </label>
            <button type="submit" disabled={busy !== null || dirty || grossP === null || grossP <= 0 || erNiP === null} className={button}>
              {busy === "confirm" ? "Posting…" : "Confirm and post"}
            </button>
          </form>
          {grossP !== null && grossP > 0 && grossP !== total("gross_pence") && (
            <p className="mt-2 text-sm text-muted">
              {pounds(Math.abs(grossP - total("gross_pence")))} {grossP > total("gross_pence") ? "more" : "less"} than the estimated gross; that&apos;s fine if it&apos;s what your provider calculated.
            </p>
          )}
        </section>
      )}

      {run && !draft && (
        <section aria-labelledby="confirmed" className="rounded-2xl border border-border bg-white p-5">
          <h2 id="confirmed" className="text-[17px] font-extrabold">Posted to your books</h2>
          <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-[15px]">
            <dt className="text-muted">Actual gross pay</dt>
            <dd className="font-bold tabular-nums">{pounds(run.confirmed_gross_pence ?? 0)}</dd>
            <dt className="text-muted">Actual employer NI</dt>
            <dd className="font-bold tabular-nums">{pounds(run.confirmed_er_ni_pence ?? 0)}</dd>
            <dt className="text-muted">Confirmed</dt>
            <dd>{run.confirmed_at ? ukDate(run.confirmed_at) : "—"} by {run.confirmed_by}</dd>
          </dl>
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => {
              if (!window.confirm("Reopen this pay run? Its ledger entries are undone (reversed) and it goes back to draft.")) return;
              act("reopen", (a) => runtime.reopenPayRun(a, period), "Pay run reopened; its ledger entries were reversed.");
            }}
            className={`${quiet} mt-3`}
          >
            {busy === "reopen" ? "Reopening…" : "Reopen (undo the posting)"}
          </button>
        </section>
      )}

      <section aria-labelledby="limits" className="rounded-2xl bg-ground p-5">
        <h2 id="limits" className="text-[15px] font-extrabold">What the estimate leaves out</h2>
        <ul className="mt-2 flex list-disc flex-col gap-1 pl-5 text-[14px] leading-6">
          {(list?.limits ?? []).map((l) => (
            <li key={l}>{l}</li>
          ))}
          <li>Monthly pay only: annual thresholds divided by 12. Gross is hours × hourly rate; salaries, overtime rates and bonuses are typed in as edits.</li>
          <li>Accnomos does not file RTI (FPS/EPS) or pay HMRC. Your payroll provider, or HMRC Basic PAYE Tools, does.</li>
        </ul>
        {list && (
          <p className="mt-2 text-[14px] text-muted">
            Rates for tax year {list.tax_year}:{" "}
            <a href={list.source_url} target="_blank" rel="noreferrer" className="font-bold underline underline-offset-2">
              HMRC rates and thresholds for employers
            </a>
          </p>
        )}
      </section>
    </div>
  );
}
