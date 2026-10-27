"use client";

import { useEffect, useState } from "react";
import VatStaggerField from "@/components/onboarding/VatStaggerField";
import { DEFAULT_BUSINESS, loadBusiness, saveBusiness, type Business, type VatPeriod } from "@/lib/business";

const PERIODS: { value: VatPeriod; label: string }[] = [
  { value: "quarterly", label: "Quarterly" },
  { value: "monthly", label: "Monthly" },
  { value: "annual", label: "Annual" },
];

/** Settings card: VAT return period and stagger. Saved on this device; Home's deadlines use it. */
export default function VatPeriodSettings({ card, heading }: { card: string; heading: string }) {
  const [business, setBusiness] = useState<Business>(DEFAULT_BUSINESS);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    queueMicrotask(() => setBusiness(loadBusiness() ?? DEFAULT_BUSINESS));
  }, []);

  function update(change: Partial<Business>) {
    const next = { ...business, ...change };
    setBusiness(next);
    saveBusiness(next);
    setSaved(true);
  }

  return (
    <section aria-labelledby="settings-vat-periods" className={card}>
      <h2 id="settings-vat-periods" className={heading}>
        VAT periods
      </h2>
      <div className="mt-3 grid grid-cols-3 gap-2" role="radiogroup" aria-label="VAT return period">
        {PERIODS.map((p) => {
          const active = business.vatPeriod === p.value;
          return (
            <button
              key={p.value}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => update({ vatPeriod: p.value })}
              className={`h-11 rounded-xl border text-[15px] font-bold ${
                active ? "border-2 border-teal bg-teal-tint text-teal-dark" : "border-border text-ink"
              }`}
            >
              {p.label}
            </button>
          );
        })}
      </div>
      {business.vatPeriod === "quarterly" && (
        <div className="mt-3">
          <VatStaggerField
            idPrefix="settings-vat"
            stagger={business.stagger}
            customStartMonth={business.customStartMonth}
            onChange={(stagger, customStartMonth) => update({ stagger, customStartMonth })}
          />
        </div>
      )}
      {business.vatPeriod === "annual" && (
        <p className="mt-3 text-sm text-muted">Annual accounting deadlines are not calculated yet; Home shows sample dates.</p>
      )}
      {saved && (
        <p role="status" className="mt-2 text-sm font-bold text-teal-dark">
          Saved on this device.
        </p>
      )}
    </section>
  );
}
