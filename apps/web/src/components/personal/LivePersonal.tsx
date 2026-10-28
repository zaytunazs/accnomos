"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { useAccount } from "@/components/jobs/useAccount";
import SignInCta from "@/components/SignInCta";
import { LoadingSkeleton, RuntimeErrorNote, isAuthError, isServerError, parseRuntimeError } from "@/components/States";
import { personalOn } from "@/lib/personal";
import {
  gbp,
  runtime,
  ukDate,
  type RtGoalPlan,
  type RtPersonalCategory,
  type RtPersonalRecurring,
  type RtPersonalRule,
  type RtPersonalSummary,
} from "@/lib/runtime";

const pounds = (pence: number) => (pence < 0 ? `-${gbp(-pence / 100)}` : gbp(pence / 100));
const londonToday = () => new Date().toLocaleDateString("en-CA", { timeZone: "Europe/London" });
const errorText = (e: unknown) => {
  const m = (e as Error).message ?? String(e);
  const detail = /"detail":\s*"([^"]+)"/.exec(m);
  return detail ? detail[1] : m;
};
/** "12.50" -> 1250; null when it is not a plain amount of pounds and pence. */
const toPence = (text: string): number | null => (/^\d{1,9}(\.\d{1,2})?$/.test(text.trim()) ? Math.round(Number(text) * 100) : null);
const fromPence = (pence: number | null | undefined) => (pence ? (pence / 100).toFixed(2) : "");
const monthLabel = (m: string) => new Date(`${m}-01T12:00:00Z`).toLocaleDateString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" });

const CADENCE: Record<string, string> = { weekly: "a week", fortnightly: "a fortnight", monthly: "a month", quarterly: "a quarter", annually: "a year" };
const GOAL_STATUS: Record<RtGoalPlan["status"], string> = {
  reached: "Reached",
  on_track: "On track at your planned amount",
  behind: "Behind at your planned amount",
  plan_needed: "Set a planned amount to see if you are on track",
  date_passed: "The date has passed",
};

const input = "h-11 min-w-0 rounded-xl border border-border bg-white px-3 text-[15px]";
const button = "h-11 rounded-xl bg-teal px-5 text-[15px] font-bold text-white disabled:opacity-60";
const quiet = "h-11 rounded-xl border border-border bg-white px-4 text-[15px] font-bold disabled:opacity-60";
const card = "rounded-2xl border border-border bg-white p-4 sm:p-5";
const h2 = "text-[19px] font-extrabold text-ink";

/** A progress bar that is also read aloud: the label says what it measures, the value is the percentage. */
function Bar({ label, percent, state }: { label: string; percent: number; state: "none" | "ok" | "near" | "over" | "goal" }) {
  const fill = state === "over" ? "bg-red-700" : state === "near" ? "bg-amber" : "bg-teal";
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.min(100, percent)}
      className="h-3 w-full overflow-hidden rounded-full bg-ground"
    >
      <div className={`h-full ${fill}`} style={{ width: `${Math.min(100, percent)}%` }} />
    </div>
  );
}

export default function LivePersonal() {
  const account = useAccount();
  const [shown, setShown] = useState<boolean | null>(null);
  useEffect(() => {
    queueMicrotask(() => setShown(personalOn()));
  }, []);

  if (shown === null || account === undefined) return <LoadingSkeleton lines={3} label="Loading Personal…" />;
  if (!shown)
    return (
      <p className={`${card} text-[15px] leading-7 text-muted`}>
        Personal finances are off. Turn on <strong>Show personal finances</strong> in{" "}
        <Link href="/settings#settings-personal" className="font-bold text-teal-dark">
          Settings
        </Link>{" "}
        to use this page.
      </p>
    );
  if (!account)
    return (
      <p className={`${card} flex flex-wrap items-center gap-x-3 gap-y-2 text-[15px] leading-7 text-muted`}>
        <SignInCta />
        <span>to keep your budgets and goals in your own OneDrive.</span>
      </p>
    );
  return <Signed account={account} />;
}

function Signed({ account }: { account: AccountInfo }) {
  const [month, setMonth] = useState(londonToday().slice(0, 7));
  const [cats, setCats] = useState<RtPersonalCategory[]>([]);
  const [summary, setSummary] = useState<RtPersonalSummary | null>(null);
  const [recurring, setRecurring] = useState<RtPersonalRecurring | null>(null);
  const [goals, setGoals] = useState<RtGoalPlan[]>([]);
  const [rules, setRules] = useState<RtPersonalRule[]>([]);
  const [budgetText, setBudgetText] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [rule, setRule] = useState({ value: "", category: "groceries" });
  const [goal, setGoal] = useState({ name: "", target: "", date: "", saved: "", planned: "" });
  const [savedText, setSavedText] = useState<Record<string, string>>({});

  const load = useCallback(
    async (m: string) => {
      const [c, s, r, g, ru] = await Promise.all([
        runtime.personal.categories(account),
        runtime.personal.summary(account, m),
        runtime.personal.recurring(account),
        runtime.personal.goals(account),
        runtime.personal.rules(account),
      ]);
      setCats(c);
      setSummary(s);
      setRecurring(r);
      setGoals(g);
      setRules(ru);
      setBudgetText(Object.fromEntries(s.categories.map((x) => [x.id, fromPence(x.budget_pence)])));
    },
    [account],
  );

  function fail(e: unknown) {
    const msg = errorText(e);
    if (isAuthError(msg) || isServerError(msg)) setError(msg);
    else setNote(parseRuntimeError(msg).detail || msg);
  }

  useEffect(() => {
    queueMicrotask(() =>
      load(month)
        .then(() => setReady(true))
        .catch((e) => {
          fail(e);
          setReady(true);
        }),
    );
  }, [load, month]);

  async function act<T>(key: string, fn: () => Promise<T>, done: string | ((r: T) => string)): Promise<boolean> {
    setBusy(key);
    setError(null);
    try {
      const r = await fn();
      setNote(typeof done === "function" ? done(r) : done);
      await load(month);
      return true;
    } catch (e) {
      fail(e);
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function saveBudgets() {
    const budgets: Record<string, number> = {};
    for (const [id, text] of Object.entries(budgetText)) {
      if (!text.trim()) continue;
      const p = toPence(text);
      if (p === null) return setNote("Budgets are amounts in pounds, such as 250 or 82.50.");
      if (p > 0) budgets[id] = p;
    }
    await act("budgets", () => runtime.personal.saveBudgets(account, budgets), "Budgets saved");
  }

  async function addRule() {
    if (!rule.value.trim()) return setNote("Type some of the payee's name, such as TESCO.");
    const name = cats.find((c) => c.id === rule.category)?.name ?? rule.category;
    if (await act("rule", () => runtime.personal.addRule(account, rule.value.trim(), rule.category), `Payments containing "${rule.value.trim()}" now go to ${name}`))
      setRule({ ...rule, value: "" });
  }

  async function addGoal() {
    const target = toPence(goal.target);
    const saved = goal.saved.trim() ? toPence(goal.saved) : 0;
    const planned = goal.planned.trim() ? toPence(goal.planned) : null;
    if (!goal.name.trim() || !target || !goal.date) return setNote("A goal needs a name, a target amount and a date.");
    if (saved === null || (goal.planned.trim() && planned === null)) return setNote("Amounts are in pounds, such as 250 or 82.50.");
    const body = { name: goal.name.trim(), target_pence: target, target_date: goal.date, saved_pence: saved, planned_monthly_pence: planned };
    if (await act("goal", () => runtime.personal.addGoal(account, body), `Added the goal ${goal.name.trim()}`))
      setGoal({ name: "", target: "", date: "", saved: "", planned: "" });
  }

  async function updateSaved(g: RtGoalPlan) {
    const p = toPence(savedText[g.goal.id] ?? "");
    if (p === null) return setNote("Saved so far is an amount in pounds, such as 250 or 82.50.");
    await act(`saved-${g.goal.id}`, () => runtime.personal.updateGoal(account, g.goal.id, { saved_pence: p }), `Updated ${g.goal.name}`);
  }

  if (!ready) return <LoadingSkeleton lines={4} label="Loading your figures…" />;
  if (error) return <RuntimeErrorNote message={error} />;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-sm font-bold text-ink">
          Month
          <input type="month" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} className={input} />
        </label>
        <p className="pb-2 text-sm text-muted">{monthLabel(month)}</p>
      </div>
      <p role="status" className="min-h-6 text-sm font-bold text-teal-dark">
        {note}
      </p>

      {summary && (
        <section aria-labelledby="p-summary" className={card}>
          <h2 id="p-summary" className={h2}>
            Summary for {monthLabel(summary.month)}
          </h2>
          <dl className="mt-3 grid grid-cols-1 gap-3 min-[420px]:grid-cols-3">
            {[
              ["Money in", pounds(summary.income_pence)],
              ["Money out", pounds(summary.spent_pence)],
              ["Left over", pounds(summary.left_pence)],
            ].map(([k, v]) => (
              <div key={k} className="rounded-xl bg-ground px-4 py-3">
                <dt className="text-sm text-muted">{k}</dt>
                <dd className="text-xl font-extrabold text-ink">{v}</dd>
              </div>
            ))}
          </dl>
          <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-muted">
            {summary.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
          {summary.lines === 0 && (
            <Link href="/bank" className="mt-2 inline-block text-sm font-bold text-teal-dark">
              Open Bank to import a statement
            </Link>
          )}
        </section>
      )}

      {summary && (
        <section aria-labelledby="p-budgets" className={card}>
          <h2 id="p-budgets" className={h2}>
            Budgets
          </h2>
          <p className="mt-1 text-sm text-muted">What you plan to spend each month. Leave blank for no budget.</p>
          <ul className="mt-3 flex flex-col gap-4">
            {summary.categories.map((c) => (
              <li key={c.id} className="flex flex-col gap-2">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span className="text-[15px] font-bold text-ink">{c.name}</span>
                  <span className="text-sm text-muted">
                    {pounds(c.spent_pence)}
                    {c.budget_pence ? ` of ${pounds(c.budget_pence)}` : " spent"}
                  </span>
                </div>
                {c.budget_pence ? (
                  <>
                    <Bar label={`${c.name} budget used`} percent={c.percent ?? 0} state={c.state} />
                    <p className={`text-sm ${c.state === "over" ? "font-bold text-red-700" : "text-muted"}`}>
                      {c.state === "over"
                        ? `${pounds(-(c.remaining_pence ?? 0))} over budget (${c.percent}%)`
                        : `${pounds(c.remaining_pence ?? 0)} left (${c.percent}% used)${c.state === "near" ? ", nearly at the limit" : ""}`}
                    </p>
                  </>
                ) : null}
                <label className="flex items-center gap-2 text-sm text-muted">
                  <span className="shrink-0">Budget £</span>
                  <input
                    inputMode="decimal"
                    aria-label={`${c.name} monthly budget in pounds`}
                    value={budgetText[c.id] ?? ""}
                    onChange={(e) => setBudgetText({ ...budgetText, [c.id]: e.target.value })}
                    className={`${input} w-32`}
                  />
                </label>
              </li>
            ))}
          </ul>
          <button type="button" onClick={saveBudgets} disabled={busy !== null} className={`${button} mt-4`}>
            Save budgets
          </button>
        </section>
      )}

      <section aria-labelledby="p-rules" className={card}>
        <h2 id="p-rules" className={h2}>
          Sorting payments
        </h2>
        <p className="mt-1 text-sm text-muted">
          Payments are put in a category by rules you control, separate from your business bank rules. The first matching rule wins.
          {summary && summary.uncategorised_count > 0
            ? ` ${summary.uncategorised_count} payment${summary.uncategorised_count === 1 ? "" : "s"} (${pounds(summary.uncategorised_pence)}) sit under Other this month.`
            : ""}
        </p>
        <div className="mt-3 flex flex-col gap-2 min-[560px]:flex-row min-[560px]:items-end">
          <label className="flex min-w-0 flex-1 flex-col gap-1 text-sm font-bold text-ink">
            When the payment contains
            <input value={rule.value} onChange={(e) => setRule({ ...rule, value: e.target.value })} placeholder="TESCO" className={input} />
          </label>
          <label className="flex flex-col gap-1 text-sm font-bold text-ink">
            Put it in
            <select value={rule.category} onChange={(e) => setRule({ ...rule, category: e.target.value })} className={input}>
              {cats.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <button type="button" onClick={addRule} disabled={busy !== null} className={button}>
            Add rule
          </button>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy !== null}
            className={quiet}
            onClick={() =>
              act("starter", () => runtime.personal.addStarterRules(account), (added) =>
                added.length ? `Added ${added.length} common UK merchants` : "Those common UK merchants are already there",
              )
            }
          >
            Add common UK merchants
          </button>
        </div>
        {rules.length > 0 && (
          <ul className="mt-3 divide-y divide-border text-sm">
            {rules.map((r) => (
              <li key={r.id} className="flex items-center justify-between gap-3 py-2">
                <span className="min-w-0 break-words">
                  Contains <strong>{r.match.value}</strong> → {cats.find((c) => c.id === r.category_id)?.name ?? r.category_id}
                </span>
                <button
                  type="button"
                  aria-label={`Delete rule ${r.match.value}`}
                  disabled={busy !== null}
                  onClick={() => act(`del-${r.id}`, () => runtime.personal.deleteRule(account, r.id), "Rule deleted")}
                  className="h-11 shrink-0 rounded-xl px-3 font-bold text-teal-dark"
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="p-bills" className={card}>
        <h2 id="p-bills" className={h2}>
          Bills and subscriptions
        </h2>
        {recurring && recurring.items.length > 0 ? (
          <>
            <p className="mt-1 text-sm text-muted">
              Estimate: about {pounds(recurring.monthly_total_pence)} a month across these. {recurring.note}
            </p>
            <ul className="mt-3 divide-y divide-border">
              {recurring.items.map((i) => (
                <li key={i.key} className="flex flex-col gap-1 py-3">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <span className="min-w-0 break-words text-[15px] font-bold text-ink">{i.label}</span>
                    <span className="text-[15px] font-bold text-ink">
                      {i.amount_varies ? "about " : ""}
                      {pounds(i.amount_pence)} {CADENCE[i.cadence]}
                    </span>
                  </div>
                  <p className="text-sm text-muted">
                    {i.status === "stopped"
                      ? `Looks stopped: last paid ${ukDate(i.last_date)}`
                      : i.status === "overdue"
                        ? `Was expected around ${ukDate(i.next_due)} (${-i.days_until} day${i.days_until === -1 ? "" : "s"} ago)`
                        : `Next due around ${ukDate(i.next_due)} (${i.days_until === 0 ? "today" : `in ${i.days_until} day${i.days_until === 1 ? "" : "s"}`})`}
                    {" · "}
                    {i.category_name} · seen {i.occurrences} times
                  </p>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="mt-1 text-sm text-muted">
            Nothing regular found yet. A bill shows up after three payments to the same payee at a regular gap for a similar amount
            (two for a yearly one). Import more statements on the Bank page.
          </p>
        )}
      </section>

      <section aria-labelledby="p-goals" className={card}>
        <h2 id="p-goals" className={h2}>
          Savings goals
        </h2>
        <p className="mt-1 text-sm text-muted">
          You set the target and the date; the monthly amount is worked out by code (an estimate: it ignores interest and assumes equal payments).
        </p>
        <ul className="mt-3 flex flex-col gap-4">
          {goals.map((g) => (
            <li key={g.goal.id} className="flex flex-col gap-2 rounded-xl border border-border p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                <span className="min-w-0 break-words text-[15px] font-bold text-ink">{g.goal.name}</span>
                <span className="text-sm text-muted">
                  {pounds(g.goal.saved_pence)} of {pounds(g.goal.target_pence)} by {ukDate(g.goal.target_date)}
                </span>
              </div>
              <Bar label={`${g.goal.name} saved`} percent={g.percent} state="goal" />
              <p className="text-sm text-muted">
                {g.status === "reached"
                  ? "Reached."
                  : `Estimate: put aside ${pounds(g.monthly_needed_pence)} a month for ${g.months_left} month${g.months_left === 1 ? "" : "s"} (${pounds(g.remaining_pence)} to go). `}
                {g.status !== "reached" && GOAL_STATUS[g.status]}
                {g.projected_date ? `. At ${pounds(g.goal.planned_monthly_pence ?? 0)} a month, about ${ukDate(g.projected_date)}` : ""}
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <label className="flex items-center gap-2 text-sm text-muted">
                  <span className="shrink-0">Saved so far £</span>
                  <input
                    inputMode="decimal"
                    aria-label={`${g.goal.name} saved so far in pounds`}
                    value={savedText[g.goal.id] ?? fromPence(g.goal.saved_pence)}
                    onChange={(e) => setSavedText({ ...savedText, [g.goal.id]: e.target.value })}
                    className={`${input} w-28`}
                  />
                </label>
                <button type="button" disabled={busy !== null} onClick={() => updateSaved(g)} className={quiet} aria-label={`Update ${g.goal.name}`}>
                  Update
                </button>
                <button
                  type="button"
                  disabled={busy !== null}
                  aria-label={`Delete goal ${g.goal.name}`}
                  onClick={() => act(`delg-${g.goal.id}`, () => runtime.personal.deleteGoal(account, g.goal.id), "Goal deleted")}
                  className="h-11 rounded-xl px-3 font-bold text-teal-dark"
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
        {goals.length === 0 && <p className="mt-3 text-sm text-muted">No goals yet.</p>}
        <fieldset className="mt-4 grid grid-cols-1 gap-3 min-[560px]:grid-cols-2">
          <legend className="mb-1 text-[15px] font-bold text-ink">Add a goal</legend>
          {(
            [
              ["Goal name", "name", "text"],
              ["Target £", "target", "text"],
              ["Target date", "date", "date"],
              ["Saved so far £ (optional)", "saved", "text"],
              ["Planned a month £ (optional)", "planned", "text"],
            ] as const
          ).map(([label, key, type]) => (
            <label key={key} className="flex min-w-0 flex-col gap-1 text-sm font-bold text-ink">
              {label}
              <input
                type={type}
                inputMode={type === "text" && key !== "name" ? "decimal" : undefined}
                value={goal[key]}
                onChange={(e) => setGoal({ ...goal, [key]: e.target.value })}
                className={input}
              />
            </label>
          ))}
          <button type="button" onClick={addGoal} disabled={busy !== null} className={`${button} self-end`}>
            Add goal
          </button>
        </fieldset>
      </section>

      <p className="text-sm leading-6 text-muted">
        Accnomos does not give investment, tax or credit advice and does not score your credit. Cash and anything missing from an imported
        statement is not counted.
      </p>
    </div>
  );
}
