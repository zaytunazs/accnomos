"use client";

import { useCallback, useEffect, useState } from "react";
import { errorText } from "@/components/invoices/InvoiceDialogs";
import { primaryButton } from "@/components/invoices/Modal";
import SignInCta from "@/components/SignInCta";
import { EmptyState, LoadingSkeleton, RuntimeErrorNote } from "@/components/States";
import RepeatingFormDialog from "@/components/trade/RepeatingFormDialog";
import { RepeatingRunNote, runDueRepeating } from "@/components/trade/repeatingRun";
import { money, useMsAccount } from "@/lib/invoices";
import { runtime, ukDate, type RtRepeating, type RtRepeatingResult } from "@/lib/runtime";

const action = "text-[13px] font-bold text-teal-dark hover:underline";
const FREQ_WORD = { weekly: "week", monthly: "month", quarterly: "quarter", yearly: "year" } as const;

function schedule(t: RtRepeating): string {
  const w = FREQ_WORD[t.frequency];
  return t.every === 1 ? `Every ${w}` : `Every ${t.every} ${w}s`;
}

export default function LiveRepeating() {
  const { account, ready } = useMsAccount();
  const [list, setList] = useState<RtRepeating[] | null>(null);
  const [result, setResult] = useState<RtRepeatingResult | null>(null);
  const [dialog, setDialog] = useState<{ template: RtRepeating | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!account) return;
    try {
      // Anything that has come due is made first, so the list below already shows what it made.
      setResult(await runDueRepeating(account));
      setList(await runtime.repeating(account));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [account]);
  useEffect(() => {
    queueMicrotask(load);
  }, [load]);

  async function stop(t: RtRepeating) {
    if (!account) return;
    try {
      await runtime.deleteRepeating(account, t.id);
      setNote(`${t.name || t.party.name} is stopped. What it already made stays.`);
      await load();
    } catch (e) {
      setError(errorText(e) ?? "Something went wrong.");
    }
  }

  async function togglePause(t: RtRepeating) {
    if (!account) return;
    try {
      const { id: _id, last_run_at: _a, last_error: _b, history: _c, next_date: _d, finished: _e, due_now: _f, totals: _g, ...body } = t;
      void [_id, _a, _b, _c, _d, _e, _f, _g];
      await runtime.updateRepeating(account, t.id, { ...body, paused: !t.paused });
      setNote(t.paused ? "Resumed." : "Paused. Nothing is made until you resume it.");
      await load();
    } catch (e) {
      setError(errorText(e) ?? "Something went wrong.");
    }
  }

  if (ready && !account) {
    return (
      <p className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl bg-ground p-4 text-sm text-muted">
        <SignInCta />
        <span>to set up repeating invoices and bills; they are saved in your OneDrive under _System/Repeating.</span>
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted">Things that have come due are made when you open this page.</p>
        <button type="button" className={primaryButton} onClick={() => setDialog({ template: null })}>New repeating item</button>
      </div>
      <RepeatingRunNote result={result} />
      {note && <p role="status" className="rounded-xl bg-teal-tint px-4 py-3 text-sm font-bold text-teal-dark">{note}</p>}
      {error && <RuntimeErrorNote message={error} title="Could not complete that" />}
      {!list && !error && <LoadingSkeleton lines={3} label="Loading your repeating items…" />}
      {list && list.length === 0 && (
        <EmptyState title="Nothing repeats yet" body="Set up an invoice you send, or a bill you receive, on a schedule. Each one is made as a draft for you, unless you tick Approve automatically." />
      )}
      {list && list.length > 0 && account && (
        <ul className="divide-y divide-border rounded-2xl border border-border bg-white">
          {list.map((t) => (
            <li key={t.id} className="px-4 py-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-[15px] font-bold">{t.name || t.party.name} · {t.kind === "invoice" ? "invoice" : "bill"}</p>
                  <p className="text-sm text-muted">
                    {schedule(t)} from {ukDate(t.start_date)}{t.end_date && ` to ${ukDate(t.end_date)}`}
                    {" · "}
                    {t.paused ? <span className="font-bold text-ink">Paused</span>
                      : t.next_date ? <>next run <span className="font-bold text-ink">{ukDate(t.next_date)}</span></>
                      : <span className="font-bold text-ink">Finished</span>}
                    {" · "}{t.approve_automatically ? "approves automatically" : t.kind === "invoice" ? "makes drafts" : "waits in Review"}
                  </p>
                  {t.last_error && <p role="alert" className="mt-1 text-sm font-semibold text-warn-ink">Last problem: {t.last_error}</p>}
                </div>
                <span className="text-[15px] font-extrabold tabular-nums">{money(t.totals[2])}</span>
              </div>
              <div className="mt-2 flex flex-wrap gap-4">
                <button type="button" className={action} onClick={() => setDialog({ template: t })}>Edit</button>
                {t.next_date && <button type="button" className={action} onClick={() => togglePause(t)}>{t.paused ? "Resume" : "Pause"}</button>}
                <button type="button" className="text-[13px] font-bold text-muted hover:underline" onClick={() => stop(t)}>Stop</button>
              </div>
              {t.history.length > 0 && (
                <details className="mt-2">
                  <summary className={`${action} cursor-pointer`}>What it made</summary>
                  <ul className="mt-2 space-y-1 text-sm">
                    {[...t.history].reverse().map((h) => (
                      <li key={h.index} className="flex justify-between gap-3">
                        <span>{ukDate(h.date)} · {h.number ?? (h.proposal_id ? "bill in Review" : "")} · {h.outcome}{h.note ? ` (${h.note})` : ""}</span>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </li>
          ))}
        </ul>
      )}
      {dialog && account && (
        <RepeatingFormDialog account={account} template={dialog.template} onClose={() => setDialog(null)}
          onSaved={(t) => { setDialog(null); setNote(`${t.name || t.party.name} saved. Next run ${t.next_date ? ukDate(t.next_date) : "none: it has finished"}.`); void load(); }} />
      )}
    </div>
  );
}
