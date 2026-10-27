"use client";

import { useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { runtime, type RtVatPeriod } from "@/lib/runtime";
import { pickedPeriod, pickPeriod, usePickedPeriod } from "@/lib/vat-period";

const short = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

function optionText(p: RtVatPeriod): string {
  const status =
    p.status === "submitted"
      ? `submitted${p.hmrc_period_key ? ` (${p.hmrc_period_key})` : ""}`
      : p.status === "open"
        ? p.current
          ? "current"
          : `open · due ${short(p.deadline)}`
        : "nothing recorded";
  return `${p.label} · ${status}${p.entries ? ` · ${p.entries} entries` : ""}`;
}

/** The current VAT period and the 8 before it, from GET /books/vat/periods; the pick is shared with the HMRC card and Ask. */
export default function VatPeriodPicker({ account }: { account: AccountInfo }) {
  const picked = usePickedPeriod();
  const [periods, setPeriods] = useState<RtVatPeriod[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    runtime.vatPeriods(account).then(
      (r) => {
        setPeriods(r.periods);
        // A pick from before the VAT settings changed may not be one of these periods any more.
        const was = pickedPeriod();
        const still = r.periods.find((p) => p.period === was?.period && p.start === was?.start);
        if (was && (!still || still.current)) pickPeriod(null);
      },
      () => setFailed(true),
    );
  }, [account]);

  if (failed || !periods) return null;
  const value = picked?.period ?? periods[0].period;
  return (
    <label className="flex flex-wrap items-center gap-2 text-[15px] font-bold">
      VAT period
      <select
        value={value}
        onChange={(e) => {
          const p = periods.find((x) => x.period === e.target.value)!;
          pickPeriod(p.current ? null : { period: p.period, start: p.start, end: p.end, label: p.label });
        }}
        className="h-11 rounded-xl border border-border bg-white px-3 text-[15px] font-semibold focus-visible:outline-2 focus-visible:outline-teal"
      >
        {periods.map((p) => (
          <option key={p.period} value={p.period}>
            {optionText(p)}
          </option>
        ))}
      </select>
    </label>
  );
}
