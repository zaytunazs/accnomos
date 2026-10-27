"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import type { AccountInfo } from "@azure/msal-browser";
import { errorText, useAccount } from "@/components/jobs/useAccount";
import { RuntimeErrorNote } from "@/components/States";
import { ago } from "@/lib/intake";
import { runtime, type RtDraftReply, type RtTriage, type RtTriageCategory, type RtTriageThread } from "@/lib/runtime";
import {
  dueLabel,
  lastTriage,
  recordTriage,
  savePendingDraft,
  sessionTriage,
  takePendingDraft,
  todosChanged,
  TRIAGE_FRESH_MS,
  triageOn,
} from "@/lib/triage";

const CATEGORY: Record<RtTriageCategory, { label: string; tone: string }> = {
  customer: { label: "Customer", tone: "bg-teal-tint text-teal-dark" },
  supplier: { label: "Supplier", tone: "bg-ground text-ink" },
  hmrc: { label: "HMRC", tone: "bg-warn-bg text-warn-ink" },
  accountant: { label: "Accountant", tone: "bg-ground text-ink" },
  other: { label: "Other", tone: "bg-ground text-muted" },
};

/**
 * Home › Inbox: the last 7 days of business email, one line each (POST /mail/triage, when Settings › Automation ›
 * Inbox triage is on). Expanding a thread shows its summary, a suggested reply that becomes an Outlook *draft* on
 * request (the user sends it from Outlook; Accnomos never sends) and its to-dos, each one *Add*-able to the list.
 */
export default function InboxTriage() {
  const account = useAccount();
  const [on, setOn] = useState<boolean | null>(null);
  const [result, setResult] = useState<RtTriage | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [showOther, setShowOther] = useState(false);
  const [pending, setPending] = useState<{ messageId: string; body: string } | null>(null);
  const started = useRef(false);

  const run = useCallback(async (a: AccountInfo) => {
    setBusy(true);
    setError(null);
    try {
      const r = await runtime.mailTriage(a, { since_days: 7, max_threads: 20 });
      recordTriage(r);
      setResult(r);
    } catch (e) {
      if ((e as Error).message !== "redirecting for consent") setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      setOn(triageOn());
      const cached = sessionTriage();
      if (cached) setResult(cached);
      const p = takePendingDraft();
      if (p) {
        setPending(p);
        const t = cached?.threads.find((x) => x.message_id === p.messageId);
        if (t) setOpen(t.conversation_id);
      }
    });
  }, []);

  useEffect(() => {
    if (!on || !account || started.current) return;
    started.current = true;
    const last = lastTriage();
    const fresh = result && last && Date.now() - new Date(last.at).getTime() < TRIAGE_FRESH_MS;
    if (!fresh) queueMicrotask(() => void run(account));
  }, [on, account, result, run]);

  if (on === null) {
    return (
      <section aria-labelledby="home-inbox" aria-busy="true" className="rounded-2xl border border-border bg-white p-4 sm:p-5 md:col-span-2 xl:col-span-2">
        <h2 id="home-inbox" className="text-lg font-extrabold tracking-tight text-ink">Inbox</h2>
        <div className="mt-3 flex min-h-[7rem] flex-col gap-2">
          <span aria-hidden="true" className="h-4 w-2/3 animate-pulse rounded-md bg-ground" />
          <span aria-hidden="true" className="h-4 w-1/2 animate-pulse rounded-md bg-ground" />
        </div>
      </section>
    );
  }

  if (!on) {
    return (
      <section aria-labelledby="home-inbox" className="rounded-2xl border border-border bg-white p-4 sm:p-5 md:col-span-2 xl:col-span-2">
        <h2 id="home-inbox" className="text-lg font-extrabold tracking-tight text-ink">Inbox</h2>
        <p className="mt-1 min-h-[7rem] text-sm leading-6 text-muted">
          A one-line summary of the week&apos;s emails from customers, suppliers, HMRC and your accountant, with suggested
          replies and to-dos.{" "}
          <Link href="/settings#automation" className="font-bold text-teal-dark">Turn on Inbox triage in Settings</Link>
        </p>
      </section>
    );
  }

  const threads = result?.threads ?? [];
  const business = threads.filter((t) => t.category !== "other");
  const other = threads.filter((t) => t.category === "other");
  const shown = showOther ? [...business, ...other] : business;
  const last = lastTriage();

  return (
    <section aria-labelledby="home-inbox" className="rounded-2xl border border-border bg-white p-4 sm:p-5 md:col-span-2 xl:col-span-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 id="home-inbox" className="text-lg font-extrabold tracking-tight text-ink">Inbox</h2>
          <p className="min-h-5 text-[13px] font-medium text-muted">
            {busy
              ? "Reading the last 7 days…"
              : last
                ? `Last triage: ${ago(last.at)} · ${business.length} business thread${business.length === 1 ? "" : "s"}`
                : "Last 7 days, business email only"}
          </p>
        </div>
        <button
          type="button"
          disabled={!account || busy}
          onClick={() => account && run(account)}
          className="shrink-0 whitespace-nowrap rounded-xl bg-teal px-4 py-2 text-sm font-bold text-white hover:bg-teal-dark disabled:opacity-60"
        >
          {busy ? "Checking…" : "Refresh"}
        </button>
      </div>

      {account === null && <p className="mt-2 min-h-[7rem] text-sm leading-6 text-muted">Sign in with Microsoft to see your inbox here.</p>}
      {error && <RuntimeErrorNote message={error} title="Could not read your inbox" />}
      {result && !busy && threads.length === 0 && (
        <p className="mt-2 min-h-[7rem] text-sm leading-6 text-muted">Nothing from customers, suppliers, HMRC or your accountant this week.</p>
      )}
      {busy && !result && (
        <div aria-busy="true" className="mt-3 flex min-h-[7rem] flex-col gap-2">
          <span aria-hidden="true" className="h-4 w-full animate-pulse rounded-md bg-ground" />
          <span aria-hidden="true" className="h-4 w-5/6 animate-pulse rounded-md bg-ground" />
          <span aria-hidden="true" className="h-4 w-2/3 animate-pulse rounded-md bg-ground" />
        </div>
      )}

      {shown.length > 0 && account && (
        <ul className="mt-3 divide-y divide-border">
          {shown.map((t) => (
            <ThreadRow
              key={t.conversation_id}
              account={account}
              thread={t}
              open={open === t.conversation_id}
              onToggle={() => setOpen(open === t.conversation_id ? null : t.conversation_id)}
              initialReply={pending?.messageId === t.message_id ? pending.body : null}
            />
          ))}
        </ul>
      )}
      {other.length > 0 && (
        <button type="button" onClick={() => setShowOther(!showOther)} className="mt-2 text-[13px] font-bold text-muted hover:text-ink">
          {showOther ? "Hide other email" : `Show ${other.length} other thread${other.length === 1 ? "" : "s"}`}
        </button>
      )}
    </section>
  );
}

function ThreadRow({
  account,
  thread: t,
  open,
  onToggle,
  initialReply,
}: {
  account: AccountInfo;
  thread: RtTriageThread;
  open: boolean;
  onToggle: () => void;
  initialReply: string | null;
}) {
  const cat = CATEGORY[t.category];
  const [reply, setReply] = useState(initialReply ?? t.suggested_reply ?? "");
  const [drafting, setDrafting] = useState(false);
  const [draft, setDraft] = useState<RtDraftReply | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [added, setAdded] = useState<Record<number, "busy" | "done">>({});

  async function makeDraft() {
    setDrafting(true);
    setNote(null);
    savePendingDraft(t.message_id, reply); // Mail.ReadWrite consent may redirect away and back
    try {
      setDraft(await runtime.draftReply(account, t.message_id, reply));
      takePendingDraft();
    } catch (e) {
      if ((e as Error).message === "redirecting for consent") return;
      takePendingDraft();
      setNote(`Could not save the draft: ${errorText(e)}`);
    } finally {
      setDrafting(false);
    }
  }

  async function addTodo(i: number) {
    const todo = t.todos[i];
    setAdded((s) => ({ ...s, [i]: "busy" }));
    try {
      await runtime.addTodo(account, {
        text: todo.text,
        due: todo.due,
        source: { kind: "mail", message_id: t.message_id, subject: t.subject.slice(0, 200), web_link: t.web_link },
      });
      setAdded((s) => ({ ...s, [i]: "done" }));
      todosChanged();
    } catch (e) {
      setAdded((s) => {
        const next = { ...s };
        delete next[i];
        return next;
      });
      setNote(`Could not add the to-do: ${errorText(e)}`);
    }
  }

  return (
    <li className="py-2">
      <button type="button" onClick={onToggle} aria-expanded={open} className="flex w-full items-center gap-2 text-left">
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-extrabold ${cat.tone}`}>{cat.label}</span>
        {t.unread && <span aria-label="unread" className="h-2 w-2 shrink-0 rounded-full bg-teal" />}
        <span className="shrink-0 text-sm font-bold text-ink">{t.from_name || t.from_address}</span>
        <span className="min-w-0 flex-1 truncate text-sm text-muted">{t.summary}</span>
        {t.needs_reply && <span className="shrink-0 text-[11px] font-extrabold text-amber">Reply</span>}
        {t.todos.length > 0 && <span className="shrink-0 text-[11px] font-bold text-muted">{t.todos.length} to-do</span>}
        <span className="shrink-0 text-[12px] text-muted">{ago(t.received_at)}</span>
      </button>

      {open && (
        <div className="mt-2 space-y-3 rounded-xl bg-ground px-3 py-3 text-sm">
          <div>
            <p className="font-bold text-ink">{t.summary}</p>
            <p className="mt-0.5 text-[13px] text-muted">
              {t.subject || "(no subject)"} · {t.message_count} message{t.message_count === 1 ? "" : "s"}
              {t.web_link && (
                <>
                  {" · "}
                  <a href={t.web_link} target="_blank" rel="noopener noreferrer" className="font-bold text-teal-dark">
                    Open in Outlook
                  </a>
                </>
              )}
            </p>
            {t.fallback_reason && <p className="mt-1 text-[13px] text-muted">{t.fallback_reason}</p>}
          </div>

          {t.needs_reply && (
            <div>
              <label htmlFor={`reply-${t.conversation_id}`} className="text-[13px] font-bold text-muted">
                Suggested reply (edit it here or in Outlook)
              </label>
              <textarea
                id={`reply-${t.conversation_id}`}
                value={reply}
                onChange={(e) => setReply(e.target.value)}
                rows={5}
                maxLength={5000}
                placeholder="Write your reply…"
                className="mt-1 w-full rounded-xl border border-border bg-white p-2 text-sm text-ink"
              />
              <div className="mt-1 flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={makeDraft}
                  disabled={drafting || !reply.trim() || draft !== null}
                  className="rounded-xl bg-teal px-4 py-2 text-sm font-bold text-white hover:bg-teal-dark disabled:opacity-60"
                >
                  {drafting ? "Saving draft…" : draft ? "Draft saved" : "Draft in Outlook"}
                </button>
                {draft?.web_link && (
                  <a href={draft.web_link} target="_blank" rel="noopener noreferrer" className="font-bold text-teal-dark">
                    Open the draft
                  </a>
                )}
                <span className="text-[12px] text-muted">Saved to your Drafts. Accnomos never sends: you send it from Outlook.</span>
              </div>
            </div>
          )}

          {t.todos.length > 0 && (
            <div>
              <p className="text-[13px] font-bold text-muted">To-dos</p>
              <ul className="mt-1 space-y-1">
                {t.todos.map((todo, i) => (
                  <li key={`${todo.text}-${i}`} className="flex items-center justify-between gap-2">
                    <span className="text-ink">
                      {todo.text}
                      {todo.due && <span className="ml-2 text-[12px] font-bold text-muted">by {dueLabel(todo.due)}</span>}
                    </span>
                    <button
                      type="button"
                      onClick={() => addTodo(i)}
                      disabled={added[i] !== undefined}
                      className="shrink-0 rounded-lg border border-border bg-white px-2 py-0.5 text-[12px] font-bold text-teal-dark disabled:opacity-60"
                    >
                      {added[i] === "done" ? "Added" : added[i] === "busy" ? "Adding…" : "Add"}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {note && <p className="text-[13px] font-bold text-warn-ink">{note}</p>}
        </div>
      )}
    </li>
  );
}
