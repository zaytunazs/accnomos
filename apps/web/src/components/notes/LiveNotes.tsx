"use client";

import { useCallback, useEffect, useState } from "react";
import { errorText, useAccount } from "@/components/jobs/useAccount";
import SignInCta from "@/components/SignInCta";
import { LoadingSkeleton, RuntimeErrorNote } from "@/components/States";
import { runtime, type RtNote } from "@/lib/runtime";

const card = "rounded-2xl border border-border bg-white p-4 sm:p-5";
const input = "h-11 min-w-0 flex-1 rounded-xl border border-border bg-white px-3 text-[15px]";
const button = "h-11 rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-60";
const quiet = "h-10 rounded-xl border border-border bg-white px-3 text-[14px] font-bold hover:bg-ground disabled:opacity-60";

const day = (iso: string) =>
  new Date(iso.length === 10 ? `${iso}T12:00:00` : iso).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "Europe/London" });

/** /notes: the notes the assistant saves, plus typed ones; delete asks first. */
export default function LiveNotes() {
  const account = useAccount();
  const [notes, setNotes] = useState<RtNote[] | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!account) return;
    try {
      setNotes(await runtime.notes(account));
      setError(null);
    } catch (e) {
      if ((e as Error).message !== "redirecting for consent") setError(errorText(e));
    }
  }, [account]);

  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  async function act(key: string, fn: () => Promise<unknown>) {
    setBusy(key);
    setError(null);
    try {
      await fn();
      await load();
      return true;
    } catch (e) {
      setError(errorText(e));
      return false;
    } finally {
      setBusy(null);
    }
  }

  if (account === undefined) return <LoadingSkeleton lines={3} label="Loading your notes…" />;
  if (account === null)
    return (
      <div className={`${card} flex flex-col items-start gap-3`}>
        <p className="text-[15px] leading-7 text-muted">Once your OneDrive is connected, notes you type or say to the assistant are kept here.</p>
        <SignInCta />
      </div>
    );

  return (
    <div className="flex flex-col gap-4">
      <form
        className={`${card} flex flex-wrap gap-2`}
        onSubmit={async (e) => {
          e.preventDefault();
          if (!text.trim()) return;
          if (await act("add", () => runtime.addNote(account, text.trim()))) setText("");
        }}
      >
        <label htmlFor="note-text" className="sr-only">
          New note
        </label>
        <input id="note-text" className={input} value={text} maxLength={500} placeholder="Write a note…" onChange={(e) => setText(e.target.value)} />
        <button type="submit" className={button} disabled={busy !== null || !text.trim()}>
          {busy === "add" ? "Saving…" : "Save note"}
        </button>
      </form>
      {error && <RuntimeErrorNote message={error} onRetry={() => void load()} />}
      {notes === null ? (
        !error && <LoadingSkeleton lines={2} label="Loading your notes…" />
      ) : notes.length === 0 ? (
        <p className={`${card} text-[15px] text-muted`}>No notes yet. Type one above, or tell the assistant “take a note: …”.</p>
      ) : (
        <ul className={`${card} divide-y divide-border`} aria-label="Your notes">
          {notes.map((n) => (
            <li key={n.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
              <div className="min-w-0 flex-1">
                <p className="text-[15px] leading-6">{n.text}</p>
                <p className="mt-0.5 text-[12px] text-muted">
                  {day(n.created)}
                  {n.source === "voice" ? " · spoken" : ""}
                  {n.due ? ` · due ${day(n.due)}` : ""}
                </p>
              </div>
              {confirming === n.id ? (
                <div className="flex items-center gap-2" role="group" aria-label="Confirm delete">
                  <span className="text-[14px] font-bold">Delete this note?</span>
                  <button
                    type="button"
                    className={`${quiet} border-warn-border text-warn-ink`}
                    disabled={busy !== null}
                    onClick={async () => {
                      if (await act(n.id, () => runtime.deleteNote(account, n.id))) setConfirming(null);
                    }}
                  >
                    {busy === n.id ? "Deleting…" : "Delete"}
                  </button>
                  <button type="button" className={quiet} onClick={() => setConfirming(null)}>
                    Keep
                  </button>
                </div>
              ) : (
                <button type="button" className={quiet} aria-label={`Delete note: ${n.text}`} onClick={() => setConfirming(n.id)}>
                  Delete
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
