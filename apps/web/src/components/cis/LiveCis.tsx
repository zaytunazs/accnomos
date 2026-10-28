"use client";

import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import Link from "next/link";
import type { AccountInfo } from "@azure/msal-browser";
import SignInCta from "@/components/SignInCta";
import { LoadingSkeleton, RuntimeErrorNote, SamplePill, parseRuntimeError } from "@/components/States";
import { fieldInput, fieldLabel, primaryButton, secondaryButton } from "@/components/invoices/Modal";
import { money, parsePounds, todayIso, useMsAccount } from "@/lib/invoices";
import {
  runtime,
  ukDate,
  type RtCisBillIn,
  type RtCisCheck,
  type RtCisEntity,
  type RtCisOverview,
  type RtCisPayment,
  type RtCisReading,
  type RtCisReturn,
  type RtCisSettings,
  type RtCisStatementView,
  type RtCisStatus,
  type RtCisYear,
  type RtReverseChargeGuide,
  type RtSubcontractor,
} from "@/lib/runtime";

const card = "rounded-2xl border border-border bg-white p-5 sm:p-6";
const th = "px-3 py-2 text-left text-[13px] font-bold text-muted";
const td = "px-3 py-2 text-[15px]";
const STATUS: Record<RtCisStatus, string> = {
  net: "Registered: net payment status (20%)",
  unverified: "Not registered or not verified (30%)",
  gross: "Gross payment status (0%)",
};
const ENTITY: Record<RtCisEntity, string> = { sole_trader: "Sole trader", partnership: "Partnership", company: "Limited company" };
const why = (e: unknown) => parseRuntimeError((e as Error).message).detail || "Something went wrong; try again.";

/** A table that may scroll sideways on a phone: focusable and named, so the keyboard can scroll it too. */
function Scroll({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div role="region" aria-label={label} tabIndex={0} className="mt-3 overflow-x-auto">
      {children}
    </div>
  );
}

function Checks({ checks }: { checks: RtCisCheck[] }) {
  return (
    <ul className="mt-1 space-y-0.5 text-[13px]">
      {checks.map((c) => (
        <li key={c.code} className={c.ok ? "text-muted" : "font-semibold text-warn-ink"}>
          {c.ok ? "✓ " : "! "}
          {c.message}
        </li>
      ))}
    </ul>
  );
}

function Status({ text }: { text: string | null }) {
  return (
    <p role="status" className="mt-2 text-[13px] text-muted">
      {text}
    </p>
  );
}

// --------------------------------------------------------------------------- settings and deadlines

function SettingsCard({ account, overview, onSaved }: { account: AccountInfo; overview: RtCisOverview; onSaved: () => void }) {
  const [s, setS] = useState<RtCisSettings>(overview.settings);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const set = (patch: Partial<RtCisSettings>) => setS((x) => ({ ...x, ...patch }));

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setNote(null);
    try {
      await runtime.cis.saveSettings(account, { ...s, utr: s.utr || null, contractor_utr: s.contractor_utr || null, accounts_office_ref: s.accounts_office_ref || null, employer_ref: s.employer_ref || null });
      setNote("Saved in your OneDrive (_System/CIS/settings.json).");
      onSaved();
    } catch (err) {
      setNote(`Not saved: ${why(err)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="cis-settings" className={card}>
      <h2 id="cis-settings" className="text-lg font-extrabold">Your CIS registration</h2>
      <form onSubmit={save} className="mt-3 space-y-4">
        <fieldset className="space-y-3">
          <legend className="text-[15px] font-bold">Working for contractors</legend>
          <label className="flex items-center gap-2 text-[15px]">
            <input type="checkbox" checked={s.subcontractor} onChange={(e) => set({ subcontractor: e.target.checked })} />
            We work for contractors under CIS (subcontractor)
          </label>
          {s.subcontractor && (
            <div className="grid gap-3 sm:grid-cols-3">
              <div>
                <label className={fieldLabel} htmlFor="cis-status">Payment status (as HMRC told your contractors)</label>
                <select id="cis-status" className={fieldInput} value={s.status} onChange={(e) => set({ status: e.target.value as RtCisStatus })}>
                  {(Object.keys(STATUS) as RtCisStatus[]).map((k) => <option key={k} value={k}>{STATUS[k]}</option>)}
                </select>
              </div>
              <div>
                <label className={fieldLabel} htmlFor="cis-utr">Your UTR (10 digits)</label>
                <input id="cis-utr" inputMode="numeric" className={fieldInput} value={s.utr ?? ""} onChange={(e) => set({ utr: e.target.value })} />
              </div>
              <div>
                <label className={fieldLabel} htmlFor="cis-entity">Business</label>
                <select id="cis-entity" className={fieldInput} value={s.entity} onChange={(e) => set({ entity: e.target.value as RtCisEntity })}>
                  {(Object.keys(ENTITY) as RtCisEntity[]).map((k) => <option key={k} value={k}>{ENTITY[k]}</option>)}
                </select>
              </div>
            </div>
          )}
        </fieldset>
        <fieldset className="space-y-3">
          <legend className="text-[15px] font-bold">Paying subcontractors</legend>
          <label className="flex items-center gap-2 text-[15px]">
            <input type="checkbox" checked={s.contractor} onChange={(e) => set({ contractor: e.target.checked })} />
            We pay subcontractors and file monthly returns (contractor)
          </label>
          {s.contractor && (
            <div className="grid gap-3 sm:grid-cols-3">
              <div>
                <label className={fieldLabel} htmlFor="cis-cutr">Contractor UTR</label>
                <input id="cis-cutr" inputMode="numeric" className={fieldInput} value={s.contractor_utr ?? ""} onChange={(e) => set({ contractor_utr: e.target.value })} />
              </div>
              <div>
                <label className={fieldLabel} htmlFor="cis-ao">Accounts Office reference</label>
                <input id="cis-ao" className={fieldInput} placeholder="123PA00045678" value={s.accounts_office_ref ?? ""} onChange={(e) => set({ accounts_office_ref: e.target.value })} />
              </div>
              <div>
                <label className={fieldLabel} htmlFor="cis-paye">Employer (PAYE) reference</label>
                <input id="cis-paye" className={fieldInput} placeholder="123/AB45678" value={s.employer_ref ?? ""} onChange={(e) => set({ employer_ref: e.target.value })} />
              </div>
            </div>
          )}
        </fieldset>
        <label className="flex items-center gap-2 text-[15px]">
          <input type="checkbox" checked={s.reverse_charge_default} onChange={(e) => set({ reverse_charge_default: e.target.checked })} />
          Start new invoices under the VAT reverse charge (only for VAT- and CIS-registered customers)
        </label>
        <button type="submit" disabled={busy} className={primaryButton}>{busy ? "Saving…" : "Save CIS settings"}</button>
        <Status text={note} />
      </form>
    </section>
  );
}

function Deadlines({ overview }: { overview: RtCisOverview }) {
  const last = overview.last_tax_month;
  const now = overview.tax_month;
  return (
    <section aria-labelledby="cis-deadlines" className={card}>
      <h2 id="cis-deadlines" className="text-lg font-extrabold">Tax months and deadlines</h2>
      <p className="mt-1 text-[15px]">
        Tax month now: <strong>{ukDate(now.tax_month_start)} – {ukDate(now.tax_month_end)}</strong> · tax year {overview.tax_year}
      </p>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-[15px]">
        <li>Statements and the monthly return for the month to {ukDate(last.tax_month_end)}: by <strong>{ukDate(last.return_due)}</strong></li>
        <li>Deductions paid to HMRC by <strong>{ukDate(last.payment_due)}</strong> (the 19th by post)</li>
      </ul>
      <p className="mt-2 text-[13px] text-muted">
        {overview.not_submitted} Rules from{" "}
        <a href={overview.source_url} target="_blank" rel="noreferrer" className="font-bold text-teal-dark underline underline-offset-2">GOV.UK</a>, checked {overview.checked}.
      </p>
    </section>
  );
}

// --------------------------------------------------------------------------- subcontractor side

const blankStatement = { contractor_name: "", tax_month_end: "", gross: "", materials: "0", deduction: "" };

function Statements({ account, rate, refreshKey, onChange }: { account: AccountInfo; rate: number; refreshKey: number; onChange: () => void }) {
  const [views, setViews] = useState<RtCisStatementView[] | null>(null);
  const [f, setF] = useState(blankStatement);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let stale = false;
    runtime.cis.statements(account).then((v) => !stale && setViews(v), (e) => !stale && setNote(why(e)));
    return () => {
      stale = true;
    };
  }, [account, refreshKey]);

  const gross = parsePounds(f.gross);
  const materials = parsePounds(f.materials || "0");
  const expected = gross !== null && materials !== null ? Math.floor(Math.max(0, gross - materials) * rate / 100) : null;

  async function add(e: FormEvent) {
    e.preventDefault();
    const deduction = parsePounds(f.deduction);
    if (!f.contractor_name.trim() || !f.tax_month_end || gross === null || materials === null || deduction === null) {
      return setNote("Fill in the contractor, the tax month end (a 5th), and the amounts in pounds and pence.");
    }
    setBusy(true);
    setNote(null);
    try {
      await runtime.cis.addStatement(account, {
        contractor_name: f.contractor_name.trim(), tax_month_end: f.tax_month_end, gross_pence: gross, materials_pence: materials, deduction_pence: deduction,
      });
      setF(blankStatement);
      setNote("Statement added.");
      onChange();
    } catch (err) {
      setNote(`Not added: ${why(err)}`);
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    try {
      await runtime.cis.removeStatement(account, id);
      onChange();
    } catch (err) {
      setNote(why(err));
    }
  }

  return (
    <section aria-labelledby="cis-statements" className={card}>
      <h2 id="cis-statements" className="text-lg font-extrabold">Statements from contractors</h2>
      <p className="mt-1 text-[13px] text-muted">
        Each month a contractor who deducted CIS must give you a payment and deduction statement. They are your evidence for the year totals;
        record the money itself on the invoice with <em>Record payment</em> and the CIS deduction, so the invoice shows paid in full.
      </p>
      {views === null ? (
        <LoadingSkeleton lines={2} label="Loading statements…" />
      ) : views.length === 0 ? (
        <p className="mt-3 text-sm font-semibold text-muted">No statements yet.</p>
      ) : (
        <Scroll label="Statements from contractors">
          <table className="w-full min-w-[720px] border-collapse tabular-nums">
            <thead className="border-b border-border">
              <tr>
                <th scope="col" className={th}>Contractor</th>
                <th scope="col" className={th}>Month to</th>
                <th scope="col" className={`${th} text-right`}>Gross</th>
                <th scope="col" className={`${th} text-right`}>Materials</th>
                <th scope="col" className={`${th} text-right`}>Deducted</th>
                <th scope="col" className={`${th} text-right`}>In your books</th>
                <th scope="col" className={th}><span className="sr-only">Remove</span></th>
              </tr>
            </thead>
            <tbody>
              {views.map((v) => (
                <tr key={v.statement.id} className="border-b border-border align-top">
                  <th scope="row" className={`${td} text-left font-semibold`}>
                    {v.statement.contractor_name}
                    <Checks checks={v.checks} />
                  </th>
                  <td className={td}>{ukDate(v.statement.tax_month_end)}</td>
                  <td className={`${td} text-right`}>{money(v.statement.gross_pence)}</td>
                  <td className={`${td} text-right`}>{money(v.statement.materials_pence)}</td>
                  <td className={`${td} text-right font-bold`}>{money(v.statement.deduction_pence)}</td>
                  <td className={`${td} text-right ${v.difference_pence ? "font-semibold text-warn-ink" : ""}`}>
                    {money(v.recorded_pence)}
                    {v.difference_pence !== 0 && <span className="block text-[12px]">{money(v.difference_pence)} not recorded on a payment</span>}
                  </td>
                  <td className={td}>
                    <button type="button" onClick={() => void remove(v.statement.id)} className="text-[13px] font-bold text-muted hover:underline">
                      Remove<span className="sr-only"> {v.statement.contractor_name} {ukDate(v.statement.tax_month_end)}</span>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Scroll>
      )}
      <form onSubmit={add} className="mt-4 rounded-xl bg-ground p-4">
        <h3 className="text-[15px] font-extrabold">Type in a statement</h3>
        <div className="mt-2 grid gap-3 sm:grid-cols-5">
          <div className="sm:col-span-2">
            <label className={fieldLabel} htmlFor="st-contractor">Contractor</label>
            <input id="st-contractor" className={fieldInput} value={f.contractor_name} onChange={(e) => setF({ ...f, contractor_name: e.target.value })} />
          </div>
          <div>
            <label className={fieldLabel} htmlFor="st-month">Tax month ending (the 5th)</label>
            <input id="st-month" type="date" className={fieldInput} value={f.tax_month_end} onChange={(e) => setF({ ...f, tax_month_end: e.target.value })} />
          </div>
          <div>
            <label className={fieldLabel} htmlFor="st-gross">Gross paid, ex VAT (£)</label>
            <input id="st-gross" inputMode="decimal" className={fieldInput} value={f.gross} onChange={(e) => setF({ ...f, gross: e.target.value })} />
          </div>
          <div>
            <label className={fieldLabel} htmlFor="st-materials">Materials (£)</label>
            <input id="st-materials" inputMode="decimal" className={fieldInput} value={f.materials} onChange={(e) => setF({ ...f, materials: e.target.value })} />
          </div>
          <div>
            <label className={fieldLabel} htmlFor="st-deduction">Amount deducted (£)</label>
            <input id="st-deduction" inputMode="decimal" className={fieldInput} value={f.deduction} onChange={(e) => setF({ ...f, deduction: e.target.value })} />
          </div>
        </div>
        {expected !== null && <p className="mt-2 text-[13px] text-muted">At your {rate}% rate the deduction would be {money(expected)}.</p>}
        <button type="submit" disabled={busy} className={`${secondaryButton} mt-3`}>{busy ? "Adding…" : "Add statement"}</button>
        <Status text={note} />
      </form>
    </section>
  );
}

function Readings({ account, refreshKey, onChange }: { account: AccountInfo; refreshKey: number; onChange: () => void }) {
  const [list, setList] = useState<RtCisReading[]>([]);
  const [name, setName] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let stale = false;
    runtime.cis.readings(account, "pending").then((r) => !stale && setList(r), () => !stale && setList([]));
    return () => {
      stale = true;
    };
  }, [account, refreshKey]);

  async function read(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return setNote("Type the file's name as it is in 00 Inbox.");
    setBusy(true);
    setNote("Your AI is reading it…");
    try {
      await runtime.cis.read(account, name.trim());
      setName("");
      setNote("Read. Check the figures below, then approve or reject.");
      onChange();
    } catch (err) {
      setNote(why(err));
    } finally {
      setBusy(false);
    }
  }

  async function decide(r: RtCisReading, approve: boolean) {
    try {
      if (approve) await runtime.cis.approveReading(account, r.id);
      else await runtime.cis.rejectReading(account, r.id);
      setNote(approve ? "Approved." : "Rejected; nothing was kept.");
      onChange();
    } catch (err) {
      setNote(why(err));
    }
  }

  return (
    <section aria-labelledby="cis-readings" className={card}>
      <h2 id="cis-readings" className="text-lg font-extrabold">Read a statement or a reverse-charge bill</h2>
      <p className="mt-1 text-[13px] text-muted">
        Put the document in 00 Inbox (upload it, or let Outlook intake copy it). Your AI reads the figures; code checks them; nothing is kept
        until you approve.
      </p>
      <form onSubmit={read} className="mt-3 flex flex-wrap items-end gap-3">
        <div className="min-w-0 flex-1">
          <label className={fieldLabel} htmlFor="cis-file">File name in 00 Inbox</label>
          <input id="cis-file" className={fieldInput} placeholder="northgate-statement-nov.pdf" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <button type="submit" disabled={busy} className={secondaryButton}>{busy ? "Reading…" : "Read with your AI"}</button>
      </form>
      <Status text={note} />
      {list.length > 0 && (
        <ul className="mt-3 space-y-3" aria-label="Waiting for you">
          {list.map((r) => (
            <li key={r.id} className="rounded-xl border border-border p-3">
              <p className="text-[15px] font-bold">
                {r.kind === "cis_statement" ? "CIS statement" : r.kind === "reverse_charge_invoice" ? "Reverse-charge bill" : "Not a CIS document"} ·{" "}
                <span className="font-normal text-muted">{r.path}</span>
              </p>
              {r.statement && (
                <p className="text-[15px]">
                  {r.statement.contractor_name}, month to {ukDate(r.statement.tax_month_end)}: gross {money(r.statement.gross_pence)}, materials{" "}
                  {money(r.statement.materials_pence)}, deducted <strong>{money(r.statement.deduction_pence)}</strong>
                </p>
              )}
              {r.bill && (
                <p className="text-[15px]">
                  {r.bill.supplier_name} {r.bill.invoice_number ?? ""}, {ukDate(r.bill.invoice_date)}: net <strong>{money(r.bill.net_pence)}</strong>, VAT you account
                  for at {r.bill.vat_rate}%
                </p>
              )}
              {r.problems.map((p) => <p key={p} className="text-[13px] font-semibold text-warn-ink">{p}</p>)}
              <Checks checks={r.checks} />
              <div className="mt-2 flex gap-3">
                {(r.statement || r.bill) && (
                  <button type="button" onClick={() => void decide(r, true)} className={primaryButton}>Approve</button>
                )}
                <button type="button" onClick={() => void decide(r, false)} className={secondaryButton}>Reject</button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function YearTotals({ account, current, refreshKey }: { account: AccountInfo; current: string; refreshKey: number }) {
  const [label, setLabel] = useState(current);
  const [year, setYear] = useState<RtCisYear | null>(null);
  const [error, setError] = useState<string | null>(null);
  const start = Number(current.slice(0, 4));
  const options = [0, 1, 2].map((n) => `${start - n}-${String((start - n + 1) % 100).padStart(2, "0")}`);

  useEffect(() => {
    let stale = false;
    runtime.cis.year(account, label).then((y) => !stale && setYear(y), (e) => !stale && setError(why(e)));
    return () => {
      stale = true;
    };
  }, [account, label, refreshKey]);

  return (
    <section aria-labelledby="cis-year" className={card}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 id="cis-year" className="text-lg font-extrabold">Year totals for your tax return</h2>
        <div>
          <label className={fieldLabel} htmlFor="cis-year-pick">Tax year</label>
          <select id="cis-year-pick" className={fieldInput} value={label} onChange={(e) => setLabel(e.target.value)}>
            {options.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </div>
      </div>
      {error && <p className="mt-2 text-sm font-semibold text-warn-ink">{error}</p>}
      {year && (
        <>
          <dl className="mt-3 grid gap-3 sm:grid-cols-3">
            <div className="rounded-xl bg-ground p-3"><dt className="text-[13px] font-bold text-muted">Gross paid to you (before deductions)</dt><dd className="text-xl font-extrabold tabular-nums">{money(year.gross_pence)}</dd></div>
            <div className="rounded-xl bg-ground p-3"><dt className="text-[13px] font-bold text-muted">CIS deducted (on statements)</dt><dd className="text-xl font-extrabold tabular-nums">{money(year.deduction_pence)}</dd></div>
            <div className="rounded-xl bg-ground p-3"><dt className="text-[13px] font-bold text-muted">CIS recorded in your books</dt><dd className="text-xl font-extrabold tabular-nums">{money(year.recorded_pence)}</dd></div>
          </dl>
          {year.difference_pence !== 0 && (
            <p className="mt-2 text-sm font-semibold text-warn-ink">
              The statements and your books differ by {money(year.difference_pence)}: record the deduction on the payment, or ask the contractor for the missing statement.
            </p>
          )}
          {year.months_missing.length > 0 && (
            <p className="mt-1 text-sm font-semibold text-warn-ink">No statement yet for the month{year.months_missing.length > 1 ? "s" : ""} to {year.months_missing.map(ukDate).join(", ")}.</p>
          )}
          <ul className="mt-3 list-disc space-y-1 pl-5 text-[15px]">
            {year.where_it_goes.map((w) => <li key={w}>{w}</li>)}
          </ul>
          {year.paid_to_subcontractors_pence > 0 && (
            <p className="mt-2 text-[15px]">
              As a contractor you paid subcontractors {money(year.paid_to_subcontractors_pence)} (SA103F box 18) and deducted {money(year.deducted_from_subcontractors_pence)}.
            </p>
          )}
        </>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------- the reverse charge

function ReverseCharge({ account, onChange }: { account: AccountInfo; onChange: () => void }) {
  const [guide, setGuide] = useState<RtReverseChargeGuide | null>(null);
  const [f, setF] = useState({ supplier: "", vrn: "", number: "", date: todayIso(), net: "", rate: "20" });
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    runtime.cis.guide(account).then(setGuide, () => setGuide(null));
  }, [account]);

  async function add(e: FormEvent) {
    e.preventDefault();
    const net = parsePounds(f.net);
    if (!f.supplier.trim() || !f.date || net === null || net <= 0) return setNote("Fill in the supplier, the date and the net amount.");
    const bill: RtCisBillIn = {
      supplier_name: f.supplier.trim(), supplier_vat_number: f.vrn.trim() || null, invoice_number: f.number.trim() || null,
      invoice_date: f.date, net_pence: net, vat_rate: f.rate === "5" ? 5 : 20,
    };
    try {
      const r = await runtime.cis.addBill(account, bill);
      setNote(`Posted: ${money(net)} owed to ${bill.supplier_name}; ${money(r.reverse_charge_vat_pence)} VAT goes in box 1 and box 4.`);
      setF({ ...f, supplier: "", vrn: "", number: "", net: "" });
      onChange();
    } catch (err) {
      setNote(`Not posted: ${why(err)}`);
    }
  }

  return (
    <section aria-labelledby="cis-rc" className={card}>
      <h2 id="cis-rc" className="text-lg font-extrabold">VAT domestic reverse charge</h2>
      {guide && (
        <div className="mt-2 grid gap-4 text-[15px] lg:grid-cols-2">
          <div>
            <h3 className="font-extrabold">It applies when</h3>
            <ul className="mt-1 list-disc space-y-1 pl-5">{guide.applies_when.map((x) => <li key={x}>{x}</li>)}</ul>
            <h3 className="mt-3 font-extrabold">It does not apply to</h3>
            <ul className="mt-1 list-disc space-y-1 pl-5">{guide.not_when.map((x) => <li key={x}>{x}</li>)}</ul>
          </div>
          <div>
            <h3 className="font-extrabold">On your VAT return</h3>
            <p className="mt-1">{guide.boxes_supplier}</p>
            <p className="mt-1">{guide.boxes_customer}</p>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-[13px] text-muted">{guide.schemes.map((x) => <li key={x}>{x}</li>)}</ul>
            <h3 className="mt-3 font-extrabold">Wording</h3>
            <p className="mt-1 text-[13px]">On your invoices: “{guide.invoice_wording}”</p>
            <p className="mt-1 text-[13px]">An end user or intermediary can tell you in writing: “{guide.end_user_wording}”</p>
            <p className="mt-2 text-[13px] text-muted">
              Sources:{" "}
              {guide.source_urls.map((u, i) => (
                <a key={u} href={u} target="_blank" rel="noreferrer" className="font-bold text-teal-dark underline underline-offset-2">
                  {i ? ", " : ""}HMRC guidance {i + 1}
                </a>
              ))}{" "}
              (checked {guide.checked}).
            </p>
          </div>
        </div>
      )}
      <p className="mt-3 text-[15px]">
        To invoice under the reverse charge, tick <em>VAT reverse charge</em> on a{" "}
        <Link href="/invoices/new" className="font-bold text-teal-dark underline underline-offset-2">new invoice</Link>.
      </p>
      <form onSubmit={add} className="mt-4 rounded-xl bg-ground p-4">
        <h3 className="text-[15px] font-extrabold">Record a reverse-charge bill from a subcontractor</h3>
        <div className="mt-2 grid gap-3 sm:grid-cols-3">
          <div>
            <label className={fieldLabel} htmlFor="rc-supplier">Supplier</label>
            <input id="rc-supplier" className={fieldInput} value={f.supplier} onChange={(e) => setF({ ...f, supplier: e.target.value })} />
          </div>
          <div>
            <label className={fieldLabel} htmlFor="rc-vrn">Their VAT number</label>
            <input id="rc-vrn" className={fieldInput} value={f.vrn} onChange={(e) => setF({ ...f, vrn: e.target.value })} />
          </div>
          <div>
            <label className={fieldLabel} htmlFor="rc-number">Invoice number</label>
            <input id="rc-number" className={fieldInput} value={f.number} onChange={(e) => setF({ ...f, number: e.target.value })} />
          </div>
          <div>
            <label className={fieldLabel} htmlFor="rc-date">Invoice date</label>
            <input id="rc-date" type="date" className={fieldInput} value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} />
          </div>
          <div>
            <label className={fieldLabel} htmlFor="rc-net">Net (£, no VAT charged)</label>
            <input id="rc-net" inputMode="decimal" className={fieldInput} value={f.net} onChange={(e) => setF({ ...f, net: e.target.value })} />
          </div>
          <div>
            <label className={fieldLabel} htmlFor="rc-rate">VAT rate you account for</label>
            <select id="rc-rate" className={fieldInput} value={f.rate} onChange={(e) => setF({ ...f, rate: e.target.value })}>
              <option value="20">20%</option>
              <option value="5">5%</option>
            </select>
          </div>
        </div>
        <button type="submit" className={`${secondaryButton} mt-3`}>Post the bill</button>
        <Status text={note} />
      </form>
    </section>
  );
}

// --------------------------------------------------------------------------- contractor side

function Contractor({ account, lastEnd, refreshKey, onChange }: { account: AccountInfo; lastEnd: string; refreshKey: number; onChange: () => void }) {
  const [subs, setSubs] = useState<RtSubcontractor[]>([]);
  const [pays, setPays] = useState<RtCisPayment[]>([]);
  const [end, setEnd] = useState(lastEnd);
  const [ret, setRet] = useState<RtCisReturn | null>(null);
  const [sub, setSub] = useState({ name: "", utr: "", status: "net" as RtCisStatus, verification: "", vat: true });
  const [pay, setPay] = useState({ subId: "", date: todayIso(), gross: "", materials: "0", vat: "reverse_charge" as RtCisPayment["vat_treatment"] });
  const [note, setNote] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    let stale = false;
    Promise.all([runtime.cis.subcontractors(account), runtime.cis.payments(account)]).then(
      ([s, p]) => {
        if (stale) return;
        setSubs(s);
        setPays(p);
      },
      (e) => !stale && setNote(why(e)),
    );
    return () => {
      stale = true;
    };
  }, [account, refreshKey]);

  useEffect(() => {
    let stale = false;
    runtime.cis.monthlyReturn(account, end).then((r) => !stale && setRet(r), (e) => !stale && setNote(why(e)));
    return () => {
      stale = true;
    };
  }, [account, end, refreshKey]);

  async function addSub(e: FormEvent) {
    e.preventDefault();
    try {
      await runtime.cis.addSubcontractor(account, {
        name: sub.name.trim(), utr: sub.utr, status: sub.status, kind: "sole_trader", vat_registered: sub.vat, verification_number: sub.verification.trim() || null,
      });
      setSub({ name: "", utr: "", status: "net", verification: "", vat: true });
      setNote("Subcontractor added.");
      onChange();
    } catch (err) {
      setNote(`Not added: ${why(err)}`);
    }
  }

  async function addPay(e: FormEvent) {
    e.preventDefault();
    const gross = parsePounds(pay.gross);
    const materials = parsePounds(pay.materials || "0");
    if (!pay.subId || gross === null || gross <= 0 || materials === null) return setNote("Pick a subcontractor and fill in the amounts.");
    try {
      const p = await runtime.cis.recordPayment(account, {
        subcontractor_id: pay.subId, date: pay.date, gross_pence: gross, materials_pence: materials, vat_treatment: pay.vat,
      });
      setNote(`Recorded: ${money(p.deduction_pence)} deducted at ${p.rate}%, ${money(p.paid_pence)} paid to ${p.subcontractor_name}.`);
      setPay({ ...pay, gross: "", materials: "0" });
      onChange();
    } catch (err) {
      setNote(`Not recorded: ${why(err)}`);
    }
  }

  async function removePay(id: string) {
    try {
      await runtime.cis.removePayment(account, id);
      onChange();
    } catch (err) {
      setNote(why(err));
    }
  }

  async function exportReturn() {
    try {
      const r = await runtime.cis.exportReturn(account, end);
      setSaved(`Saved ${r.paths[0]} (and .json) in your OneDrive. File it through HMRC's CIS online service or your CIS software.`);
    } catch (err) {
      setSaved(`Not saved: ${why(err)}`);
    }
  }

  const live = pays.filter((p) => !p.removed_at);
  return (
    <section aria-labelledby="cis-contractor" className={card}>
      <h2 id="cis-contractor" className="text-lg font-extrabold">Paying subcontractors</h2>
      <p className="mt-1 text-[13px] text-muted">
        Verify each new subcontractor with HMRC (CIS online service) first; type in the status and verification number HMRC gives you. Code
        works out each deduction from that status, on the payment less materials, never on VAT.
      </p>
      <form onSubmit={addSub} className="mt-3 rounded-xl bg-ground p-4">
        <h3 className="text-[15px] font-extrabold">Add a subcontractor</h3>
        <div className="mt-2 grid gap-3 sm:grid-cols-4">
          <div>
            <label className={fieldLabel} htmlFor="sub-name">Name (as registered with HMRC)</label>
            <input id="sub-name" className={fieldInput} value={sub.name} onChange={(e) => setSub({ ...sub, name: e.target.value })} />
          </div>
          <div>
            <label className={fieldLabel} htmlFor="sub-utr">UTR</label>
            <input id="sub-utr" inputMode="numeric" className={fieldInput} value={sub.utr} onChange={(e) => setSub({ ...sub, utr: e.target.value })} />
          </div>
          <div>
            <label className={fieldLabel} htmlFor="sub-status">Status from verification</label>
            <select id="sub-status" className={fieldInput} value={sub.status} onChange={(e) => setSub({ ...sub, status: e.target.value as RtCisStatus })}>
              {(Object.keys(STATUS) as RtCisStatus[]).map((k) => <option key={k} value={k}>{STATUS[k]}</option>)}
            </select>
          </div>
          <div>
            <label className={fieldLabel} htmlFor="sub-vn">Verification number</label>
            <input id="sub-vn" className={fieldInput} placeholder="V1234567890" value={sub.verification} onChange={(e) => setSub({ ...sub, verification: e.target.value })} />
          </div>
        </div>
        <label className="mt-2 flex items-center gap-2 text-[15px]">
          <input type="checkbox" checked={sub.vat} onChange={(e) => setSub({ ...sub, vat: e.target.checked })} />
          VAT-registered
        </label>
        <button type="submit" className={`${secondaryButton} mt-3`}>Add subcontractor</button>
      </form>

      <form onSubmit={addPay} className="mt-3 rounded-xl bg-ground p-4">
        <h3 className="text-[15px] font-extrabold">Record a payment to a subcontractor</h3>
        <div className="mt-2 grid gap-3 sm:grid-cols-5">
          <div>
            <label className={fieldLabel} htmlFor="pay-sub">Subcontractor</label>
            <select id="pay-sub" className={fieldInput} value={pay.subId} onChange={(e) => setPay({ ...pay, subId: e.target.value })}>
              <option value="">Choose…</option>
              {subs.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
          <div>
            <label className={fieldLabel} htmlFor="pay-date">Paid on</label>
            <input id="pay-date" type="date" className={fieldInput} value={pay.date} onChange={(e) => setPay({ ...pay, date: e.target.value })} />
          </div>
          <div>
            <label className={fieldLabel} htmlFor="pay-gross">Their invoice, ex VAT (£)</label>
            <input id="pay-gross" inputMode="decimal" className={fieldInput} value={pay.gross} onChange={(e) => setPay({ ...pay, gross: e.target.value })} />
          </div>
          <div>
            <label className={fieldLabel} htmlFor="pay-materials">Materials they paid for (£)</label>
            <input id="pay-materials" inputMode="decimal" className={fieldInput} value={pay.materials} onChange={(e) => setPay({ ...pay, materials: e.target.value })} />
          </div>
          <div>
            <label className={fieldLabel} htmlFor="pay-vat">VAT</label>
            <select id="pay-vat" className={fieldInput} value={pay.vat} onChange={(e) => setPay({ ...pay, vat: e.target.value as RtCisPayment["vat_treatment"] })}>
              <option value="reverse_charge">Reverse charge (you account for it)</option>
              <option value="standard">VAT charged at 20%</option>
              <option value="none">No VAT</option>
            </select>
          </div>
        </div>
        <button type="submit" className={`${secondaryButton} mt-3`}>Record payment</button>
      </form>
      <Status text={note} />

      {live.length > 0 && (
        <Scroll label="Payments to subcontractors">
          <table className="w-full min-w-[640px] border-collapse tabular-nums">
            <thead className="border-b border-border">
              <tr>
                <th scope="col" className={th}>Subcontractor</th>
                <th scope="col" className={th}>Date</th>
                <th scope="col" className={`${th} text-right`}>Gross</th>
                <th scope="col" className={`${th} text-right`}>Deducted</th>
                <th scope="col" className={`${th} text-right`}>Paid</th>
                <th scope="col" className={th}><span className="sr-only">Remove</span></th>
              </tr>
            </thead>
            <tbody>
              {live.map((p) => (
                <tr key={p.id} className="border-b border-border">
                  <th scope="row" className={`${td} text-left font-semibold`}>{p.subcontractor_name}</th>
                  <td className={td}>{ukDate(p.date)}</td>
                  <td className={`${td} text-right`}>{money(p.gross_pence)}</td>
                  <td className={`${td} text-right font-bold`}>{money(p.deduction_pence)} ({p.rate}%)</td>
                  <td className={`${td} text-right`}>{money(p.paid_pence)}</td>
                  <td className={td}>
                    <button type="button" onClick={() => void removePay(p.id)} className="text-[13px] font-bold text-muted hover:underline">
                      Remove<span className="sr-only"> payment to {p.subcontractor_name} on {ukDate(p.date)}</span>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Scroll>
      )}

      <div className="mt-5 border-t border-border pt-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h3 className="text-[17px] font-extrabold">Monthly return (CIS300)</h3>
          <div>
            <label className={fieldLabel} htmlFor="ret-end">Tax month ending</label>
            <input id="ret-end" type="date" className={fieldInput} value={end} onChange={(e) => e.target.value && setEnd(e.target.value)} />
          </div>
        </div>
        {ret && (
          <>
            {ret.sample && <p className="mt-2 text-sm font-bold text-warn-ink">SAMPLE — FICTIONAL COMPANY · these are the demo books</p>}
            <p className="mt-2 text-[15px]">
              {ukDate(ret.tax_month_start)} – {ukDate(ret.tax_month_end)} · due <strong>{ukDate(ret.return_due)}</strong> · deductions of{" "}
              <strong>{money(ret.total_deductions_pence)}</strong> payable by {ukDate(ret.payment_due)}
              {ret.nil_return ? " · nil return (no payments this month)" : ""}
            </p>
            {ret.problems.map((p) => <p key={p} className="text-[13px] font-semibold text-warn-ink">{p}</p>)}
            {ret.lines.length > 0 && (
              <Scroll label="Monthly return lines">
                <table className="w-full min-w-[640px] border-collapse tabular-nums">
                  <thead className="border-b border-border">
                    <tr>
                      <th scope="col" className={th}>Subcontractor</th>
                      <th scope="col" className={th}>UTR</th>
                      <th scope="col" className={th}>Verification no.</th>
                      <th scope="col" className={`${th} text-right`}>Total payments</th>
                      <th scope="col" className={`${th} text-right`}>Materials</th>
                      <th scope="col" className={`${th} text-right`}>Deducted</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ret.lines.map((l) => (
                      <tr key={l.utr} className="border-b border-border">
                        <th scope="row" className={`${td} text-left font-semibold`}>{l.subcontractor_name}</th>
                        <td className={td}>{l.utr}</td>
                        <td className={td}>{l.verification_number ?? "—"}</td>
                        <td className={`${td} text-right`}>{money(l.total_payments_pence)}</td>
                        <td className={`${td} text-right`}>{money(l.materials_pence)}</td>
                        <td className={`${td} text-right font-bold`}>{money(l.deduction_pence)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Scroll>
            )}
            <p className="mt-2 text-[13px] text-muted">{ret.declaration}</p>
            <p className="mt-1 text-[13px] font-semibold">{ret.not_submitted}</p>
            <button type="button" onClick={() => void exportReturn()} className={`${primaryButton} mt-3`}>Save CIS300 to OneDrive</button>
            <Status text={saved} />
          </>
        )}
      </div>
    </section>
  );
}

// --------------------------------------------------------------------------- the page

function SignedOut() {
  return (
    <div className="flex flex-col gap-6">
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] font-medium text-muted">
        <SamplePill />
        <span>What the CIS page does, with fictional figures.</span>
        <SignInCta />
      </p>
      <section aria-labelledby="cis-sample" className={card}>
        <h2 id="cis-sample" className="text-lg font-extrabold">A CIS invoice, worked out by code</h2>
        <p className="mt-1 text-sm font-bold text-warn-ink">SAMPLE — FICTIONAL COMPANY</p>
        <dl className="mt-3 grid max-w-md grid-cols-[1fr_auto] gap-x-6 gap-y-1 text-[15px] tabular-nums">
          <dt>Labour</dt><dd className="text-right">£1,000.00</dd>
          <dt>Materials (no deduction)</dt><dd className="text-right">£200.00</dd>
          <dt>VAT 20%</dt><dd className="text-right">£240.00</dd>
          <dt className="font-bold">Invoice total</dt><dd className="text-right font-bold">£1,440.00</dd>
          <dt>Less CIS deduction 20% of labour</dt><dd className="text-right">−£200.00</dd>
          <dt className="font-extrabold">Payable after CIS</dt><dd className="text-right font-extrabold">£1,240.00</dd>
        </dl>
        <p className="mt-3 text-[15px]">
          When £1,240.00 arrives, recording it with a £200.00 CIS deduction pays the invoice in full and puts £200.00 into CIS suffered: tax
          already paid towards your bill, claimed in box 38 (SA103S) or box 81 (SA103F), or on a company&apos;s EPS.
        </p>
      </section>
    </div>
  );
}

/** /cis: CIS for subcontractors and contractors, and the VAT reverse charge. Live when signed in. */
export default function LiveCis() {
  const { account, ready } = useMsAccount();
  const [overview, setOverview] = useState<RtCisOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);

  useEffect(() => {
    if (!account) return;
    let stale = false;
    runtime.cis.overview(account).then((o) => !stale && setOverview(o), (e: Error) => !stale && setError(e.message));
    return () => {
      stale = true;
    };
  }, [account, refreshKey]);

  if (!ready) return <LoadingSkeleton lines={4} label="Loading CIS…" />;
  if (!account) return <SignedOut />;
  if (error) return <RuntimeErrorNote message={error} title="Couldn't load CIS" onRetry={() => { setError(null); refresh(); }} />;
  if (!overview) return <LoadingSkeleton lines={4} label="Loading CIS…" />;
  const s = overview.settings;
  return (
    <div className="flex flex-col gap-6">
      <SettingsCard key={JSON.stringify(s)} account={account} overview={overview} onSaved={refresh} />
      <Deadlines overview={overview} />
      {s.subcontractor && (
        <>
          <Readings account={account} refreshKey={refreshKey} onChange={refresh} />
          <Statements account={account} rate={overview.rate} refreshKey={refreshKey} onChange={refresh} />
          <YearTotals account={account} current={overview.tax_year} refreshKey={refreshKey} />
        </>
      )}
      {!s.subcontractor && s.contractor && <Readings account={account} refreshKey={refreshKey} onChange={refresh} />}
      <ReverseCharge account={account} onChange={refresh} />
      {s.contractor && <Contractor account={account} lastEnd={overview.last_tax_month.tax_month_end} refreshKey={refreshKey} onChange={refresh} />}
    </div>
  );
}
