"use client";

import type { RtPeriodDeadline } from "@/lib/runtime";
import { deadlines as sampleDeadlines, type Deadline } from "@/lib/sample-home";
import { Skeleton, UNKNOWN, useHome } from "./HomeData";

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

/** Home deadlines: the VAT block of GET /books/dashboard when signed in, otherwise the sample. */
export default function Deadlines() {
  const home = useHome();
  const vat = home.mode === "live" && !home.annualVat ? home.data.vat : null;
  const live = vat ? { tiles: toTiles(vat.current, vat.due), rule: vat.rule } : null;
  const tiles: Deadline[] | null =
    home.mode === "sample" ? sampleDeadlines
    : live ? live.tiles
    : home.mode === "live" && home.annualVat ? unknownTiles("Annual VAT returns are not worked out yet")
    : home.mode === "live" || home.mode === "error" ? unknownTiles("Could not work out your VAT period")
    : null;

  if (tiles === null)
    return (
      <section aria-labelledby="deadlines-heading" aria-busy="true" className="flex flex-col gap-3">
        <h2 id="deadlines-heading" className="text-lg font-extrabold tracking-tight">
          Deadlines
        </h2>
        <div className="grid grid-cols-1 gap-3 min-[560px]:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex items-center gap-3 rounded-2xl border border-border bg-white p-4">
              <Skeleton className="h-14 w-14 shrink-0 rounded-xl" />
              <div className="flex min-w-0 flex-col gap-2">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-3 w-24" />
              </div>
            </div>
          ))}
        </div>
      </section>
    );

  return (
    <section aria-labelledby="deadlines-heading" className="flex flex-col gap-3">
      <h2
        id="deadlines-heading"
        className="text-lg font-extrabold tracking-tight"
      >
        Deadlines
      </h2>
      <div className="grid grid-cols-1 gap-3 min-[560px]:grid-cols-3">
        {tiles.map((d) => (
          <div
            key={d.title}
            className="flex items-center gap-3 rounded-2xl border border-border bg-white p-4"
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
              <p className="mt-0.5 text-[13px] font-medium leading-snug text-muted">
                {d.sub}
              </p>
            </div>
          </div>
        ))}
      </div>
      {live && (
        <p className="text-[13px] font-medium text-muted">
          Calculated by code from your approved entries and VAT quarters in Settings. {live.rule}
        </p>
      )}
    </section>
  );
}
