"use client";

import Link from "next/link";
import { Skeleton, useHome } from "@/components/home/HomeData";
import { tileData } from "@/lib/runtime";
import { deadlines as sampleDeadlines } from "@/lib/sample-home";

/** "7 Nov" from "2026-11-07", without going through a time zone. */
function shortUk(iso: string): string {
  const [, m, d] = iso.split("-").map(Number);
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${d} ${months[m - 1] ?? ""}`;
}

function daysText(n: number): string {
  if (n === 0) return "Due today";
  if (n < 0) return `${-n} day${n === -1 ? "" : "s"} overdue`;
  return `${n} day${n === 1 ? "" : "s"} left`;
}

/**
 * Deadline strip at the top of /vat, from the same GET /books/dashboard VAT block as Home's
 * Deadlines (the Bramblewood sample when signed out): the next return, days left, and an
 * "Add to calendar" link that opens Home's day planner on the due date — Apply there adds the
 * deadline to the Outlook calendar. Nothing is written from here.
 */
export default function VatDeadlineStrip() {
  const home = useHome();

  if (home.mode === "checking" || home.mode === "loading") {
    return (
      <section aria-label="VAT deadline" aria-busy="true" className="rounded-2xl border border-border bg-white px-4 py-3">
        <Skeleton className="h-5 w-64 max-w-full" />
      </section>
    );
  }

  if (home.mode === "sample") {
    const [first] = sampleDeadlines;
    return (
      <Strip title={first.title} sub={first.sub} plan="2026-11-07" />
    );
  }

  if (home.mode === "live" && !home.annualVat && tileData(home.data.vat)) {
    const vat = tileData(home.data.vat)!;
    const next = vat.due ?? vat.current;
    return (
      <Strip
        title={`VAT return ${next.label} due ${shortUk(next.deadline)}`}
        sub={daysText(next.days_remaining)}
        plan={next.deadline}
      />
    );
  }

  if (home.mode === "live" && home.annualVat) {
    return <Strip title="VAT return due" sub="Annual VAT returns are not worked out yet" plan={null} />;
  }

  return <Strip title="VAT return due" sub="Could not work out your VAT period" plan={null} />;
}

function Strip({ title, sub, plan }: { title: string; sub: string; plan: string | null }) {
  return (
    <section aria-label="VAT deadline" className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-2xl border border-border bg-white px-4 py-3">
      <p className="min-w-0 text-[15px]">
        <strong>{title}</strong> <span className="text-muted">· {sub}</span>
      </p>
      {plan ? (
        <Link
          href={`/?plan=${plan}`}
          title="Open the day planner on the due date; Apply adds the deadline to your Outlook calendar"
          className="shrink-0 rounded-xl border border-border bg-white px-4 py-2 text-sm font-bold text-teal-dark underline underline-offset-2 hover:bg-ground"
        >
          Add to calendar
        </Link>
      ) : null}
    </section>
  );
}
