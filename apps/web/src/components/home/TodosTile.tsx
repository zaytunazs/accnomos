"use client";

import { useCallback, useEffect, useState } from "react";
import { errorText, useAccount } from "@/components/jobs/useAccount";
import { RuntimeErrorNote } from "@/components/States";
import { runtime, type RtTodo } from "@/lib/runtime";
import { dueLabel, overdue, TODOS_CHANGED } from "@/lib/triage";

const SHOWN = 5;

/** Home › To-dos: the list in _System/Todos/todos.json, soonest first. *Done* removes one. */
export default function TodosTile() {
  const account = useAccount();
  const [todos, setTodos] = useState<RtTodo[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!account) return;
    try {
      setTodos(await runtime.todos(account));
      setError(null);
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
    <section aria-labelledby="home-todos" className="rounded-2xl border border-border bg-white p-4">
      <h2 id="home-todos" className="text-sm font-semibold text-muted">To-dos</h2>
      <p className="mt-1 text-2xl font-extrabold tracking-tight text-ink">{todos ? todos.length : "–"}</p>
      <p className={`text-[13px] font-semibold ${late ? "text-warn-ink" : "text-muted"}`}>
        {account === null ? "Sign in to keep a to-do list" : late ? `${late} overdue` : "Add them from your inbox"}
      </p>
      {error && <RuntimeErrorNote message={error} />}
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
    </section>
  );
}
