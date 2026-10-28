"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { money } from "@/lib/invoices";
import { ukDate, type RtBucket, type RtOwedRow } from "@/lib/runtime";

/** One figure: a label, the amount, and how many. Whole tile is a link when `href` is given. */
export function Tile({ label, bucket, pence, href, tone = "plain", hint }: {
  label: string;
  bucket?: RtBucket;
  pence?: number;
  href?: string;
  tone?: "plain" | "warn";
  hint?: string;
}) {
  const amount = pence ?? bucket?.total_pence ?? 0;
  const body = (
    <>
      <p className="text-xs font-bold text-muted">{label}</p>
      <p className={`mt-1 text-2xl font-extrabold tabular-nums ${tone === "warn" && amount > 0 ? "text-warn-ink" : ""}`}>{money(amount)}</p>
      {(bucket || hint) && <p className="mt-0.5 text-sm text-muted">{hint ?? `${bucket!.count} ${bucket!.count === 1 ? "item" : "items"}`}</p>}
    </>
  );
  const cls = "block rounded-2xl border border-border bg-white p-4";
  return href ? <Link href={href} className={`${cls} hover:bg-ground`}>{body}</Link> : <div className={cls}>{body}</div>;
}

export function Tiles({ children, label }: { children: ReactNode; label: string }) {
  return <section aria-label={label} className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2 lg:grid-cols-4">{children}</section>;
}

const BUCKET_LABEL: Record<string, string> = { current: "Not due yet", "0-30": "1 to 30 days late", "31-60": "31 to 60 days late", "61-90": "61 to 90 days late", "90+": "Over 90 days late" };

export function AgedStrip({ aged, title }: { aged: Record<string, number>; title: string }) {
  const keys = ["current", "0-30", "31-60", "61-90", "90+"];
  return (
    <section aria-label={title} className="rounded-2xl border border-border bg-white p-4">
      <h2 className="text-[17px] font-extrabold">{title}</h2>
      <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1 text-sm min-[420px]:grid-cols-2">
        {keys.map((k) => (
          <div key={k} className="flex justify-between gap-3">
            <dt className="text-muted">{BUCKET_LABEL[k]}</dt>
            <dd className="font-bold tabular-nums">{money(aged[k] ?? 0)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export function OwedList({ rows, title, empty, hrefFor }: { rows: RtOwedRow[]; title: string; empty: string; hrefFor?: (r: RtOwedRow) => string | null }) {
  return (
    <section aria-label={title} className="rounded-2xl border border-border bg-white p-4">
      <h2 className="text-[17px] font-extrabold">{title}</h2>
      {rows.length === 0 ? <p className="mt-2 text-sm text-muted">{empty}</p> : (
        <ul className="mt-2 divide-y divide-border">
          {rows.map((r) => {
            const href = hrefFor?.(r);
            return (
              <li key={`${r.event_id ?? r.reference}-${r.name}`} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <div className="min-w-0">
                  <p className="truncate text-[15px] font-bold">
                    {href ? <Link href={href} className="text-teal-dark hover:underline">{r.reference}</Link> : r.reference} · {r.name}
                  </p>
                  <p className="text-sm text-muted">
                    due {ukDate(r.due_date)}
                    {r.days_overdue > 0 && <> · <span className="font-bold text-warn-ink">{r.days_overdue} day{r.days_overdue === 1 ? "" : "s"} late</span></>}
                  </p>
                </div>
                <span className="text-[15px] font-extrabold tabular-nums">{money(r.owed_pence)}</span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
