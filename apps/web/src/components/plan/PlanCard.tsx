"use client";

import { useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { Markdown } from "@/components/ask/AnswerCard";
import { errorText } from "@/components/jobs/useAccount";
import { loadBusiness, planVat } from "@/lib/business";
import { runtime, type RtPlan, type RtPlanApplied, type RtPlanItem } from "@/lib/runtime";

const KIND: Record<RtPlanItem["kind"], { label: string; chip: string }> = {
  visit: { label: "Visit", chip: "bg-teal-tint text-teal-dark" },
  travel: { label: "Travel", chip: "bg-ground text-muted" },
  lunch: { label: "Lunch", chip: "bg-ground text-muted" },
  admin: { label: "Admin", chip: "bg-warn-bg text-warn-ink" },
  existing: { label: "In your calendar", chip: "border border-border text-muted" },
};

const added = (a: RtPlanApplied) => a.created.filter((c) => !c.reused).length;

/** "14:30" in UK time, whatever the device's time zone. */
const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/London" });

/** "Thursday 29 October" from "2026-10-29", without going through a time zone. */
export function dayLabel(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", {
    weekday: "long", day: "numeric", month: "long", timeZone: "UTC",
  });
}

/**
 * A proposed day from POST /plan/day: timeline, rationale and warnings, then Apply (creates the new items as
 * Outlook events, asking for Calendars.ReadWrite only then) or Discard. Nothing is written until Apply.
 */
export default function PlanCard({
  account,
  date,
  jobIds,
  onClose,
}: {
  account: AccountInfo;
  date: string;
  jobIds?: string[];
  onClose: () => void;
}) {
  const [plan, setPlan] = useState<RtPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [applied, setApplied] = useState<RtPlanApplied | null>(null);
  const jobKey = jobIds?.join(",") ?? "";

  useEffect(() => {
    let live = true;
    queueMicrotask(async () => {
      setPlan(null);
      setApplied(null);
      setError(null);
      const business = loadBusiness();
      try {
        const p = await runtime.planDay(account, {
          date,
          constraints: business ? { start: business.workStart, end: business.workEnd, max_visits: business.maxVisits } : undefined,
          vat: planVat(business),
          ...(jobKey ? { job_ids: jobKey.split(",") } : {}),
        });
        if (live) setPlan(p);
      } catch (e) {
        if (live) setError(errorText(e));
      }
    });
    return () => {
      live = false;
    };
  }, [account, date, jobKey]);

  async function apply() {
    if (!plan) return;
    setApplying(true);
    setError(null);
    try {
      setApplied(await runtime.applyPlan(account, plan.date, plan.plan));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setApplying(false);
    }
  }

  const fresh = plan?.plan.filter((i) => i.kind !== "existing") ?? [];
  const card = "rounded-2xl border border-border bg-white p-5";

  return (
    <article className={card} aria-labelledby="plan-heading" aria-busy={!plan && !error}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="plan-heading" className="text-lg font-extrabold tracking-tight">
            Plan for {dayLabel(date)}
          </h2>
          <p className="mt-0.5 text-[13px] font-medium text-muted">
            Order and times worked out by code from your calendar and open jobs.
          </p>
        </div>
        <button type="button" onClick={onClose} className="text-sm font-bold text-muted hover:text-ink">
          Close
        </button>
      </div>

      {!plan && !error && <p className="mt-4 text-sm text-muted">Reading your calendar and jobs…</p>}

      {plan && (
        <>
          {plan.plan.length === 0 ? (
            <p className="mt-4 text-sm text-muted">Nothing to plan for this day.</p>
          ) : (
            <ol className="mt-4 divide-y divide-border" aria-label="Timeline">
              {plan.plan.map((i) => (
                <li
                  key={`${i.kind}-${i.start}-${i.title}`}
                  className={`flex items-baseline gap-3 py-2.5 ${i.kind === "existing" ? "opacity-70" : ""}`}
                >
                  <span className="w-28 shrink-0 font-mono text-[13px] tabular-nums text-ink">
                    {clock(i.start)}–{clock(i.end)}
                  </span>
                  <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-extrabold ${KIND[i.kind].chip}`}>
                    {KIND[i.kind].label}
                  </span>
                  <span className="min-w-0">
                    <span className={`block text-[15px] ${i.kind === "visit" ? "font-bold" : ""}`}>{i.title}</span>
                    {i.location && <span className="block text-[13px] text-muted">{i.location}</span>}
                  </span>
                </li>
              ))}
            </ol>
          )}

          <div className="mt-4 rounded-xl bg-ground p-4 text-[14px] leading-6">
            <Markdown md={plan.rationale_md} />
            <p className="mt-2 text-[12px] text-muted">
              {plan.fallback_reason ?? `Words by ${plan.model}, checked against the plan's times.`}
            </p>
          </div>

          {plan.warnings.length > 0 && (
            <ul className="mt-3 flex flex-col gap-1 rounded-xl border border-warn-border bg-warn-bg p-3 text-[14px] text-warn-ink">
              {plan.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}

          {applied ? (
            <div role="status" className="mt-4 text-[14px] font-bold text-teal-dark">
              {applied.already_applied
                ? "This plan is already in your calendar."
                : `Added ${added(applied)} event${added(applied) === 1 ? "" : "s"} to your calendar, each marked [Accnomos].`}
              {applied.mileage_proposals.length > 0 && (
                <div className="mt-3 font-medium text-ink">
                  <p className="font-bold">Mileage to confirm ({applied.mileage_proposals.length} trips)</p>
                  <ul className="mt-1 list-disc pl-5 text-[13px]">
                    {applied.mileage_proposals.map((m) => (
                      <li key={`${m.job_id}-${m.to_district}`}>
                        {m.from_district ?? "Start"} → {m.to_district ?? "site"}: miles to add
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ) : (
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={apply}
                disabled={applying || fresh.length === 0}
                className="h-11 rounded-xl bg-teal px-5 text-[15px] font-extrabold text-white hover:bg-teal-dark disabled:opacity-60"
              >
                {applying ? "Adding…" : `Apply: add ${fresh.length} event${fresh.length === 1 ? "" : "s"} to Outlook`}
              </button>
              <button
                type="button"
                onClick={onClose}
                className="h-11 rounded-xl border border-border px-5 text-[15px] font-bold text-ink hover:bg-ground"
              >
                Discard
              </button>
            </div>
          )}
        </>
      )}

      {error && (
        <p role="alert" className="mt-4 text-sm font-bold text-warn-ink">
          {error}
        </p>
      )}
    </article>
  );
}
