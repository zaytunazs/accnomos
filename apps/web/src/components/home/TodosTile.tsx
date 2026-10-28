"use client";

import { useCallback, useEffect, useState } from "react";
import ByWhom from "@/components/ByWhom";
import ExplainMore from "@/components/ExplainMore";
import { errorText, useAccount } from "@/components/jobs/useAccount";
import { RuntimeErrorNote } from "@/components/States";
import Link from "next/link";
import { getClientContext, SUBJECT_LABELS, type RtQuery } from "@/lib/accountant";
import { accountantApi, runtime, type RtTodo } from "@/lib/runtime";
import { dueLabel, overdue, TODOS_CHANGED } from "@/lib/triage";

const SHOWN = 5;

/** Home › To-dos: the list in _System/Todos/todos.json, soonest first. *Done* removes one. */
export default function TodosTile() {
  const account = useAccount();
  const [todos, setTodos] = useState<RtTodo[] | null>(null);
  const [queries, setQueries] = useState<RtQuery[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!account) return;
    try {
      setTodos(await runtime.todos(account));
      setError(null);
      // Your accountant's questions waiting on you (app/queries.py); not while you look at a client's books.
      if (!getClientContext()) {
        setQueries(await accountantApi.queries(account, { status: "open", waiting_on: "client" }).catch(() => []));
      }
    } catch (e) {
      if ((e as Error).message !== "redirecting for consent") setError(errorText(e));
    }
  }, [account]);

  useEffect(() => {
    queueMicrotask(() => void load());
    const onChange = () => void load();
    window.addEventListener(TODOS_CHANGED, onChange);
    return () => window.removeEventListener(TODOS_CHANGED, onChange);
  }, [load]);

  async function done(id: string) {
    if (!account) return;
    setTodos((ts) => ts?.filter((t) => t.id !== id) ?? null);
    try {
      await runtime.deleteTodo(account, id);
    } catch (e) {
      setError(errorText(e));
      void load();
    }
  }

  const late = todos?.filter((t) => t.due && overdue(t.due)).length ?? 0;

  return (
    <section aria-labelledby="home-todos" className="flex flex-col rounded-2xl border border-border bg-white p-4 sm:p-5">
      <div className="flex items-center gap-2">
        <h2 id="home-todos" className="text-lg font-extrabold tracking-tight">To-dos</h2>
        <ExplainMore title="Where to-dos come from" anchor="inbox">
          To-dos are suggested by your AI from your inbox threads and added when you tap Add; Done removes one.
          The list lives in _System/Todos in your OneDrive.
        </ExplainMore>
      </div>
      <p className="mt-1 min-h-9 text-3xl font-extrabold tracking-tight tabular-nums text-ink">{todos ? todos.length + queries.length : "–"}</p>
      <p className={`min-h-5 text-[13px] font-semibold ${late ? "text-warn-ink" : "text-muted"}`}>
        {account === null ? "Sign in to keep a to-do list" : late ? `${late} overdue` : "Add them from your inbox"}
      </p>
      {error && <RuntimeErrorNote message={error} />}
      <div className="min-h-[7rem]">
        {queries.length > 0 && (
          <ul aria-label="Queries from your accountant" className="mt-3 space-y-1.5">
            {queries.map((q) => (
              <li key={q.id} className="text-sm">
                <Link href="/settings#settings-accountant" className="font-semibold text-ink hover:underline">
                  Answer your accountant: {q.subject.label || SUBJECT_LABELS[q.subject.kind]}
                </Link>
              </li>
            ))}
          </ul>
        )}
        {todos && todos.length > 0 && (
          <ul className="mt-3 space-y-1.5">
            {todos.slice(0, SHOWN).map((t) => (
              <li key={t.id} className="flex items-start justify-between gap-2 text-sm">
                <span className="min-w-0 text-ink">
                  {t.source?.web_link ? (
                    <a href={t.source.web_link} target="_blank" rel="noopener noreferrer" title={t.source.subject} className="hover:underline">
                      {t.text}
                    </a>
                  ) : (
                    t.text
                  )}
                  {t.due && (
                    <span className={`ml-2 text-[12px] font-bold ${overdue(t.due) ? "text-warn-ink" : "text-muted"}`}>{dueLabel(t.due)}</span>
                  )}
                </span>
                <button
                  type="button"
                  onClick={() => done(t.id)}
                  aria-label={`Done: ${t.text}`}
                  className="shrink-0 rounded-lg border border-border px-2 py-0.5 text-[12px] font-bold text-teal-dark hover:bg-ground"
                >
                  Done
                </button>
              </li>
            ))}
            {todos.length > SHOWN && <li className="text-[12px] text-muted">and {todos.length - SHOWN} more</li>}
          </ul>
        )}
      </div>
      <ByWhom className="mt-2" code="Added by you from your inbox" ai="suggested by your AI" />
      {account ? (
        <div className="mt-auto pt-4">
          <a
            href="#home-inbox"
            className="inline-block whitespace-nowrap rounded-xl bg-teal px-4 py-2 text-sm font-bold text-white hover:bg-teal-dark"
          >
            Go to inbox
          </a>
        </div>
      ) : null}
    </section>
  );
}
