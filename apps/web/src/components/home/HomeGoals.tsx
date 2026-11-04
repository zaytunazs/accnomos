"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import GoalCard, { GoalsNotePanel } from "@/components/goals/GoalCard";
import { errorText, todayIso } from "@/components/jobs/useAccount";
import { RuntimeErrorNote } from "@/components/States";
import { byUrgency, goalsApi, type RtGoalsView } from "@/lib/goals";
import { sampleGoals } from "@/lib/sample-goals";
import { Skeleton, useHome } from "./HomeData";

/**
 * Home › Goals & progress (design brief §6–8): up to three goals, most urgent first, and the checked note. Its own
 * GET /books/goals, so a failure here blanks only this section. Signed out (/try): the fictional sample goals.
 * The note is first in the DOM (right under the heading on a phone) and moves below the cards from `md`
 * (`md:order-last`), so the reading order matches the visual order at every width.
 */
export default function HomeGoals() {
  const home = useHome();
  const account = home.mode === "loading" || home.mode === "live" || home.mode === "error" ? home.account : null;
  const [view, setView] = useState<RtGoalsView | null>(null);
  const [wording, setWording] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!account) return;
    try {
      setError(null);
      // Fast first (code's note), then the AI's note swapped in, so the cards never wait on the model.
      const fast = await goalsApi.list(account, todayIso(), false);
      setView(fast);
      if (!fast.goals.length) return;
      setWording(true);
      goalsApi.list(account, todayIso()).then(
        (full) => setView((cur) => (cur ? { ...cur, note: full.note } : full)),
        () => undefined, // keep code's note
      ).finally(() => setWording(false));
    } catch (e) {
      setError(errorText(e));
    }
  }, [account]);

  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  if (home.mode === "checking") return null;
  const v = home.mode === "sample" ? sampleGoals : view;
  const sample = home.mode === "sample";
  const link = "inline-flex min-h-11 items-center rounded-xl border border-border bg-white px-4 text-[15px] font-bold text-ink hover:bg-ground";

  return (
    <section aria-labelledby="home-goals-title" data-home-goals="" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 id="home-goals-title" className="text-[20px] font-bold tracking-tight text-ink">
            Goals &amp; progress
          </h2>
          <p className="mt-0.5 text-[15px] text-muted">
            {sample ? "Sample — fictional figures. " : ""}Your targets, against the evidence in your books.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {v && v.goals.length ? (
            <Link href="/goals" className={link}>
              View all
            </Link>
          ) : null}
          {!sample ? (
            <Link href="/goals#add" className={link}>
              + Add a goal
            </Link>
          ) : null}
        </div>
      </div>
      {error && !v ? (
        <RuntimeErrorNote message={error} title="Your goals could not be loaded" onRetry={() => void load()} />
      ) : !v ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" role="status">
          <span className="sr-only">Loading your goals…</span>
          {[0, 1, 2].map((i) => (
            <div key={i} className="rounded-2xl border border-border bg-white p-5">
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="mt-4 block h-7 w-1/3" />
              <Skeleton className="mt-4 block h-2 w-full" />
            </div>
          ))}
        </div>
      ) : v.goals.length === 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border bg-white px-4 py-4 sm:px-5">
          <p className="text-[15px] text-muted">
            No goals yet. Save for something, spend less on a category or reach a {v.household ? "income" : "sales"} figure.
          </p>
          <Link href="/goals#add" className="inline-flex h-11 items-center rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark">
            Set your first goal
          </Link>
        </div>
      ) : (
        <>
          {/* Rendered once: first in the DOM, last from md (the section is a flex column). */}
          <GoalsNotePanel note={v.note} sample={sample} wording={!sample && wording} className="md:order-last" />
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {byUrgency(v.goals)
              .slice(0, 3)
              .map((p) => (
                <GoalCard key={p.goal.id} p={p} sample={sample} detailsHref={`/goals#goal-${p.goal.id}`} />
              ))}
          </div>
        </>
      )}
    </section>
  );
}
