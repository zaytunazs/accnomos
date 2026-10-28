"use client";

import { useCallback, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { errorText, todayIso } from "@/components/jobs/useAccount";
import {
  accounting,
  money,
  penceText,
  toPence,
  ukDay,
  type RtAccount,
  type RtBudget,
  type RtBudgetSummary,
  type RtVariance,
} from "@/lib/accounting";
import { Field, Gate, Notes, Scroll, button, card, input, quiet, td, th, useLoad } from "./Shared";

const PL_TYPES = new Set(["revenue", "direct_costs", "overhead"]);
const SECTION_LABEL: Record<string, string> = { sales: "Sales", cost_of_sales: "Cost of sales", overheads: "Overheads", net_profit: "Net profit" };

function monthsFrom(start: string): string[] {
  const [y, m] = start.split("-").map(Number);
  return Array.from({ length: 12 }, (_, i) => {
    const d = new Date(Date.UTC(y, m - 1 + i, 1));
    return d.toLocaleDateString("en-GB", { month: "short", year: "2-digit", timeZone: "UTC" });
  });
}
const monthKey = (start: string, i: number) => {
  const [y, m] = start.split("-").map(Number);
  const d = new Date(Date.UTC(y, m - 1 + i, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
};

interface Data { budgets: RtBudget[]; accounts: RtAccount[] }

export default function Budgets() {
  const load = useCallback(async (a: AccountInfo): Promise<Data> => {
    const [b, c] = await Promise.all([accounting.budgets(a), accounting.chart(a)]);
    return { budgets: b.budgets, accounts: c.accounts.filter((x) => PL_TYPES.has(x.type) && !x.archived) };
  }, []);
  const { account, data, error, setError, note, busy, act } = useLoad(load);
  const [start, setStart] = useState(todayIso().slice(0, 7));
  const [name, setName] = useState("Budget");
  const [grid, setGrid] = useState<Record<string, string[]>>({});
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [summary, setSummary] = useState<RtBudgetSummary | null>(null);
  const [variance, setVariance] = useState<RtVariance | null>(null);
  const [through, setThrough] = useState("");

  const saved = data?.budgets.find((b) => b.start === start) ?? null;
  // Fill the grid from the saved budget whenever another start month (or a reload) is shown.
  const stamp = `${start}|${saved?.updated_at ?? "new"}|${data ? "y" : "n"}`;
  if (data && stamp !== loadedFor) {
    setLoadedFor(stamp);
    setName(saved?.name ?? "Budget");
    const g: Record<string, string[]> = {};
    for (const l of saved?.lines ?? []) g[l.account] = l.months.map(penceText);
    setGrid(g);
    setSummary(null);
    setVariance(null);
  }

  const months = monthsFrom(start);
  const bad = Object.entries(grid).flatMap(([acc, row]) => row.map((v, i) => (v.trim() && toPence(v) === null ? `${acc} ${months[i]}` : null))).filter(Boolean);

  function save() {
    const lines = Object.entries(grid)
      .map(([account, row]) => ({ account, months: row.map((v) => toPence(v) ?? 0) }))
      .filter((l) => l.months.some(Boolean));
    void act("save", (a) => accounting.saveBudget(a, start, { name, lines }), (b) => `Budget from ${ukDay(`${b.start}-01`)} saved (${b.lines.length} account${b.lines.length === 1 ? "" : "s"}). Nothing is posted.`);
  }

  async function show(kind: "summary" | "variance") {
    if (!account) return;
    setError(null);
    try {
      if (kind === "summary") setSummary(await accounting.budgetSummary(account, start));
      else setVariance(await accounting.budgetVariance(account, start, through || null));
    } catch (e) {
      setError(errorText(e));
    }
  }

  const set = (acc: string, i: number, v: string) => {
    const row = grid[acc] ?? Array(12).fill("");
    setGrid({ ...grid, [acc]: row.map((x, j) => (j === i ? v : x)) });
  };

  return (
    <Gate account={account} ready={!!data || !!error} what="to set a monthly budget for each income and cost account and compare it with what actually happened.">
      <div className="flex min-w-0 flex-col gap-5">
        <Notes note={note} error={error} />
        <section aria-labelledby="budget-edit" className={card}>
          <h2 id="budget-edit" className="text-[17px] font-extrabold">Budget</h2>
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-[12rem_1fr]">
            <Field label="First month">
              <input type="month" className={input} value={start} onChange={(e) => e.target.value && setStart(e.target.value)} />
            </Field>
            <Field label="Name"><input maxLength={80} className={input} value={name} onChange={(e) => setName(e.target.value)} /></Field>
          </div>
          {data && data.budgets.length > 0 && (
            <p className="mt-2 text-sm text-muted">
              Saved budgets:{" "}
              {data.budgets.map((b, i) => (
                <span key={b.start}>
                  {i ? ", " : ""}
                  <button type="button" className="min-h-8 font-bold text-teal-dark underline" onClick={() => setStart(b.start)}>
                    {b.name} ({b.start})
                  </button>
                </span>
              ))}
            </p>
          )}
          <p className="mt-2 text-sm text-muted">Amounts in pounds. Income as income, costs as spending, as on the profit and loss.</p>
          <Scroll label="Budget grid">
            <table className="mt-2 w-max min-w-full text-left text-[14px]">
              <caption className="sr-only">Monthly budget by account</caption>
              <thead>
                <tr className="border-b border-border">
                  <th scope="col" className={`${th} sticky left-0 bg-white`}>Account</th>
                  {months.map((m) => <th key={m} scope="col" className={`${th} text-right`}>{m}</th>)}
                </tr>
              </thead>
              <tbody>
                {(data?.accounts ?? []).map((a) => (
                  <tr key={a.code} className="border-b border-border last:border-0">
                    <th scope="row" className={`${td} sticky left-0 max-w-[12rem] bg-white font-normal`}>{a.label}</th>
                    {months.map((m, i) => (
                      <td key={m} className="py-1 pr-1">
                        <input inputMode="decimal" aria-label={`${a.label}, ${m}`} className="h-10 w-24 rounded-lg border border-border px-2 text-right text-[14px]"
                          value={grid[a.label]?.[i] ?? ""} onChange={(e) => set(a.label, i, e.target.value)} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroll>
          {bad.length > 0 && <p role="alert" className="mt-2 text-sm font-semibold text-warn-ink">Not an amount: {bad.slice(0, 3).join(", ")}</p>}
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" className={button} disabled={busy !== null || bad.length > 0} onClick={save}>Save budget</button>
            {saved && <button type="button" className={quiet} onClick={() => void show("summary")}>Budget summary</button>}
          </div>
        </section>

        {saved && (
          <section aria-labelledby="variance" className={card}>
            <h2 id="variance" className="text-[17px] font-extrabold">Budget variance</h2>
            <form className="mt-3 flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); void show("variance"); }}>
              <Field label="Up to and including">
                <select className={input} value={through} onChange={(e) => setThrough(e.target.value)}>
                  <option value="">All twelve months</option>
                  {months.map((m, i) => <option key={m} value={monthKey(start, i)}>{m}</option>)}
                </select>
              </Field>
              <button type="submit" className={button}>Compare with actual</button>
            </form>
            {variance && (
              <>
                <p className="mt-2 text-sm text-muted">{ukDay(variance.period_start)} – {ukDay(variance.period_end)} · {variance.basis}</p>
                <Scroll label="Budget variance table">
                  <table className="mt-2 w-full min-w-[36rem] text-left text-[14px]">
                    <caption className="sr-only">Actual against budget</caption>
                    <thead>
                      <tr className="border-b border-border">
                        <th scope="col" className={th}>Account</th>
                        <th scope="col" className={`${th} text-right`}>Budget</th>
                        <th scope="col" className={`${th} text-right`}>Actual</th>
                        <th scope="col" className={`${th} text-right`}>Variance</th>
                        <th scope="col" className={`${th} text-right`}>%</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...variance.rows, ...(["sales", "cost_of_sales", "overheads", "net_profit"] as const).map((k) => ({ ...variance.totals[k], account: `Total ${SECTION_LABEL[k].toLowerCase()}` }))].map((r) => (
                        <tr key={r.account} className={`border-b border-border ${r.account.startsWith("Total") ? "font-extrabold" : ""}`}>
                          <th scope="row" className={`${td} font-[inherit]`}>{r.account}</th>
                          <td className={`${td} text-right tabular-nums`}>{money(r.budget_pence)}</td>
                          <td className={`${td} text-right tabular-nums`}>{money(r.actual_pence)}</td>
                          <td className={`${td} text-right tabular-nums ${r.favourable === false ? "text-warn-ink" : r.favourable ? "text-teal-dark" : ""}`}>
                            {money(r.variance_pence)}
                            <span className="sr-only">{r.favourable === null ? "" : r.favourable ? " favourable" : " adverse"}</span>
                            <span aria-hidden="true">{r.favourable === null ? "" : r.favourable ? " F" : " A"}</span>
                          </td>
                          <td className={`${td} text-right tabular-nums`}>{r.variance_percent === null ? "—" : `${r.variance_percent > 0 ? "+" : ""}${r.variance_percent.toFixed(1)}%`}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Scroll>
                <p className="mt-1 text-[13px] text-muted">F favourable, A adverse: income above budget or costs below it is favourable.</p>
              </>
            )}
          </section>
        )}

        {summary && (
          <section aria-labelledby="budget-summary" className={card}>
            <h2 id="budget-summary" className="text-[17px] font-extrabold">Budget summary · {summary.name}</h2>
            <Scroll label="Budget summary table">
              <table className="mt-2 w-max min-w-full text-left text-[14px]">
                <caption className="sr-only">Budget by month</caption>
                <thead>
                  <tr className="border-b border-border">
                    <th scope="col" className={th}>Account</th>
                    {summary.months.map((m) => <th key={m} scope="col" className={`${th} text-right`}>{m}</th>)}
                    <th scope="col" className={`${th} text-right`}>Total</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.rows.map((r) => (
                    <tr key={r.account} className="border-b border-border">
                      <th scope="row" className={`${td} font-normal`}>{r.account}</th>
                      {r.months.map((v, i) => <td key={i} className={`${td} text-right tabular-nums`}>{money(v)}</td>)}
                      <td className={`${td} text-right tabular-nums`}>{money(r.total_pence)}</td>
                    </tr>
                  ))}
                  <tr className="font-extrabold">
                    <th scope="row" className={td}>Net profit</th>
                    {summary.net_profit.map((v, i) => <td key={i} className={`${td} text-right tabular-nums`}>{money(v)}</td>)}
                    <td className={`${td} text-right tabular-nums`}>{money(summary.net_profit_total_pence)}</td>
                  </tr>
                </tbody>
              </table>
            </Scroll>
          </section>
        )}
      </div>
    </Gate>
  );
}
