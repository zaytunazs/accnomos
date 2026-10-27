"use client";

import { useEffect, useState } from "react";
import {
  DEFAULT_BUSINESS,
  loadBusiness,
  saveBusiness,
  validateVatNumber,
  type Business,
} from "@/lib/business";

const input =
  "mt-1 h-11 w-full rounded-xl border border-border bg-white px-3 text-[15px] text-ink";
const label = "text-xs font-bold text-muted";

/** Settings card: the trading name and VAT number. Saved on this device; invoices pre-fill from it. */
export default function BusinessDetails({ card, heading }: { card: string; heading: string }) {
  const [business, setBusiness] = useState<Business>(DEFAULT_BUSINESS);
  const [vatError, setVatError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    queueMicrotask(() => setBusiness(loadBusiness() ?? DEFAULT_BUSINESS));
  }, []);

  function update(change: Partial<Business>) {
    const next = { ...business, ...change };
    setBusiness(next);
    saveBusiness({ ...next, name: next.name.trim(), vatNumber: next.vatNumber.trim(), email: next.email.trim() });
    setSaved(true);
  }

  return (
    <section aria-labelledby="settings-business" className={card}>
      <h2 id="settings-business" className={heading}>
        Business details
      </h2>
      <p className="mt-1 text-sm text-muted">
        Your trading name and VAT number. Used across Home and pre-filled on your invoices.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <label className={label} htmlFor="settings-business-name">
            Business name
          </label>
          <input
            id="settings-business-name"
            className={input}
            autoComplete="organization"
            value={business.name}
            onChange={(e) => update({ name: e.target.value })}
          />
        </div>
        <div>
          <label className={label} htmlFor="settings-vat-number">
            VAT number
          </label>
          <input
            id="settings-vat-number"
            className={`${input} ${vatError ? "border-warn-border" : ""}`}
            placeholder="GB 123 4567 89"
            autoComplete="off"
            aria-invalid={vatError ? true : undefined}
            aria-describedby={vatError ? "settings-vat-error" : undefined}
            value={business.vatNumber}
            onChange={(e) => {
              update({ vatNumber: e.target.value });
              if (vatError) setVatError(validateVatNumber(e.target.value));
            }}
            onBlur={(e) => {
              if (e.target.value.trim() !== "") setVatError(validateVatNumber(e.target.value));
            }}
          />
          {vatError && (
            <p id="settings-vat-error" role="alert" className="mt-2 text-xs font-semibold text-warn-ink">
              {vatError}
            </p>
          )}
        </div>
      </div>
      {saved && (
        <p role="status" className="mt-2 text-sm font-bold text-teal-dark">
          Saved on this device.
        </p>
      )}
    </section>
  );
}
