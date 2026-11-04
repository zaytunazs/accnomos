"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { runtime, type RtCalendarClash, type RtDeadlineStatus } from "@/lib/runtime";

/** "‘Site visit, Hartwell’ 10:00–11:00" or "‘Holiday’ (all day)". */
export function clashLabel(c: RtCalendarClash): string {
  const t = (s: string) => s.slice(11, 16);
  return `‘${c.subject}’ ${c.all_day ? "(all day)" : `${t(c.start)}–${t(c.end)}`}`;
}

/** "updated 01:15" today, else "updated 3 Nov". */
export function updatedLabel(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay
    ? `updated ${d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}`
    : `updated ${d.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}`;
}

export function statusLine(s: RtDeadlineStatus | null): string {
  if (!s?.synced) return "No deadlines in your calendar yet.";
  return `${s.count} deadline${s.count === 1 ? "" : "s"} in your calendar · ${updatedLabel(s.last_sync)}`;
}

const RESYNC_MS = 6 * 60 * 60 * 1000; // automatic: refresh when Home opens and the last update is older than this

/**
 * Deadlines into the user's calendar: "Add to calendar" (all upcoming deadlines, safe to repeat) and the switch
 * "Add all deadlines to my calendar automatically", which re-adds them when Home opens. Used on Home and on /calendar.
 */
export function useDeadlineSync(account: AccountInfo | null | undefined, auto: boolean) {
  const [status, setStatus] = useState<RtDeadlineStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const autoRan = useRef(false);

  const sync = useCallback(async () => {
    if (!account) return;
    setBusy(true);
    setMessage(null);
    try {
      const r = await runtime.syncDeadlines(account);
      const parts = [
        r.added && `${r.added} added`,
        r.updated && `${r.updated} moved`,
        r.removed && `${r.removed} removed`,
      ].filter(Boolean);
      const said = parts.length ? `Done: ${parts.join(", ")}.` : "Your calendar already has every deadline.";
      const clashes = r.conflicts.map((c) => `${c.a.subject} is on the same day as ${clashLabel(c.b)}`);
      setMessage(clashes.length ? `${said} Note: ${clashes.join("; ")}.` : said);
      setStatus(await runtime.deadlinesStatus(account));
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Couldn't add the deadlines just now.");
    } finally {
      setBusy(false);
    }
  }, [account]);

  const setKeep = useCallback(
    async (keep: boolean) => {
      if (!account) return;
      setBusy(true);
      try {
        setStatus(await runtime.setDeadlinesKeep(account, keep));
      } catch (e) {
        setMessage(e instanceof Error ? e.message : "Couldn't save that just now.");
      } finally {
        setBusy(false);
      }
      if (keep) await sync();
    },
    [account, sync],
  );

  useEffect(() => {
    if (!account) return;
    let live = true;
    runtime.deadlinesStatus(account).then(
      (s) => {
        if (!live) return;
        setStatus(s);
        const stale = !s.last_sync || Date.now() - new Date(s.last_sync).getTime() > RESYNC_MS;
        if (auto && s.keep && stale && !autoRan.current) {
          autoRan.current = true;
          void sync();
        }
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [account, auto, sync]);

  return { status, busy, message, sync, setKeep };
}

export type DeadlineSync = ReturnType<typeof useDeadlineSync>;

export default function CalendarSync({ account, auto = false }: { account: AccountInfo; auto?: boolean }) {
  return <CalendarSyncPanel state={useDeadlineSync(account, auto)} />;
}

/** The switch, the "Add to calendar" button and the status line, for a sync state owned by the caller. */
export function CalendarSyncPanel({ state }: { state: DeadlineSync }) {
  const { status, busy, message, sync, setKeep } = state;
  return (
    <div data-calendar-sync="" className="flex flex-col gap-2 rounded-2xl border border-border bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="flex min-h-11 cursor-pointer items-center gap-3 text-[15px] font-bold text-ink">
          <input
            type="checkbox"
            role="switch"
            className="h-5 w-5 accent-[var(--color-teal)]"
            checked={!!status?.keep}
            disabled={busy || status === null}
            onChange={(e) => void setKeep(e.target.checked)}
          />
          Add all deadlines to my calendar automatically
        </label>
        <button
          type="button"
          onClick={() => void sync()}
          disabled={busy}
          className="inline-flex h-11 items-center rounded-lg border border-border bg-white px-4 text-[15px] font-bold text-ink hover:bg-ground disabled:opacity-60"
        >
          {busy ? "Adding…" : "Add to calendar"}
        </button>
      </div>
      <p className="text-[13px] text-muted" aria-live="polite">
        {message ?? statusLine(status)}
      </p>
      <p className="text-[12px] text-muted">
        Uses your Microsoft 365 / Outlook calendar, so the dates show on every device. Each deadline is an all-day
        event with a reminder at 9:00 the day before; Accnomos only changes events it added.
      </p>
    </div>
  );
}
