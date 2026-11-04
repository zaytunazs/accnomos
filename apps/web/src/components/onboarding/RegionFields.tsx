"use client";

import { useId, useMemo, useState } from "react";
import {
  COUNTRIES,
  CURRENCIES,
  TAX_NAMES,
  UK,
  countryName,
  defaultCurrency,
  defaultTax,
  type TaxName,
} from "@/lib/region";

/** Where the books are kept: the answers lib/region.ts and the runtime's profile (`country`, `sales_tax`, `currency`)
 *  take. UK books need nothing else here; HMRC's questions stay where they were. */
export interface RegionAnswers {
  country: string;
  taxName: TaxName;
  taxRate: number;
  currency: string;
}

export const UK_ANSWERS: RegionAnswers = { country: UK, taxName: "VAT", taxRate: 20, currency: "GBP" };

/** The answers a newly chosen country starts from: its usual tax, rate and currency. */
export function answersFor(country: string): RegionAnswers {
  if (country === UK) return UK_ANSWERS;
  const tax = defaultTax(country);
  return { country, taxName: tax.name, taxRate: tax.rate, currency: defaultCurrency(country) };
}

/** The profile settings for these answers (PUT /profile); UK books send only the country. */
export function regionSettings(a: RegionAnswers): {
  country: string;
  currency?: string;
  sales_tax?: { name: TaxName; rate_percent: number };
} {
  if (a.country === UK) return { country: UK };
  return {
    country: a.country,
    currency: a.currency,
    sales_tax: { name: a.taxName, rate_percent: a.taxName === "None" ? 0 : a.taxRate },
  };
}

/** A sentence when the answers cannot be saved, else null. */
export function regionProblem(a: RegionAnswers): string | null {
  if (a.country === UK) return null;
  if (!a.currency) return "Choose the currency your books are kept in.";
  if (a.taxName !== "None" && !(a.taxRate >= 0 && a.taxRate <= 100)) return "Enter a percentage from 0 to 100.";
  return null;
}

const input = "mt-1 h-11 w-full rounded-xl border border-border bg-white px-3 text-[15px] text-ink";
const label = "text-xs font-bold text-muted";

/**
 * Country first (searchable, the UK by default); outside the UK: "Do you charge VAT, GST or sales tax?", "What
 * percentage?" (prefilled with the country's usual rate) and the currency (prefilled where known).
 */
export default function RegionFields({
  value,
  onChange,
  card = "rounded-2xl border border-border bg-white p-4",
}: {
  value: RegionAnswers;
  onChange: (next: RegionAnswers) => void;
  card?: string;
}) {
  const ids = useId();
  const [search, setSearch] = useState("");
  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    const hits = q ? COUNTRIES.filter(([c, n]) => n.toLowerCase().includes(q) || c.toLowerCase() === q) : COUNTRIES;
    // the chosen country always stays in the list, so the select never shows the wrong one
    return hits.some(([c]) => c === value.country) ? hits : [[value.country, countryName(value.country)] as const, ...hits];
  }, [search, value.country]);
  const abroad = value.country !== UK;

  return (
    <>
      <div className={card}>
        <label className={label} htmlFor={`${ids}-country`}>
          Country
        </label>
        <input
          type="search"
          className={input}
          aria-label="Search countries"
          placeholder="Search countries"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            const q = e.target.value.trim().toLowerCase();
            const exact = COUNTRIES.find(([, n]) => n.toLowerCase() === q);
            if (exact && exact[0] !== value.country) onChange(answersFor(exact[0]));
          }}
        />
        <select
          id={`${ids}-country`}
          className={input}
          value={value.country}
          onChange={(e) => onChange(answersFor(e.target.value))}
        >
          {shown.map(([c, n]) => (
            <option key={c} value={c}>
              {n}
            </option>
          ))}
        </select>
        <p className="mt-2 text-xs text-muted">
          {abroad
            ? "Bookkeeping, invoices, reports and CSV exports work the same everywhere. HMRC filing (VAT returns, payroll, MTD) is for UK books, so it stays hidden."
            : "UK books: VAT returns, payroll and MTD filing with HMRC are all here."}
        </p>
      </div>

      {abroad && (
        <>
          <fieldset className={card}>
            <legend className={label}>Do you charge VAT, GST or sales tax?</legend>
            <div className="mt-2 grid grid-cols-2 gap-2" role="radiogroup" aria-label="Do you charge VAT, GST or sales tax?">
              {TAX_NAMES.map((t) => {
                const active = value.taxName === t.value;
                return (
                  <button
                    key={t.value}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    onClick={() => onChange({ ...value, taxName: t.value })}
                    className={`min-h-11 rounded-xl border px-2 text-[15px] font-bold ${
                      active ? "border-2 border-teal bg-teal-tint text-teal-dark" : "border-border text-ink"
                    }`}
                  >
                    {t.label}
                  </button>
                );
              })}
            </div>
          </fieldset>

          {value.taxName !== "None" && (
            <div className={card}>
              <label className={label} htmlFor={`${ids}-rate`}>
                What percentage?
              </label>
              <input
                id={`${ids}-rate`}
                className={input}
                type="number"
                inputMode="decimal"
                min={0}
                max={100}
                step="any"
                value={Number.isFinite(value.taxRate) ? value.taxRate : ""}
                onChange={(e) => onChange({ ...value, taxRate: e.target.value === "" ? NaN : Number(e.target.value) })}
              />
              <p className="mt-2 text-xs text-muted">
                Your standard rate. New invoice lines use it, and receipts are checked against it.
              </p>
            </div>
          )}

          <div className={card}>
            <label className={label} htmlFor={`${ids}-currency`}>
              Currency
            </label>
            <select
              id={`${ids}-currency`}
              className={input}
              value={value.currency}
              onChange={(e) => onChange({ ...value, currency: e.target.value })}
            >
              {!value.currency && <option value="">Choose a currency</option>}
              {CURRENCIES.map(([c, n]) => (
                <option key={c} value={c}>
                  {n} ({c})
                </option>
              ))}
            </select>
          </div>
        </>
      )}
    </>
  );
}
