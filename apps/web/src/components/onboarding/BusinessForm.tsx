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
  type PeriodEnd,
  type VatPeriod,
} from "@/lib/business";

const PERIODS: { value: VatPeriod; label: string }[] = [
  { value: "quarterly", label: "Quarterly" },
  { value: "monthly", label: "Monthly" },
  { value: "annual", label: "Annual" },
];

const PERIOD_ENDS: PeriodEnd[] = ["Mar/Jun/Sep/Dec", "Jan/Apr/Jul/Oct", "Feb/May/Aug/Nov"];

export default function BusinessForm() {
  const router = useRouter();
  const [form, setForm] = useState<Business>(DEFAULT_BUSINESS);
  const [vatError, setVatError] = useState<string | null>(null);
  const [emailError, setEmailError] = useState<string | null>(null);

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
    const vatMessage = validateVatNumber(form.vatNumber);
    const emailMessage =
      form.email.trim() === "" || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim())
        ? null
        : "Enter a valid email address.";
    setVatError(vatMessage);
    setEmailError(emailMessage);
    if (vatMessage || emailMessage) return;
    saveBusiness({ ...form, name: form.name.trim(), vatNumber: form.vatNumber.trim(), email: form.email.trim() });
    router.push("/connect/ready");
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="mt-6 space-y-4">
      <div className="rounded-2xl border border-border bg-white p-4">
        <label className={label} htmlFor="business-name">
          Business name
        </label>
        <input
          id="business-name"
          className={input}
          autoComplete="organization"
          value={form.name}
          onChange={(e) => set("name", e.target.value)}
        />
      </div>

      <div className="rounded-2xl border border-border bg-white p-4">
        <label className={label} htmlFor="vat-number">
          VAT number
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
            if (vatError) setVatError(validateVatNumber(e.target.value));
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
            Found on your VAT certificate; we check the format
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
          <label className={label} htmlFor="period-end">
            Period ends
          </label>
          <select
            id="period-end"
            className={input}
            value={form.periodEnd}
            onChange={(e) => set("periodEnd", e.target.value as PeriodEnd)}
          >
            {PERIOD_ENDS.map((end) => (
              <option key={end} value={end}>
                {end}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="rounded-2xl border border-border bg-white p-4">
        <div className="flex items-center justify-between gap-3">
          <label className="text-[15px] font-extrabold text-ink" htmlFor="flat-rate">
            Flat rate scheme?
          </label>
          <button
            id="flat-rate"
            type="button"
            role="switch"
            aria-checked={form.flatRate}
            onClick={() => set("flatRate", !form.flatRate)}
            className={`relative h-7 w-12 shrink-0 rounded-full transition-colors ${
              form.flatRate ? "bg-teal" : "bg-border"
            }`}
          >
            <span
              aria-hidden="true"
              className={`absolute top-1 h-5 w-5 rounded-full bg-white shadow transition-all ${
                form.flatRate ? "left-6" : "left-1"
              }`}
            />
          </button>
        </div>
        <p className="mt-1 text-xs text-muted">Not supported yet — standard scheme only</p>
      </div>

      <div className="rounded-2xl border border-border bg-white p-4">
        <label className={label} htmlFor="contact-email">
          Contact email
        </label>
        <input
          id="contact-email"
          type="email"
          className={`${input} ${emailError ? "border-warn-border" : ""}`}
          autoComplete="email"
          aria-invalid={emailError ? true : undefined}
          aria-describedby={emailError ? "email-error" : undefined}
          value={form.email}
          onChange={(e) => {
            set("email", e.target.value);
            if (emailError) setEmailError(null);
          }}
        />
        {emailError && (
          <p id="email-error" role="alert" className="mt-2 text-xs font-semibold text-warn-ink">
            {emailError}
          </p>
        )}
      </div>

      <div className="flex flex-wrap gap-3">
        <Link
          href="/connect/ai"
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
