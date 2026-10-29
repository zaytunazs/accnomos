"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useScanRun, type ScanItem } from "@/lib/scan-queue";

const STATE_TEXT: Record<ScanItem["state"], string> = {
  waiting: "Waiting",
  reading: "Reading…",
  done: "Read",
  slow: "Still being read",
  error: "Not read",
};

function itemLine(x: ScanItem): string {
  if (x.state === "done") return `${x.cards ?? 0} card${x.cards === 1 ? "" : "s"}${x.autopilot ? `, ${x.autopilot} approved by Autopilot` : ""}`;
  return x.message ?? "";
}

/** Review: "Reading 1 of 2 … supplier.pdf" and each document's state (lib/scan-queue.ts). */
export function ScanProgress() {
  const run = useScanRun();
  // Finished with every document read: Review's own note says how many cards ("1 new proposal"); nothing to add.
  if (!run || (!run.running && !run.items.some((x) => x.state === "slow" || x.state === "error"))) return null;
  const n = run.items.length;
  const now = run.current !== null ? run.items[run.current] : null;
  return (
    <section aria-label="Inbox scan" className="rounded-2xl border border-border bg-white p-4">
      <p role={run.running ? "status" : undefined} className="text-[15px] font-bold text-ink">
        {run.running
          ? now
            ? `Reading ${run.current! + 1} of ${n} … ${now.name}`
            : "Looking in 00 Inbox…"
          : `Scan finished · ${n} document${n === 1 ? "" : "s"}`}
      </p>
      {run.running && (
        <p className="mt-1 text-sm text-muted">You can leave this page: the scan carries on, and new cards appear in Review as each document is read.</p>
      )}
      {n > 0 && (
        <ol aria-label="Documents in this scan" className="mt-2 flex flex-col gap-1 text-sm">
          {run.items.map((x) => (
            <li key={x.path} className="flex min-w-0 flex-wrap items-baseline gap-x-2">
              <span className={`shrink-0 font-bold ${x.state === "error" || x.state === "slow" ? "text-warn-ink" : x.state === "done" ? "text-teal-dark" : "text-muted"}`}>
                {STATE_TEXT[x.state]}
              </span>
              <span className="min-w-0 break-all font-semibold">{x.name}</span>
              {itemLine(x) && <span className="text-muted">{itemLine(x)}</span>}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

/** Every other page while a scan runs: a one-line status with the way to Review (AppShell). */
export function ScanStatus() {
  const run = useScanRun();
  const path = usePathname();
  if (!run?.running || path === "/review") return null;
  const now = run.current !== null ? run.items[run.current] : null;
  return (
    <div role="status" className="border-b border-border bg-teal-tint px-4 py-2 text-sm text-teal-dark print:hidden">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-2">
        <span className="font-semibold">
          {now ? `Reading ${run.current! + 1} of ${run.items.length} … ${now.name}` : "Looking in 00 Inbox…"}
        </span>
        <Link href="/review" className="font-bold underline">
          Open Review
        </Link>
      </div>
    </div>
  );
}
