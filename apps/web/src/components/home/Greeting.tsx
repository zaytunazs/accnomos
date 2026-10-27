"use client";

import { loadBusiness } from "@/lib/business";
import { ago } from "@/lib/intake";
import type { RtDashboard } from "@/lib/runtime";
import LastInboxCheck from "./LastInboxCheck";
import { firstName, Skeleton, useHome } from "./HomeData";

const LONDON = "Europe/London";

function greeting(now: Date): string {
  const hour = Number(now.toLocaleTimeString("en-GB", { timeZone: LONDON, hour: "2-digit", hour12: false }));
  return hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
}

/** The latest of the runs the runtime found in the audit files, as one line; null when there are none. */
function lastRun(runs: RtDashboard["runs"]): string | null {
  const named = [
    ["Last Autopilot run", runs.autopilot],
    ["Last inbox check", runs.intake],
    ["Last inbox triage", runs.triage],
    ["Last scan", runs.scan],
  ] as const;
  const latest = named
    .filter(([, run]) => run)
    .sort(([, a], [, b]) => Date.parse(b!.at) - Date.parse(a!.at))[0];
  if (!latest) return null;
  const [label, run] = latest;
  return `${label} ${ago(run!.at)}${run!.summary ? ` · ${run!.summary}` : ""}`;
}

/** Date, greeting and last agent run. The sample's Priya at Bramblewood only when signed out, and labelled. */
export default function Greeting() {
  const home = useHome();

  if (home.mode === "sample")
    return (
      <Header
        date="Monday 26 October"
        title="Good evening, Priya"
        badge="Fictional demo company · Bramblewood Joinery Ltd"
        run="Last Autopilot run 4 min ago · 2 receipts imported from Outlook"
      />
    );

  if (home.mode === "checking")
    return (
      <div aria-busy="true" className="flex flex-col gap-2">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-9 w-64" />
      </div>
    );

  const now = new Date();
  const date = now.toLocaleDateString("en-GB", { timeZone: LONDON, weekday: "long", day: "numeric", month: "long" });
  const business = loadBusiness()?.name?.trim();
  const run =
    home.mode === "live" ? lastRun(home.data.runs) ?? "No agent runs yet"
    : home.mode === "error" ? "Last run —"
    : null;
  return (
    <Header
      date={business ? `${date} · ${business}` : date}
      title={`${greeting(now)}, ${firstName(home.account)}`}
      run={run}
    />
  );
}

function Header({ date, title, badge, run }: { date: string; title: string; badge?: string; run: string | null }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-2">
      <div>
        <p className="text-sm font-semibold text-muted">
          {date}
          {badge && (
            <span className="ml-2 rounded-full bg-ink px-2 py-0.5 text-[11px] font-extrabold uppercase tracking-wide text-ground">
              {badge}
            </span>
          )}
        </p>
        <h1 className="mt-1 text-3xl font-extrabold tracking-tight">{title}</h1>
      </div>
      {run === null ? <Skeleton className="h-4 w-56" /> : <LastInboxCheck>{run}</LastInboxCheck>}
    </div>
  );
}
