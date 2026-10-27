"use client";

import Link from "next/link";
import ExplainMore from "@/components/ExplainMore";
import VatDeadlineStrip from "@/components/vat/VatDeadlineStrip";
import type { RtPeriodDeadline } from "@/lib/runtime";
import { deadlines as sampleDeadlines, type Deadline } from "@/lib/sample-home";
import { SampleTag, Skeleton, UNKNOWN, useHome } from "./HomeData";

const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

/** "2026-11-07" → { month: "NOV", day: "7" } without going through a time zone. */
function calendar(iso: string): Pick<Deadline, "month" | "day"> {
  const [, m, d] = iso.split("-").map(Number);
  return { month: MONTHS[m - 1] ?? "", day: String(d) };
}

function daysLeft(n: number): string {
  if (n === 0) return "Due today";
  if (n < 0) return `${-n} day${n === -1 ? "" : "s"} late`;
  return `${n} day${n === 1 ? "" : "s"} left`;
}

function box5(p: RtPeriodDeadline, soFar: boolean): string {
  const amount = `£${Number(p.box5).toLocaleString("en-GB", { minimumFractionDigits: 2 })}`;
  const prefix = soFar ? "so far" : "estimated";
  if (p.box5_direction === "pay") return `${amount} to pay (${prefix})`;
  if (p.box5_direction === "reclaim") return `${amount} to reclaim (${prefix})`;
  return soFar ? "Nothing to pay so far" : "Nothing to pay on approved entries";
}

/** Three tiles: the return to file next, its payment, and when the current period ends. */
function toTiles(current: RtPeriodDeadline, due: RtPeriodDeadline | null): Deadline[] {
  const next = due ?? current;
  return [
    { ...calendar(next.deadline), title: `VAT return ${next.label} due`, sub: daysLeft(next.days_remaining), tinted: true },
    { ...calendar(next.deadline), title: "VAT payment due", sub: box5(next, next === current) },
    {
      ...calendar(current.end),
      title: `VAT period ${current.label} ends`,
      sub: due ? `Box 5 ${box5(current, true)}` : `${current.entries} approved entr${current.entries === 1 ? "y" : "ies"} so far`,
    },
  ];
}

/** Three "—" tiles when signed in but the VAT period is unknown. */
function unknownTiles(sub: string): Deadline[] {
  return ["VAT return due", "VAT payment due", "VAT period ends"].map((title) => ({ month: "", day: UNKNOWN, title, sub }));
}

function TileSkeleton() {
  return (
    <div className="flex min-h-[5.5rem] items-center gap-3 rounded-2xl border border-border bg-white p-4">
      <Skeleton className="h-14 w-14 shrink-0 rounded-xl" />
      <div className="flex min-w-0 flex-col gap-2">
        <Skeleton className="h-4 w-32 max-w-full" />
        <Skeleton className="h-3 w-24" />
      </div>
    </div>
  );
}

/**
 * Home › Deadlines: the same deadline strip as /vat (one shared component, one
 * GET /books/dashboard VAT block) plus the next three dated items from that
 * payload — the return to file, its payment, and the end of the current period.
 * The Bramblewood sample when signed out.
 */
export default function Deadlines() {
  const home = useHome();
  const sample = home.mode === "sample";
  const vat = home.mode === "live" && !home.annualVat ? home.data.vat : null;
  const live = vat ? { tiles: toTiles(vat.current, vat.due), rule: vat.rule } : null;
  const tiles: Deadline[] | null =
    sample ? sampleDeadlines
    : live ? live.tiles
    : home.mode === "live" && home.annualVat ? unknownTiles("Annual VAT returns are not worked out yet")
    : home.mode === "live" || home.mode === "error" ? unknownTiles("Could not work out your VAT period")
    : null;

  return (
    <section aria-labelledby="deadlines-heading" aria-busy={tiles === null} className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <h2 id="deadlines-heading" className="text-lg font-extrabold tracking-tight">
          Deadlines{sample && <SampleTag />}
        </h2>
        <ExplainMore title="Where the dates come from" anchor="vat-periods">
          The return date, the payment and the period end are worked out by code from your approved entries and
          the VAT quarters in Settings.
        </ExplainMore>
      </div>
      <VatDeadlineStrip />
      {tiles === null ? (
        <div className="grid grid-cols-1 gap-3 min-[560px]:grid-cols-3 md:grid-cols-1">
          {[0, 1, 2].map((i) => <TileSkeleton key={i} />)}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 min-[560px]:grid-cols-3 md:grid-cols-1">
          {tiles.map((d) => (
            <div
              key={d.title}
              className="flex min-h-[5.5rem] items-center gap-3 rounded-2xl border border-border bg-white p-4"
            >
              <div
                aria-hidden="true"
                className={`flex h-14 w-14 shrink-0 flex-col items-center justify-center rounded-xl ${
                  d.tinted ? "bg-teal-tint text-teal-dark" : "bg-ground text-muted"
                }`}
              >
                <span className="text-[11px] font-extrabold tracking-wide">
                  {d.month}
                </span>
                <span className="text-xl font-extrabold leading-none">
                  {d.day}
                </span>
              </div>
              <div className="min-w-0">
                <p className="text-[15px] font-bold leading-snug">
                  {d.month && <span className="sr-only">{d.day} {d.month}: </span>}
                  {d.title}
                </p>
                <p className="mt-0.5 min-h-5 text-[13px] font-medium leading-snug text-muted">
                  {d.sub}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
      {live && (
        <p className="text-[13px] font-medium text-muted">
          Calculated by code from your approved entries and VAT quarters in Settings. {live.rule}
        </p>
      )}
      <div className="mt-auto">
        <Link
          href="/vat"
          className="inline-block whitespace-nowrap rounded-xl bg-teal px-4 py-2 text-sm font-bold text-white hover:bg-teal-dark"
        >
          Open the VAT return
        </Link>
      </div>
    </section>
  );
}
