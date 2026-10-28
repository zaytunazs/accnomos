"use client";

import Link from "next/link";
import { useState } from "react";
import { todayIso } from "@/components/jobs/useAccount";
import { accounting, money, toPence, ukDay, type AssetIn, type RtAsset, type RtSchedulePeriod } from "@/lib/accounting";
import { Field, Gate, Notes, Scroll, button, card, input, quiet, small, td, th, useLoad } from "./Shared";

const TYPE_LABEL: Record<RtAsset["asset_type"], string> = {
  plant: "Plant and machinery",
  office: "Office equipment",
  motor: "Motor vehicle",
  computer: "Computer equipment",
  other: "Other",
};
const METHOD_LABEL: Record<RtAsset["method"], string> = {
  none: "Not depreciated",
  straight_line: "Straight line",
  reducing_balance: "Reducing balance",
};

function describe(a: RtAsset) {
  if (a.method === "none") return METHOD_LABEL.none;
  const how = a.life_years ? `${a.life_years} years` : `${a.rate_percent}% a year`;
  return `${METHOD_LABEL[a.method]}, ${how}, ${a.frequency}`;
}

export default function FixedAssets() {
  const { account, data, error, note, busy, act } = useLoad(accounting.assets);
  const [form, setForm] = useState({
    name: "", type: "computer" as RtAsset["asset_type"], date: todayIso(), cost: "", residual: "",
    method: "straight_line" as RtAsset["method"], basis: "life" as "life" | "rate", life: "3", rate: "25",
    frequency: "monthly" as "monthly" | "yearly", costAccount: "", accAccount: "",
  });
  const [runTo, setRunTo] = useState(todayIso());
  const [schedule, setSchedule] = useState<{ asset: RtAsset; periods: RtSchedulePeriod[] } | null>(null);
  const [disposing, setDisposing] = useState<RtAsset | null>(null);
  const [disposal, setDisposal] = useState({ date: todayIso(), proceeds: "", vat: "" });

  function register() {
    const body: AssetIn = {
      name: form.name,
      asset_type: form.type,
      purchase_date: form.date,
      cost_pence: toPence(form.cost) ?? 0,
      residual_pence: toPence(form.residual) ?? 0,
      method: form.method,
      rate_percent: form.method === "reducing_balance" || form.basis === "rate" ? Number(form.rate) : null,
      life_years: form.method === "straight_line" && form.basis === "life" ? Number(form.life) : null,
      frequency: form.frequency,
      cost_account: form.type === "other" ? form.costAccount || null : null,
      accumulated_account: form.type === "other" ? form.accAccount || null : null,
    };
    void act("register", (a) => accounting.registerAsset(a, body), (r) => {
      setForm({ ...form, name: "", cost: "", residual: "" });
      return `${r.number} ${r.name} registered. Nothing was posted: its purchase is already in your books on ${r.cost_account}.`;
    });
  }

  return (
    <Gate account={account} ready={!!data || !!error} what="to keep a fixed asset register, run depreciation and record disposals.">
      <div className="flex min-w-0 flex-col gap-5">
        <p role="note" className="rounded-xl border border-warn-border bg-warn-bg px-4 py-3 text-[15px] font-semibold leading-6 text-warn-ink">
          {data?.note ?? "Book depreciation only. Capital allowances are worked out separately for tax."}
        </p>
        <Notes note={note} error={error} />

        <section aria-labelledby="run-dep" className={card}>
          <h2 id="run-dep" className="text-[17px] font-extrabold">Run depreciation</h2>
          <p className="mt-1 text-sm text-muted">
            Proposes one journal for every period ending by that month end. It posts only when you approve it on{" "}
            <Link className="font-bold text-teal-dark underline" href="/accounting/journals">Manual journals</Link>.
          </p>
          <form className="mt-3 flex flex-wrap items-end gap-3" onSubmit={(e) => {
            e.preventDefault();
            void act("run", (a) => accounting.runDepreciation(a, runTo), (r) => r.message);
          }}>
            <Field label="Up to the end of">
              <input type="date" required className={input} value={runTo} onChange={(e) => setRunTo(e.target.value)} />
            </Field>
            <button type="submit" className={button} disabled={busy !== null}>Run depreciation</button>
          </form>
        </section>

        <section aria-labelledby="register" className={card}>
          <h2 id="register" className="text-[17px] font-extrabold">Register</h2>
          {data && data.assets.length === 0 && <p className="mt-2 text-[15px] text-muted">No assets registered yet.</p>}
          {data && data.assets.length > 0 && (
            <Scroll label="Asset register table">
              <table className="mt-3 w-full min-w-[44rem] text-left text-[15px]">
                <caption className="sr-only">Fixed asset register</caption>
                <thead>
                  <tr className="border-b border-border">
                    <th scope="col" className={th}>Asset</th>
                    <th scope="col" className={th}>Bought</th>
                    <th scope="col" className={`${th} text-right`}>Cost</th>
                    <th scope="col" className={`${th} text-right`}>Depreciation</th>
                    <th scope="col" className={`${th} text-right`}>Book value</th>
                    <th scope="col" className={th}><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {data.assets.map((a) => (
                    <tr key={a.id} className="border-b border-border last:border-0">
                      <td className={td}>
                        <span className="font-bold">{a.number} {a.name}</span>
                        <span className="block text-[12px] text-muted">{TYPE_LABEL[a.asset_type]} · {describe(a)}</span>
                        {a.status === "disposed" && (
                          <span className="block text-[12px] font-bold text-muted">
                            Disposed {ukDay(a.state.disposed_on ?? "")}: {a.state.gain_pence! >= 0 ? "gain" : "loss"} {money(Math.abs(a.state.gain_pence ?? 0))}
                          </span>
                        )}
                        {a.state.pending_journal && <span className="block text-[12px] font-bold text-warn-ink">{a.state.pending_journal} waiting for approval</span>}
                      </td>
                      <td className={td}>{ukDay(a.purchase_date)}</td>
                      <td className={`${td} text-right tabular-nums`}>{money(a.cost_pence)}</td>
                      <td className={`${td} text-right tabular-nums`}>
                        {money(a.state.accumulated_pence)}
                        {a.state.depreciated_to && <span className="block text-[12px] text-muted">to {ukDay(a.state.depreciated_to)}</span>}
                      </td>
                      <td className={`${td} text-right tabular-nums`}>{money(a.book_value_pence)}</td>
                      <td className={`${td} whitespace-nowrap`}>
                        <div className="flex flex-col items-end gap-1">
                          <button type="button" className={small} aria-label={`Schedule for ${a.number}`}
                            onClick={() => void act(`s${a.id}`, (acc) => accounting.schedule(acc, a.id), (r) => { setSchedule(r); return null; })}>
                            Schedule
                          </button>
                          {a.status === "registered" && (
                            <button type="button" className={small} aria-label={`Dispose of ${a.number}`} onClick={() => setDisposing(a)}>Dispose</button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Scroll>
          )}
        </section>

        {disposing && (
          <section aria-labelledby="dispose" className={card}>
            <h2 id="dispose" className="text-[17px] font-extrabold">Dispose of {disposing.number} {disposing.name}</h2>
            <p className="mt-1 text-sm text-muted">
              Code adds depreciation for full periods up to the date, takes the asset out at cost, and posts the gain or loss.
              Proceeds go to 1200 Bank.
            </p>
            <form className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-4 sm:items-end" onSubmit={(e) => {
              e.preventDefault();
              void act("dispose", (a) => accounting.dispose(a, disposing.id, {
                date: disposal.date, proceeds_pence: toPence(disposal.proceeds) ?? 0, vat_pence: toPence(disposal.vat) ?? 0,
              }), (j) => {
                setDisposing(null);
                const g = j.lines.find((l) => l.account.startsWith("8010"));
                const what = g ? `${g.credit_pence ? "gain" : "loss"} of ${money(g.credit_pence || g.debit_pence)}` : "no gain or loss";
                return `${j.number} is ready for you to approve on Manual journals: ${what}.`;
              });
            }}>
              <Field label="Date"><input type="date" required className={input} value={disposal.date} onChange={(e) => setDisposal({ ...disposal, date: e.target.value })} /></Field>
              <Field label="Proceeds £ (ex VAT)"><input inputMode="decimal" className={input} value={disposal.proceeds} onChange={(e) => setDisposal({ ...disposal, proceeds: e.target.value })} /></Field>
              <Field label="VAT charged £"><input inputMode="decimal" className={input} value={disposal.vat} onChange={(e) => setDisposal({ ...disposal, vat: e.target.value })} /></Field>
              <div className="flex gap-2">
                <button type="submit" className={button} disabled={busy !== null}>Propose disposal</button>
                <button type="button" className={quiet} onClick={() => setDisposing(null)}>Cancel</button>
              </div>
            </form>
          </section>
        )}

        {schedule && (
          <section aria-labelledby="schedule" className={card}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 id="schedule" className="text-[17px] font-extrabold">Depreciation schedule · {schedule.asset.number} {schedule.asset.name}</h2>
              <button type="button" className={small} onClick={() => setSchedule(null)}>Close</button>
            </div>
            {schedule.periods.length === 0 ? (
              <p className="mt-2 text-muted">This asset is not depreciated.</p>
            ) : (
              <Scroll label="Depreciation schedule table">
                <table className="mt-3 w-full min-w-[34rem] text-left text-[14px]">
                  <caption className="sr-only">Depreciation schedule for {schedule.asset.number}</caption>
                  <thead>
                    <tr className="border-b border-border">
                      <th scope="col" className={th}>Period</th>
                      <th scope="col" className={`${th} text-right`}>Charge</th>
                      <th scope="col" className={`${th} text-right`}>Accumulated</th>
                      <th scope="col" className={`${th} text-right`}>Book value</th>
                      <th scope="col" className={th}>Posted</th>
                    </tr>
                  </thead>
                  <tbody>
                    {schedule.periods.map((p) => (
                      <tr key={p.index} className="border-b border-border last:border-0">
                        <td className={td}>{ukDay(p.start)} – {ukDay(p.end)}</td>
                        <td className={`${td} text-right tabular-nums`}>{money(p.charge_pence)}</td>
                        <td className={`${td} text-right tabular-nums`}>{money(p.accumulated_pence)}</td>
                        <td className={`${td} text-right tabular-nums`}>{money(p.book_value_pence)}</td>
                        <td className={td}>{p.posted ? "Yes" : "No"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Scroll>
            )}
          </section>
        )}

        <section aria-labelledby="add-asset" className={card}>
          <h2 id="add-asset" className="text-[17px] font-extrabold">Register an asset</h2>
          <p className="mt-1 text-sm text-muted">
            Registering posts nothing. Code the purchase to the asset&apos;s account (for example 0050 Computer equipment); if it went to an
            expense, move it with <Link className="font-bold text-teal-dark underline" href="/accounting/recode">Find and recode</Link>.
          </p>
          <form className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3" onSubmit={(e) => { e.preventDefault(); register(); }}>
            <Field label="Name"><input required maxLength={120} className={input} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label="Type">
              <select className={input} value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value as RtAsset["asset_type"] })}>
                {Object.entries(TYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </Field>
            <Field label="Purchase date"><input type="date" required className={input} value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} /></Field>
            <Field label="Cost £ (ex VAT)"><input required inputMode="decimal" className={input} value={form.cost} onChange={(e) => setForm({ ...form, cost: e.target.value })} /></Field>
            <Field label="Residual value £"><input inputMode="decimal" className={input} value={form.residual} onChange={(e) => setForm({ ...form, residual: e.target.value })} /></Field>
            <Field label="Method">
              <select className={input} value={form.method} onChange={(e) => setForm({ ...form, method: e.target.value as RtAsset["method"] })}>
                {Object.entries(METHOD_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </Field>
            {form.method === "straight_line" && (
              <Field label="Spread by">
                <select className={input} value={form.basis} onChange={(e) => setForm({ ...form, basis: e.target.value as "life" | "rate" })}>
                  <option value="life">Useful life</option>
                  <option value="rate">Rate a year</option>
                </select>
              </Field>
            )}
            {form.method === "straight_line" && form.basis === "life" && (
              <Field label="Life (years)"><input type="number" min={1} max={100} className={input} value={form.life} onChange={(e) => setForm({ ...form, life: e.target.value })} /></Field>
            )}
            {(form.method === "reducing_balance" || (form.method === "straight_line" && form.basis === "rate")) && (
              <Field label="Rate % a year"><input type="number" min={0.01} max={100} step={0.01} className={input} value={form.rate} onChange={(e) => setForm({ ...form, rate: e.target.value })} /></Field>
            )}
            {form.method !== "none" && (
              <Field label="Charge">
                <select className={input} value={form.frequency} onChange={(e) => setForm({ ...form, frequency: e.target.value as "monthly" | "yearly" })}>
                  <option value="monthly">Monthly</option>
                  <option value="yearly">Yearly</option>
                </select>
              </Field>
            )}
            {form.type === "other" && (
              <>
                <Field label="Cost account (0000–0999)"><input className={input} value={form.costAccount} onChange={(e) => setForm({ ...form, costAccount: e.target.value })} /></Field>
                <Field label="Depreciation account"><input className={input} value={form.accAccount} onChange={(e) => setForm({ ...form, accAccount: e.target.value })} /></Field>
              </>
            )}
            <div className="sm:col-span-3"><button type="submit" className={button} disabled={busy !== null}>Register asset</button></div>
          </form>
        </section>

        {data && data.reconciliation.length > 0 && (
          <section aria-labelledby="recon" className={card}>
            <h2 id="recon" className="text-[17px] font-extrabold">Register against the ledger</h2>
            <Scroll label="Asset reconciliation table">
              <table className="mt-3 w-full min-w-[32rem] text-left text-[15px]">
                <caption className="sr-only">Asset reconciliation</caption>
                <thead>
                  <tr className="border-b border-border">
                    <th scope="col" className={th}>Account</th>
                    <th scope="col" className={`${th} text-right`}>Register</th>
                    <th scope="col" className={`${th} text-right`}>Ledger</th>
                    <th scope="col" className={`${th} text-right`}>Difference</th>
                  </tr>
                </thead>
                <tbody>
                  {data.reconciliation.map((r) => (
                    <tr key={r.account} className="border-b border-border last:border-0">
                      <td className={td}>{r.account}</td>
                      <td className={`${td} text-right tabular-nums`}>{money(r.register_pence)}</td>
                      <td className={`${td} text-right tabular-nums`}>{money(r.ledger_pence)}</td>
                      <td className={`${td} text-right tabular-nums font-bold ${r.difference_pence ? "text-warn-ink" : ""}`}>{money(r.difference_pence)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Scroll>
          </section>
        )}
      </div>
    </Gate>
  );
}
