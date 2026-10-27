"use client";

import { MONTH_NAMES, STAGGER_OPTIONS, type Stagger } from "@/lib/business";

/** Which quarters the VAT returns cover: HMRC stagger 1/2/3, or a custom start month. Shared by onboarding and Settings. */
export default function VatStaggerField({
  stagger,
  customStartMonth,
  onChange,
  idPrefix = "vat",
}: {
  stagger: Stagger;
  customStartMonth: number;
  onChange: (stagger: Stagger, customStartMonth: number) => void;
  idPrefix?: string;
}) {
  const input = "mt-1 h-11 w-full rounded-xl border border-border bg-white px-3 text-[15px] text-ink";
  const label = "text-xs font-bold text-muted";
  return (
    <div className="space-y-3">
      <div>
        <label className={label} htmlFor={`${idPrefix}-stagger`}>
          VAT quarters
        </label>
        <select
          id={`${idPrefix}-stagger`}
          className={input}
          value={stagger}
          onChange={(e) => onChange(e.target.value as Stagger, customStartMonth)}
        >
          {STAGGER_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <p className="mt-2 text-xs text-muted">On your VAT certificate or in your HMRC online account. Used for your deadlines.</p>
      </div>
      {stagger === "custom" && (
        <div>
          <label className={label} htmlFor={`${idPrefix}-start-month`}>
            A VAT period starts in
          </label>
          <select
            id={`${idPrefix}-start-month`}
            className={input}
            value={customStartMonth}
            onChange={(e) => onChange(stagger, Number(e.target.value))}
          >
            {MONTH_NAMES.map((m, i) => (
              <option key={m} value={i + 1}>
                {m}
              </option>
            ))}
          </select>
        </div>
      )}
    </div>
  );
}
