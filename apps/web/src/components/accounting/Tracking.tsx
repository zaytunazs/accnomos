"use client";

import { useState } from "react";
import { errorText, todayIso } from "@/components/jobs/useAccount";
import { accounting, money, ukDay, type RtTrackingSummary } from "@/lib/accounting";
import { Field, Gate, Notes, Scroll, button, card, input, quiet, small, td, th, useLoad } from "./Shared";

const SECTIONS: [string, string][] = [["sales", "Sales"], ["cost_of_sales", "Cost of sales"], ["overheads", "Overheads"]];

function quarterStart(iso: string) {
  const [y, m] = iso.split("-").map(Number);
  return `${y}-${String(Math.floor((m - 1) / 3) * 3 + 1).padStart(2, "0")}-01`;
}

export default function Tracking() {
  const { account, data, error, setError, note, busy, act } = useLoad(accounting.tracking);
  const [newCat, setNewCat] = useState("");
  const [newOpt, setNewOpt] = useState<Record<string, string>>({});
  const [period, setPeriod] = useState({ from: quarterStart(todayIso()), to: todayIso(), category: "" });
  const [summary, setSummary] = useState<RtTrackingSummary | null>(null);

  const cats = data?.categories ?? [];
  const category = period.category || cats[0]?.id || "";

  async function run() {
    if (!account || !category) return;
    setError(null);
    try {
      setSummary(await accounting.trackingSummary(account, category, period.from, period.to));
    } catch (e) {
      setError(errorText(e));
    }
  }

  return (
    <Gate account={account} ready={!!data || !!error} what="to set up tracking categories (for example Department or Project) and see profit and loss by option.">
      <div className="flex min-w-0 flex-col gap-5">
        <Notes note={note} error={error} />
        <section aria-labelledby="cats" className={card}>
          <h2 id="cats" className="text-[17px] font-extrabold">Categories</h2>
          <p className="mt-1 text-sm text-muted">
            Up to {data?.max_categories ?? 2}. Tag lines on invoices, on bills when you approve them, and on manual journals.
            An option in use can be archived, not deleted.
          </p>
          <div className="mt-3 flex flex-col gap-4">
            {cats.map((c) => (
              <div key={c.id} className="rounded-xl border border-border p-3">
                <h3 className="text-[15px] font-extrabold">{c.name}</h3>
                <ul className="mt-2 flex flex-wrap gap-2">
                  {c.options.map((o) => (
                    <li key={o.id} className="flex items-center gap-2 rounded-full border border-border px-3 py-1 text-[14px]">
                      <span className={o.archived ? "text-muted line-through" : ""}>{o.name}</span>
                      <button type="button" className="min-h-8 rounded-full px-2 text-[13px] font-bold text-teal-dark underline"
                        aria-label={`${o.archived ? "Restore" : "Archive"} ${c.name} ${o.name}`} disabled={busy !== null}
                        onClick={() => void act(`o${o.id}`, (a) => accounting.editOption(a, c.id, o.id, { archived: !o.archived }), () => `${o.name} ${o.archived ? "restored" : "archived"}.`)}>
                        {o.archived ? "Restore" : "Archive"}
                      </button>
                    </li>
                  ))}
                </ul>
                <form className="mt-2 flex flex-wrap items-end gap-2" onSubmit={(e) => {
                  e.preventDefault();
                  const name = newOpt[c.id] ?? "";
                  void act(`add${c.id}`, (a) => accounting.addOption(a, c.id, name), () => { setNewOpt({ ...newOpt, [c.id]: "" }); return `Added ${name} to ${c.name}.`; });
                }}>
                  <Field label={`New ${c.name} option`}>
                    <input required maxLength={60} className={input} value={newOpt[c.id] ?? ""} onChange={(e) => setNewOpt({ ...newOpt, [c.id]: e.target.value })} />
                  </Field>
                  <button type="submit" className={small} disabled={busy !== null}>Add option</button>
                </form>
              </div>
            ))}
          </div>
          {cats.length < (data?.max_categories ?? 2) && (
            <form className="mt-3 flex flex-wrap items-end gap-2" onSubmit={(e) => {
              e.preventDefault();
              void act("cat", (a) => accounting.addCategory(a, newCat), () => { const n = newCat; setNewCat(""); return `Added the ${n} category.`; });
            }}>
              <Field label="New category">
                <input required maxLength={40} className={input} value={newCat} onChange={(e) => setNewCat(e.target.value)} />
              </Field>
              <button type="submit" className={quiet} disabled={busy !== null}>Add category</button>
            </form>
          )}
        </section>

        {cats.length > 0 && (
          <section aria-labelledby="tracking-summary" className={card}>
            <h2 id="tracking-summary" className="text-[17px] font-extrabold">Tracking Summary</h2>
            <form className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4 sm:items-end" onSubmit={(e) => { e.preventDefault(); void run(); }}>
              <Field label="Category">
                <select className={input} value={category} onChange={(e) => setPeriod({ ...period, category: e.target.value })}>
                  {cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </Field>
              <Field label="From"><input type="date" required className={input} value={period.from} onChange={(e) => setPeriod({ ...period, from: e.target.value })} /></Field>
              <Field label="To"><input type="date" required className={input} value={period.to} onChange={(e) => setPeriod({ ...period, to: e.target.value })} /></Field>
              <button type="submit" className={button}>Show</button>
            </form>
            {summary && (
              <>
                <p className="mt-2 text-sm text-muted">{ukDay(summary.start)} – {ukDay(summary.end)} · {summary.basis}</p>
                <Scroll label="Tracking summary table">
                  <table className="mt-2 w-full min-w-[36rem] text-left text-[14px]">
                    <caption className="sr-only">Profit and loss by {summary.category.name}</caption>
                    <thead>
                      <tr className="border-b border-border">
                        <th scope="col" className={th}>Account</th>
                        {summary.columns.map((c) => <th key={c.id} scope="col" className={`${th} text-right`}>{c.name}</th>)}
                        <th scope="col" className={`${th} text-right`}>Total</th>
                      </tr>
                    </thead>
                    {SECTIONS.map(([sec, label]) => (
                      <tbody key={sec}>
                        <tr><th scope="rowgroup" colSpan={summary.columns.length + 2} className="pt-3 text-left text-[13px] font-extrabold">{label}</th></tr>
                        {summary.rows.filter((r) => r.section === sec).map((r) => (
                          <tr key={r.account} className="border-b border-border">
                            <th scope="row" className={`${td} font-normal`}>{r.account}</th>
                            {summary.columns.map((c) => <td key={c.id} className={`${td} text-right tabular-nums`}>{money(r.by_option[c.id] ?? 0)}</td>)}
                            <td className={`${td} text-right tabular-nums`}>{money(r.total_pence)}</td>
                          </tr>
                        ))}
                      </tbody>
                    ))}
                    <tfoot>
                      <tr className="border-t-2 border-ink font-extrabold">
                        <th scope="row" className={td}>Net profit</th>
                        {summary.columns.map((c) => <td key={c.id} className={`${td} text-right tabular-nums`}>{money(summary.totals.net_profit[c.id] ?? 0)}</td>)}
                        <td className={`${td} text-right tabular-nums`}>{money(summary.net_profit_total_pence)}</td>
                      </tr>
                    </tfoot>
                  </table>
                </Scroll>
              </>
            )}
          </section>
        )}
      </div>
    </Gate>
  );
}
