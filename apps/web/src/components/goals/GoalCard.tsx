import Link from "next/link";
import type { ReactNode } from "react";
import AiWorking from "@/components/AiWorking";
import { BADGE_TONE, badgeClass, type BadgeTone } from "@/components/StatusBadge";
import { headline, money, type GoalTone, type RtGoalProgress, type RtGoalsNote } from "@/lib/goals";

/**
 * One goal as a card (design brief §7), in this order of weight: the name and the runtime's own status words; the
 * figure so far, large; the target or limit and the progress bar with the even-pace plan marked (only when the
 * runtime gives one); one variance sentence that says what the gap is; then, quieter, what is still needed or the
 * run-rate estimate, where the figure comes from, and View details.
 * Status is never colour alone: the badge and the variance line carry the words.
 */

const BADGE_OF: Record<GoalTone, BadgeTone> = { positive: "success", warning: "warning", negative: "negative", neutral: "neutral" };

/** The shared badge classes per goal tone (components/StatusBadge.tsx). */
export const TONE_BADGE: Record<GoalTone, string> = {
  positive: BADGE_TONE.success,
  warning: BADGE_TONE.warning,
  negative: BADGE_TONE.negative,
  neutral: BADGE_TONE.neutral,
};
const TONE_TEXT: Record<GoalTone, string> = {
  positive: "text-pos-ink",
  warning: "text-warn-ink",
  negative: "text-neg-ink",
  neutral: "text-muted",
};

export function StatusBadge({ p }: { p: RtGoalProgress }) {
  return (
    <span data-goal-status={p.status} className={badgeClass(BADGE_OF[p.tone], "shrink-0")}>
      {p.status_label}
    </span>
  );
}

const up = (p: RtGoalProgress) => p.goal.kind === "save" || p.goal.kind === "earn";

export function GoalBar({ p }: { p: RtGoalProgress }) {
  if (p.target_pence === null || p.percent === null) return null;
  const width = Math.max(0, Math.min(100, p.percent));
  const plan =
    p.plan_to_date_pence !== null && p.target_pence > 0
      ? Math.max(0, Math.min(100, (p.plan_to_date_pence / p.target_pence) * 100))
      : null;
  const fill = p.tone === "negative" ? "bg-neg-ink" : "bg-teal";
  const label = up(p) ? `${p.goal.name}: ${p.percent}% of target` : `${p.goal.name}: ${p.percent}% of limit used`;
  return (
    <div className="mt-3">
      <div className="relative">
        <div
          role="progressbar"
          aria-label={label}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={width}
          className="h-2 w-full overflow-hidden rounded-full bg-border"
        >
          <div className={`h-full rounded-full ${fill}`} style={{ width: `${width}%` }} />
        </div>
        {plan !== null && p.status !== "not_started" ? (
          <span
            aria-hidden="true"
            className="absolute -top-1 h-4 w-0.5 rounded bg-ink"
            style={{ left: `calc(${plan}% - 1px)` }}
          />
        ) : null}
      </div>
      <div className="mt-1.5 flex flex-wrap justify-between gap-x-3 gap-y-0.5 text-[13px] text-muted">
        <span>{up(p) ? `${p.percent}% of target` : `${p.percent}% of limit used`}</span>
        {p.plan_to_date_pence !== null && p.status !== "not_started" ? (
          <span>Plan to date: {money(p.plan_to_date_pence)}</span>
        ) : null}
      </div>
    </div>
  );
}

/** The quieter detail: what is still needed, and the run-rate estimate (never guaranteed). */
export function Inset({ p }: { p: RtGoalProgress }) {
  // A run-rate of nothing says nothing (no money in or out yet): leave it out.
  const run = p.run_rate_pence ? p.run_rate_pence : null;
  if (!p.needed_text && (run === null || run === undefined)) return null;
  return (
    <div className="mt-3 rounded-xl bg-ground px-3 py-2.5 text-[13px] leading-5 text-muted">
      {p.needed_text ? <p>{p.needed_text}</p> : null}
      {run !== null && run !== undefined ? (
        <p className={p.needed_text ? "mt-1" : ""}>
          <span className="font-bold text-ink">Run-rate estimate: {money(run)}</span> — at the same daily pace. Not guaranteed.
        </p>
      ) : null}
    </div>
  );
}

export default function GoalCard({
  p,
  detailsHref,
  footer,
  sample = false,
}: {
  p: RtGoalProgress;
  detailsHref?: string;
  footer?: ReactNode;
  sample?: boolean;
}) {
  const id = `goal-${p.goal.id}`;
  return (
    <article
      aria-labelledby={`${id}-name`}
      data-goal={p.goal.id}
      className="flex min-w-0 flex-col rounded-2xl border border-border bg-white p-4 sm:p-5"
    >
      <div className="flex items-start justify-between gap-3">
        <h3 id={`${id}-name`} className="min-w-0 break-words text-base font-bold leading-6 text-ink">
          {p.goal.name}
        </h3>
        <StatusBadge p={p} />
      </div>
      <p className="mt-0.5 text-[13px] text-muted">
        {p.kind_label} · {p.period_label}
        {sample ? " · Sample" : ""}
      </p>
      <p className="mt-3 text-[30px] font-bold leading-none tracking-tight text-ink tabular-nums">
        {headline(p.current_pence)}
      </p>
      <p className="mt-1.5 text-[13px] font-semibold text-muted">{p.target_label}</p>
      <GoalBar p={p} />
      <p className={`mt-3 text-[15px] font-semibold leading-6 ${TONE_TEXT[p.tone]}`}>{p.variance_text}</p>
      <Inset p={p} />
      <p className="mt-3 text-[12px] leading-5 text-muted">{p.source_text}</p>
      <div className="mt-auto flex flex-wrap items-center gap-3 pt-3">
        {detailsHref ? (
          <Link href={detailsHref} className="inline-flex min-h-11 items-center text-[15px] font-bold text-teal-dark hover:underline">
            View details <span aria-hidden="true">&nbsp;→</span>
          </Link>
        ) : null}
        {footer}
      </div>
    </article>
  );
}

/**
 * "What your goals are telling you": a calm note, not a chat (design brief §8). On a phone it sits right under the
 * section heading, before the cards; from `md` the cards come first (`md:order-last` in a flex column), so the DOM
 * order is the reading order at every width and the note is rendered once.
 */
export function GoalsNotePanel({
  note,
  sample = false,
  wording = false,
  className = "",
}: {
  note: RtGoalsNote;
  sample?: boolean;
  wording?: boolean;
  className?: string;
}) {
  if (!note.note_md) return null;
  const who = sample
    ? "Sample — fictional figures. Code wrote this note."
    : note.model !== "code" && !note.fallback_reason
      ? "Written by your AI from the figures above; every number checked."
      : note.fallback_reason ?? "Written by code from the figures above.";
  return (
    <section
      aria-labelledby="goals-note-title"
      data-goals-note=""
      aria-busy={wording ? "true" : undefined}
      className={`relative flex gap-3 overflow-hidden rounded-2xl border border-border bg-teal-tint p-4 sm:p-5 ${className}`}
    >
      <span aria-hidden="true" className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border border-border bg-white">
        <svg width="18" height="18" viewBox="0 0 20 20" fill="none">
          <path d="M10 2.5v3M10 14.5v3M2.5 10h3M14.5 10h3M5 5l1.8 1.8M13.2 13.2 15 15M5 15l1.8-1.8M13.2 6.8 15 5" stroke="#3F2000" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      </span>
      <div className="min-w-0">
        <h3 id="goals-note-title" className="text-base font-bold text-ink">
          What your goals are telling you
        </h3>
        <p aria-live="polite" className={`mt-1 max-w-3xl text-[15px] leading-6 text-ink transition-opacity duration-300 ${wording ? "opacity-80" : ""}`}>
          {note.note_md}
        </p>
        {wording ? (
          <AiWorking label="Your AI is looking for suggestions — the figures are already checked." />
        ) : (
          <p className="mt-2 text-[13px] text-muted">{who}</p>
        )}
      </div>
    </section>
  );
}
