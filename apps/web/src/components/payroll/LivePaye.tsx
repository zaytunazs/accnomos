"use client";

import { useCallback, useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import SignInCta from "@/components/SignInCta";
import { errorText, todayIso, useAccount } from "@/components/jobs/useAccount";
import { LoadingSkeleton, RuntimeErrorNote, isAuthError, isServerError } from "@/components/States";
import { money } from "@/lib/invoices";
import {
  runtime,
  ukDate,
  type RtPayFrequency,
  type RtPayeEmployee,
  type RtPayeEmployer,
  type RtPayeFile,
  type RtPayeReportKey,
  type RtPayeRun,
  type RtPayeSetup,
  type RtPayeTable,
  type RtPensionProvider,
  type RtStaff,
} from "@/lib/runtime";

/** Said next to every RTI download and at the top of the page (owner's wording). */
export const FILING =
  "File with HMRC's Basic PAYE Tools or your payroll provider. Direct submission from Accnomos is currently not available.";
export const CHECK = "Estimate — check before filing";

const pounds = money; // exact pence to "£1,234.50", no floats
const toPence = (s: string): number | null => {
  const n = Number(s.trim().replace(/^£/, "").replace(/,/g, ""));
  return s.trim() !== "" && Number.isFinite(n) && n >= 0 ? Math.round(n * 100) : null;
};
const input = "h-10 rounded-xl border border-border bg-white px-3 text-[15px]";
const button = "h-10 rounded-xl bg-teal px-4 text-[15px] font-bold text-white disabled:opacity-60";
const quiet = "h-10 rounded-xl border border-border bg-white px-4 text-[14px] font-bold disabled:opacity-60";
const label = "flex flex-col gap-1 text-[13px] font-bold text-muted";
const FREQ: Record<RtPayFrequency, string> = { weekly: "Weekly", fortnightly: "Fortnightly", four_weekly: "Four-weekly", monthly: "Monthly" };
const PROVIDERS: Record<RtPensionProvider, string> = {
  generic: "Generic CSV",
  nest: "Nest",
  peoples_pension: "The People's Pension",
  smart_pension: "Smart Pension (PAPDIS)",
  now_pensions: "NOW: Pensions",
};
const REPORTS: { key: RtPayeReportKey; label: string; needs: "run" | "employee" | "none" }[] = [
  { key: "payroll_summary", label: "Payroll summary (this run)", needs: "run" },
  { key: "pension", label: "Pension workings (this run)", needs: "run" },
  { key: "fps", label: "FPS contents (this run)", needs: "run" },
  { key: "journal", label: "Payroll journal (this run)", needs: "run" },
  { key: "p32", label: "Employer payment record (P32-style)", needs: "none" },
  { key: "p11", label: "Employee payroll record (P11-style)", needs: "employee" },
  { key: "p60", label: "P60 figures", needs: "employee" },
  { key: "p45", label: "P45 figures (leavers)", needs: "employee" },
];

function save(file: RtPayeFile) {
  const bytes = Uint8Array.from(atob(file.base64), (c) => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: file.media_type }));
  const a = Object.assign(document.createElement("a"), { href: url, download: file.name });
  a.click();
  URL.revokeObjectURL(url);
}

/** The filing reminder that sits beside every RTI download. */
function FilingNote() {
  return (
    <p role="note" className="rounded-xl border border-warn-border bg-warn-bg px-3 py-2 text-[14px] font-semibold text-warn-ink">
      {FILING}
    </p>
  );
}

function Table({ t }: { t: RtPayeTable }) {
  const cell = (v: string | number | undefined, kind: string) =>
    v === undefined || v === "" ? "" : kind === "money" ? pounds(Number(v)) : String(v);
  return (
    <div className="mt-2 overflow-x-auto">
      <table className="w-full text-left text-[14px]" aria-label={t.title}>
        <caption className="pb-2 text-left text-[13px] text-muted">{t.subtitle}</caption>
        <thead>
          <tr className="border-b border-border text-[12px] font-bold text-muted">
            {t.columns.map((c) => (
              <th key={c.key} scope="col" className={`py-1.5 pr-3 ${c.kind === "money" ? "text-right" : ""}`}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {t.rows.map((r, i) => (
            <tr key={i} className="border-t border-border">
              {t.columns.map((c) => (
                <td key={c.key} className={`py-1.5 pr-3 ${c.kind === "money" ? "text-right tabular-nums" : ""}`}>{cell(r[c.key], c.kind)}</td>
              ))}
            </tr>
          ))}
          {t.totals && (
            <tr className="border-t-2 border-border font-bold">
              {t.columns.map((c, i) => (
                <td key={c.key} className={`py-1.5 pr-3 ${c.kind === "money" ? "text-right tabular-nums" : ""}`}>
                  {i === 0 ? "Total" : cell(t.totals?.[c.key], c.kind)}
                </td>
              ))}
            </tr>
          )}
        </tbody>
      </table>
      <ul className="mt-2 list-disc pl-5 text-[12px] leading-5 text-muted">
        {t.notes.map((n) => (
          <li key={n}>{n}</li>
        ))}
      </ul>
    </div>
  );
}

type Draft = {
  payroll_id: string;
  forenames: string;
  surname: string;
  nino: string;
  dob: string;
  gender: "M" | "F";
  address1: string;
  address2: string;
  postcode: string;
  start_date: string;
  starter_declaration: "" | "A" | "B" | "C";
  tax_code: string;
  week1_month1: boolean;
  ni_category: string;
  frequency: RtPayFrequency;
  pay_type: "salary" | "hourly";
  salary: string;
  rate: string;
  hours: string;
  student_loan_plan: "" | "1" | "2" | "4" | "5";
  postgrad_loan: boolean;
  director: boolean;
  pension_exempt: boolean;
  leaving_date: string;
  staff_id: string;
  ot_after: string;
  ot_mult: string;
};
const emptyDraft = (): Draft => ({
  payroll_id: "", forenames: "", surname: "", nino: "", dob: "", gender: "F", address1: "", address2: "", postcode: "",
  start_date: todayIso(), starter_declaration: "A", tax_code: "1257L", week1_month1: false, ni_category: "A",
  frequency: "monthly", pay_type: "salary", salary: "", rate: "", hours: "", student_loan_plan: "", postgrad_loan: false,
  director: false, pension_exempt: false, leaving_date: "", staff_id: "", ot_after: "", ot_mult: "1.5",
});
const draftOf = (e: RtPayeEmployee): Draft => ({
  payroll_id: e.payroll_id, forenames: e.forenames, surname: e.surname, nino: e.nino ?? "", dob: e.dob, gender: e.gender,
  address1: e.address[0] ?? "", address2: e.address[1] ?? "", postcode: e.postcode, start_date: e.start_date,
  starter_declaration: e.starter_declaration ?? "", tax_code: e.tax_code, week1_month1: e.week1_month1,
  ni_category: e.ni_category, frequency: e.frequency, pay_type: e.pay_type, salary: (e.annual_salary_pence / 100).toFixed(2),
  rate: (e.hourly_rate_pence / 100).toFixed(2), hours: String(e.usual_hours), student_loan_plan: e.student_loan_plan ?? "",
  postgrad_loan: e.postgrad_loan, director: e.director, pension_exempt: e.pension_exempt, leaving_date: e.leaving_date ?? "",
  staff_id: e.staff_id ?? "", ot_after: e.overtime_after_hours_week == null ? "" : String(e.overtime_after_hours_week),
  ot_mult: String(e.overtime_multiplier ?? 1.5),
});

export default function LivePaye() {
  const account = useAccount();
  const [setup, setSetup] = useState<RtPayeSetup | null>(null);
  const [staff, setStaff] = useState<RtStaff[]>([]);
  const [runs, setRuns] = useState<RtPayeRun[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [freq, setFreq] = useState<RtPayFrequency>("monthly");
  const [payDate, setPayDate] = useState(todayIso());
  const [employer, setEmployer] = useState<RtPayeEmployer | null>(null);
  // Open on first load while the PAYE reference is missing; after that only the user opens or closes it (binding it to
  // the reference would collapse the form as soon as one is typed).
  const [settingsOpen, setSettingsOpen] = useState<boolean | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [bonus, setBonus] = useState<Record<string, string>>({});
  const [epsMonth, setEpsMonth] = useState(7);
  const [epsEa, setEpsEa] = useState(false);
  const [epsFinal, setEpsFinal] = useState(false);
  const [fpsRows, setFpsRows] = useState<RtPayeTable | null>(null);
  const [epsRows, setEpsRows] = useState<{ item: string; value: string }[] | null>(null);
  const [reportKey, setReportKey] = useState<RtPayeReportKey>("payroll_summary");
  const [reportEmployee, setReportEmployee] = useState("");
  const [report, setReport] = useState<RtPayeTable | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fail = (e: unknown) => {
    const msg = errorText(e);
    if (isAuthError(msg) || isServerError(msg)) setError(msg);
    else setNote(msg);
  };

  const load = useCallback(async (a: AccountInfo) => {
    const [s, r, st] = await Promise.all([runtime.paye.setup(a), runtime.paye.runs(a), runtime.staff(a).catch(() => [] as RtStaff[])]);
    setSetup(s);
    setStaff(st);
    setEmployer(s.employer);
    setRuns(r.runs);
    setRunId((cur) => cur ?? r.runs[0]?.id ?? null);
  }, []);

  useEffect(() => {
    if (account) queueMicrotask(() => load(account).catch(fail));
  }, [account, load]);

  async function act<T>(key: string, fn: (a: AccountInfo) => Promise<T>, done?: string | ((r: T) => string)): Promise<T | undefined> {
    if (!account) return undefined;
    setBusy(key);
    setError(null);
    setNote(null);
    try {
      const r = await fn(account);
      if (done) setNote(typeof done === "string" ? done : done(r));
      await load(account);
      return r;
    } catch (e) {
      fail(e);
      return undefined;
    } finally {
      setBusy(null);
    }
  }

  if (account === undefined) return <LoadingSkeleton lines={3} label="Loading payroll…" />;
  if (account === null)
    return (
      <p className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl border border-border bg-white p-6 text-[15px] leading-7 text-muted">
        <SignInCta />
        <span>to run PAYE payroll: Accnomos calculates tax, NI, student loans and pensions and prepares the RTI files. {FILING}</span>
      </p>
    );

  const run = runs.find((r) => r.id === runId) ?? null;
  const employees = setup?.employees ?? [];

  function submitEmployee() {
    if (!draft) return;
    const salary = toPence(draft.salary || "0");
    const rate = toPence(draft.rate || "0");
    const body: Partial<RtPayeEmployee> = {
      payroll_id: draft.payroll_id.trim(),
      forenames: draft.forenames.trim(),
      surname: draft.surname.trim(),
      nino: draft.nino.trim() || null,
      dob: draft.dob,
      gender: draft.gender,
      address: [draft.address1, draft.address2].map((x) => x.trim()).filter(Boolean),
      postcode: draft.postcode.trim(),
      start_date: draft.start_date,
      starter_declaration: draft.starter_declaration || null,
      tax_code: draft.tax_code.trim(),
      week1_month1: draft.week1_month1,
      ni_category: draft.ni_category,
      frequency: draft.frequency,
      pay_type: draft.pay_type,
      annual_salary_pence: salary ?? 0,
      hourly_rate_pence: rate ?? 0,
      usual_hours: Number(draft.hours || "0"),
      student_loan_plan: draft.student_loan_plan || null,
      postgrad_loan: draft.postgrad_loan,
      director: draft.director,
      pension_exempt: draft.pension_exempt,
      leaving_date: draft.leaving_date || null,
      staff_id: draft.staff_id || null,
      overtime_after_hours_week: draft.ot_after.trim() ? Number(draft.ot_after) : null,
      overtime_multiplier: Number(draft.ot_mult || "1.5"),
    };
    const existing = editing ? employees.find((e) => e.id === editing) : null;
    act(
      "employee",
      (a) => (existing ? runtime.paye.editEmployee(a, existing.id, { ...existing, ...body }) : runtime.paye.addEmployee(a, body)),
      `${body.forenames} ${body.surname} saved.`,
    ).then((r) => {
      if (r) {
        setDraft(null);
        setEditing(null);
      }
    });
  }

  async function suggestCode(decl: Draft["starter_declaration"]) {
    if (!account || !draft) return;
    try {
      const s = await runtime.paye.starterCode(account, decl || "none");
      setDraft({ ...draft, starter_declaration: decl, tax_code: s.tax_code, week1_month1: s.week1_month1 });
      setNote(`Suggested tax code ${s.tax_code}${s.week1_month1 ? " (week 1/month 1)" : ""}. ${s.note}`);
    } catch (e) {
      fail(e);
    }
  }

  const set = (patch: Partial<Draft>) => draft && setDraft({ ...draft, ...patch });

  return (
    <div className="flex flex-col gap-6">
      <div role="note" aria-label="Filing" className="rounded-2xl border border-warn-border bg-warn-bg px-4 py-3 text-[15px] font-semibold leading-6 text-warn-ink">
        <p>{FILING}</p>
        <p className="mt-1 font-normal">
          {CHECK}. Accnomos calculates PAYE, NI, student loans and pensions with HMRC&apos;s {setup?.tax_year ?? "2026-27"} rates
          (checked against GOV.UK on {setup?.verified_on ?? "28 Oct 2026"}) and prepares FPS and EPS files to the 2026-27
          schema for you to check. It is not HMRC-recognised payroll software and never sends anything to HMRC.
        </p>
      </div>

      {note && (
        <p role="status" className="rounded-xl bg-teal-tint px-4 py-2 text-sm text-teal-dark">
          {note}
        </p>
      )}
      {error && <RuntimeErrorNote message={error} />}

      {/* ---------------------------------------------------------------- Settings */}
      <details
        className="rounded-2xl border border-border bg-white p-5"
        open={settingsOpen ?? (!!employer && !employer.paye_reference)}
        onToggle={(e) => employer && setSettingsOpen(e.currentTarget.open)}
      >
        <summary className="cursor-pointer text-[17px] font-extrabold">Payroll settings</summary>
        {employer && (
          <form
            aria-label="Payroll settings"
            className="mt-3 grid gap-3 sm:grid-cols-3"
            onSubmit={(e) => {
              e.preventDefault();
              act("employer", (a) => runtime.paye.saveEmployer(a, employer), "Payroll settings saved.");
            }}
          >
            <label className={label}>
              Employer name
              <input className={input} value={employer.name} onChange={(e) => setEmployer({ ...employer, name: e.target.value })} />
            </label>
            <label className={label}>
              HMRC office number
              <input className={input} inputMode="numeric" maxLength={3} value={employer.paye_office} onChange={(e) => setEmployer({ ...employer, paye_office: e.target.value })} />
            </label>
            <label className={label}>
              PAYE reference
              <input className={input} maxLength={10} value={employer.paye_reference} onChange={(e) => setEmployer({ ...employer, paye_reference: e.target.value })} />
            </label>
            <label className={label}>
              Accounts Office reference
              <input className={input} maxLength={13} value={employer.accounts_office_ref} onChange={(e) => setEmployer({ ...employer, accounts_office_ref: e.target.value })} />
            </label>
            <label className="flex items-center gap-2 text-[14px]">
              <input type="checkbox" checked={employer.claim_employment_allowance} onChange={(e) => setEmployer({ ...employer, claim_employment_allowance: e.target.checked })} />
              Claim Employment Allowance (£10,500)
            </label>
            <label className="flex items-center gap-2 text-[14px]">
              <input type="checkbox" checked={employer.small_employer_relief} onChange={(e) => setEmployer({ ...employer, small_employer_relief: e.target.checked })} />
              Small employer relief (Class 1 NI last year £45,000 or less)
            </label>
            <label className={label}>
              Pension provider
              <select className={input} value={employer.pension.provider} onChange={(e) => setEmployer({ ...employer, pension: { ...employer.pension, provider: e.target.value as RtPensionProvider } })}>
                {Object.entries(PROVIDERS).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </label>
            <label className={label}>
              Tax relief basis
              <select className={input} value={employer.pension.arrangement} onChange={(e) => setEmployer({ ...employer, pension: { ...employer.pension, arrangement: e.target.value as RtPayeEmployer["pension"]["arrangement"] } })}>
                <option value="relief_at_source">Relief at source</option>
                <option value="net_pay">Net pay arrangement</option>
                <option value="salary_sacrifice">Salary sacrifice</option>
              </select>
            </label>
            <label className={label}>
              Contributions based on
              <select className={input} value={employer.pension.basis} onChange={(e) => setEmployer({ ...employer, pension: { ...employer.pension, basis: e.target.value as "qualifying" | "full_pay" } })}>
                <option value="qualifying">Qualifying earnings</option>
                <option value="full_pay">All pay</option>
              </select>
            </label>
            <label className={label}>
              Employer contribution %
              <input className={input} inputMode="decimal" value={employer.pension.employer_bp / 100} onChange={(e) => setEmployer({ ...employer, pension: { ...employer.pension, employer_bp: Math.round(Number(e.target.value || "0") * 100) } })} />
            </label>
            <label className={label}>
              Employee contribution %
              <input className={input} inputMode="decimal" value={employer.pension.employee_bp / 100} onChange={(e) => setEmployer({ ...employer, pension: { ...employer.pension, employee_bp: Math.round(Number(e.target.value || "0") * 100) } })} />
            </label>
            <label className={label}>
              Provider reference
              <input className={input} maxLength={40} value={employer.pension.provider_ref} onChange={(e) => setEmployer({ ...employer, pension: { ...employer.pension, provider_ref: e.target.value } })} />
            </label>
            {employer.pension.provider === "nest" && (
              <label className={label}>
                Nest payment source
                <input className={input} maxLength={40} value={employer.pension.payment_source} onChange={(e) => setEmployer({ ...employer, pension: { ...employer.pension, payment_source: e.target.value } })} />
              </label>
            )}
            <div className="flex items-center gap-3 sm:col-span-3">
              <button type="submit" disabled={busy !== null} className={button}>{busy === "employer" ? "Saving…" : "Save settings"}</button>
              <label className="flex items-center gap-2 text-[14px] text-muted" title={setup?.submission.reason}>
                <input type="checkbox" checked={false} disabled aria-describedby="rti-switch-note" />
                Submit RTI to HMRC from Accnomos (not available)
              </label>
              <span id="rti-switch-note" className="text-[13px] text-muted">{setup?.submission.reason}</span>
            </div>
          </form>
        )}
      </details>

      {/* ---------------------------------------------------------------- Employees */}
      <section aria-labelledby="employees" className="rounded-2xl border border-border bg-white p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="employees" className="text-[17px] font-extrabold">Employees</h2>
          <button type="button" className={quiet} onClick={() => { setDraft(emptyDraft()); setEditing(null); }}>Add employee</button>
        </div>
        {employees.length === 0 && !draft && <p className="mt-2 text-[14px] text-muted">No employees yet.</p>}
        {employees.length > 0 && (
          <ul className="mt-2 divide-y divide-border">
            {employees.map((e) => (
              <li key={e.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-[15px]">
                <span>
                  <strong>{e.forenames} {e.surname}</strong>{" "}
                  <span className="text-muted">
                    {e.payroll_id} · {FREQ[e.frequency]} · {e.tax_code}{e.week1_month1 ? " W1/M1" : ""} · NI {e.ni_category}
                    {e.leaving_date ? ` · left ${ukDate(e.leaving_date)}` : ""}
                  </span>
                </span>
                <button type="button" className="text-sm font-bold underline underline-offset-2" onClick={() => { setDraft(draftOf(e)); setEditing(e.id); }}>
                  Edit {e.forenames}
                </button>
              </li>
            ))}
          </ul>
        )}
        {draft && (
          <form
            aria-label={editing ? "Edit employee" : "New employee"}
            className="mt-3 grid gap-3 border-t border-border pt-3 sm:grid-cols-3"
            onSubmit={(e) => {
              e.preventDefault();
              submitEmployee();
            }}
          >
            <label className={label}>Payroll ID<input required className={input} value={draft.payroll_id} onChange={(e) => set({ payroll_id: e.target.value })} /></label>
            <label className={label}>Forenames<input required className={input} value={draft.forenames} onChange={(e) => set({ forenames: e.target.value })} /></label>
            <label className={label}>Surname<input required className={input} value={draft.surname} onChange={(e) => set({ surname: e.target.value })} /></label>
            <label className={label}>NI number<input className={input} value={draft.nino} onChange={(e) => set({ nino: e.target.value })} placeholder="QQ123456C" /></label>
            <label className={label}>Date of birth<input required type="date" className={input} value={draft.dob} onChange={(e) => set({ dob: e.target.value })} /></label>
            <label className={label}>
              Gender (as HMRC records it)
              <select className={input} value={draft.gender} onChange={(e) => set({ gender: e.target.value as "M" | "F" })}>
                <option value="F">F</option>
                <option value="M">M</option>
              </select>
            </label>
            <label className={label}>Address line 1<input className={input} value={draft.address1} onChange={(e) => set({ address1: e.target.value })} /></label>
            <label className={label}>Address line 2<input className={input} value={draft.address2} onChange={(e) => set({ address2: e.target.value })} /></label>
            <label className={label}>Postcode<input className={input} value={draft.postcode} onChange={(e) => set({ postcode: e.target.value })} /></label>
            <label className={label}>Start date<input required type="date" className={input} value={draft.start_date} onChange={(e) => set({ start_date: e.target.value })} /></label>
            <label className={label}>
              Starter declaration
              <select className={input} value={draft.starter_declaration} onChange={(e) => suggestCode(e.target.value as Draft["starter_declaration"])}>
                <option value="">None / P45 given</option>
                <option value="A">A: first job since 6 April</option>
                <option value="B">B: only job now</option>
                <option value="C">C: another job or pension</option>
              </select>
            </label>
            <label className={label}>Tax code<input required className={input} value={draft.tax_code} onChange={(e) => set({ tax_code: e.target.value })} /></label>
            <label className="flex items-center gap-2 text-[14px]">
              <input type="checkbox" checked={draft.week1_month1} onChange={(e) => set({ week1_month1: e.target.checked })} />
              Week 1 / month 1 basis
            </label>
            <label className={label}>
              NI category letter
              <select className={input} value={draft.ni_category} onChange={(e) => set({ ni_category: e.target.value })}>
                {Object.entries(setup?.ni_categories ?? { A: "Standard" }).map(([k, v]) => (
                  <option key={k} value={k}>{k}: {v}</option>
                ))}
              </select>
            </label>
            <label className={label}>
              Pay frequency
              <select className={input} value={draft.frequency} onChange={(e) => set({ frequency: e.target.value as RtPayFrequency })}>
                {Object.entries(FREQ).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </label>
            <label className={label}>
              Paid by
              <select className={input} value={draft.pay_type} onChange={(e) => set({ pay_type: e.target.value as "salary" | "hourly" })}>
                <option value="salary">Annual salary</option>
                <option value="hourly">Hourly rate</option>
              </select>
            </label>
            {draft.pay_type === "hourly" && (
              <>
                <label className={label}>
                  Timesheet name (pay from timesheets)
                  <select className={input} value={draft.staff_id} onChange={(e) => set({ staff_id: e.target.value })}>
                    <option value="">Not linked</option>
                    {staff.map((st) => (
                      <option key={st.id} value={st.id}>{st.name}</option>
                    ))}
                  </select>
                </label>
                <label className={label}>Overtime after hours a week<input className={input} inputMode="decimal" placeholder="none" value={draft.ot_after} onChange={(e) => set({ ot_after: e.target.value })} /></label>
                <label className={label}>Overtime multiplier<input className={input} inputMode="decimal" value={draft.ot_mult} onChange={(e) => set({ ot_mult: e.target.value })} /></label>
              </>
            )}
            {draft.pay_type === "salary" ? (
              <label className={label}>Annual salary £<input className={input} inputMode="decimal" value={draft.salary} onChange={(e) => set({ salary: e.target.value })} /></label>
            ) : (
              <>
                <label className={label}>Hourly rate £<input className={input} inputMode="decimal" value={draft.rate} onChange={(e) => set({ rate: e.target.value })} /></label>
                <label className={label}>Usual hours per period<input className={input} inputMode="decimal" value={draft.hours} onChange={(e) => set({ hours: e.target.value })} /></label>
              </>
            )}
            <label className={label}>
              Student loan plan
              <select className={input} value={draft.student_loan_plan} onChange={(e) => set({ student_loan_plan: e.target.value as Draft["student_loan_plan"] })}>
                <option value="">None</option>
                <option value="1">Plan 1</option>
                <option value="2">Plan 2</option>
                <option value="4">Plan 4</option>
                <option value="5">Plan 5</option>
              </select>
            </label>
            <label className="flex items-center gap-2 text-[14px]"><input type="checkbox" checked={draft.postgrad_loan} onChange={(e) => set({ postgrad_loan: e.target.checked })} />Postgraduate loan</label>
            <label className="flex items-center gap-2 text-[14px]"><input type="checkbox" checked={draft.director} onChange={(e) => set({ director: e.target.checked })} />Company director</label>
            <label className="flex items-center gap-2 text-[14px]"><input type="checkbox" checked={draft.pension_exempt} onChange={(e) => set({ pension_exempt: e.target.checked })} />Not a worker for auto-enrolment</label>
            <label className={label}>Leaving date<input type="date" className={input} value={draft.leaving_date} onChange={(e) => set({ leaving_date: e.target.value })} /></label>
            <div className="flex gap-3 sm:col-span-3">
              <button type="submit" disabled={busy !== null} className={button}>{busy === "employee" ? "Saving…" : "Save employee"}</button>
              <button type="button" className={quiet} onClick={() => { setDraft(null); setEditing(null); }}>Cancel</button>
            </div>
          </form>
        )}
      </section>

      {/* ---------------------------------------------------------------- Pay runs */}
      <section aria-labelledby="payruns" className="rounded-2xl border border-border bg-white p-5">
        <h2 id="payruns" className="text-[17px] font-extrabold">Pay runs</h2>
        <div className="mt-2 flex flex-wrap items-end gap-3">
          <label className={label}>
            Pay frequency
            <select className={input} value={freq} onChange={(e) => setFreq(e.target.value as RtPayFrequency)}>
              {Object.entries(FREQ).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
          </label>
          <label className={label}>
            Pay date
            <input type="date" className={input} value={payDate} onChange={(e) => e.target.value && setPayDate(e.target.value)} />
          </label>
          <button
            type="button"
            disabled={busy !== null}
            className={button}
            onClick={() =>
              act("prepare", (a) => runtime.paye.prepare(a, freq, payDate), (r) => `Pay run ${r.id} calculated.`).then((r) => r && setRunId(r.id))
            }
          >
            {busy === "prepare" ? "Calculating…" : "Calculate pay run"}
          </button>
          {runs.length > 0 && (
            <label className={label}>
              Show pay run
              <select className={input} value={runId ?? ""} onChange={(e) => setRunId(e.target.value)}>
                {runs.map((r) => (
                  <option key={r.id} value={r.id}>{r.id} ({r.status})</option>
                ))}
              </select>
            </label>
          )}
        </div>

        {run && (
          <div className="mt-4" role="region" aria-label={`Pay run ${run.id}`}>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-[16px] font-extrabold">
                {FREQ[run.frequency]} pay, {run.frequency === "monthly" ? "month" : "week"} {run.period}, paid {ukDate(run.pay_date)}
              </h3>
              <span className={`rounded-full px-2.5 py-0.5 text-[12px] font-bold ${run.status === "posted" ? "bg-teal-tint text-teal-dark" : "bg-ground text-muted"}`}>
                {run.status === "draft" ? "Draft" : run.status === "proposed" ? "Waiting for approval in Review" : "Approved and posted"}
              </span>
              <span className="rounded-full bg-warn-bg px-2.5 py-0.5 text-[12px] font-bold text-warn-ink ring-1 ring-warn-border">{CHECK}</span>
            </div>
            {run.warnings.map((w) => (
              <p key={w} className="mt-1 text-sm font-semibold text-warn-ink">{w}</p>
            ))}
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-left text-[14px]">
                <thead>
                  <tr className="border-b border-border text-[12px] font-bold text-muted">
                    <th scope="col" className="py-2 pr-3">Employee</th>
                    <th scope="col" className="py-2 pr-3 text-right">Gross</th>
                    <th scope="col" className="py-2 pr-3 text-right">Tax</th>
                    <th scope="col" className="py-2 pr-3 text-right">Employee NI</th>
                    <th scope="col" className="py-2 pr-3 text-right">Student loan</th>
                    <th scope="col" className="py-2 pr-3 text-right">Pension (employee)</th>
                    <th scope="col" className="py-2 pr-3 text-right">Net pay</th>
                    <th scope="col" className="py-2 pr-3 text-right">Employer NI</th>
                    <th scope="col" className="py-2 pr-3 text-right">Employer pension</th>
                    <th scope="col" className="py-2">Bonus / payslip</th>
                  </tr>
                </thead>
                <tbody>
                  {run.lines.map((l) => (
                    <tr key={l.employee_id} className="border-t border-border align-top">
                      <th scope="row" className="py-2 pr-3 font-bold">
                        {l.name}
                        <span className="block text-[12px] font-normal text-muted">
                          {l.tax_code} · NI {l.ni_category}{l.starter ? " · starter" : ""}{l.leaver ? " · leaver" : ""}
                        </span>
                        {l.pay_items
                          .filter((i) => i.multiplier !== 1)
                          .map((i) => (
                            <span key={i.label} className="block text-[12px] font-normal">
                              {i.label}: {i.hours} h, {pounds(i.pence)}
                            </span>
                          ))}
                        {[...l.warnings, ...l.pension.notes].map((w) => (
                          <span key={w} className="block text-[12px] font-normal text-warn-ink">{w}</span>
                        ))}
                      </th>
                      <td className="py-2 pr-3 text-right tabular-nums">{pounds(l.gross_pence)}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{pounds(l.tax_pence)}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{pounds(l.ee_ni_pence)}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{pounds(l.student_loan_pence + l.postgrad_loan_pence)}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{pounds(l.ee_pension_net_pay_pence + l.ee_pension_from_net_pence)}</td>
                      <td className="py-2 pr-3 text-right font-bold tabular-nums">{pounds(l.net_pay_pence)}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{pounds(l.er_ni_pence)}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{pounds(l.pension.employer_pence)}</td>
                      <td className="py-2">
                        <div className="flex flex-wrap items-center gap-2">
                          {run.status === "draft" && (
                            <input
                              aria-label={`Bonus for ${l.name}`}
                              className={`${input} h-8 w-24 text-right`}
                              inputMode="decimal"
                              placeholder="0.00"
                              value={bonus[l.employee_id] ?? (l.bonus_pence ? (l.bonus_pence / 100).toFixed(2) : "")}
                              onChange={(e) => setBonus({ ...bonus, [l.employee_id]: e.target.value })}
                            />
                          )}
                          <button
                            type="button"
                            className="text-sm font-bold underline underline-offset-2"
                            onClick={() => act(`slip-${l.employee_id}`, (a) => runtime.paye.payslip(a, run.id, l.employee_id)).then((f) => f && save(f))}
                          >
                            Payslip for {l.name}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-[14px] text-muted">
              Due to HMRC from this run: <strong className="text-ink">{pounds(run.hmrc_due_pence)}</strong>
              {run.employment_allowance_pence > 0 && ` after ${pounds(run.employment_allowance_pence)} Employment Allowance`}. Pay by the 22nd of
              the next tax month (see the employer payment record).
            </p>
            <div className="mt-3 flex flex-wrap gap-3">
              {run.status === "draft" && (
                <>
                  <button
                    type="button"
                    disabled={busy !== null}
                    className={quiet}
                    onClick={() =>
                      act(
                        "save",
                        (a) =>
                          runtime.paye.edit(
                            a,
                            run.id,
                            run.lines.map((l) => ({ ...l.inputs, bonus_pence: toPence(bonus[l.employee_id] ?? "") ?? l.inputs.bonus_pence ?? 0 })),
                          ),
                        "Pay run worked out again.",
                      ).then(() => setBonus({}))
                    }
                  >
                    Recalculate
                  </button>
                  <button type="button" disabled={busy !== null || run.lines.length === 0} className={button} onClick={() => act("propose", (a) => runtime.paye.propose(a, run.id), "Sent to Review. Nothing is posted until you approve it.")}>
                    Send to Review
                  </button>
                  <button type="button" disabled={busy !== null} className={quiet} onClick={() => window.confirm("Set this draft aside?") && act("discard", (a) => runtime.paye.discard(a, run.id), "Draft set aside.").then(() => setRunId(null))}>
                    Discard draft
                  </button>
                </>
              )}
              {run.status === "proposed" && (
                <>
                  <button
                    type="button"
                    disabled={busy !== null}
                    className={button}
                    onClick={() => window.confirm(`Approve pay run ${run.id}? Its journal is posted to your books.`) && act("approve", (a) => runtime.paye.approve(a, run.id), "Pay run approved and posted to your books.")}
                  >
                    Approve and post
                  </button>
                  <button type="button" disabled={busy !== null} className={quiet} onClick={() => act("draft", (a) => runtime.paye.toDraft(a, run.id), "Back to draft.")}>
                    Back to draft
                  </button>
                </>
              )}
            </div>
            {run.journal.length > 0 && (
              <details className="mt-3">
                <summary className="cursor-pointer text-[14px] font-bold">Journal posted on approval</summary>
                <table className="mt-2 text-[14px]">
                  <tbody>
                    {run.journal.map((j) => (
                      <tr key={j.account}>
                        <td className="pr-4">{j.account}</td>
                        <td className="pr-4 text-right tabular-nums">{j.debit_pence ? pounds(j.debit_pence) : ""}</td>
                        <td className="text-right tabular-nums">{j.credit_pence ? pounds(j.credit_pence) : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            )}
          </div>
        )}
      </section>

      {/* ---------------------------------------------------------------- RTI */}
      <section aria-labelledby="rti" className="rounded-2xl border border-border bg-white p-5">
        <h2 id="rti" className="text-[17px] font-extrabold">RTI files (FPS and EPS)</h2>
        <p className="mt-1 text-[14px] text-muted">
          Built to HMRC&apos;s 2026-27 schemas and checked against them. Basic PAYE Tools does not import these files: use them to check
          what you (or your provider) send, figure by figure.
        </p>
        <div className="mt-2"><FilingNote /></div>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <button
            type="button"
            disabled={busy !== null || run?.status !== "posted"}
            title={run?.status !== "posted" ? "Approve the pay run first" : undefined}
            className={quiet}
            onClick={() =>
              run &&
              act("fps", (a) => runtime.paye.fps(a, run.id), (r) => `${r.file.name} saved to ${r.file.saved_to}. ${FILING}`).then((r) => {
                if (r) {
                  save(r.file);
                  setFpsRows(r.contents);
                }
              })
            }
          >
            Download FPS for {run?.id ?? "this pay run"}
          </button>
          <label className={label}>
            Tax month
            <select className={input} value={epsMonth} onChange={(e) => setEpsMonth(Number(e.target.value))}>
              {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-[14px]"><input type="checkbox" checked={epsEa} onChange={(e) => setEpsEa(e.target.checked)} />Claim Employment Allowance on this EPS</label>
          <label className="flex items-center gap-2 text-[14px]"><input type="checkbox" checked={epsFinal} onChange={(e) => setEpsFinal(e.target.checked)} />Final submission for the year</label>
          <button
            type="button"
            disabled={busy !== null}
            className={quiet}
            onClick={() =>
              act("eps", (a) => runtime.paye.eps(a, epsMonth, { employmentAllowance: epsEa, final: epsFinal }), (r) => `${r.file.name} saved to ${r.file.saved_to}. ${FILING}`).then((r) => {
                if (r) {
                  save(r.file);
                  setEpsRows(r.contents);
                }
              })
            }
          >
            Download EPS
          </button>
        </div>
        {fpsRows && <Table t={fpsRows} />}
        {epsRows && (
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-[14px]" aria-label="EPS contents">
            {epsRows.map((r) => (
              <div key={r.item} className="contents">
                <dt className="text-muted">{r.item}</dt>
                <dd>{r.value}</dd>
              </div>
            ))}
          </dl>
        )}
      </section>

      {/* ---------------------------------------------------------------- Pension */}
      <section aria-labelledby="pension" className="rounded-2xl border border-border bg-white p-5">
        <h2 id="pension" className="text-[17px] font-extrabold">Pension contribution schedule</h2>
        <p className="mt-1 text-[14px] text-muted">
          For your pension provider. Nest, The People&apos;s Pension, Smart Pension (PAPDIS 1.0, net pay arrangement only) and NOW: Pensions
          layouts follow their published guides (sources in each file&apos;s note); check one upload against the provider&apos;s current
          template first.
        </p>
        <div className="mt-2 flex flex-wrap gap-3">
          {(Object.keys(PROVIDERS) as RtPensionProvider[]).map((p) => (
            <button
              key={p}
              type="button"
              disabled={busy !== null || !run}
              className={quiet}
              onClick={() => run && act(`pension-${p}`, (a) => runtime.paye.pensionFile(a, run.id, p), (f) => f.note).then((f) => f && save(f))}
            >
              {PROVIDERS[p]} CSV
            </button>
          ))}
        </div>
      </section>

      {/* ---------------------------------------------------------------- Reports */}
      <section aria-labelledby="reports" className="rounded-2xl border border-border bg-white p-5">
        <h2 id="reports" className="text-[17px] font-extrabold">Payroll reports</h2>
        <div className="mt-2 flex flex-wrap items-end gap-3">
          {/* min-w-0 and full width: a select is as wide as its longest option, which overflowed a 360 px phone. */}
          <label className={`${label} min-w-0 max-w-full`}>
            Report
            <select className={`${input} w-full min-w-0`} value={reportKey} onChange={(e) => { setReportKey(e.target.value as RtPayeReportKey); setReport(null); }}>
              {REPORTS.map((r) => (
                <option key={r.key} value={r.key}>{r.label}</option>
              ))}
            </select>
          </label>
          {REPORTS.find((r) => r.key === reportKey)?.needs === "employee" && (
            <label className={label}>
              Employee
              <select className={input} value={reportEmployee} onChange={(e) => setReportEmployee(e.target.value)}>
                <option value="">Choose…</option>
                {employees.map((e) => (
                  <option key={e.id} value={e.id}>{e.forenames} {e.surname}</option>
                ))}
              </select>
            </label>
          )}
          <button
            type="button"
            disabled={busy !== null}
            className={quiet}
            onClick={() => act("report", (a) => runtime.paye.report(a, reportKey, { run: run?.id, employee: reportEmployee })).then((t) => t && setReport(t))}
          >
            Show
          </button>
          {(["pdf", "csv", "xlsx"] as const).map((fmt) => (
            <button
              key={fmt}
              type="button"
              disabled={busy !== null}
              className={quiet}
              onClick={() => act(`report-${fmt}`, (a) => runtime.paye.reportFile(a, reportKey, fmt, { run: run?.id, employee: reportEmployee })).then((f) => f && save(f))}
            >
              {fmt.toUpperCase()}
            </button>
          ))}
        </div>
        {report && <Table t={report} />}
      </section>

      <section aria-labelledby="paye-limits" className="rounded-2xl bg-ground p-5">
        <h2 id="paye-limits" className="text-[15px] font-extrabold">What this payroll does not do</h2>
        <ul className="mt-2 flex list-disc flex-col gap-1 pl-5 text-[14px] leading-6">
          {(setup?.limits ?? []).map((l) => (
            <li key={l}>{l}</li>
          ))}
          <li>{FILING}</li>
        </ul>
        {setup && (
          <p className="mt-2 text-[13px] text-muted">
            Sources (checked {setup.verified_on}):{" "}
            {setup.sources.map((s, i) => (
              <span key={s.url}>
                {i > 0 && " · "}
                <a href={s.url} target="_blank" rel="noreferrer" className="underline underline-offset-2">{s.label}</a>
              </span>
            ))}
          </p>
        )}
      </section>
    </div>
  );
}
