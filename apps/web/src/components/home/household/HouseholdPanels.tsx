"use client";

import Link from "next/link";
import ByWhom from "@/components/ByWhom";
import { RuntimeErrorNote } from "@/components/States";
import { monthName } from "@/lib/personal";
import type { RtCategorySpend, RtRecurringItem } from "@/lib/runtime";
import { pounds, shortDate, Skeleton, useHome } from "../HomeData";
import { AttentionLink, type AttentionTile } from "../Tiles";
import { hasStatements, useHousehold } from "./HouseholdData";

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const card = "rounded-2xl border border-border bg-white p-4 sm:p-5";
const title = "text-[19px] font-bold tracking-tight text-ink";

/** Upcoming regular payments (not stopped, not yet past), soonest first. */
function upcoming(items: RtRecurringItem[], within = 30): RtRecurringItem[] {
  return items
    .filter((i) => i.status !== "stopped" && i.days_until >= 0 && i.days_until <= within)
    .sort((a, b) => a.days_until - b.days_until || a.label.localeCompare(b.label));
}

function budgeted(categories: RtCategorySpend[]): RtCategorySpend[] {
  const rank = { over: 0, near: 1, ok: 2, none: 3 };
  return categories
    .filter((c) => c.budget_pence)
    .sort((a, b) => rank[a.state] - rank[b.state] || (b.percent ?? 0) - (a.percent ?? 0));
}

function daysText(days: number): string {
  return days === 0 ? "today" : days === 1 ? "tomorrow" : `in ${days} days`;
}

/**
 * Home for a household › what needs attention: receipts in Review, bank lines with no category, budgets over or
 * near their limit, and the next regular bill. Counts from GET /books/dashboard (Review) and GET /personal/summary
 * and /personal/recurring; nothing made up when a count is unknown (its tile is left out).
 */
export function HouseholdTiles() {
  const home = useHome();
  const { state } = useHousehold();
  const att = home.mode === "live" && home.data.attention && "proposed" in home.data.attention ? home.data.attention : null;
  if (home.mode === "error") return null;
  if (state.mode === "loading" || home.mode !== "live")
    return (
      <section aria-label="What needs attention" aria-busy="true" className="grid grid-cols-2 gap-3 md:grid-cols-4 md:gap-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="min-h-[6.5rem] rounded-2xl border border-border bg-white p-3 sm:p-4">
            <Skeleton className="h-4 w-24 max-w-full" />
            <Skeleton className="mt-3 h-8 w-12" />
          </div>
        ))}
      </section>
    );
  const tiles: AttentionTile[] = [];
  if (att) {
    const n = att.proposed + att.needs_a_look;
    tiles.push({
      key: "review",
      label: "Receipts to review",
      value: String(n),
      text: n ? `${plural(n, "receipt")} waiting for you` : "Nothing waiting",
      href: "/review",
      waiting: n > 0,
    });
  }
  if (state.mode === "live") {
    const t = state.thisMonth;
    tiles.push({
      key: "uncategorised",
      label: "Spending with no category",
      value: String(t.uncategorised_count),
      text: t.uncategorised_count
        ? `${plural(t.uncategorised_count, "bank line")} this month · add a rule`
        : t.lines
          ? "Every line this month has a category"
          : "No bank lines this month yet",
      href: t.lines ? "/personal" : "/bank",
      waiting: t.uncategorised_count > 0,
    });
    const b = budgeted(t.categories);
    const over = b.filter((c) => c.state === "over").length;
    const near = b.filter((c) => c.state === "near").length;
    tiles.push(
      b.length
        ? {
            key: "budgets",
            label: "Budgets",
            value: String(over + near),
            unit: "to watch",
            text: over || near ? [over && `${over} over`, near && `${near} near the limit`].filter(Boolean).join(" · ") : "All within budget so far",
            href: "/personal",
            waiting: over + near > 0,
          }
        : { key: "budgets", label: "Budgets", value: "None set", text: "Set a monthly budget per category", href: "/personal", waiting: false },
    );
    const next = upcoming(state.recurring.items, 14)[0];
    tiles.push(
      next
        ? {
            key: "bill",
            label: "Next regular bill",
            value: next.days_until === 0 ? "Today" : String(next.days_until),
            unit: next.days_until === 0 ? undefined : next.days_until === 1 ? "day" : "days",
            text: `${next.label}, about ${pounds(next.amount_pence)} on ${shortDate(next.next_due)} (estimate)`,
            href: "/personal",
            waiting: true,
          }
        : { key: "bill", label: "Regular bills", value: "None due", text: "Nothing expected in the next 14 days", href: "/personal", waiting: false },
    );
  }
  if (!tiles.length) return null;
  return (
    <section aria-label="What needs attention">
      <ul className="grid grid-cols-2 gap-3 md:grid-cols-4 md:gap-4">
        {tiles.map((t) => (
          <AttentionLink key={t.key} tile={t} />
        ))}
      </ul>
    </section>
  );
}

function Change({ now, before, lessIsBetter }: { now: number; before: number; lessIsBetter?: boolean }) {
  const diff = now - before;
  if (diff === 0) return <span>the same as last month</span>;
  const up = diff > 0;
  const good = lessIsBetter ? !up : up;
  return (
    <span className={good ? "text-pos-ink" : "text-warn-ink"}>
      {pounds(Math.abs(diff))} {up ? "more" : "less"} than last month
    </span>
  );
}

/** The household's month so far: money in, money out and what is left, each against last month. */
export function ThisMonth() {
  const { state, reload } = useHousehold();
  return (
    <section aria-labelledby="household-month" data-household-month="" className={card}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="household-month" className={title}>
          This month{state.mode === "live" ? ` · ${monthName(state.month)} so far` : ""}
        </h2>
        <Link href="/personal" className="text-[15px] font-bold text-teal hover:underline">
          Monthly summary
        </Link>
      </div>
      {state.mode === "error" ? (
        <div className="mt-3">
          <RuntimeErrorNote message={state.message} title="Your month could not be loaded" onRetry={reload} />
        </div>
      ) : state.mode === "loading" ? (
        <div aria-busy="true" className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i}>
              <Skeleton className="h-4 w-20" />
              <Skeleton className="mt-2 block h-8 w-28" />
            </div>
          ))}
        </div>
      ) : !hasStatements(state) ? (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <p className="text-[15px] text-muted">
            Import a bank statement to see what came in, what went out and what is left each month.
          </p>
          <Link href="/bank" className="inline-flex min-h-11 items-center rounded-xl bg-teal px-4 text-[15px] font-bold text-white hover:bg-teal-dark">
            Import a statement
          </Link>
        </div>
      ) : (
        <>
          <dl className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3 sm:gap-0 sm:divide-x sm:divide-border">
            {[
              { k: "Money in", now: state.thisMonth.income_pence, before: state.lastMonth.income_pence, less: false },
              { k: "Money out", now: state.thisMonth.spent_pence, before: state.lastMonth.spent_pence, less: true },
              { k: "Left over", now: state.thisMonth.left_pence, before: state.lastMonth.left_pence, less: false },
            ].map((x, i) => (
              <div key={x.k} className={i ? "sm:pl-5" : "sm:pr-5"}>
                <dt className="text-[13px] font-semibold text-muted">{x.k}</dt>
                <dd className={`mt-1 text-[28px] font-bold leading-tight tracking-tight tabular-nums ${x.now < 0 ? "text-neg-ink" : "text-ink"}`}>
                  {pounds(x.now)}
                </dd>
                <dd className="mt-1 text-[13px] font-semibold">
                  <Change now={x.now} before={x.before} lessIsBetter={x.less} />
                </dd>
                <dd className="text-[13px] text-muted">
                  {monthName(state.lastMonth.month)}: {pounds(x.before)}
                </dd>
              </div>
            ))}
          </dl>
          <ByWhom
            className="mt-3"
            code="From your imported bank statements, transfers and ignored lines left out, worked out by code"
            ai="no AI involved"
          />
        </>
      )}
    </section>
  );
}

function BudgetRow({ c }: { c: RtCategorySpend }) {
  const pct = Math.min(100, c.percent ?? 0);
  const fill = c.state === "over" ? "bg-neg-ink" : c.state === "near" ? "bg-amber" : "bg-teal";
  const words = c.state === "over" ? "Over budget" : c.state === "near" ? "Near the limit" : "Within budget";
  const remaining = c.remaining_pence ?? 0;
  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <p className="text-[15px] font-semibold text-ink">{c.name}</p>
        <p className="text-[15px] tabular-nums text-ink">
          {pounds(c.spent_pence)} <span className="text-muted">of {pounds(c.budget_pence)}</span>
        </p>
      </div>
      <div
        className="mt-2 h-2 w-full overflow-hidden rounded-full bg-[#e6edf0]"
        role="progressbar"
        aria-label={`${c.name}: ${c.percent ?? 0}% of budget`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
      >
        <div className={`h-full rounded-full ${fill}`} style={{ width: `${pct}%` }} />
      </div>
      <p className={`mt-1 text-[13px] font-semibold ${c.state === "over" ? "text-neg-ink" : c.state === "near" ? "text-warn-ink" : "text-muted"}`}>
        {words} · {remaining < 0 ? `${pounds(-remaining)} over` : `${pounds(remaining)} left`}
      </p>
    </li>
  );
}

/** Each budgeted category this month: spent of budget, a bar, and what is left; over first, then near, then the rest. */
export function Budgets() {
  const { state } = useHousehold();
  if (state.mode !== "live" || !hasStatements(state)) return null;
  const rows = budgeted(state.thisMonth.categories);
  return (
    <section aria-labelledby="household-budgets" data-household-budgets="" className={card}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="household-budgets" className={title}>
          Budgets this month
        </h2>
        <Link href="/personal" className="text-[15px] font-bold text-teal hover:underline">
          {rows.length ? "Change budgets" : "Set budgets"}
        </Link>
      </div>
      {rows.length ? (
        <ul className="mt-3 divide-y divide-border">
          {rows.map((c) => (
            <BudgetRow key={c.id} c={c} />
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-[15px] text-muted">No budgets yet. Set a monthly amount per category to see how each is going.</p>
      )}
    </section>
  );
}

/** Regular bills and subscriptions code found on the statements, due in the next 30 days (estimates). */
export function Bills() {
  const { state } = useHousehold();
  if (state.mode !== "live" || !hasStatements(state)) return null;
  const items = upcoming(state.recurring.items);
  return (
    <section aria-labelledby="household-bills" data-household-bills="" className={card}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="household-bills" className={title}>
          Bills and subscriptions due
        </h2>
        <Link href="/personal" className="text-[15px] font-bold text-teal hover:underline">
          All regular payments
        </Link>
      </div>
      {items.length ? (
        <ul className="mt-3 divide-y divide-border">
          {items.slice(0, 6).map((i) => (
            <li key={i.key} className="flex items-center justify-between gap-3 py-2.5 first:pt-0 last:pb-0">
              <div className="min-w-0">
                <p className="truncate text-[15px] font-semibold text-ink">{i.label}</p>
                <p className="text-[13px] text-muted">
                  {i.category_name} · {shortDate(i.next_due)} ({daysText(i.days_until)})
                </p>
              </div>
              <p className="shrink-0 text-[15px] font-semibold tabular-nums text-ink">
                {i.amount_varies ? "about " : ""}
                {pounds(i.amount_pence)}
              </p>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-[15px] text-muted">Nothing regular expected in the next 30 days.</p>
      )}
      <p className="mt-3 text-[12px] leading-5 text-muted">
        Estimates: the last payment plus one cycle, found by code from your statements, not dates from the provider.
      </p>
    </section>
  );
}

/** Where the money went this month: the largest categories, with what has no category shown, never hidden. */
export function WhereItWent() {
  const { state } = useHousehold();
  if (state.mode !== "live" || !hasStatements(state)) return null;
  const t = state.thisMonth;
  const rows = [...t.categories].filter((c) => c.spent_pence > 0).sort((a, b) => b.spent_pence - a.spent_pence).slice(0, 6);
  const top = rows[0]?.spent_pence ?? 0;
  return (
    <section aria-labelledby="household-where" data-household-where="" className={card}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="household-where" className={title}>
          Where the money went
        </h2>
        <Link href="/spending" className="text-[15px] font-bold text-teal hover:underline">
          Spending
        </Link>
      </div>
      {rows.length ? (
        <ul className="mt-3 flex flex-col gap-2.5">
          {rows.map((c) => (
            <li key={c.id}>
              <div className="flex items-baseline justify-between gap-3 text-[15px]">
                <span className="min-w-0 truncate text-ink">{c.name}</span>
                <span className="shrink-0 font-semibold tabular-nums text-ink">{pounds(c.spent_pence)}</span>
              </div>
              <div aria-hidden="true" className="mt-1 h-1.5 rounded-full bg-[#e6edf0]">
                <div className="h-full rounded-full bg-teal/70" style={{ width: `${top ? Math.max(3, (c.spent_pence * 100) / top) : 0}%` }} />
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-[15px] text-muted">No spending this month yet.</p>
      )}
      {t.uncategorised_count > 0 && (
        <p className="mt-3 text-[13px] font-semibold text-warn-ink">
          {pounds(t.uncategorised_pence)} on {plural(t.uncategorised_count, "line")} has no category yet (shown as Other).
        </p>
      )}
    </section>
  );
}
