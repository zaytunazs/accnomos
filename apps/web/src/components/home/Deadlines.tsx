"use client";

import { useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { deadlinesQuery, loadBusiness } from "@/lib/business";
import { getMsal, msalConfigured } from "@/lib/msal";
import { runtime, type RtPeriodDeadline } from "@/lib/runtime";
import { deadlines as sampleDeadlines, type Deadline } from "@/lib/sample-home";

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

/** Home deadlines: from GET /books/deadlines when signed in, otherwise the sample. */
export default function Deadlines() {
  const [live, setLive] = useState<{ tiles: Deadline[]; rule: string } | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const query = deadlinesQuery(loadBusiness());
        if (!query || !msalConfigured()) return;
        const msal = await getMsal();
        await msal.handleRedirectPromise().catch(() => null);
        const acct: AccountInfo | undefined = msal.getActiveAccount() ?? msal.getAllAccounts()[0];
        if (!acct) return;
        // Today's date in the UK, not the runtime's time zone (UTC would be a day behind just after midnight BST).
        const today = new Date().toLocaleDateString("en-CA", { timeZone: "Europe/London" });
        const d = await runtime.deadlines(acct, `${query}&today=${today}`);
        setLive({ tiles: toTiles(d.current, d.due), rule: d.rule });
      } catch {
        /* runtime unreachable or token expired: keep the sample */
      }
    })();
  }, []);

  const tiles = live?.tiles ?? sampleDeadlines;
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
              <p className="text-[15px] font-bold leading-snug">{d.title}</p>
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
