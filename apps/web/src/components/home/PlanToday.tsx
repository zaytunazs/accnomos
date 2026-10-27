"use client";

import { useEffect, useState } from "react";
import PlanCard, { dayLabel } from "@/components/plan/PlanCard";
import { todayIso, useAccount } from "@/components/jobs/useAccount";

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Home: *Plan today* opens a proposed day. Ask's "Plan my Thursday" links here as `/?plan=YYYY-MM-DD`, which
 * opens that day's plan straight away.
 */
export default function PlanToday() {
  const account = useAccount();
  const [day, setDay] = useState<string | null>(null);

  useEffect(() => {
    const asked = new URLSearchParams(window.location.search).get("plan");
    if (asked && ISO_DAY.test(asked)) queueMicrotask(() => setDay(asked));
  }, []);

  function close() {
    setDay(null);
    if (window.location.search.includes("plan=")) window.history.replaceState(null, "", window.location.pathname);
  }

  if (day && account)
    return (
      <div className="col-span-full">
        <PlanCard account={account} date={day} onClose={close} />
      </div>
    );

  return (
    <section aria-labelledby="plan-today-heading" className="flex flex-col rounded-2xl border border-border bg-white p-4 sm:p-5">
      <h2 id="plan-today-heading" className="text-lg font-extrabold tracking-tight">
        Plan today
      </h2>
      <p className="mt-1 min-h-[3.5rem] text-sm leading-6 text-muted">
        {account === null
          ? "Sign in to plan your day from your calendar and open jobs."
          : day
            ? `Opening the plan for ${dayLabel(day)}…`
            : "Visits grouped by postcode, travel, lunch and admin, around what is already in your calendar."}
      </p>
      <div className="mt-auto pt-4">
        <button
          type="button"
          disabled={!account}
          onClick={() => setDay(todayIso())}
          className="shrink-0 whitespace-nowrap rounded-xl bg-teal px-4 py-2 text-sm font-bold text-white hover:bg-teal-dark disabled:opacity-60"
        >
          Plan today
        </button>
      </div>
    </section>
  );
}
