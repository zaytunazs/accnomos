"use client";

import Link from "next/link";
import ByWhom from "@/components/ByWhom";
import ExplainMore from "@/components/ExplainMore";
import { activity as sampleActivity } from "@/lib/sample-home";
import { SampleTag, Skeleton, useHome } from "./HomeData";
import type { RtDashboard } from "@/lib/runtime";

const LONDON = { timeZone: "Europe/London" } as const;

type Kind = "receipt" | "invoice" | "bank" | "vat" | "autopilot" | "intake";

const KIND_LABEL: Record<Kind, string> = {
  receipt: "Receipt",
  invoice: "Invoice",
  bank: "Bank",
  vat: "VAT",
  autopilot: "Autopilot",
  intake: "Intake",
};

/** Where "the thing" behind an audit line lives. Same-page anchors start with #. */
function kindOf(action: string, actor: string): { kind: Kind; href: string } {
  if (action.startsWith("invoice")) return { kind: "invoice", href: "/invoices" };
  if (action.startsWith("bank")) return { kind: "bank", href: "/bank" };
  if (action.startsWith("vat")) return { kind: "vat", href: "/vat" };
  if (action === "mail_scanned") return { kind: "intake", href: "/review" };
  if (action.startsWith("mail")) return { kind: "intake", href: "#home-inbox" };
  if (action.startsWith("todo")) return { kind: "intake", href: "#home-todos" };
  if (actor === "Autopilot") return { kind: "autopilot", href: "/review" };
  return { kind: "receipt", href: "/review" };
}

function Icon({ kind, warn }: { kind: Kind; warn: boolean }) {
  const paths: Record<Kind, React.ReactNode> = {
    receipt: (<><rect x="4.5" y="2.5" width="7" height="11" rx="1" /><path d="M4.5 10.5l1.2 1.2 1.1-1.2 1.2 1.2 1.1-1.2 1.2 1.2" /><path d="M6.5 5.5h3M6.5 7.5h3" /></>),
    invoice: (<><path d="M4.5 2.5h4.5L11.5 5v8.5h-7z" /><path d="M9 2.5V5h2.5" /><path d="M6.5 8h3M6.5 10h3" /></>),
    bank: (<><path d="M2.5 6.5L8 3l5.5 3.5" /><path d="M3.5 6.5v5M6 6.5v5M8.5 6.5v5M11 6.5v5M13.5 6.5v5M2.5 12.8h11" /></>),
    vat: (<><circle cx="5" cy="5" r="1.8" /><circle cx="11" cy="11" r="1.8" /><path d="M12.5 3.5L3.5 12.5" /></>),
    autopilot: (<><path d="M8.8 2.5L4 8.5h3l-1 5 5-6.5h-3z" /></>),
    intake: (<><path d="M2.5 9.5h11V13.5h-11z" /><path d="M2.5 9.5l1-4h9l1 4M8 5.5v4M6.2 8l1.8 1.8L9.8 8" /></>),
  };
  return (
    <span
      aria-hidden="true"
      className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${warn ? "bg-warn-bg text-warn-ink" : "bg-teal-tint text-teal-dark"}`}
    >
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        {paths[kind]}
      </svg>
    </span>
  );
}

interface Row {
  key: string;
  day: string; // YYYY-MM-DD in the UK, or "sample"
  time: string;
  text: string;
  actor: string;
  warn: boolean;
  kind: Kind;
  href: string;
}

/** "17:42" for today (UK time), "26 Oct" before that. */
function when(iso: string, today: string): string {
  const d = new Date(iso);
  if (d.toLocaleDateString("en-CA", LONDON) === today)
    return d.toLocaleTimeString("en-GB", { ...LONDON, hour: "2-digit", minute: "2-digit" });
  return d.toLocaleDateString("en-GB", { ...LONDON, day: "numeric", month: "short" });
}

/** "2026-10-26" in the UK, whatever the device's time zone. */
function dayKey(iso: string): string {
  return new Date(iso).toLocaleDateString("en-CA", LONDON);
}

/** "Today", "Yesterday", or "26 Oct" for a YYYY-MM-DD day against the dashboard's today. */
function dayLabel(day: string, today: string): string {
  if (day === today) return "Today";
  const [y, m, d] = today.split("-").map(Number);
  const yesterday = new Date(Date.UTC(y, m - 1, d) - 86_400_000).toISOString().slice(0, 10);
  if (day === yesterday) return "Yesterday";
  const [yy, mm, dd] = day.split("-").map(Number);
  return new Date(Date.UTC(yy, mm - 1, dd)).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}

function liveRows(d: RtDashboard): Row[] {
  return d.activity.map((a, i) => {
    const { kind, href } = kindOf(a.action, a.actor);
    return {
      key: `${i}-${a.at}-${a.actor}`,
      day: dayKey(a.at), time: when(a.at, d.today), text: a.text, actor: a.actor,
      warn: a.tone === "warn", kind, href,
    };
  });
}

const SAMPLE_META: { kind: Kind; href: string }[] = [
  { kind: "intake", href: "/review" },
  { kind: "receipt", href: "/review" },
  { kind: "bank", href: "/bank" },
];

function sampleRows(): Row[] {
  return sampleActivity.map((item, i) => ({
    key: `sample-${i}`, day: "sample", time: item.time, text: item.text, actor: item.actor,
    warn: item.dot === "amber", kind: SAMPLE_META[i]?.kind ?? "receipt", href: SAMPLE_META[i]?.href ?? "/review",
  }));
}

function RowLink({ row, children }: { row: Row; children: React.ReactNode }) {
  const className = "flex min-h-[3.5rem] items-center gap-3 rounded-xl px-2 py-2 hover:bg-ground";
  return row.href.startsWith("#") ? (
    <a href={row.href} className={className}>{children}</a>
  ) : (
    <Link href={row.href} className={className}>{children}</Link>
  );
}

/**
 * What happened lately: the last ten audit lines when signed in, the sample
 * when signed out. Grouped by day, one icon per kind, each row linking to
 * the receipt, invoice, bank line, VAT return or inbox behind it.
 */
export default function Activity() {
  const home = useHome();
  const sample = home.mode === "sample";
  const rows = sample ? sampleRows() : home.mode === "live" ? liveRows(home.data) : null;
  const heading = sample ? "What the agents did on 26 October" : "Recent activity";

  const days: { day: string; label: string; rows: Row[] }[] = [];
  if (rows) {
    const today = home.mode === "live" ? home.data.today : "";
    for (const row of rows) {
      const label = row.day === "sample" ? "Monday 26 October" : dayLabel(row.day, today);
      const last = days[days.length - 1];
      if (last && last.day === row.day) last.rows.push(row);
      else days.push({ day: row.day, label, rows: [row] });
    }
  }

  return (
    <section
      aria-labelledby="activity-heading"
      aria-busy={rows === null && home.mode !== "error"}
      className="flex flex-col rounded-2xl border border-border bg-white p-4 sm:p-5 md:col-span-2 xl:col-span-2"
    >
      <div className="flex items-center gap-2">
        <h2 id="activity-heading" className="text-lg font-extrabold tracking-tight">
          {heading}{sample && <SampleTag />}
        </h2>
        <ExplainMore title="What this list is" anchor="data">
          The latest audit lines from your books — scans, approvals and bank matches — each linking to the thing
          behind it. They are written by code as things happen.
        </ExplainMore>
      </div>
      {home.mode === "error" ? (
        <p className="mt-3 min-h-[3.5rem] text-sm font-medium text-muted">— Could not reach your books: {home.message}</p>
      ) : rows === null ? (
        <div className="mt-3 flex flex-col gap-1" aria-hidden="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex min-h-[3.5rem] items-center gap-3 px-2 py-2">
              <Skeleton className="h-9 w-9 shrink-0 rounded-xl" />
              <div className="flex min-w-0 flex-1 flex-col gap-2">
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-3 w-2/3" />
              </div>
            </div>
          ))}
        </div>
      ) : rows.length === 0 ? (
        <p className="mt-3 min-h-[3.5rem] text-sm font-medium text-muted">Nothing yet. Scans, approvals and bank matches show up here.</p>
      ) : (
        <div className="mt-1 flex min-h-[10rem] flex-col">
          {days.map((group) => (
            <div key={group.day}>
              <h3 className="mt-3 text-[13px] font-extrabold uppercase tracking-wide text-muted">{group.label}</h3>
              <ul className="flex flex-col divide-y divide-border">
                {group.rows.map((row) => (
                  <li key={row.key}>
                    <RowLink row={row}>
                      <Icon kind={row.kind} warn={row.warn} />
                      <span className="min-w-0 flex-1 text-sm leading-6">
                        <span className="sr-only">{KIND_LABEL[row.kind]}: </span>
                        <span className="font-bold tabular-nums">{row.time}</span>
                        <span className="text-muted"> · </span>
                        {row.text}
                      </span>
                      <span className="shrink-0 text-right text-[13px] font-semibold text-muted">
                        {row.actor}
                      </span>
                    </RowLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
      <ByWhom className="mt-3" code="Logged by code as things happen" ai="no AI involved" />
      <div className="mt-auto pt-4">
        <Link
          href="/review"
          className="inline-block whitespace-nowrap rounded-xl border border-border px-4 py-2 text-sm font-bold text-teal-dark hover:bg-ground"
        >
          Open Review
        </Link>
      </div>
    </section>
  );
}
