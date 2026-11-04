"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { errorText, todayIso, useAccount } from "@/components/jobs/useAccount";
import SignInCta from "@/components/SignInCta";
import { LoadingSkeleton, RuntimeErrorNote } from "@/components/States";
import { runtime, type RtCalendarClash, type RtCalendarEvent, type RtCalendarEventIn } from "@/lib/runtime";
import CalendarSync, { clashLabel } from "./CalendarSync";

const primary = "inline-flex h-11 items-center rounded-lg bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-60";
const secondary = "inline-flex h-11 items-center rounded-lg border border-border bg-white px-4 text-[15px] font-bold text-ink hover:bg-ground disabled:opacity-60";
const input = "h-11 w-full rounded-lg border border-border bg-white px-3 text-[15px]";

function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

function dayHeading(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
}

function timeOf(e: RtCalendarEvent): string {
  if (e.all_day) return "All day";
  const t = (s: string) => s.slice(11, 16);
  return `${t(e.start)}–${t(e.end)}`;
}

function Header({ action }: { action?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-[28px] font-bold leading-tight tracking-tight text-ink sm:text-[30px]">Calendar</h1>
        <p className="mt-1 text-[15px] text-muted">This week and next, with your deadlines from the books.</p>
      </div>
      {action}
    </div>
  );
}

/** /calendar: the next two weeks by day, add an event, remove one (asked first), and deadlines into the calendar. */
export default function LiveCalendar() {
  const account = useAccount();
  if (account === undefined) return <LoadingSkeleton lines={4} label="Loading your calendar…" />;
  if (!account)
    return (
      <div className="flex flex-col gap-5">
        <Header action={<SignInCta />} />
        <p className="rounded-lg border border-border bg-white px-4 py-3 text-[15px] text-muted">
          Sign in, or try the demo, to see your calendar and add your deadlines to it.
        </p>
      </div>
    );
  return <Signed account={account} />;
}

function Signed({ account }: { account: AccountInfo }) {
  const start = todayIso();
  const end = addDays(start, 13);
  const [events, setEvents] = useState<RtCalendarEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [form, setForm] = useState({ subject: "", date: start, time: "", location: "" });
  const [formError, setFormError] = useState<string | null>(null);
  const [clashes, setClashes] = useState<RtCalendarClash[] | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      setEvents(await runtime.calendarEvents(account, start, end));
    } catch (e) {
      setError(errorText(e));
    }
  }, [account, start, end]);

  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  const byDay = useMemo(() => {
    const groups = new Map<string, RtCalendarEvent[]>();
    for (const e of events ?? []) {
      const day = e.start.slice(0, 10);
      groups.set(day, [...(groups.get(day) ?? []), e]);
    }
    return [...groups.entries()];
  }, [events]);

  function draft(): RtCalendarEventIn {
    return {
      subject: form.subject.trim(),
      start: form.time ? `${form.date}T${form.time}` : form.date,
      ...(form.location.trim() ? { location: form.location.trim() } : {}),
    };
  }

  async function write(allowConflict: boolean) {
    const made = await runtime.addCalendarEvent(account, { ...draft(), ...(allowConflict ? { allow_conflict: true } : {}) });
    setNotice(`Added “${made.subject}”.`);
    setAdding(false);
    setClashes(null);
    setForm({ subject: "", date: start, time: "", location: "" });
    await load();
  }

  /** Check the calendar first; a clash is shown with Add anyway / Cancel, never added silently. */
  async function add(ev: React.FormEvent) {
    ev.preventDefault();
    setFormError(null);
    if (!form.subject.trim()) return setFormError("Give the event a title.");
    setBusy(true);
    try {
      const { conflicts } = await runtime.checkCalendarEvent(account, draft());
      if (conflicts.length) setClashes(conflicts);
      else await write(false);
    } catch (e) {
      setFormError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  async function addAnyway() {
    setBusy(true);
    try {
      await write(true);
    } catch (e) {
      setFormError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove(e: RtCalendarEvent) {
    setBusy(true);
    try {
      await runtime.removeCalendarEvent(account, e.id);
      setNotice(`Removed “${e.subject}”.`);
      setConfirm(null);
      await load();
    } catch (err) {
      setNotice(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <Header
        action={
          <button type="button" className={primary} onClick={() => setAdding((v) => !v)} aria-expanded={adding}>
            {adding ? "Close" : "+ Add an event"}
          </button>
        }
      />
      {adding && (
        <form onSubmit={add} aria-label="Add an event" className="grid grid-cols-1 gap-3 rounded-2xl border border-border bg-white p-4 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-[13px] font-bold text-ink sm:col-span-2">
            Title
            <input className={input} value={form.subject} maxLength={120} onChange={(e) => setForm({ ...form, subject: e.target.value })} />
          </label>
          <label className="flex flex-col gap-1 text-[13px] font-bold text-ink">
            Date
            <input type="date" className={input} value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} />
          </label>
          <label className="flex flex-col gap-1 text-[13px] font-bold text-ink">
            Time (leave empty for all day)
            <input type="time" className={input} value={form.time} onChange={(e) => setForm({ ...form, time: e.target.value })} />
          </label>
          <label className="flex flex-col gap-1 text-[13px] font-bold text-ink sm:col-span-2">
            Where (optional)
            <input className={input} value={form.location} maxLength={200} onChange={(e) => setForm({ ...form, location: e.target.value })} />
          </label>
          {formError && <p role="alert" className="text-[13px] font-semibold text-warn-ink sm:col-span-2">{formError}</p>}
          {clashes && (
            <div role="alert" data-clash="" className="flex flex-col gap-2 rounded-lg border border-warn-border bg-warn-bg px-3 py-2 sm:col-span-2">
              <p className="text-[14px] font-semibold text-warn-ink">
                Clashes with {clashes.map(clashLabel).join(", ")}
              </p>
              <div className="flex gap-2">
                <button type="button" className={primary} disabled={busy} onClick={() => void addAnyway()}>Add anyway</button>
                <button type="button" className={secondary} onClick={() => setClashes(null)}>Cancel</button>
              </div>
            </div>
          )}
          <div className="flex gap-2 sm:col-span-2">
            <button type="submit" className={primary} disabled={busy || !!clashes}>{busy ? "Checking…" : "Add to calendar"}</button>
            <button type="button" className={secondary} onClick={() => setAdding(false)}>Cancel</button>
          </div>
        </form>
      )}
      <CalendarSync account={account} />
      {notice && <p className="text-[14px] font-semibold text-teal-dark" aria-live="polite">{notice}</p>}
      {error ? (
        <RuntimeErrorNote message={error} onRetry={() => void load()} />
      ) : events === null ? (
        <LoadingSkeleton lines={4} label="Loading your calendar…" />
      ) : byDay.length === 0 ? (
        <p className="rounded-lg border border-border bg-white px-4 py-3 text-[15px] text-muted">
          Nothing in the next two weeks.
        </p>
      ) : (
        <ol className="flex flex-col gap-4" aria-label="Events by day">
          {byDay.map(([day, list]) => (
            <li key={day} className="flex flex-col gap-2">
              <h2 className="text-[15px] font-bold text-ink">{dayHeading(day)}</h2>
              <ul className="flex flex-col gap-2">
                {list.map((e) => (
                  <li key={e.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-white px-4 py-3">
                    <span className="w-24 shrink-0 text-[13px] font-semibold text-muted">{timeOf(e)}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-[15px] font-bold text-ink">{e.subject}</span>
                      {(e.location || e.accnomos) && (
                        <span className="block text-[13px] text-muted">
                          {[e.location, e.accnomos ? "Added by Accnomos" : null].filter(Boolean).join(" · ")}
                        </span>
                      )}
                    </span>
                    {confirm === e.id ? (
                      <span className="flex items-center gap-2">
                        <span className="text-[13px] font-semibold text-ink">Remove it?</span>
                        <button type="button" className={secondary} disabled={busy} onClick={() => void remove(e)}>
                          Yes, remove
                        </button>
                        <button type="button" className={secondary} onClick={() => setConfirm(null)}>Keep</button>
                      </span>
                    ) : (
                      <button type="button" className={secondary} onClick={() => setConfirm(e.id)} aria-label={`Remove ${e.subject}`}>
                        Remove
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
