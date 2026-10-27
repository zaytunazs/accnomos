"use client";

import { useEffect, useState } from "react";
import { DEFAULT_BUSINESS, loadBusiness, saveBusiness, type Business } from "@/lib/business";

/** Settings › Business: the day planner's default working hours and visit limit. Saved on this device. */
export default function WorkingHours({ card, heading }: { card: string; heading: string }) {
  const [business, setBusiness] = useState<Business>(DEFAULT_BUSINESS);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    queueMicrotask(() => setBusiness(loadBusiness() ?? DEFAULT_BUSINESS));
  }, []);

  function update(change: Partial<Business>) {
    const next = { ...business, ...change };
    setBusiness(next);
    if (!next.workStart || !next.workEnd || next.workStart >= next.workEnd) {
      setNote("The working day must end after it starts.");
      return;
    }
    saveBusiness(next);
    setNote("Saved on this device.");
  }

  const input = "h-11 rounded-xl border border-border px-3 font-normal";
  return (
    <section aria-labelledby="settings-business-hours" className={card}>
      <h2 id="settings-business-hours" className={heading}>
        Business · working hours
      </h2>
      <p className="mt-1 text-sm text-muted">Used when you plan a day: visits, travel and lunch fit inside these hours.</p>
      <div className="mt-3 flex flex-wrap gap-3">
        <label className="flex flex-col gap-1 text-sm font-bold text-ink">
          Start
          <input type="time" step={900} value={business.workStart} onChange={(e) => update({ workStart: e.target.value })} className={input} />
        </label>
        <label className="flex flex-col gap-1 text-sm font-bold text-ink">
          Finish
          <input type="time" step={900} value={business.workEnd} onChange={(e) => update({ workEnd: e.target.value })} className={input} />
        </label>
        <label className="flex flex-col gap-1 text-sm font-bold text-ink">
          Most visits a day
          <input
            type="number"
            min={1}
            max={12}
            value={business.maxVisits}
            onChange={(e) => update({ maxVisits: Math.min(12, Math.max(1, Math.round(Number(e.target.value) || 1))) })}
            className={`${input} w-28`}
          />
        </label>
      </div>
      {note && (
        <p role="status" className="mt-2 text-sm font-bold text-teal-dark">
          {note}
        </p>
      )}
    </section>
  );
}
