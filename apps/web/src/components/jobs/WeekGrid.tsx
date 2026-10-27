"use client";

import { useMemo, useRef, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { runtime, type RtStaff, type RtTimesheetEntry } from "@/lib/runtime";
import { errorText, todayIso } from "./useAccount";

const cellKey = (staffId: string, date: string) => `${staffId}|${date}`;
const field = "h-10 w-full min-w-16 rounded-xl border border-border px-2 text-right text-sm tabular-nums";
const unsavedField = "border-warn-border bg-warn-bg";

function mondayOf(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  const back = (dt.getDay() + 6) % 7; // Monday first
  dt.setDate(dt.getDate() - back);
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
}

function addDays(iso: string, n: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d + n);
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
}

const dayLabel = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
};

const fmtHours = (h: number) => (h === 0 ? "" : String(Math.round(h * 100) / 100));

/** Is this what someone typed a valid cell value? Empty means "no hours". */
function parseCell(raw: string): { ok: true; hours: number } | { ok: false; why: string } {
  const t = raw.trim();
  if (t === "") return { ok: true, hours: 0 };
  const n = Number(t);
  if (!Number.isFinite(n)) return { ok: false, why: `"${t}" is not a number.` };
  if (n < 0 || n > 24) return { ok: false, why: "Hours are 0 to 24 a day." };
  if (Math.abs(n * 4 - Math.round(n * 4)) > 1e-9) return { ok: false, why: "Hours use 0.25 steps, e.g. 7.5." };
  return { ok: true, hours: Math.round(n * 4) / 4 };
}

interface Props {
  account: AccountInfo;
  jobId: string;
  open: boolean;
  staff: RtStaff[];
  entries: RtTimesheetEntry[];
  reload: () => Promise<void>;
}

/**
 * Staff × days for one week on one job. Typing a cell saves that staff member's
 * day (Enter moves to the next cell); right-click or long-press edits its note.
 * Row, column and week totals are sums of the runtime's entries after each save.
 */
export default function WeekGrid({ account, jobId, open, staff, entries, reload }: Props) {
  const [monday, setMonday] = useState(() => mondayOf(todayIso()));
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [pendingNotes, setPendingNotes] = useState<Record<string, string>>({});
  const [noteFor, setNoteFor] = useState<{ staffId: string; date: string } | null>(null);
  const [noteText, setNoteText] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const sectionRef = useRef<HTMLElement>(null);
  const pressTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(monday, i)), [monday]);
  const byCell = useMemo(() => {
    const map = new Map<string, RtTimesheetEntry[]>();
    for (const e of entries) {
      if (e.date < monday || e.date > days[6]) continue;
      const k = cellKey(e.staff_id, e.date);
      map.set(k, [...(map.get(k) ?? []), e]);
    }
    return map;
  }, [entries, monday, days]);

  // Active staff plus anyone with hours this week (so former staff keep their row).
  const rows = useMemo(() => {
    const ids = new Set(byCell.keys());
    const withHours = [...ids].map((k) => k.split("|")[0]);
    return staff.filter((s) => s.active || withHours.includes(s.id));
  }, [staff, byCell]);

  const names = useMemo(() => Object.fromEntries(staff.map((s) => [s.id, s.role ? `${s.name} (${s.role})` : s.name])), [staff]);

  // Totals straight from the runtime's entries (after each save the parent reloads them).
  const savedOf = (staffId: string, date: string) =>
    (byCell.get(cellKey(staffId, date)) ?? []).reduce((t, e) => t + e.hours, 0);
  const rowTotal = (staffId: string) => days.reduce((t, d) => t + savedOf(staffId, d), 0);
  const colTotal = (date: string) => rows.reduce((t, s) => t + savedOf(s.id, date), 0);
  const weekTotal = days.reduce((t, d) => t + colTotal(d), 0);

  function focusNext(current: HTMLInputElement) {
    const cells = [...(sectionRef.current?.querySelectorAll<HTMLInputElement>("input[data-weekcell]") ?? [])];
    const i = cells.indexOf(current);
    if (i >= 0) cells[(i + 1) % cells.length]?.focus();
  }

  function openNoteEditor(staffId: string, date: string) {
    const cell = byCell.get(cellKey(staffId, date)) ?? [];
    setNoteFor({ staffId, date });
    setNoteText(cell.length === 1 ? cell[0].note : (pendingNotes[cellKey(staffId, date)] ?? ""));
    setNote(cell.length > 1 ? "Several entries share this cell — edit their notes in the list below." : null);
  }

  async function saveCell(staffId: string, date: string) {
    const k = cellKey(staffId, date);
    const raw = drafts[k];
    if (raw === undefined || busy !== null) return;
    const parsed = parseCell(raw);
    if (!parsed.ok) {
      setNote(parsed.why);
      return;
    }
    const cell = byCell.get(k) ?? [];
    const billed = cell.filter((e) => e.invoiced_in);
    if (billed.length > 0) {
      setNote("Those hours are already billed, so they are locked.");
      setDrafts((d) => {
        const next = { ...d };
        delete next[k];
        return next;
      });
      return;
    }
    if (cell.length > 1 && parsed.hours !== savedOf(staffId, date)) {
      setNote("Several entries share this cell — change them in the list below.");
      return;
    }
    setBusy(k);
    setNote(null);
    try {
      const noteTextForCell = (pendingNotes[k] ?? "").trim();
      if (cell.length === 0) {
        if (parsed.hours > 0) {
          await runtime.addTimesheet(account, { staff_id: staffId, job_id: jobId, date, hours: parsed.hours, note: noteTextForCell, billable: true });
        }
      } else if (parsed.hours === 0) {
        await runtime.deleteTimesheet(account, cell[0].id);
      } else {
        await runtime.updateTimesheet(account, cell[0].id, { hours: parsed.hours });
      }
      setDrafts((d) => {
        const next = { ...d };
        delete next[k];
        return next;
      });
      setPendingNotes((p) => {
        const next = { ...p };
        delete next[k];
        return next;
      });
      await reload();
      setNote(
        parsed.hours === 0 && cell.length > 0
          ? `${dayLabel(date)} cleared for ${names[staffId] ?? "staff"}.`
          : `${parsed.hours} h saved for ${names[staffId] ?? "staff"} on ${dayLabel(date)}.`,
      );
    } catch (e) {
      setNote(errorText(e));
    } finally {
      setBusy(null);
    }
  }

  async function saveNote(e: React.FormEvent) {
    e.preventDefault();
    if (!noteFor || busy !== null) return;
    const k = cellKey(noteFor.staffId, noteFor.date);
    const cell = byCell.get(k) ?? [];
    if (cell.length > 1) return;
    setBusy(`note-${k}`);
    try {
      if (cell.length === 1) {
        await runtime.updateTimesheet(account, cell[0].id, { note: noteText.trim() });
        await reload();
        setNote(`Note saved for ${dayLabel(noteFor.date)}.`);
      } else {
        setPendingNotes((p) => ({ ...p, [k]: noteText }));
        setNote(noteText.trim() ? `Note kept — it is added when ${dayLabel(noteFor.date)} gets hours.` : "Note cleared.");
      }
      setNoteFor(null);
    } catch (err) {
      setNote(errorText(err));
    } finally {
      setBusy(null);
    }
  }

  const weekLabel = `${dayLabel(monday)} – ${dayLabel(days[6])}`;
  const cellInput = (s: RtStaff, date: string) => {
    const k = cellKey(s.id, date);
    const cell = byCell.get(k) ?? [];
    const locked = cell.some((e) => e.invoiced_in) || cell.length > 1;
    const unsaved = drafts[k] !== undefined && drafts[k] !== fmtHours(savedOf(s.id, date));
    const hasNote = cell.some((e) => e.note) || (pendingNotes[k] ?? "").trim() !== "";
    return (
      <input
        key={k}
        data-weekcell={k}
        type="number"
        min="0"
        max="24"
        step="0.25"
        inputMode="decimal"
        disabled={!open || locked || busy !== null}
        aria-label={`${names[s.id] ?? s.name}, ${dayLabel(date)} in hours${hasNote ? `, note: ${cell.map((e) => e.note).filter(Boolean).join("; ") || pendingNotes[k]}` : ""}`}
        title={locked ? "Billed or shared — change it in the list below" : "Hours in 0.25 steps; right-click for the note"}
        value={drafts[k] ?? fmtHours(savedOf(s.id, date))}
        onChange={(e) => setDrafts((d) => ({ ...d, [k]: e.target.value }))}
        onBlur={() => saveCell(s.id, date)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            saveCell(s.id, date).then(() => focusNext(e.currentTarget));
          }
        }}
        onContextMenu={(e) => {
          e.preventDefault();
          openNoteEditor(s.id, date);
        }}
        onTouchStart={() => {
          if (pressTimer.current) clearTimeout(pressTimer.current);
          pressTimer.current = setTimeout(() => openNoteEditor(s.id, date), 550);
        }}
        onTouchEnd={() => {
          if (pressTimer.current) clearTimeout(pressTimer.current);
        }}
        onTouchMove={() => {
          if (pressTimer.current) clearTimeout(pressTimer.current);
        }}
        className={`${field} ${unsaved ? unsavedField : "bg-white"} ${hasNote ? "font-extrabold" : ""} disabled:bg-ground disabled:text-muted`}
      />
    );
  };

  return (
    <section ref={sectionRef} aria-labelledby="job-week" className="rounded-2xl border border-border bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="job-week" className="text-[17px] font-extrabold text-ink">
          Week
        </h2>
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Pick a week">
          <button type="button" onClick={() => setMonday(addDays(monday, -7))} aria-label="Previous week" className="h-10 rounded-xl border border-border bg-white px-3 text-sm font-bold text-ink">←</button>
          <button type="button" onClick={() => setMonday(mondayOf(todayIso()))} className="h-10 rounded-xl border border-border bg-white px-3 text-sm font-bold text-ink">This week</button>
          <button type="button" onClick={() => setMonday(addDays(monday, 7))} aria-label="Next week" className="h-10 rounded-xl border border-border bg-white px-3 text-sm font-bold text-ink">→</button>
        </div>
      </div>
      <p className="mt-1 text-sm text-muted">
        {weekLabel} · {fmtHours(weekTotal) || "0"} h so far. Type hours straight into a cell (0.25 steps); right-click or
        long-press a cell for its note. Bold cells have a note.
      </p>

      {rows.length === 0 ? (
        <p className="mt-3 text-sm text-muted">No active staff — add them in Settings first.</p>
      ) : (
        <>
          {/* Wide screens: the grid; its own sideways scroller, never the page's. */}
          <div className="mt-3 hidden overflow-x-auto min-[560px]:block">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="text-xs font-bold text-muted">
                  <th scope="col" className="py-2 pr-3">Staff</th>
                  {days.map((d) => (
                    <th key={d} scope="col" className="min-w-20 py-2 pr-2 text-right">{dayLabel(d)}</th>
                  ))}
                  <th scope="col" className="py-2 pl-2 text-right">Week</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {rows.map((s) => (
                  <tr key={s.id} className="text-ink">
                    <th scope="row" className="py-2 pr-3 font-bold">{names[s.id] ?? s.name}</th>
                    {days.map((d) => (
                      <td key={d} className="py-2 pr-2">{cellInput(s, d)}</td>
                    ))}
                    <td className="py-2 pl-2 text-right font-extrabold tabular-nums">{fmtHours(rowTotal(s.id)) || "—"}</td>
                  </tr>
                ))}
                <tr className="font-extrabold text-ink">
                  <th scope="row" className="py-2 pr-3">Day total</th>
                  {days.map((d) => (
                    <td key={d} className="py-2 pr-2 text-right tabular-nums">{fmtHours(colTotal(d)) || "—"}</td>
                  ))}
                  <td className="py-2 pl-2 text-right tabular-nums">{fmtHours(weekTotal) || "—"}</td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* Narrow screens: one section per day instead of a grid. */}
          <div className="mt-3 flex flex-col gap-4 min-[560px]:hidden">
            {days.map((d) => (
              <div key={d}>
                <p className="text-sm font-extrabold text-ink">
                  {dayLabel(d)} <span className="font-semibold text-muted">· {fmtHours(colTotal(d)) || "0"} h</span>
                </p>
                <ul className="mt-1 flex flex-col gap-2">
                  {rows.map((s) => (
                    <li key={s.id} className="flex items-center gap-3">
                      <span className="min-w-0 flex-1 truncate text-sm font-bold text-ink">{names[s.id] ?? s.name}</span>
                      <span className="w-28">{cellInput(s, d)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            <p className="text-sm font-extrabold text-ink">Week total · {fmtHours(weekTotal) || "0"} h</p>
          </div>
        </>
      )}

      {noteFor && (
        <form onSubmit={saveNote} aria-label="Cell note" className="mt-3 rounded-xl border border-border bg-ground p-3">
          <label className="flex flex-col gap-1 text-sm font-bold text-ink">
            Note for {names[noteFor.staffId] ?? "staff"} on {dayLabel(noteFor.date)}
            <input
              value={noteText}
              maxLength={500}
              onChange={(e) => setNoteText(e.target.value)}
              placeholder="e.g. First fix, loft"
              className="h-10 rounded-xl border border-border bg-white px-2 text-sm font-normal"
            />
          </label>
          <div className="mt-2 flex gap-2">
            <button type="submit" disabled={busy !== null} className="h-10 rounded-xl bg-teal px-4 text-sm font-extrabold text-white disabled:opacity-60">
              {busy !== null ? "Saving…" : "Save note"}
            </button>
            <button type="button" onClick={() => setNoteFor(null)} className="h-10 rounded-xl border border-border bg-white px-4 text-sm font-bold text-ink">
              Cancel
            </button>
          </div>
        </form>
      )}

      <p role="status" aria-live="polite" className="mt-2 min-h-5 text-sm font-bold text-teal-dark">
        {busy !== null ? "Saving…" : (note ?? "")}
      </p>
    </section>
  );
}
