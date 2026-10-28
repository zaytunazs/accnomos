"use client";

import { useCallback, useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { errorText } from "@/components/jobs/useAccount";
import { RuntimeErrorNote } from "@/components/States";
import { SUBJECT_LABELS, type QuerySubjectKind, type RtQuery } from "@/lib/accountant";
import { accountantApi } from "@/lib/runtime";

const when = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/London" });

/**
 * Client queries in whichever books are open (yours, or the client's from the portal). `me` is the side this page
 * speaks for: the accountant asks and answers on /accountant, the client answers in Settings › Your accountant.
 */
export default function QueryThreads({
  account,
  me,
  canAsk,
  prefill,
  heading,
}: {
  account: AccountInfo;
  me: "accountant" | "client";
  canAsk: boolean;
  prefill?: { kind: QuerySubjectKind; ref: string; label: string } | null;
  heading: string;
}) {
  const [threads, setThreads] = useState<RtQuery[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showResolved, setShowResolved] = useState(false);
  const [kind, setKind] = useState<QuerySubjectKind>(prefill?.kind ?? "transaction");
  const [about, setAbout] = useState(prefill?.label ?? "");
  const [ref] = useState(prefill?.ref ?? "");
  const [text, setText] = useState("");
  const [replies, setReplies] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");

  const load = useCallback(async () => {
    try {
      setThreads(await accountantApi.queries(account, {}, me === "client"));
      setError(null);
    } catch (e) {
      setError(errorText(e));
    }
  }, [account, me]);

  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    try {
      await accountantApi.openQuery(account, { subject: { kind, ref, label: about.trim() }, text }, me === "client");
      setText("");
      setAbout("");
      setStatus("Query sent. It shows on your client's to-do list.");
      await load();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function answer(id: string) {
    const reply = (replies[id] ?? "").trim();
    if (!reply) return;
    setBusy(true);
    try {
      await accountantApi.reply(account, id, reply, me === "client");
      setReplies((r) => ({ ...r, [id]: "" }));
      setStatus("Reply sent.");
      await load();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function resolve(id: string) {
    setBusy(true);
    try {
      await accountantApi.resolve(account, id, me === "client");
      setStatus("Marked as resolved.");
      await load();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const shown = (threads ?? []).filter((q) => showResolved || q.status === "open");
  const resolvedCount = (threads ?? []).filter((q) => q.status === "resolved").length;

  return (
    <section aria-labelledby="queries-heading" className="rounded-2xl border border-border bg-white p-4">
      <h2 id="queries-heading" className="text-[17px] font-extrabold text-ink">
        {heading}
      </h2>
      <p className="mt-1 text-sm text-muted">
        {me === "accountant"
          ? "Ask about a transaction or a document. Your client sees it as a to-do and answers here; you both see the thread."
          : "Questions from your accountant. Answer here; they see your reply on their side. Kept in _System/queries in your OneDrive."}
      </p>
      {error && <RuntimeErrorNote message={error} />}
      <p role="status" className="mt-2 min-h-5 text-sm text-ink">
        {status}
      </p>

      {canAsk && (
        <form onSubmit={ask} aria-label="New query" className="mt-2 space-y-2 rounded-xl bg-ground p-3">
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="text-sm font-semibold text-ink">
              About
              <select
                value={kind}
                onChange={(e) => setKind(e.target.value as QuerySubjectKind)}
                className="mt-1 h-11 w-full rounded-xl border border-border bg-white px-3 text-[15px]"
              >
                {(Object.keys(SUBJECT_LABELS) as QuerySubjectKind[]).map((k) => (
                  <option key={k} value={k}>
                    {SUBJECT_LABELS[k]}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm font-semibold text-ink">
              Which one
              <input
                value={about}
                onChange={(e) => setAbout(e.target.value)}
                maxLength={200}
                placeholder="e.g. Screwfix, £12.00, 3 Oct"
                className="mt-1 h-11 w-full rounded-xl border border-border bg-white px-3 text-[15px]"
              />
            </label>
          </div>
          <label className="block text-sm font-semibold text-ink">
            Your question
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              maxLength={4000}
              rows={3}
              required
              className="mt-1 w-full rounded-xl border border-border bg-white p-3 text-[15px]"
            />
          </label>
          <button
            type="submit"
            disabled={busy || !text.trim()}
            className="h-11 rounded-xl bg-teal px-5 text-[15px] font-extrabold text-white disabled:opacity-60"
          >
            Send query
          </button>
        </form>
      )}

      {threads === null && !error && <p className="mt-3 text-sm text-muted">Loading queries…</p>}
      {threads !== null && shown.length === 0 && <p className="mt-3 text-sm text-muted">No open queries.</p>}
      <ul className="mt-3 space-y-3" aria-label="Queries">
        {shown.map((q) => {
          const title = `${SUBJECT_LABELS[q.subject.kind]}${q.subject.label ? `: ${q.subject.label}` : ""}`;
          const yourTurn = q.waiting_on === me;
          return (
            <li key={q.id} className="rounded-xl border border-border p-3">
              <article aria-label={title}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-[15px] font-bold text-ink">{title}</h3>
                  <span
                    className={`rounded-full px-2 py-0.5 text-[12px] font-bold ${
                      q.status === "resolved" ? "bg-ground text-muted" : yourTurn ? "bg-warn-bg text-warn-ink" : "bg-teal-tint text-teal-dark"
                    }`}
                  >
                    {q.status === "resolved" ? "Resolved" : yourTurn ? "Waiting on you" : me === "accountant" ? "Waiting on client" : "Waiting on accountant"}
                  </span>
                </div>
                <ol className="mt-2 space-y-2">
                  {q.messages.map((m, i) => (
                    <li key={i} className="text-sm">
                      <p className="text-[12px] font-semibold text-muted">
                        {m.role === me ? "You" : m.role === "accountant" ? `Accountant (${m.author})` : `Client (${m.author})`} · {when(m.ts)}
                      </p>
                      <p className="whitespace-pre-wrap text-ink">{m.text}</p>
                    </li>
                  ))}
                </ol>
                <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-end">
                  <label className="flex-1 text-sm font-semibold text-ink">
                    Reply
                    <textarea
                      value={replies[q.id] ?? ""}
                      onChange={(e) => setReplies((r) => ({ ...r, [q.id]: e.target.value }))}
                      rows={2}
                      maxLength={4000}
                      className="mt-1 w-full rounded-xl border border-border p-2 text-[15px]"
                    />
                  </label>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => answer(q.id)}
                      disabled={busy || !(replies[q.id] ?? "").trim()}
                      className="h-11 rounded-xl bg-teal px-4 text-sm font-bold text-white disabled:opacity-60"
                    >
                      Send reply
                    </button>
                    {q.status === "open" && (
                      <button
                        type="button"
                        onClick={() => resolve(q.id)}
                        disabled={busy}
                        className="h-11 rounded-xl border-2 border-teal bg-white px-4 text-sm font-bold text-teal-dark disabled:opacity-60"
                      >
                        Mark resolved
                      </button>
                    )}
                  </div>
                </div>
              </article>
            </li>
          );
        })}
      </ul>
      {resolvedCount > 0 && (
        <button type="button" onClick={() => setShowResolved((v) => !v)} className="mt-3 text-sm font-bold text-teal-dark underline">
          {showResolved ? "Hide resolved" : `Show resolved (${resolvedCount})`}
        </button>
      )}
    </section>
  );
}
