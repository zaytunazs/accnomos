"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import ByWhom from "@/components/ByWhom";
import ExplainMore from "@/components/ExplainMore";
import { errorText, useAccount } from "@/components/jobs/useAccount";
import { RuntimeErrorNote } from "@/components/States";
import { useLandlordOn } from "@/lib/property";
import { runtime, type RtAgedSide, type RtPriceReport, type RtShoppingItem } from "@/lib/runtime";
import { pounds, SampleTag, shortDate, Skeleton } from "./HomeData";
import { useOverview, useOverviewData } from "./Overview";

/** "in 4 days", "today", "3 days late". */
export function daysWord(n: number): string {
  if (n === 0) return "today";
  if (n < 0) return `${-n} day${n === -1 ? "" : "s"} late`;
  return `in ${n} day${n === 1 ? "" : "s"}`;
}

const quiet = "inline-block whitespace-nowrap rounded-xl border border-border px-4 py-2 text-sm font-bold text-teal-dark hover:bg-ground";

/** One Home card: a heading, its body, the "who did what" line and the link to its page. */
function Card({
  id,
  title,
  href,
  action,
  children,
  by,
  warn = false,
  wide = false,
}: {
  id: string;
  title: ReactNode;
  href: string;
  action: string;
  children: ReactNode;
  by?: ReactNode;
  warn?: boolean;
  wide?: boolean;
}) {
  return (
    <section
      aria-labelledby={id}
      data-home-card={id}
      className={`flex min-w-0 flex-col rounded-2xl border bg-white p-4 sm:p-5 ${warn ? "border-warn-border" : "border-border"} ${wide ? "md:col-span-2" : ""}`}
    >
      <h2 id={id} className="text-lg font-extrabold tracking-tight">
        {title}
      </h2>
      {children}
      {by}
      <div className="mt-auto pt-4">
        <Link href={href} className={quiet}>
          {action}
        </Link>
      </div>
    </section>
  );
}

function Sample() {
  return useOverview().mode === "sample" ? <SampleTag /> : null;
}

/** The summary at the top of Home: the AI's words (checked by code) or code's own, with what it was based on. */
export function SummaryCard() {
  const o = useOverview();
  const data = useOverviewData();
  const s = data?.summary;
  const byAi = s && s.model !== "code" && !s.fallback_reason;
  return (
    <section aria-labelledby="home-summary" className="col-span-full rounded-2xl border border-teal/30 bg-teal-tint p-4 sm:p-5">
      <div className="flex items-start justify-between gap-2">
        <h2 id="home-summary" className="text-lg font-extrabold tracking-tight text-teal-dark">
          Your summary
          <Sample />
        </h2>
        <ExplainMore title="How this summary is written" anchor="books">
          Code works out every figure from your books first. If you have set up an AI, it only puts those figures into
          words; code then checks that every number it wrote is one of them, and writes the summary itself if not.
        </ExplainMore>
      </div>
      <div aria-live="polite" className="mt-2 min-h-[3.5rem]">
        {s ? (
          <p data-home-summary="" className="text-[15px] leading-7 text-ink">
            {s.summary_md}
          </p>
        ) : o.mode === "error" ? (
          <RuntimeErrorNote message={o.message} />
        ) : (
          <div aria-busy="true" className="flex flex-col gap-2">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-4/5" />
            <Skeleton className="h-4 w-3/5" />
          </div>
        )}
      </div>
      {s ? (
        <ByWhom
          className="mt-2"
          code={o.mode === "sample" ? "Sample figures from the fictional Bramblewood books" : "Every figure by code from your books"}
          ai={byAi ? `worded by your AI (${s.model}), numbers checked by code` : s.fallback_reason ?? "written by code"}
        />
      ) : null}
    </section>
  );
}

/** A pair of bars drawn for sighted users; the table beside them is the same figures as text. */
function Bars({ rows }: { rows: { label: string; inP: number; outP: number }[] }) {
  const max = Math.max(0, ...rows.flatMap((r) => [r.inP, r.outP]));
  if (max === 0) return null; // nothing to draw: the table says £0
  const w = (p: number) => (p ? `${Math.max(2, Math.round((p / max) * 100))}%` : "0");
  return (
    <div aria-hidden="true" className="mt-3 flex flex-col gap-2">
      {rows.map((r) => (
        <div key={r.label} className="flex flex-col gap-1">
          <span className="h-2.5 rounded-full bg-teal" style={{ width: w(r.inP) }} />
          <span className="h-2.5 rounded-full bg-amber" style={{ width: w(r.outP) }} />
        </div>
      ))}
    </div>
  );
}

/** Money in and out of the bank: this month so far against last month, bars plus the figures as a table. */
export function MoneyCard() {
  const data = useOverviewData();
  const m = data?.money;
  if (data && !m) return null;
  const rows = m
    ? [
        { label: `${m.this_month.label} so far`, inP: m.this_month.money_in_pence, outP: m.this_month.money_out_pence },
        { label: m.last_month.label, inP: m.last_month.money_in_pence, outP: m.last_month.money_out_pence },
      ]
    : [];
  return (
    <Card
      id="home-money"
      title={<>Money in and out<Sample /></>}
      href="/reports/cashflow"
      action="Open cash flow"
      by={<ByWhom className="mt-2" code="Added up by code from your bank lines" ai="no AI involved" />}
    >
      {m ? (
        <>
          <Bars rows={rows} />
          <table className="mt-3 w-full text-left text-[14px] tabular-nums">
            <caption className="sr-only">Money in and out of the bank, this month so far and last month</caption>
            <thead>
              <tr className="text-[12px] text-muted">
                <th scope="col" className="py-1 font-semibold">Month</th>
                <th scope="col" className="py-1 text-right font-semibold">
                  <span aria-hidden="true" className="mr-1 inline-block h-2 w-2 rounded-full bg-teal" />In
                </th>
                <th scope="col" className="py-1 text-right font-semibold">
                  <span aria-hidden="true" className="mr-1 inline-block h-2 w-2 rounded-full bg-amber" />Out
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.label} className="border-t border-border">
                  <th scope="row" className="py-1.5 font-semibold">{r.label}</th>
                  <td className="py-1.5 text-right">{pounds(r.inP)}</td>
                  <td className="py-1.5 text-right">{pounds(r.outP)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data?.week ? (
            <p className="mt-2 text-[13px] text-muted">
              Last 7 days: {pounds(data.week.money_in_pence)} in, {pounds(data.week.money_out_pence)} out ·{" "}
              {data.week.approved} approved, {data.week.proposed} proposed
            </p>
          ) : null}
        </>
      ) : (
        <Skeleton className="mt-3 h-24 w-full" />
      )}
    </Card>
  );
}

const BUCKETS: [keyof RtAgedSide["buckets"], string][] = [
  ["current", "Not due"],
  ["0-30", "1–30 days"],
  ["31-60", "31–60"],
  ["61-90", "61–90"],
  ["90+", "90+"],
];

/** Unpaid invoices and bills by age (the Aged report's figures). Personal books have neither. */
export function AgedCard() {
  const data = useOverviewData();
  const a = data?.aged;
  if (!data || !a || data.kind === "personal") return null;
  const late = a.debtors.overdue_pence > 0 || a.creditors.overdue_pence > 0;
  return (
    <Card
      id="home-aged"
      title={<>Unpaid invoices and bills<Sample /></>}
      href="/reports#aged-heading"
      action="Open aged report"
      warn={a.debtors.overdue_pence > 0}
      by={<ByWhom className="mt-2" code="Aged by code from your ledger, by days past due" ai="no AI involved" />}
    >
      <table className="mt-3 w-full text-left text-[13px] tabular-nums">
        <caption className="sr-only">What is unpaid, by how many days past its due date</caption>
        <thead>
          <tr className="text-[12px] text-muted">
            <th scope="col" className="py-1 font-semibold"><span className="sr-only">Who</span></th>
            {BUCKETS.map(([k, label]) => (
              <th key={k} scope="col" className="py-1 text-right font-semibold">{label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(
            [
              ["Owed to you", a.debtors],
              ["You owe", a.creditors],
            ] as const
          ).map(([label, side]) => (
            <tr key={label} className="border-t border-border">
              <th scope="row" className="py-1.5 pr-1 font-semibold">
                {label}
                <span className="block text-[12px] font-normal text-muted">{pounds(side.total_pence)}</span>
              </th>
              {BUCKETS.map(([k]) => (
                <td key={k} className={`py-1.5 text-right ${k !== "current" && side.buckets[k] ? "font-bold text-warn-ink" : ""}`}>
                  {side.buckets[k] ? pounds(side.buckets[k]) : "–"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {late ? <p className="mt-2 text-[13px] font-semibold text-warn-ink">Overdue: {pounds(a.debtors.overdue_pence)} owed to you, {pounds(a.creditors.overdue_pence)} you owe.</p> : null}
    </Card>
  );
}

/** Coming up: every deadline code worked out, soonest first, each linking to its page. */
export function ComingUpCard() {
  const data = useOverviewData();
  if (!data || data.deadlines.length === 0) return null;
  return (
    <Card
      id="home-coming-up"
      title={<>Coming up<Sample /></>}
      href={data.deadlines[0].href}
      action="Open the next one"
      by={<ByWhom className="mt-2" code="Dates by code from HMRC's published rules" ai="no AI involved" />}
    >
      <ul className="mt-2 flex flex-col">
        {data.deadlines.map((d) => (
          <li key={`${d.key}-${d.due}`} className="flex items-baseline justify-between gap-3 border-t border-border py-2 first:border-t-0">
            <Link href={d.href} className="min-w-0 text-[14px] font-semibold text-ink hover:underline">
              {d.title}
            </Link>
            <span className={`shrink-0 text-[13px] tabular-nums ${d.days_left <= 7 ? "font-bold text-warn-ink" : "text-muted"}`}>
              {shortDate(d.due)} · {daysWord(d.days_left)}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

/** MTD for Income Tax: the next quarterly update, and the Self Assessment return. Sole traders and landlords. */
export function IncomeTaxCard() {
  const data = useOverviewData();
  const i = data?.itsa;
  if (!data || !i) return null;
  const sa = data.deadlines.find((d) => d.key === "self_assessment");
  return (
    <Card
      id="home-income-tax"
      title={<>Income Tax (MTD)<Sample /></>}
      href={data.property && data.kind !== "sole_trader" ? "/property" : "/self-employment"}
      action="Open quarterly updates"
      warn={i.days_left <= 14}
      by={
        <p className="mt-2 text-[12px] leading-5 text-muted">
          Dates by code from{" "}
          <a href={i.source_url} className="underline" rel="noreferrer">
            HMRC&apos;s quarterly update deadlines
          </a>{" "}
          · updates go to HMRC&apos;s sandbox only
        </p>
      }
    >
      <p className="mt-1 text-3xl font-extrabold tracking-tight tabular-nums">{shortDate(i.due)}</p>
      <p className="text-[13px] font-semibold text-muted">
        Quarterly update to {shortDate(i.period_end)} ({i.tax_year}) due {daysWord(i.days_left)}
      </p>
      {sa ? <p className="mt-2 text-[14px]">Self Assessment return and payment due {shortDate(sa.due)} {sa.due.slice(0, 4)} ({daysWord(sa.days_left)})</p> : null}
    </Card>
  );
}

/** Payroll: the pay run waiting to be confirmed, or the next month to prepare. */
export function PayrollCard() {
  const data = useOverviewData();
  const p = data?.payroll;
  if (!data || !p) return null;
  return (
    <Card
      id="home-payroll"
      title={<>Payroll<Sample /></>}
      href="/payroll"
      action={p.draft_period ? "Confirm the pay run" : "Open pay runs"}
      warn={!!p.draft_pay_date}
      by={<ByWhom className="mt-2" code="Estimates by code; your payroll provider files with HMRC" ai="no AI involved" />}
    >
      <p className="mt-1 text-[15px] leading-6">
        {p.draft_period
          ? `The ${p.draft_period} pay run is prepared and waits for you: pay date ${shortDate(p.draft_pay_date)}.`
          : `Next pay run: ${p.next_period}.`}
      </p>
      <p className="text-[13px] text-muted">
        {p.employees} employee{p.employees === 1 ? "" : "s"}
        {p.last_pay_date ? ` · last paid ${shortDate(p.last_pay_date)}` : ""}
      </p>
    </Card>
  );
}

/** CIS: deductions suffered this tax year, the contractor's monthly return. Only when Settings › CIS is on. */
export function CisCard() {
  const data = useOverviewData();
  const c = data?.cis;
  if (!data || !c) return null;
  return (
    <Card
      id="home-cis"
      title={<>CIS (construction)<Sample /></>}
      href="/cis"
      action="Open CIS"
      by={<ByWhom className="mt-2" code="Totals by code from your CIS statements" ai="statements read by AI, approved by you" />}
    >
      {c.subcontractor ? (
        <>
          <p className="mt-1 text-3xl font-extrabold tracking-tight tabular-nums">{pounds(c.suffered_pence)}</p>
          <p className="text-[13px] font-semibold text-muted">
            Deducted by contractors in {c.tax_year} · {c.status_label} ({c.rate}%)
          </p>
        </>
      ) : null}
      {c.return_due ? <p className="mt-2 text-[14px]">CIS300 return for last month due {shortDate(c.return_due)}</p> : null}
      {c.pending_readings ? (
        <p className="mt-1 text-[14px] font-semibold text-warn-ink">
          {c.pending_readings} statement{c.pending_readings === 1 ? "" : "s"} to approve
        </p>
      ) : null}
    </Card>
  );
}

/** Property income this tax year (your share), for anyone with a property register or landlord mode on. */
export function PropertyCard() {
  const data = useOverviewData();
  const landlord = useLandlordOn();
  const p = data?.property;
  if (!data || (!p && !landlord)) return null;
  return (
    <Card
      id="home-property"
      title={<>Property income<Sample /></>}
      href="/property"
      action={p ? "Open property" : "Add a property"}
      by={<ByWhom className="mt-2" code="Your share, worked out by code from tagged entries" ai="no AI involved" />}
    >
      {p ? (
        <>
          <p className="mt-1 text-3xl font-extrabold tracking-tight tabular-nums">{pounds(p.profit_pence)}</p>
          <p className="text-[13px] font-semibold text-muted">
            Profit in {p.tax_year} so far: {pounds(p.income_pence)} rent, {pounds(p.expenses_pence)} costs ·{" "}
            {p.properties} propert{p.properties === 1 ? "y" : "ies"}
          </p>
        </>
      ) : (
        <p className="mt-1 text-[15px]">Landlord mode is on but no property is registered yet.</p>
      )}
    </Card>
  );
}

/** Cheaper options and the shopping list: what you could save on regular buys, and what is on the list. */
export function BuyingCard() {
  const account = useAccount();
  const [prices, setPrices] = useState<RtPriceReport | null>(null);
  const [shopping, setShopping] = useState<RtShoppingItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!account) return;
    let stale = false;
    const fail = (e: unknown) => !stale && (e as Error).message !== "redirecting for consent" && setError(errorText(e));
    runtime.prices(account).then((d) => !stale && setPrices(d), fail);
    runtime.shopping(account).then((d) => !stale && setShopping(d.items), () => undefined); // no list: no line
    return () => {
      stale = true;
    };
  }, [account]);
  if (!account) return null;
  const open = shopping?.filter((i) => !i.done) ?? null;
  const saving = prices && Number(prices.total_saving_per_year) > 0 ? prices.total_saving_per_year : null;
  return (
    <Card
      id="home-buying"
      title="Cheaper options and shopping"
      href={saving ? "/prices" : "/shopping"}
      action={saving ? "See cheaper options" : "Open shopping list"}
      by={<ByWhom className="mt-2" code="Prices compared by code from your own receipts" ai="matches suggested by AI" />}
    >
      <p className="mt-1 text-[15px] leading-6">
        {prices === null && !error
          ? "Checking your regular buys…"
          : saving
            ? `You could save about £${Number(saving).toLocaleString("en-GB", { maximumFractionDigits: 0 })} a year by buying the same things elsewhere.`
            : "No cheaper options found in your receipts yet."}
      </p>
      {open ? (
        <p className="text-[14px] text-muted">
          <Link href="/shopping" className="font-semibold text-teal-dark hover:underline">
            Shopping list: {open.length} item{open.length === 1 ? "" : "s"}
          </Link>
        </p>
      ) : null}
      {error && <RuntimeErrorNote message={error} />}
    </Card>
  );
}
