"use client";

import Link from "next/link";
import type { AccountInfo } from "@azure/msal-browser";
import { runtime, ukDate, type RtRepeatingResult } from "@/lib/runtime";

let inFlight: Promise<RtRepeatingResult | null> | null = null;

/**
 * Nothing of ours runs for a user between visits, so repeating invoices and bills that have come due are made when the
 * Sales, Purchases or Repeating page opens (the runtime does it; POST /repeating/process). Null when nothing was due.
 * Mail permission is asked for only when a due invoice is set to approve automatically, so opening a page never
 * sends the user to a consent screen for no reason.
 */
export function runDueRepeating(account: AccountInfo): Promise<RtRepeatingResult | null> {
  if (inFlight) return inFlight;
  const p = (async () => {
    const list = await runtime.repeating(account);
    const due = list.filter((t) => t.due_now);
    if (due.length === 0) return null;
    return runtime.processRepeating(account, due.some((t) => t.kind === "invoice" && t.approve_automatically));
  })().finally(() => {
    inFlight = null;
  });
  inFlight = p;
  return p;
}

const OUTCOME: Record<string, string> = {
  draft: "a draft",
  sent: "sent and posted",
  proposed: "waiting in Review",
  posted: "approved and posted",
};

/** What a visit made, one line each, with where to find it. */
export function RepeatingRunNote({ result }: { result: RtRepeatingResult | null }) {
  if (!result || (result.made.length === 0 && result.problems.length === 0)) return null;
  return (
    <div role="status" className="rounded-xl bg-teal-tint px-4 py-3 text-sm text-teal-dark">
      {result.made.length > 0 && (
        <>
          <p className="font-bold">Made from your repeating schedules just now:</p>
          <ul className="mt-1 list-disc pl-5">
            {result.made.map((m) => (
              <li key={`${m.template}-${m.date}`}>
                {m.kind === "invoice" ? `Invoice ${m.number ?? ""}` : "Bill"} for {ukDate(m.date)}: {OUTCOME[m.outcome] ?? m.outcome}
                {m.note ? ` (${m.note})` : ""}.{" "}
                <Link href={m.kind === "invoice" ? `/invoices?q=${encodeURIComponent(m.number ?? "")}` : "/review"} className="font-bold underline">
                  {m.kind === "invoice" ? "Open invoices" : "Open Review"}
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
      {result.more_due > 0 && <p className="mt-1">{result.more_due} more {result.more_due === 1 ? "is" : "are"} due and will be made the next time you open this page.</p>}
      {result.problems.length > 0 && (
        <ul className="mt-1 list-disc pl-5 font-semibold text-warn-ink">{result.problems.map((p) => <li key={p}>{p}</li>)}</ul>
      )}
    </div>
  );
}
