"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode, type RefObject } from "react";
import ByWhom from "@/components/ByWhom";
import { GRID, money, monthTick, MUTED, NET, PURCHASES, SALES, whole, yAxis } from "@/components/reports/chart";
import type { RtCashSeries, RtHomeSnapshot, RtTrendMonth } from "@/lib/runtime";
import { pounds, SampleTag, shortDate, Skeleton, UNKNOWN } from "./HomeData";
import { useOverview, useOverviewData } from "./Overview";

/**
 * Home › Business snapshot (GET /books/home `snapshot`, `trend`, `cash_points`; the Bramblewood sample on /try):
 * the year to date against last year, the last 12 months as bars with the net line, and the 90-day cash forecast.
 * Every figure is worked out by code (services/runtime/app/home_overview.py); the charts are inline SVG, each with a
 * text alternative: an aria-label and the same figures as a table for screen readers. Changes are said with an arrow
 * and words ("▲ 12% vs last year"), never colour alone.
 */

const link = "inline-block whitespace-nowrap rounded-xl border border-border px-3 py-1.5 text-sm font-bold text-teal-dark hover:bg-ground";

/** The width of a box in CSS pixels, so a chart draws at its real size (crisp text on a phone, no sideways scroll). */
function useWidth(fallback: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.max(200, Math.floor(entry.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

function Panel({ id, title, children, className = "" }: { id: string; title: string; children: ReactNode; className?: string }) {
  return (
    <section aria-labelledby={id} className={`flex min-w-0 flex-col rounded-2xl border border-border bg-white p-4 sm:p-5 ${className}`}>
      <h3 id={id} className="text-base font-bold tracking-tight">
        {title}
      </h3>
      {children}
    </section>
  );
}

// --------------------------------------------------------------------------- //
// The year to date
// --------------------------------------------------------------------------- //

/** "▲ 12% vs last year", "▼ 8% vs last year", "— no change", or "— no figure last year". `good` is the direction
 *  that is good news for this figure (turnover up, expenses down); the words carry it, the tint only repeats it. */
function Change({ pct, good }: { pct: number | null; good: "up" | "down" }) {
  if (pct === null)
    return (
      <p className="mt-1 text-[13px] font-semibold text-muted">
        <span aria-hidden="true">—</span> no figure last year
      </p>
    );
  const dir = pct > 0 ? "up" : pct < 0 ? "down" : "same";
  const tone = dir === "same" ? "text-muted" : dir === good ? "text-teal-dark" : "text-warn-ink";
  return (
    <p className={`mt-1 text-[13px] font-semibold ${tone}`} data-change={dir}>
      <span aria-hidden="true">{dir === "up" ? "▲" : dir === "down" ? "▼" : "—"}</span>{" "}
      {dir === "same" ? (
        "no change vs last year"
      ) : (
        <>
          <span className="sr-only">{dir} </span>
          {Math.abs(pct)}% vs last year
        </>
      )}
    </p>
  );
}

function Figure({ label, value, children }: { label: string; value: string; children: ReactNode }) {
  return (
    <div role="group" aria-label={label} className="min-w-0">
      <p className="text-sm font-semibold text-muted">{label}</p>
      <p className="mt-1 text-2xl leading-tight font-bold tracking-tight tabular-nums sm:text-[28px]">{value}</p>
      {children}
    </div>
  );
}

function LastYear({ pence }: { pence: number }) {
  return <p className="text-[12px] text-muted">Last year {pounds(pence)}</p>;
}

export function SnapshotCard({ snapshot, vat }: { snapshot: RtHomeSnapshot; vat: boolean }) {
  const s = snapshot;
  const loss = s.net_profit_pence < 0;
  const v = s.vat_position;
  const vatLabel = v ? { pay: "VAT to pay", reclaim: "VAT to reclaim", nil: "VAT" }[v.direction] : "VAT";
  return (
    <Panel id="snapshot-year" title="Year to date" className="lg:col-span-3">
      <div className={`mt-3 grid grid-cols-2 gap-x-3 gap-y-4 ${vat ? "md:grid-cols-4" : "md:grid-cols-3"}`}>
        <Figure label="Turnover" value={pounds(s.turnover_pence)}>
          <Change pct={s.change_pct.turnover} good="up" />
          <LastYear pence={s.last_year.turnover_pence} />
        </Figure>
        <Figure label="Expenses" value={pounds(s.expenses_pence)}>
          <Change pct={s.change_pct.expenses} good="down" />
          <LastYear pence={s.last_year.expenses_pence} />
        </Figure>
        <Figure label={loss ? "Net loss" : "Net profit"} value={pounds(Math.abs(s.net_profit_pence))}>
          <Change pct={s.change_pct.net_profit} good="up" />
          <LastYear pence={s.last_year.net_profit_pence} />
        </Figure>
        {vat ? (
          <Figure label={vatLabel} value={v ? pounds(v.amount_pence) : UNKNOWN}>
            <p className="mt-1 text-[13px] font-semibold text-muted">
              {v ? `${v.label} · due ${shortDate(v.due)}${v.estimate ? " · so far" : ""}` : "Could not work out the VAT period"}
            </p>
          </Figure>
        ) : null}
      </div>
      <p className="mt-3 text-[12px] leading-5 text-muted">
        {s.period_label} against {s.last_year_label} · {s.basis} · year from {s.year_start_rule}
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Link href="/reports" className={link}>
          Profit and loss
        </Link>
        {vat ? (
          <Link href="/vat" className={link}>
            VAT return
          </Link>
        ) : null}
      </div>
    </Panel>
  );
}

// --------------------------------------------------------------------------- //
// The last 12 months
// --------------------------------------------------------------------------- //

const CHART_H = 220;
const CHART_PAD = { top: 12, right: 8, bottom: 26, left: 52 };

export function MonthlyChart({ months }: { months: RtTrendMonth[] }) {
  const [box, width] = useWidth(640);
  const hatch = `hatch-${useId().replace(/:/g, "")}`;
  const [active, setActive] = useState<number | null>(null);
  const empty = months.every((m) => !m.sales_pence && !m.purchases_pence);
  const first = months[0];
  const last = months.at(-1);

  const W = width;
  const { y, ticks } = yAxis(months.flatMap((m) => [m.sales_pence, m.purchases_pence, m.net_pence]), CHART_H, CHART_PAD);
  const plotW = W - CHART_PAD.left - CHART_PAD.right;
  const slot = plotW / Math.max(months.length, 1);
  const bar = Math.max(2, Math.min(18, slot * 0.34));
  const left = (i: number) => CHART_PAD.left + i * slot;
  const centre = (i: number) => left(i) + slot / 2;
  const y0 = y(0);
  const every = slot < 30 ? 3 : slot < 48 ? 2 : 1; // fewer month labels when the chart is narrow
  const shown = active ?? months.length - 1;
  const m = months[shown];
  const best = months.reduce((a, b) => (b.net_pence > a.net_pence ? b : a), months[0]);
  const up = (last?.net_pence ?? 0) >= (first?.net_pence ?? 0);

  const keys = (e: KeyboardEvent) => {
    const i = active ?? months.length - 1;
    const next = e.key === "ArrowLeft" ? i - 1 : e.key === "ArrowRight" ? i + 1 : e.key === "Home" ? 0 : e.key === "End" ? months.length - 1 : null;
    if (next === null) return;
    e.preventDefault();
    setActive(Math.min(months.length - 1, Math.max(0, next)));
  };

  const barRect = (v: number, x: number, fill: string, label: string) => (
    <rect x={x} y={Math.min(y(v), y0)} width={bar} height={Math.max(Math.abs(y(v) - y0), v ? 1 : 0)} fill={fill} rx={2}>
      <title>{label}</title>
    </rect>
  );

  return (
    <Panel id="snapshot-trend" title="Last 12 months" className="lg:col-span-2">
      {empty ? (
        <p className="mt-2 text-[15px] text-muted">No approved sales or costs in the last 12 months yet. Approve an entry in Review to start the chart.</p>
      ) : (
        <figure className="mt-2 flex flex-col gap-2">
          <figcaption className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] font-semibold text-muted">
            <span className="flex items-center gap-1.5">
              <span aria-hidden="true" className="h-3 w-3 rounded-sm" style={{ background: SALES }} /> Sales
            </span>
            <span className="flex items-center gap-1.5">
              <svg aria-hidden="true" width="12" height="12">
                <rect width="12" height="12" rx="2" fill={`url(#${hatch})`} />
              </svg>
              Purchases (cost of sales + overheads)
            </span>
            <span className="flex items-center gap-1.5">
              <span aria-hidden="true" className="h-0.5 w-4" style={{ background: NET }} /> Net profit
            </span>
          </figcaption>
          {/* What the pointer or arrow keys are on: the month's three figures in words. */}
          <p aria-live="polite" className="min-h-5 text-[13px] font-semibold tabular-nums text-ink" data-chart-readout="">
            {m ? `${m.label}: sales ${money(m.sales_pence)} · purchases ${money(m.purchases_pence)} · net ${money(m.net_pence)}` : ""}
          </p>
          <div ref={box} className="w-full min-w-0">
            <svg
              viewBox={`0 0 ${W} ${CHART_H}`}
              width="100%"
              height={CHART_H}
              role="img"
              tabIndex={0}
              onKeyDown={keys}
              onMouseLeave={() => setActive(null)}
              aria-label={`Sales and purchases as bars and net profit as a line for each month, ${first?.label ?? ""} to ${last?.label ?? ""}. Best month ${best?.label ?? ""}, net ${money(best?.net_pence ?? 0)}. Net ${up ? "rose" : "fell"} from ${money(first?.net_pence ?? 0)} to ${money(last?.net_pence ?? 0)}. Left and right arrow keys read each month; the figures are also in a table.`}
              className="block rounded-lg"
            >
              <defs>
                <pattern id={hatch} patternUnits="userSpaceOnUse" width="5" height="5" patternTransform="rotate(45)">
                  <rect width="5" height="5" fill={PURCHASES} />
                  <line x1="0" y1="0" x2="0" y2="5" stroke="#fff" strokeWidth="1.6" strokeOpacity="0.55" />
                </pattern>
              </defs>
              {ticks.map((v) => (
                <g key={v}>
                  <line x1={CHART_PAD.left} x2={W - CHART_PAD.right} y1={y(v)} y2={y(v)} stroke={v === 0 ? MUTED : GRID} strokeWidth={1} />
                  <text x={CHART_PAD.left - 6} y={y(v) + 4} textAnchor="end" fontSize={11} fill={MUTED}>
                    {whole(v)}
                  </text>
                </g>
              ))}
              {months.map((mo, i) => (
                <g key={mo.month} onMouseEnter={() => setActive(i)}>
                  <rect x={left(i)} y={CHART_PAD.top} width={slot} height={CHART_H - CHART_PAD.top - CHART_PAD.bottom} fill={i === active ? "#f4f3ee" : "transparent"}>
                    <title>{`${mo.label}: sales ${money(mo.sales_pence)}, purchases ${money(mo.purchases_pence)}, net ${money(mo.net_pence)}`}</title>
                  </rect>
                  {barRect(mo.sales_pence, centre(i) - bar - 1, SALES, `${mo.label}: sales ${money(mo.sales_pence)}`)}
                  {barRect(mo.purchases_pence, centre(i) + 1, `url(#${hatch})`, `${mo.label}: purchases ${money(mo.purchases_pence)}`)}
                  {(i % every === 0 || i === months.length - 1) && (
                    <text x={centre(i)} y={CHART_H - CHART_PAD.bottom + 16} textAnchor="middle" fontSize={11} fill={MUTED}>
                      {monthTick(mo.month, mo.label, i === 0)}
                    </text>
                  )}
                </g>
              ))}
              <polyline
                points={months.map((mo, i) => `${centre(i).toFixed(1)},${y(mo.net_pence).toFixed(1)}`).join(" ")}
                fill="none"
                stroke={NET}
                strokeWidth={2}
                strokeLinejoin="round"
                pointerEvents="none"
              />
              {months.map((mo, i) => (
                <circle key={mo.month} cx={centre(i)} cy={y(mo.net_pence)} r={i === active ? 4.5 : 3} fill={NET} stroke="#fff" strokeWidth={1.5} pointerEvents="none" />
              ))}
            </svg>
          </div>
          <div className="sr-only">
            <table>
              <caption>Sales, purchases and net profit per month</caption>
              <thead>
                <tr>
                  <th scope="col">Month</th>
                  <th scope="col">Sales</th>
                  <th scope="col">Purchases</th>
                  <th scope="col">Net profit</th>
                </tr>
              </thead>
              <tbody>
                {months.map((mo) => (
                  <tr key={mo.month}>
                    <th scope="row">{mo.label}</th>
                    <td>{money(mo.sales_pence)}</td>
                    <td>{money(mo.purchases_pence)}</td>
                    <td>{money(mo.net_pence)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </figure>
      )}
      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-3">
        <p className="text-[12px] text-muted">As approved, by calendar month; this month so far.</p>
        <Link href="/reports" className={link}>
          Full trend
        </Link>
      </div>
    </Panel>
  );
}

// --------------------------------------------------------------------------- //
// The cash forecast
// --------------------------------------------------------------------------- //

const SPARK_H = 96;
const SPARK_PAD = { top: 10, right: 8, bottom: 10, left: 8 };

function WarnIcon() {
  return (
    <svg aria-hidden="true" width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" className="mt-0.5 shrink-0">
      <circle cx="10" cy="10" r="7.5" />
      <path d="M10 6v4.5M10 13.6v.1" />
    </svg>
  );
}

export function CashSparkline({ cash }: { cash: RtCashSeries | null }) {
  const [box, width] = useWidth(300);
  const pts = cash?.points ?? [];
  return (
    <Panel id="snapshot-cash" title="Cash, next 90 days">
      {!cash || pts.length < 2 ? (
        <p className="mt-2 text-[15px] text-muted" data-cash-empty="">
          Import a bank statement to see cash forecast.{" "}
          <Link href="/bank" className="font-semibold text-teal-dark underline underline-offset-2 hover:text-teal">
            Go to Bank
          </Link>
        </p>
      ) : (
        <Spark cash={cash} width={width} box={box} />
      )}
      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-3">
        <p className="text-[12px] text-muted">Open invoices, bills and repeating items; no pay runs or VAT.</p>
        <Link href="/reports/cashflow" className={link}>
          Cash flow forecast
        </Link>
      </div>
    </Panel>
  );
}

function Spark({ cash, width, box }: { cash: RtCashSeries; width: number; box: RefObject<HTMLDivElement | null> }) {
  const pts = cash.points;
  const W = width;
  const last = pts[pts.length - 1];
  const span = Math.max(last.days, 1);
  const { y } = yAxis([...pts.map((p) => p.balance_pence), cash.lowest_balance_pence], SPARK_H, SPARK_PAD, 2);
  const x = (days: number) => SPARK_PAD.left + (days / span) * (W - SPARK_PAD.left - SPARK_PAD.right);
  const line = pts.map((p) => `${x(p.days).toFixed(1)},${y(p.balance_pence).toFixed(1)}`).join(" ");
  const area = `${x(0).toFixed(1)},${y(0).toFixed(1)} ${line} ${x(last.days).toFixed(1)},${y(0).toFixed(1)}`;
  const lowDays = Math.round((Date.parse(cash.lowest_on) - Date.parse(cash.as_of)) / 86_400_000);
  const lowest = `Lowest ${pounds(cash.lowest_balance_pence)} on ${shortDate(cash.lowest_on)}`;
  const negative = pts.some((p) => p.balance_pence < 0) || cash.lowest_balance_pence < 0;
  return (
    <div className="mt-2 flex flex-col gap-1.5">
      <p className="text-[13px] font-semibold tabular-nums text-muted">
        Today {pounds(cash.opening_balance_pence)} · {shortDate(last.date)} {pounds(last.balance_pence)}
      </p>
      <div ref={box} className="w-full min-w-0">
        <svg
          viewBox={`0 0 ${W} ${SPARK_H}`}
          width="100%"
          height={SPARK_H}
          role="img"
          aria-label={`Forecast bank balance over the next 90 days, from ${pounds(cash.opening_balance_pence)} today to ${pounds(last.balance_pence)} on ${shortDate(last.date)}. ${lowest}.${cash.below_zero_on ? ` It goes below £0 on ${shortDate(cash.below_zero_on)}.` : ""}`}
          className="block"
        >
          <polygon points={area} fill="#f4ede5" />
          {negative && <line x1={SPARK_PAD.left} x2={W - SPARK_PAD.right} y1={y(0)} y2={y(0)} stroke={MUTED} strokeDasharray="3 3" strokeWidth={1} />}
          <polyline points={line} fill="none" stroke={SALES} strokeWidth={2} strokeLinejoin="round" />
          {pts.map((p) => (
            <circle key={p.days} cx={x(p.days)} cy={y(p.balance_pence)} r={6} fill="transparent">
              <title>{`${shortDate(p.date)}: ${pounds(p.balance_pence)}`}</title>
            </circle>
          ))}
          <circle cx={x(lowDays)} cy={y(cash.lowest_balance_pence)} r={4} fill="#fff" stroke={negative ? PURCHASES : NET} strokeWidth={2}>
            <title>{lowest}</title>
          </circle>
        </svg>
      </div>
      <p className="text-[13px] font-bold tabular-nums text-ink" data-cash-lowest="">
        {lowest}
      </p>
      {cash.below_zero_on ? (
        <p className="flex items-start gap-1.5 rounded-lg border border-warn-border bg-warn-bg px-2 py-1.5 text-[13px] font-semibold text-warn-ink">
          <WarnIcon />
          Goes below £0 on {shortDate(cash.below_zero_on)}
        </p>
      ) : null}
      <div className="sr-only">
        <table>
          <caption>Forecast bank balance</caption>
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col">Balance</th>
            </tr>
          </thead>
          <tbody>
            {pts.map((p) => (
              <tr key={p.days}>
                <th scope="row">{shortDate(p.date)}</th>
                <td>{pounds(p.balance_pence)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// The block
// --------------------------------------------------------------------------- //

/** The three together, between What needs attention and Today. Personal books (no snapshot) show nothing. */
export function BusinessSnapshot() {
  const o = useOverview();
  const data = useOverviewData();
  if (o.mode === "error") return null; // the summary card says why
  if (data && !data.snapshot && !data.trend) return null;
  const sample = o.mode === "sample";
  const vat = data ? data.features.includes("vat") : false;
  return (
    <section aria-labelledby="business-snapshot" data-home-card="business-snapshot" className="flex min-w-0 flex-col gap-3">
      <h2 id="business-snapshot" className="text-[19px] font-semibold tracking-tight">
        Business snapshot
        {sample ? <SampleTag /> : null}
      </h2>
      {data ? (
        <div className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-3">
          {data.snapshot ? <SnapshotCard snapshot={data.snapshot} vat={vat} /> : null}
          {data.trend ? <MonthlyChart months={data.trend.months} /> : null}
          <CashSparkline cash={data.cash_points} />
        </div>
      ) : (
        <div aria-busy="true" className="grid grid-cols-1 gap-3 lg:grid-cols-3">
          <div className="rounded-2xl border border-border bg-white p-4 lg:col-span-3">
            <Skeleton className="h-5 w-32" />
            <Skeleton className="mt-3 h-8 w-full" />
          </div>
          <div className="min-h-56 rounded-2xl border border-border bg-white p-4 lg:col-span-2">
            <Skeleton className="h-5 w-40" />
          </div>
          <div className="min-h-56 rounded-2xl border border-border bg-white p-4">
            <Skeleton className="h-5 w-32" />
          </div>
        </div>
      )}
      {data ? (
        <ByWhom
          code={sample ? "Sample figures from the fictional Bramblewood books" : "Every figure by code from your approved entries and bank statements"}
          ai="no AI involved"
        />
      ) : null}
    </section>
  );
}
