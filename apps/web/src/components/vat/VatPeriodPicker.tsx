"use client";

import { useEffect, useRef, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { runtime, type RtVatPeriod } from "@/lib/runtime";
import { periodFromUrl, pickedPeriod, pickPeriod, usePickedPeriod, type PickedPeriod } from "@/lib/vat-period";

const short = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

const CHIP: Record<RtVatPeriod["status"], { text: string; className: string }> = {
  open: { text: "Open", className: "bg-teal-tint text-teal-dark" },
  submitted: { text: "Submitted", className: "bg-ground text-muted" },
  none: { text: "None", className: "bg-ground text-muted" },
};

function detail(p: RtVatPeriod): string {
  const bits: string[] = [];
  if (p.current) bits.push("current period");
  else if (p.status === "open") bits.push(`due ${short(p.deadline)}`);
  else if (p.status === "submitted") bits.push(p.hmrc_period_key ? `filed as ${p.hmrc_period_key}` : "filed");
  else bits.push("nothing recorded");
  if (p.entries) bits.push(`${p.entries} ${p.entries === 1 ? "entry" : "entries"}`);
  return bits.join(" · ");
}

const toPick = (p: RtVatPeriod): PickedPeriod | null =>
  p.current ? null : { period: p.period, start: p.start, end: p.end, label: p.label };

/**
 * The current VAT period and the 8 before it, from GET /books/vat/periods, as a segmented
 * radio list with status chips; the pick is shared with the HMRC card and Ask, and mirrored in
 * `?period=` so a period can be linked. Arrow keys move through the periods.
 */
export default function VatPeriodPicker({ account, onPeriods }: { account: AccountInfo; onPeriods?: (periods: RtVatPeriod[]) => void }) {
  const picked = usePickedPeriod();
  const [periods, setPeriods] = useState<RtVatPeriod[] | null>(null);
  const [failed, setFailed] = useState(false);
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const onPeriodsRef = useRef(onPeriods);
  onPeriodsRef.current = onPeriods;

  useEffect(() => {
    runtime.vatPeriods(account).then(
      (r) => {
        setPeriods(r.periods);
        onPeriodsRef.current?.(r.periods);
        const byName = (name: string | null) => r.periods.find((p) => p.period === name);
        // A linked ?period= wins over the remembered pick; a stale pick is cleared.
        const linked = byName(periodFromUrl());
        if (linked) {
          if (linked.current ? pickedPeriod() !== null : pickedPeriod()?.period !== linked.period) pickPeriod(toPick(linked));
        } else {
          const was = pickedPeriod();
          const still = was && byName(was.period);
          if ((was && !still) || still?.current) pickPeriod(null);
        }
      },
      () => setFailed(true),
    );
  }, [account]);

  if (failed || !periods) return null;
  const value = picked?.period ?? periods[0].period;
  const focus = Math.max(0, periods.findIndex((p) => p.period === value));

  function choose(i: number) {
    const p = periods![(i + periods!.length) % periods!.length];
    pickPeriod(toPick(p));
    buttons.current[periods!.indexOf(p)]?.focus();
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown" || e.key === "ArrowRight") {
      e.preventDefault();
      choose(focus + 1);
    } else if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
      e.preventDefault();
      choose(focus - 1);
    } else if (e.key === "Home") {
      e.preventDefault();
      choose(0);
    } else if (e.key === "End") {
      e.preventDefault();
      choose(periods.length - 1);
    }
  }

  return (
    <div>
      <p id="vat-period-label" className="text-[15px] font-bold">
        VAT period
      </p>
      <div
        role="radiogroup"
        aria-labelledby="vat-period-label"
        onKeyDown={onKeyDown}
        className="mt-1 flex max-w-full flex-col gap-1"
      >
        {periods.map((p, i) => {
          const selected = p.period === value;
          const chip = CHIP[p.status];
          return (
            <button
              key={p.period}
              ref={(el) => {
                buttons.current[i] = el;
              }}
              type="button"
              role="radio"
              aria-checked={selected}
              tabIndex={i === focus ? 0 : -1}
              onClick={() => pickPeriod(toPick(p))}
              className={`flex min-h-11 flex-wrap items-center gap-x-2 gap-y-0.5 rounded-xl border px-3 py-1.5 text-left text-[14px] ${
                selected ? "border-teal bg-teal-tint" : "border-border bg-white hover:bg-ground"
              }`}
            >
              <span className="font-extrabold">{p.label}</span>
              <span className={`rounded-full px-2 py-0.5 text-[11px] font-extrabold ${chip.className}`}>
                {chip.text}
              </span>
              <span className="text-[13px] font-medium text-muted">{detail(p)}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
