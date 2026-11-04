"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  DEFAULT_BUSINESS,
  loadBusiness,
  saveBusiness,
  validateVatNumber,
  type Business,
  type VatPeriod,
} from "@/lib/business";
import VatStaggerField from "@/components/onboarding/VatStaggerField";
import RegionFields, {
  UK_ANSWERS,
  regionProblem,
  regionSettings,
  type RegionAnswers,
} from "@/components/onboarding/RegionFields";
import { useNextParam, withNext } from "@/components/connect/ConnectSteps";
import { errorText, useAccount } from "@/components/jobs/useAccount";
import { rememberProfile } from "@/lib/profiles";
import { runtime } from "@/lib/runtime";

const PERIODS: { value: VatPeriod; label: string }[] = [
  { value: "quarterly", label: "Quarterly" },
  { value: "monthly", label: "Monthly" },
  { value: "annual", label: "Annual" },
];

/**
 * Connect step 3: the country first (the UK unless chosen), then for UK books the name, an optional VAT number and
 * the VAT period (or nothing VAT at all); for books elsewhere the tax they charge, its rate and the currency, saved
 * to the books' own profile (GET/PUT /profile `country`, `sales_tax`, `currency`), so HMRC's pages stay hidden.
 */
export default function BusinessForm() {
  const router = useRouter();
  const next = useNextParam();
  const account = useAccount();
  const [form, setForm] = useState<Business>(DEFAULT_BUSINESS);
  const [region, setRegion] = useState<RegionAnswers>(UK_ANSWERS);
  const [wasAbroad, setWasAbroad] = useState(false);
  const [nameError, setNameError] = useState<string | null>(null);
  const [vatError, setVatError] = useState<string | null>(null);
  const [regionError, setRegionError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const abroad = region.country !== UK_ANSWERS.country;

  useEffect(() => {
    const saved = loadBusiness();
    if (!saved) return;
    // Defer to avoid a synchronous setState in the effect body.
    queueMicrotask(() => setForm(saved));
  }, []);

  useEffect(() => {
    if (!account) return;
    runtime.profile(account).then(
      (p) => {
        const r = p.region;
        if (r && !r.uk) {
          setWasAbroad(true);
          setRegion({
            country: r.country,
            taxName: (p.settings.sales_tax?.name ?? "Sales tax") as RegionAnswers["taxName"],
            taxRate: r.tax_rate_percent,
            currency: r.currency,
          });
        }
      },
      () => undefined, // no profile to read yet: the UK, as before
    );
  }, [account]);

  const input =
    "mt-1 h-11 w-full rounded-xl border border-border bg-white px-3 text-[15px] text-ink";
  const label = "text-xs font-bold text-muted";

  function set<K extends keyof Business>(key: K, value: Business[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  /** Books outside the UK (or moving back to it): the country, tax and currency go to the books' own profile. */
  async function saveRegion(): Promise<string | null> {
    if (!account || (!abroad && !wasAbroad)) return null; // UK books: nothing changes, as before
    try {
      const p = await runtime.profile(account);
      const settings = { ...p.settings };
      delete settings.country;
      delete settings.currency;
      delete settings.sales_tax;
      const saved = await runtime.saveProfile(account, {
        name: p.exists ? p.name : form.name.trim() || p.name,
        kind: p.kind,
        settings: { ...settings, ...regionSettings(region) },
      });
      rememberProfile(account.homeAccountId, saved);
      return null;
    } catch (err) {
      return errorText(err);
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const nameMessage = form.name.trim() === "" ? "Enter your business name." : null;
    // The VAT number is optional: only a filled-in one is checked. Outside the UK there is no UK VAT number.
    const vatMessage =
      abroad || !form.vatRegistered || form.vatNumber.trim() === "" ? null : validateVatNumber(form.vatNumber);
    const regionMessage = regionProblem(region);
    setNameError(nameMessage);
    setVatError(vatMessage);
    setRegionError(regionMessage);
    if (nameMessage || vatMessage || regionMessage) return;
    setSaving(true);
    const problem = await saveRegion();
    setSaving(false);
    if (problem) {
      setRegionError(problem);
      return;
    }
    saveBusiness({
      ...form,
      name: form.name.trim(),
      vatNumber: abroad ? "" : form.vatNumber.trim(),
      vatRegistered: abroad ? false : form.vatRegistered,
    });
    router.push(withNext("/connect/ready", next));
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="mt-6 space-y-4">
      <RegionFields value={region} onChange={(r) => {
          setRegion(r);
          setRegionError(null);
        }} />
      {regionError && (
        <p role="alert" className="text-xs font-semibold text-warn-ink">
          {regionError}
        </p>
      )}
      <div className="rounded-2xl border border-border bg-white p-4">
        <label className={label} htmlFor="business-name">
          Business name
        </label>
        <input
          id="business-name"
          className={`${input} ${nameError ? "border-warn-border" : ""}`}
          autoComplete="organization"
          aria-invalid={nameError ? true : undefined}
          aria-describedby={nameError ? "business-name-error" : undefined}
          value={form.name}
          onChange={(e) => {
            set("name", e.target.value);
            if (nameError && e.target.value.trim() !== "") setNameError(null);
          }}
        />
        {nameError && (
          <p id="business-name-error" role="alert" className="mt-2 text-xs font-semibold text-warn-ink">
            {nameError}
          </p>
        )}
      </div>

      {!abroad && (
      <div className="rounded-2xl border border-border bg-white p-4">
        <label className="flex cursor-pointer items-start gap-3" htmlFor="not-vat-registered">
          <input
            id="not-vat-registered"
            type="checkbox"
            className="mt-0.5 h-5 w-5 shrink-0 accent-teal"
            checked={!form.vatRegistered}
            onChange={(e) => {
              set("vatRegistered", !e.target.checked);
              if (e.target.checked) setVatError(null);
            }}
          />
          <span>
            <span className="text-[15px] font-extrabold text-ink">I&apos;m not VAT-registered</span>
            <span className="mt-0.5 block text-xs text-muted">
              Tick this if you don&apos;t charge VAT — the VAT steps stay hidden.
            </span>
          </span>
        </label>
      </div>

      )}

      {!abroad && form.vatRegistered && (
        <>
          <div className="rounded-2xl border border-border bg-white p-4">
            <label className={label} htmlFor="vat-number">
              VAT number <span className="font-normal">(optional)</span>
            </label>
            <input
              id="vat-number"
              className={`${input} ${vatError ? "border-warn-border" : ""}`}
              placeholder="GB 123 4567 89"
              autoComplete="off"
              inputMode="text"
              aria-invalid={vatError ? true : undefined}
              aria-describedby={vatError ? "vat-error" : "vat-help"}
              value={form.vatNumber}
              onChange={(e) => {
                set("vatNumber", e.target.value);
                if (vatError) setVatError(e.target.value.trim() === "" ? null : validateVatNumber(e.target.value));
              }}
              onBlur={(e) => {
                if (e.target.value.trim() !== "") setVatError(validateVatNumber(e.target.value));
              }}
            />
            {vatError ? (
              <p id="vat-error" role="alert" className="mt-2 text-xs font-semibold text-warn-ink">
                {vatError}
              </p>
            ) : (
              <p id="vat-help" className="mt-2 text-xs text-muted">
                Leave it blank if you don&apos;t know it yet — found on your VAT certificate
              </p>
            )}
          </div>

          <fieldset className="rounded-2xl border border-border bg-white p-4">
            <legend className={label}>VAT return period</legend>
            <div className="mt-2 grid grid-cols-3 gap-2" role="radiogroup" aria-label="VAT return period">
              {PERIODS.map((p) => {
                const active = form.vatPeriod === p.value;
                return (
                  <button
                    key={p.value}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    onClick={() => set("vatPeriod", p.value)}
                    className={`h-11 rounded-xl border text-[15px] font-bold ${
                      active ? "border-2 border-teal bg-teal-tint text-teal-dark" : "border-border text-ink"
                    }`}
                  >
                    {p.label}
                  </button>
                );
              })}
            </div>
          </fieldset>

          {form.vatPeriod === "quarterly" && (
            <div className="rounded-2xl border border-border bg-white p-4">
              <VatStaggerField
                stagger={form.stagger}
                customStartMonth={form.customStartMonth}
                onChange={(stagger, customStartMonth) => setForm((prev) => ({ ...prev, stagger, customStartMonth }))}
              />
            </div>
          )}
        </>
      )}

      <div className="flex flex-wrap gap-3">
        <Link
          href={withNext("/connect/ai", next)}
          className="inline-flex h-12 items-center rounded-xl border border-border bg-white px-5 text-[15px] font-bold text-ink"
        >
          Back
        </Link>
        <button
          type="submit"
          disabled={saving}
          className="h-12 flex-1 rounded-xl bg-teal px-5 text-[15px] font-extrabold text-white hover:bg-teal-dark"
        >
          {saving ? "Saving…" : "Save and continue"}
        </button>
      </div>
    </form>
  );
}
