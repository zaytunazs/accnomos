/* The new-user set-up wizard: one question per step, saved as you go into `_System/profile.json`.

Step order and rules come from GET /setup-wizard (services/runtime/app/routes_setup_wizard.py); Companies House
and HMRC VAT checks go through the existing /lookup/* helpers and the user confirms what they show. Nothing here
files anything: confirm only writes the profile.
*/

"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useAccount, errorText } from "@/components/jobs/useAccount";
import {
  runtime,
  vatCheckSourceLabel,
  type RtCompanyMatch,
  type RtVatCheck,
  type RtWizardStatus,
} from "@/lib/runtime";

const input =
  "mt-1 h-11 w-full rounded-xl border border-border bg-white px-3 text-[15px] text-ink";
const label = "text-xs font-bold text-muted";
const card = "rounded-2xl border border-border bg-white p-4";
const primary =
  "h-12 flex-1 rounded-xl bg-teal px-5 text-[15px] font-extrabold text-white hover:bg-teal-dark disabled:opacity-50";
const back =
  "inline-flex h-12 items-center rounded-xl border border-border bg-white px-5 text-[15px] font-bold text-ink";

const STEP_TITLES: Record<string, string> = {
  business_type: "What are you?",
  company: "Your company",
  vat: "VAT",
  income_tax: "Income Tax",
  cis: "Construction work",
  payroll: "Employees",
  property: "Property",
  summary: "Check and confirm",
};

const SCHEMES: { value: string; label: string; explains: string }[] = [
  { value: "standard", label: "Standard", explains: "Pay VAT on what you charge, reclaim VAT on what you buy." },
  {
    value: "flat_rate",
    label: "Flat rate",
    explains: "Pay a fixed percentage of turnover (by sector); you keep the rest. Cannot combine with cash accounting.",
  },
  {
    value: "cash",
    label: "Cash accounting",
    explains: "Count VAT when money changes hands, not when invoices go out. Turnover £1.35m or less.",
  },
  {
    value: "annual",
    label: "Annual accounting",
    explains: "One return a year with advance payments. Turnover £1.35m or less.",
  },
];

function get<T>(setup: Record<string, unknown>, step: string, key: string, fallback: T): T {
  const s = setup[step];
  if (typeof s !== "object" || s === null) return fallback;
  const v = (s as Record<string, unknown>)[key];
  return (v === undefined ? fallback : v) as T;
}

function gbpToPence(text: string): number | null {
  const t = text.replace(/[£,\s]/g, "");
  if (!/^\d+(\.\d{1,2})?$/.test(t)) return null;
  return Math.round(parseFloat(t) * 100);
}

function penceToGbp(pence: unknown): string {
  if (typeof pence !== "number" || pence < 0) return "";
  return (pence / 100).toFixed(2).replace(/\.00$/, "");
}

export default function SetupWizard() {
  const account = useAccount();
  const [status, setStatus] = useState<RtWizardStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [businessType, setBusinessType] = useState("");
  const [companyNumber, setCompanyNumber] = useState("");
  const [company, setCompany] = useState<RtCompanyMatch | null>(null);
  const [vatRegistered, setVatRegistered] = useState(true);
  const [vatNumber, setVatNumber] = useState("");
  const [vatCheck, setVatCheck] = useState<RtVatCheck | null>(null);
  const [acknowledge, setAcknowledge] = useState(false);
  const [scheme, setScheme] = useState("standard");
  const [extraSchemes, setExtraSchemes] = useState<string[]>([]);
  const [sector, setSector] = useState("");
  const [percentage, setPercentage] = useState("");
  const [discountFrom, setDiscountFrom] = useState("");
  const [goodsShare, setGoodsShare] = useState("");
  const [limitedCost, setLimitedCost] = useState(false);
  const [stagger, setStagger] = useState("quarterly");
  const [periodStart, setPeriodStart] = useState("");
  const [utr, setUtr] = useState("");
  const [basis, setBasis] = useState("cash");
  const [turnover, setTurnover] = useState("");
  const [isSubcontractor, setIsSubcontractor] = useState(false);
  const [isContractor, setIsContractor] = useState(false);
  const [verifyNo, setVerifyNo] = useState("");
  const [hasEmployees, setHasEmployees] = useState(false);
  const [payeRef, setPayeRef] = useState("");
  const [aoRef, setAoRef] = useState("");
  const [lets, setLets] = useState("");
  const [joint, setJoint] = useState(false);
  const [done, setDone] = useState(false);

  const refresh = useCallback(async () => {
    if (!account) return;
    try {
      const s = await runtime.setupWizard.status(account);
      setStatus(s);
      const setup = s.setup;
      setName(typeof setup.business_name === "string" ? setup.business_name : "");
      setBusinessType(typeof setup.business_type === "string" ? setup.business_type : "");
      const co = (setup.company ?? {}) as Record<string, unknown>;
      if (typeof co.number === "string") setCompanyNumber(co.number);
      if (co.confirmed)
        setCompany({
          company_number: String(co.number ?? ""),
          name: String(co.name ?? ""),
          status: null,
          type: null,
          address: typeof co.address === "string" ? co.address : null,
          date_of_creation: typeof co.incorporation_date === "string" ? co.incorporation_date : null,
          source: "companies-house",
          sample: false,
        });
      setVatRegistered(get(setup, "vat", "registered", true));
      setVatNumber(get(setup, "vat", "vat_number", ""));
      const vc = get<Record<string, unknown> | null>(setup, "vat", "vat_check", null);
      if (vc && typeof vc.registered === "boolean")
        setVatCheck({
          vrn: get(setup, "vat", "vat_number", ""),
          registered: vc.registered,
          name: typeof vc.name === "string" ? vc.name : null,
          address: typeof vc.address === "string" ? vc.address : null,
          consultation_number: typeof vc.consultation_number === "string" ? vc.consultation_number : null,
          checked_at: typeof vc.checked_at === "string" ? vc.checked_at : "",
          source: "hmrc",
        });
      setAcknowledge(get(setup, "vat", "mismatch_acknowledged", false));
      setScheme(get(setup, "vat", "scheme", "standard"));
      const schemes = get<string[]>(setup, "vat", "schemes", ["standard"]);
      setExtraSchemes(schemes.filter((x) => x !== get(setup, "vat", "scheme", "standard")));
      const fr = get<Record<string, unknown>>(setup, "vat", "flat_rate", {});
      setSector(typeof fr.sector === "string" ? fr.sector : "");
      setUtr(get(setup, "income_tax", "utr", "") ?? "");
      setBasis(get(setup, "income_tax", "accounting_basis", "cash"));
      setTurnover(penceToGbp(get(setup, "income_tax", "turnover_pence", 0)));
      setIsSubcontractor(get(setup, "cis", "is_subcontractor", false));
      setIsContractor(get(setup, "cis", "is_contractor", false));
      setVerifyNo(get(setup, "cis", "verification_number", "") ?? "");
      setHasEmployees(get(setup, "payroll", "has_employees", false));
      setPayeRef(get(setup, "payroll", "paye_reference", "") ?? "");
      setAoRef(get(setup, "payroll", "accounts_office_reference", "") ?? "");
      const nlets = get<number>(setup, "property", "number_of_lets", 0);
      setLets(nlets ? String(nlets) : "");
      setJoint(get(setup, "property", "joint_ownership", false));
      setDone(!!setup.confirmed_at);
    } catch (e) {
      setError(errorText(e));
    }
  }, [account]);

  useEffect(() => {
    // Defer to avoid a synchronous setState in the effect body.
    queueMicrotask(() => {
      refresh();
    });
  }, [refresh]);

  if (account === undefined) return <p className="mt-6 text-sm text-muted">Signing you in…</p>;
  if (!account) return <p className="mt-6 text-sm text-muted">Sign in with your Microsoft account to set up.</p>;
  if (!status) return <p className="mt-6 text-sm text-muted">{error ?? "Reading your set-up…"}</p>;

  const steps = status.steps;
  const current = done ? "summary" : status.current_step;
  const index = Math.max(0, steps.indexOf(current));

  async function save(step: string, answers: Record<string, unknown>, goTo?: string) {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const s = await runtime.setupWizard.answer(account!, step, answers);
      setStatus(s);
      if (goTo) {
        // Jump the wizard display to the fix step.
        s.current_step = goTo;
        setStatus({ ...s });
      }
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  }

  function goStep(i: number) {
    const s = { ...status!, current_step: steps[Math.min(Math.max(i, 0), steps.length - 1)] };
    setStatus(s);
  }

  async function lookUpCompany() {
    setSaving(true);
    setError(null);
    try {
      const found = await runtime.lookupCompany(account!, companyNumber.trim());
      setCompany(found);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  }

  async function checkVat() {
    setSaving(true);
    setError(null);
    try {
      const checked = await runtime.lookupVat(account!, vatNumber.trim());
      setVatCheck(checked);
      setAcknowledge(false);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  }

  const mismatch = status.blocking.find((i) => i.code === "vat_name_mismatch");
  const stepError = (step: string) =>
    status!.issues.find((i) => i.fix_step === step && (step === current || step === "summary"));

  return (
    <div className="mx-auto max-w-xl">
      <div className="mt-4" role="progressbar" aria-valuenow={index + 1} aria-valuemin={1} aria-valuemax={steps.length} aria-label={`Step ${index + 1} of ${steps.length}`}>
        <div className="h-2 overflow-hidden rounded-full bg-border">
          <div className="h-full rounded-full bg-teal" style={{ width: `${((index + 1) / steps.length) * 100}%` }} />
        </div>
        <p className="mt-1 text-xs text-muted">
          Step {index + 1} of {steps.length} · {STEP_TITLES[current] ?? current}
        </p>
      </div>

      {error && (
        <p role="alert" className="mt-3 rounded-xl border border-warn-border bg-warn-tint p-3 text-sm font-semibold text-warn-ink">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="mt-3 rounded-xl bg-teal-tint p-3 text-sm font-semibold text-teal-dark">
          {notice}
        </p>
      )}

      <div className="mt-4 space-y-4">
        {current === "business_type" && (
          <div className={card}>
            <h2 className="text-[17px] font-extrabold text-ink">What are you?</h2>
            <div className="mt-2 grid gap-2" role="radiogroup" aria-label="What are you?">
              {status.business_types.map((t) => (
                <label key={t.value} className="flex items-start gap-3 rounded-xl border border-border px-3 py-2">
                  <input type="radio" name="bt" value={t.value} checked={businessType === t.value} onChange={() => setBusinessType(t.value)} className="mt-1" />
                  <span>
                    <span className="block text-[15px] font-semibold text-ink">{t.label}</span>
                    <span className="block text-xs text-muted">{t.explains}</span>
                  </span>
                </label>
              ))}
            </div>
            <label className={`${label} mt-3 block`} htmlFor="wiz-name">Business or personal name</label>
            <input id="wiz-name" className={input} value={name} maxLength={80} placeholder="e.g. Sam Builds Ltd" onChange={(e) => setName(e.target.value)} />
            <button type="button" disabled={saving || !businessType || !name.trim()} className={`${primary} mt-3 w-full`} onClick={() => save("business_type", { business_type: businessType, business_name: name.trim() })}>
              Save and continue
            </button>
          </div>
        )}

        {current === "company" && (
          <div className={card}>
            <h2 className="text-[17px] font-extrabold text-ink">Your company</h2>
            <p className="mt-1 text-sm text-muted">Enter the company number, look it up at Companies House, then confirm it is you.</p>
            <label className={`${label} mt-3 block`} htmlFor="wiz-cr">Company number</label>
            <div className="flex gap-2">
              <input id="wiz-crn" className={input} value={companyNumber} placeholder="e.g. 01234567" onChange={(e) => setCompanyNumber(e.target.value)} />
              <button type="button" disabled={saving || !companyNumber.trim()} className={back} onClick={lookUpCompany}>Look up</button>
            </div>
            {company && (
              <div className="mt-3 rounded-xl bg-ground p-3 text-sm text-ink">
                <p className="font-bold">{company.name}</p>
                <p className="mt-0.5">{company.address}</p>
                <p className="mt-0.5 text-muted">Incorporated {company.date_of_creation ?? "unknown"}</p>
              </div>
            )}
            <div className="mt-3 flex gap-3">
              <button type="button" className={back} onClick={() => goStep(index - 1)}>Back</button>
              <button type="button" disabled={saving || !company} className={primary} onClick={() => save("company", {
                company_number: company!.company_number, name: company!.name, address: company!.address ?? "",
                incorporation_date: company!.date_of_creation ?? "",
              })}>
                {company ? "Confirm — this is us" : "Look up first"}
              </button>
            </div>
          </div>
        )}

        {current === "vat" && (
          <div className={card}>
            <h2 className="text-[17px] font-extrabold text-ink">VAT</h2>
            <label className="mt-2 flex items-center gap-3 text-[15px] font-semibold text-ink">
              <input type="checkbox" checked={vatRegistered} onChange={(e) => setVatRegistered(e.target.checked)} />
              VAT-registered
            </label>
            {vatRegistered && (
              <>
                <label className={`${label} mt-3 block`} htmlFor="wiz-vrn">VAT number</label>
                <div className="flex gap-2">
                  <input id="wiz-vrn" className={input} value={vatNumber} placeholder="GB 123 4567 89" onChange={(e) => setVatNumber(e.target.value)} />
                  <button type="button" disabled={saving || !vatNumber.trim()} className={back} onClick={checkVat}>Check with HMRC</button>
                </div>
                {vatCheck && (
                  <div className="mt-3 rounded-xl bg-ground p-3 text-sm text-ink">
                    <p>{vatCheck.registered ? `Registered: ${vatCheck.name}` : "HMRC says this number is not registered."}</p>
                    {vatCheck.address && <p className="mt-0.5">{vatCheck.address}</p>}
                    <p className="mt-0.5 text-muted">({vatCheckSourceLabel(vatCheck.source)})</p>
                  </div>
                )}
                {mismatch && (
                  <div className="mt-3 rounded-xl border border-warn-border bg-warn-tint p-3 text-sm text-warn-ink" role="alert">
                    <p className="font-bold">The names do not match — the wizard stops here.</p>
                    <p className="mt-1">{mismatch.message}</p>
                    <label className="mt-2 flex items-start gap-2 font-semibold text-ink">
                      <input type="checkbox" checked={acknowledge} onChange={(e) => setAcknowledge(e.target.checked)} className="mt-1" />
                      This VAT number is ours anyway (recorded with your confirmation).
                    </label>
                  </div>
                )}
                <fieldset className="mt-3">
                  <legend className={label}>VAT scheme</legend>
                  <div className="mt-1 grid gap-2">
                    {SCHEMES.map((s) => (
                      <label key={s.value} className="flex items-start gap-3 rounded-xl border border-border px-3 py-2">
                        <input type="radio" name="scheme" value={s.value} checked={scheme === s.value} onChange={() => setScheme(s.value)} className="mt-1" />
                        <span>
                          <span className="block text-[15px] font-semibold text-ink">{s.label}</span>
                          <span className="block text-xs text-muted">{s.explains}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                </fieldset>
                {scheme === "flat_rate" && (
                  <>
                    <label className={`${label} mt-3 block`} htmlFor="wiz-sector">Flat-rate sector</label>
                    <input id="wiz-sector" className={input} value={sector} placeholder="e.g. Photography" onChange={(e) => setSector(e.target.value)} />
                    <div className="mt-2 grid grid-cols-2 gap-2">
                      <div>
                        <label className={label} htmlFor="wiz-pct">Rate (%)</label>
                        <input id="wiz-pct" className={input} value={percentage} inputMode="decimal" placeholder="e.g. 12.5" onChange={(e) => setPercentage(e.target.value)} />
                      </div>
                      <div>
                        <label className={label} htmlFor="wiz-disc">Registered since (first-year 1% off)</label>
                        <input id="wiz-disc" className={input} type="date" value={discountFrom} onChange={(e) => setDiscountFrom(e.target.value)} />
                      </div>
                    </div>
                    <label className={`${label} mt-2 block`} htmlFor="wiz-goods">Relevant goods, % of turnover</label>
                    <input id="wiz-goods" className={input} value={goodsShare} inputMode="decimal" placeholder="Under 2% means limited-cost trader" onChange={(e) => setGoodsShare(e.target.value)} />
                    <label className="mt-2 flex items-center gap-3 text-[15px] font-semibold text-ink">
                      <input type="checkbox" checked={limitedCost} onChange={(e) => setLimitedCost(e.target.checked)} />
                      Limited-cost trader (flat rate 16.5%)
                    </label>
                  </>
                )}
                <div className="mt-3 grid grid-cols-2 gap-2">
                  <div>
                    <label className={label} htmlFor="wiz-stagger">VAT periods</label>
                    <select id="wiz-stagger" className={input} value={stagger} onChange={(e) => setStagger(e.target.value)}>
                      <option value="quarterly">Quarterly</option>
                      <option value="monthly">Monthly</option>
                      <option value="annual">Annual</option>
                    </select>
                  </div>
                  <div>
                    <label className={label} htmlFor="wiz-pstart">First period starts</label>
                    <input id="wiz-pstart" className={input} type="date" value={periodStart} onChange={(e) => setPeriodStart(e.target.value)} />
                  </div>
                </div>
              </>
            )}
            {stepError("vat") && !mismatch && (
              <p role="alert" className="mt-2 text-xs font-semibold text-warn-ink">{stepError("vat")!.message}</p>
            )}
            <div className="mt-3 flex gap-3">
              <button type="button" className={back} onClick={() => goStep(index - 1)}>Back</button>
              <button type="button" disabled={saving} className={primary} onClick={() => {
                if (!vatRegistered) return save("vat", { registered: false });
                const answers: Record<string, unknown> = {
                  registered: true, vat_number: vatNumber.trim(), scheme, schemes: [scheme, ...extraSchemes],
                  stagger, period_start: periodStart, mismatch_acknowledged: acknowledge,
                };
                if (vatCheck) answers.vat_check = {
                  registered: vatCheck.registered, name: vatCheck.name, address: vatCheck.address,
                  consultation_number: vatCheck.consultation_number, checked_at: vatCheck.checked_at,
                };
                if (scheme === "flat_rate") answers.flat_rate = {
                  sector, percentage: percentage ? parseFloat(percentage) : null,
                  first_year_discount_from: discountFrom || null,
                  relevant_goods_share_pct: goodsShare ? parseFloat(goodsShare) : null, limited_cost: limitedCost,
                };
                save("vat", answers);
              }}>
                Save and continue
              </button>
            </div>
          </div>
        )}

        {current === "income_tax" && (
          <div className={card}>
            <h2 className="text-[17px] font-extrabold text-ink">Income Tax</h2>
            <label className={`${label} mt-2 block`} htmlFor="wiz-utr">Unique Taxpayer Reference (10 digits)</label>
            <input id="wiz-utr" className={input} value={utr} inputMode="numeric" maxLength={14} placeholder="e.g. 1234567890" onChange={(e) => setUtr(e.target.value)} />
            <fieldset className="mt-3">
              <legend className={label}>Accounting basis</legend>
              <p className="text-xs text-muted">Cash basis has been HMRC&apos;s default for sole traders since 6 April 2024.</p>
              <div className="mt-1 grid gap-2">
                <label className="flex items-start gap-3 rounded-xl border border-border px-3 py-2">
                  <input type="radio" name="basis" value="cash" checked={basis === "cash"} onChange={() => setBasis("cash")} className="mt-1" />
                  <span><span className="block text-[15px] font-semibold text-ink">Cash basis (default)</span>
                  <span className="block text-xs text-muted">Count income and costs when money changes hands.</span></span>
                </label>
                <label className="flex items-start gap-3 rounded-xl border border-border px-3 py-2">
                  <input type="radio" name="basis" value="traditional" checked={basis === "traditional"} onChange={() => setBasis("traditional")} className="mt-1" />
                  <span><span className="block text-[15px] font-semibold text-ink">Traditional (accruals)</span>
                  <span className="block text-xs text-muted">Count income and costs when invoices go out and come in.</span></span>
                </label>
              </div>
            </fieldset>
            <label className={`${label} mt-3 block`} htmlFor="wiz-turn">Yearly turnover (£)</label>
            <input id="wiz-turn" className={input} value={turnover} inputMode="decimal" placeholder="e.g. 42000" onChange={(e) => setTurnover(e.target.value)} />
            <p className="mt-1 text-xs text-muted">Over £50,000 means quarterly updates from 6 April 2026; over £30,000 from April 2027.</p>
            <div className="mt-3 flex gap-3">
              <button type="button" className={back} onClick={() => goStep(index - 1)}>Back</button>
              <button type="button" disabled={saving} className={primary} onClick={() => {
                const pence = turnover.trim() === "" ? 0 : gbpToPence(turnover);
                if (pence === null) { setError("Turnover is a number of pounds, e.g. 42000."); return; }
                save("income_tax", { utr: utr.trim() || null, accounting_basis: basis, turnover_pence: pence });
              }}>
                Save and continue
              </button>
            </div>
          </div>
        )}

        {current === "cis" && (
          <div className={card}>
            <h2 className="text-[17px] font-extrabold text-ink">Construction work</h2>
            <p className="mt-1 text-sm text-muted">The Construction Industry Scheme takes tax off payments before you are paid.</p>
            <label className="mt-2 flex items-center gap-3 text-[15px] font-semibold text-ink">
              <input type="checkbox" checked={isSubcontractor} onChange={(e) => setIsSubcontractor(e.target.checked)} />
              Subcontractor — I do construction work for contractors
            </label>
            <label className="mt-2 flex items-center gap-3 text-[15px] font-semibold text-ink">
              <input type="checkbox" checked={isContractor} onChange={(e) => setIsContractor(e.target.checked)} />
              Contractor — I pay subcontractors for construction work
            </label>
            {(isSubcontractor || isContractor) && (
              <>
                <label className={`${label} mt-3 block`} htmlFor="wiz-verify">CIS verification number (if you have one)</label>
                <input id="wiz-verify" className={input} value={verifyNo} onChange={(e) => setVerifyNo(e.target.value)} />
              </>
            )}
            <div className="mt-3 flex gap-3">
              <button type="button" className={back} onClick={() => goStep(index - 1)}>Back</button>
              <button type="button" disabled={saving} className={primary} onClick={() => save("cis", {
                is_subcontractor: isSubcontractor, is_contractor: isContractor, verification_number: verifyNo.trim() || null,
              })}>
                Save and continue
              </button>
            </div>
          </div>
        )}

        {current === "payroll" && (
          <div className={card}>
            <h2 className="text-[17px] font-extrabold text-ink">Employees</h2>
            <label className="mt-2 flex items-center gap-3 text-[15px] font-semibold text-ink">
              <input type="checkbox" checked={hasEmployees} onChange={(e) => setHasEmployees(e.target.checked)} />
              The business has employees
            </label>
            {hasEmployees && (
              <>
                <label className={`${label} mt-3 block`} htmlFor="wiz-paye">Employer PAYE reference</label>
                <input id="wiz-paye" className={input} value={payeRef} placeholder="e.g. 123/AB45678" onChange={(e) => setPayeRef(e.target.value)} />
                <label className={`${label} mt-3 block`} htmlFor="wiz-ao">Accounts Office reference</label>
                <input id="wiz-ao" className={input} value={aoRef} placeholder="e.g. 123PA00045678" onChange={(e) => setAoRef(e.target.value)} />
              </>
            )}
            <div className="mt-3 flex gap-3">
              <button type="button" className={back} onClick={() => goStep(index - 1)}>Back</button>
              <button type="button" disabled={saving} className={primary} onClick={() => save("payroll", {
                has_employees: hasEmployees, paye_reference: payeRef.trim() || null, accounts_office_reference: aoRef.trim() || null,
              })}>
                Save and continue
              </button>
            </div>
          </div>
        )}

        {current === "property" && (
          <div className={card}>
            <h2 className="text-[17px] font-extrabold text-ink">Property</h2>
            <label className={`${label} mt-2 block`} htmlFor="wiz-lets">Number of lets</label>
            <input id="wiz-lets" className={input} value={lets} inputMode="numeric" placeholder="e.g. 2" onChange={(e) => setLets(e.target.value)} />
            <label className="mt-2 flex items-center gap-3 text-[15px] font-semibold text-ink">
              <input type="checkbox" checked={joint} onChange={(e) => setJoint(e.target.checked)} />
              Jointly owned
            </label>
            <div className="mt-3 flex gap-3">
              <button type="button" className={back} onClick={() => goStep(index - 1)}>Back</button>
              <button type="button" disabled={saving} className={primary} onClick={() => {
                const n = lets.trim() === "" ? 0 : Number(lets);
                if (!Number.isInteger(n) || n < 0) { setError("The number of lets is a whole number, 0 or more."); return; }
                save("property", { number_of_lets: n, joint_ownership: joint });
              }}>
                Save and continue
              </button>
            </div>
          </div>
        )}

        {current === "summary" && (
          <div className="space-y-4">
            <div className={card}>
              <h2 className="text-[17px] font-extrabold text-ink">What the app will do</h2>
              <ul className="mt-2 divide-y divide-border">
                {status.returns.map((r) => (
                  <li key={r.return} className="py-2">
                    <p className="text-[15px] font-bold text-ink">{r.return}</p>
                    <p className="text-[13px] text-muted">{r.when}</p>
                  </li>
                ))}
              </ul>
            </div>
            <div className={card}>
              <h2 className="text-[17px] font-extrabold text-ink">Anything that looks off</h2>
              {status.issues.length === 0 && <p className="mt-1 text-sm text-muted">Nothing — the answers hang together.</p>}
              <ul className="mt-2 space-y-2">
                {status.issues.map((i) => (
                  <li key={i.code} className={`rounded-xl p-3 text-sm ${i.blocking ? "border border-warn-border bg-warn-tint text-warn-ink" : "bg-ground text-ink"}`}>
                    <p className={i.blocking ? "font-bold" : "font-semibold"}>{i.message}</p>
                    <button type="button" className="mt-1 min-h-11 font-bold text-teal-dark" onClick={() => goStep(steps.indexOf(i.fix_step))}>
                      Fix in {STEP_TITLES[i.fix_step] ?? i.fix_step} →
                    </button>
                  </li>
                ))}
              </ul>
            </div>
            <div className="flex gap-3">
              <button type="button" className={back} onClick={() => goStep(index - 1)}>Back</button>
              <button type="button" disabled={saving || !status.can_continue || done} className={primary} onClick={async () => {
                setSaving(true);
                setError(null);
                try {
                  const s = await runtime.setupWizard.confirm(account!);
                  setStatus(s);
                  setDone(true);
                  setNotice("Saved. Nothing was filed with HMRC or Companies House.");
                } catch (e) {
                  setError(errorText(e));
                } finally {
                  setSaving(false);
                }
              }}>
                {done ? "Confirmed ✓" : "Confirm — file nothing"}
              </button>
            </div>
            <p className="text-xs text-muted">Confirming writes your profile to your OneDrive. {status.filing_note}</p>
            <Link href="/settings" className="inline-block min-h-11 font-bold text-teal-dark">Open Settings →</Link>
          </div>
        )}
      </div>
    </div>
  );
}
