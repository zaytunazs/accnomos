"use client";

import { useState } from "react";
import { accounting, money, ukDay } from "@/lib/accounting";
import { Gate, Notes, Scroll, card, quiet, td, th, useLoad } from "./Shared";

export default function CashFlow() {
  const { account, data, error, note, busy, act } = useLoad(accounting.cashflow);
  const [line, setLine] = useState<{ line: string | null; reason: string | null } | null>(null);

  return (
    <Gate account={account} ready={!!data || !!error} what="to see the next 90 days of cash: your bank balance plus open invoices and bills by due date.">
      <div className="flex min-w-0 flex-col gap-5">
        <Notes note={note} error={error} />
        {data && (
          <>
            <section aria-labelledby="cash-now" className={card}>
              <h2 id="cash-now" className="text-[17px] font-extrabold">Bank today · {ukDay(data.as_of)}</h2>
              <p className="mt-1 text-3xl font-extrabold tabular-nums">{money(data.opening_balance_pence)}</p>
              <p className="mt-1 text-sm text-muted">The ledger balance of {data.bank_accounts.join(" and ")}, worked out by code.</p>
              <ul className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
                {data.points.map((p) => (
                  <li key={p.days} className="rounded-xl border border-border p-3">
                    <p className="text-[13px] font-bold text-muted">In {p.days} days · {ukDay(p.date)}</p>
                    <p className={`text-xl font-extrabold tabular-nums ${p.balance_pence < 0 ? "text-warn-ink" : ""}`}>{money(p.balance_pence)}</p>
                    <p className="text-[13px] text-muted">+{money(p.money_in_pence)} in, −{money(p.money_out_pence)} out</p>
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-sm">
                Lowest point: <strong className="tabular-nums">{money(data.lowest_balance_pence)}</strong> on {ukDay(data.lowest_on)}.
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <button type="button" className={quiet} disabled={busy !== null}
                  onClick={() => void act("line", accounting.cashflowLine, (r) => { setLine(r); return null; })}>
                  Say it in a sentence
                </button>
                {line?.line && <p className="text-[15px]" aria-live="polite">{line.line} <span className="text-[12px] text-muted">(written by your AI, every figure checked by code)</span></p>}
                {line && !line.line && <p className="text-sm text-muted" aria-live="polite">{line.reason}</p>}
              </div>
            </section>

            <section aria-labelledby="cash-buckets" className={card}>
              <h2 id="cash-buckets" className="text-[17px] font-extrabold">By due date</h2>
              <Scroll label="Cash flow by period">
                <table className="mt-2 w-full min-w-[30rem] text-left text-[15px]">
                  <caption className="sr-only">Money in and out by period</caption>
                  <thead>
                    <tr className="border-b border-border">
                      <th scope="col" className={th}>Period</th>
                      <th scope="col" className={`${th} text-right`}>Money in</th>
                      <th scope="col" className={`${th} text-right`}>Money out</th>
                      <th scope="col" className={`${th} text-right`}>Net</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.buckets.map((b) => (
                      <tr key={b.label} className="border-b border-border last:border-0">
                        <th scope="row" className={`${td} font-normal`}>
                          {b.label}
                          <span className="block text-[12px] text-muted">{b.start ? `${ukDay(b.start)} – ${ukDay(b.end)}` : `due before ${ukDay(data.as_of)}, counted as due now`}</span>
                        </th>
                        <td className={`${td} text-right tabular-nums`}>{money(b.money_in_pence)}</td>
                        <td className={`${td} text-right tabular-nums`}>{money(b.money_out_pence)}</td>
                        <td className={`${td} text-right tabular-nums`}>{money(b.net_pence)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Scroll>
              {(data.later_in_pence > 0 || data.later_out_pence > 0) && (
                <p className="mt-2 text-sm text-muted">Due after 90 days, not shown: {money(data.later_in_pence)} in, {money(data.later_out_pence)} out.</p>
              )}
              <p role="note" className="mt-2 rounded-xl border border-border bg-ground px-3 py-2 text-sm">{data.not_included}</p>
            </section>

            <section aria-labelledby="cash-items" className={card}>
              <h2 id="cash-items" className="text-[17px] font-extrabold">Invoices and bills in the forecast</h2>
              {data.items.length === 0 ? (
                <p className="mt-2 text-muted">No open invoices or bills.</p>
              ) : (
                <Scroll label="Open invoices and bills">
                  <table className="mt-2 w-full min-w-[30rem] text-left text-[14px]">
                    <caption className="sr-only">Open invoices and bills by due date</caption>
                    <thead>
                      <tr className="border-b border-border">
                        <th scope="col" className={th}>Due</th>
                        <th scope="col" className={th}>Contact</th>
                        <th scope="col" className={th}>Reference</th>
                        <th scope="col" className={`${th} text-right`}>In</th>
                        <th scope="col" className={`${th} text-right`}>Out</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.items.map((i) => (
                        <tr key={`${i.direction}${i.event_id}`} className="border-b border-border last:border-0">
                          <td className={td}>{ukDay(i.due_date)}{i.overdue && <span className="ml-1 text-[12px] font-bold text-warn-ink">overdue</span>}</td>
                          <td className={td}>{i.contact}</td>
                          <td className={td}>{i.reference ?? "—"}</td>
                          <td className={`${td} text-right tabular-nums`}>{i.direction === "in" ? money(i.amount_pence) : ""}</td>
                          <td className={`${td} text-right tabular-nums`}>{i.direction === "out" ? money(i.amount_pence) : ""}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Scroll>
              )}
            </section>
          </>
        )}
      </div>
    </Gate>
  );
}
