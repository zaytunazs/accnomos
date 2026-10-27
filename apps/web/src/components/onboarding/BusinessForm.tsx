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
import { useNextParam, withNext } from "@/components/connect/ConnectSteps";

const PERIODS: { value: VatPeriod; label: string }[] = [
  { value: "quarterly", label: "Quarterly" },
  { value: "monthly", label: "Monthly" },
  { value: "annual", label: "Annual" },
];

/** Connect step 3: the name, an optional VAT number, and the VAT period — or nothing VAT at all. */
export default function BusinessForm() {
  const router = useRouter();
  const next = useNextParam();
  const [form, setForm] = useState<Business>(DEFAULT_BUSINESS);
  const [nameError, setNameError] = useState<string | null>(null);
  const [vatError, setVatError] = useState<string | null>(null);

  useEffect(() => {
    const saved = loadBusiness();
    if (!saved) return;
    // Defer to avoid a synchronous setState in the effect body.
    queueMicrotask(() => setForm(saved));
  }, []);

  const input =
    "mt-1 h-11 w-full rounded-xl border border-border bg-white px-3 text-[15px] text-ink";
  const label = "text-xs font-bold text-muted";

  function set<K extends keyof Business>(key: K, value: Business[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const nameMessage = form.name.trim() === "" ? "Enter your business name." : null;
    // The VAT number is optional: only a filled-in one is checked.
    const vatMessage =
      !form.vatRegistered || form.vatNumber.trim() === "" ? null : validateVatNumber(form.vatNumber);
    setNameError(nameMessage);
    setVatError(vatMessage);
    if (nameMessage || vatMessage) return;
    saveBusiness({ ...form, name: form.name.trim(), vatNumber: form.vatNumber.trim() });
    router.push(withNext("/connect/ready", next));
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="mt-6 space-y-4">
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

      {form.vatRegistered && (
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
          className="h-12 flex-1 rounded-xl bg-teal px-5 text-[15px] font-extrabold text-white hover:bg-teal-dark"
        >
          Save and continue
        </button>
      </div>
    </form>
  );
}
