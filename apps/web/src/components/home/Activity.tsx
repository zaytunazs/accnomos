"use client";

import { activity as sampleActivity, type ActivityItem } from "@/lib/sample-home";
import { Skeleton, useHome } from "./HomeData";
import type { RtDashboard } from "@/lib/runtime";

const LONDON = { timeZone: "Europe/London" } as const;

/** "17:42" for today (UK time), "26 Oct" before that. */
function when(iso: string, today: string): string {
  const d = new Date(iso);
  if (d.toLocaleDateString("en-CA", LONDON) === today)
    return d.toLocaleTimeString("en-GB", { ...LONDON, hour: "2-digit", minute: "2-digit" });
  return d.toLocaleDateString("en-GB", { ...LONDON, day: "numeric", month: "short" });
}

function liveItems(d: RtDashboard): ActivityItem[] {
  return d.activity.map((a) => ({
    time: when(a.at, d.today), text: a.text, actor: a.actor, dot: a.tone === "warn" ? "amber" : "teal",
  }));
}

/** What happened lately: the last ten audit lines when signed in, the sample when signed out. */
export default function Activity() {
  const home = useHome();
  const items = home.mode === "sample" ? sampleActivity : home.mode === "live" ? liveItems(home.data) : null;
  const heading = home.mode === "sample" ? "What the agents did today" : "Recent activity";

  return (
    <section
      aria-labelledby="activity-heading"
      aria-busy={items === null && home.mode !== "error"}
      className="rounded-2xl border border-border bg-white p-5"
    >
      <h2
        id="activity-heading"
        className="text-lg font-extrabold tracking-tight"
      >
        {heading}
      </h2>
      {home.mode === "error" ? (
        <p className="mt-3 text-sm font-medium text-muted">— Could not reach your books: {home.message}</p>
      ) : items === null ? (
        <div className="mt-3 flex flex-col gap-3">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-5 w-full" />)}
        </div>
      ) : items.length === 0 ? (
        <p className="mt-3 text-sm font-medium text-muted">Nothing yet. Scans, approvals and bank matches show up here.</p>
      ) : (
        <ul className="mt-3 flex flex-col divide-y divide-border">
          {items.map((item, i) => (
            <li key={`${i}-${item.time}-${item.actor}`} className="flex gap-3 py-3">
              <span
                aria-hidden="true"
                className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${
                  item.dot === "amber" ? "bg-amber" : "bg-teal"
                }`}
              />
              <div className="min-w-0 flex-1">
                <p className="text-sm leading-6">
                  <span className="font-bold tabular-nums">{item.time}</span>
                  <span className="text-muted"> · </span>
                  {item.text}
                </p>
              </div>
              <p className="shrink-0 text-right text-[13px] font-semibold text-muted">
                {item.actor}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
