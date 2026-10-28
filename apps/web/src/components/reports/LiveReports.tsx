"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { getMsal, msalConfigured } from "@/lib/msal";
import { loadBusiness } from "@/lib/business";
import PrintButton from "@/components/PrintButton";
import SignInCta from "@/components/SignInCta";
import { LoadingSkeleton, RuntimeErrorNote, SamplePill, parseRuntimeError } from "@/components/States";
import VatPeriodPicker from "@/components/vat/VatPeriodPicker";
import {
  runtime,
  ukDate,
  type RtAged,
  type RtAgedReport,
  AGED_BUCKETS,
  agedBucketLabel,
  type RtAgedBucket,
  type RtAgedRow,
  type RtAgedTable,
  type RtBasis,
  type RtPlSection,
  type RtProfitAndLoss,
  type RtTrend,
  type RtVatSummary,
} from "@/lib/runtime";
import { sampleAged, samplePl, samplePlPrev, samplePlYear, sampleTrend, sampleVat } from "@/lib/sample-reports";
import { usePickedPeriod } from "@/lib/vat-period";
import { useSelfEmployed } from "@/lib/itsa";
import TrendBars from "./TrendBars";

const BUCKETS: RtAgedBucket[] = AGED_BUCKETS;
const money = (pence: number) => (pence / 100).toLocaleString("en-GB", { style: "currency", currency: "GBP" });
const card = "rounded-2xl border border-border bg-white p-5 sm:p-6";
const th = "px-3 py-2 text-left text-[13px] font-bold text-muted";
const td = "px-3 py-2 text-[15px]";

/** A table that may scroll sideways on a phone: focusable and named, so the keyboard can scroll it too. */
function Scroll({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div role="region" aria-label={label} tabIndex={0} className="mt-2 overflow-x-auto">
      {children}
    </div>
  );
}

/** Paper only: who the report is for. Business details live on this device (localStorage), read once. */
function PrintHeader({ title, period }: { title: string; period: string }) {
  const [business] = useState<{ name: string; vatNumber: string } | null>(() => {
    const b = loadBusiness();
    return b && (b.name || b.vatNumber) ? { name: b.name, vatNumber: b.vatNumber } : null;
  });
  return (
    <div className="hidden print:block">
      <p className="text-sm font-bold">
        {business?.name ? business.name : "Reports"}
        {business?.name && business?.vatNumber ? " · " : ""}
        {business?.vatNumber ? `VRN ${business.vatNumber}` : ""}
      </p>
      <p className="text-sm">
        {title} · {period}
      </p>
      <p className="text-sm text-muted">Calculated by code from approved entries.</p>
    </div>
  );
}

const dayMs = 86_400_000;
const isoToUtc = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, m - 1, d);
};
const toIso = (t: number) => new Date(t).toISOString().slice(0, 10);

/** The same-length period ending the day before `start` (e.g. the previous quarter). */
export function prevSpan(start: string, end: string): { start: string; end: string } {
  const days = Math.round((isoToUtc(end) - isoToUtc(start)) / dayMs) + 1;
  const pe = isoToUtc(start) - dayMs;
  return { start: toIso(pe - (days - 1) * dayMs), end: toIso(pe) };
}

/** The same dates a year earlier (29 Feb becomes 28 Feb). */
export function yearSpan(start: string, end: string): { start: string; end: string } {
  const back = (iso: string) => {
    const [y, m, d] = iso.split("-").map(Number);
    const last = new Date(Date.UTC(y - 1, m, 0)).getUTCDate();
    return toIso(Date.UTC(y - 1, m - 1, Math.min(d, last)));
  };
  return { start: back(start), end: back(end) };
}

const signedMoney = (pence: number) =>
  (pence / 100).toLocaleString("en-GB", { style: "currency", currency: "GBP", signDisplay: "exceptZero" });
const pct = (current: number, base: number) =>
  base === 0 ? "—" : `${current >= base ? "+" : "−"}${(Math.abs(current - base) / Math.abs(base) * 100).toFixed(1)}%`;

/** One horizontal bar per value (this period, previous, last year): inline SVG, never colour alone (the figures sit beside it). */
function SectionBar({ label, values }: { label: string; values: [number, number, number] }) {
  const names = ["this period", "previous period", "same period last year"];
  const fills = ["#0f6e63", "#4b5159", "#b45309"];
  const max = Math.max(...values.map(Math.abs), 1);
  return (
    <svg
      viewBox="0 0 120 34"
      role="img"
      aria-label={`${label}: ${values.map((v, i) => `${money(v)} ${names[i]}`).join(", ")}`}
      className="h-[34px] w-[120px] max-w-none shrink-0"
    >
      {values.map((v, i) => (
        <rect key={i} x={0} y={i * 12} width={Math.max((Math.abs(v) / max) * 120, v === 0 ? 0 : 2)} height={8} rx={2} fill={fills[i]}>
          <title>{`${names[i]}: ${money(v)}`}</title>
        </rect>
      ))}
    </svg>
  );
}

function CompareCell({ current, base }: { current: number; base: number | null }) {
  if (base === null) return <span className="text-muted">…</span>;
  return (
    <span>
      <span className="font-bold">{signedMoney(current - base)}</span> <span className="text-muted">({pct(current, base)})</span>
    </span>
  );
}

/** This period against the previous period and the same period last year, with change £ and %. */
function PlCompare({ pl, prev, year }: { pl: RtProfitAndLoss; prev: RtProfitAndLoss | null; year: RtProfitAndLoss | null }) {
  const rows: { name: string; now: number; was: number | null; last: number | null }[] = [
    { name: "Sales", now: pl.sales.total_pence, was: prev?.sales.total_pence ?? null, last: year?.sales.total_pence ?? null },
    { name: "Cost of sales", now: pl.cost_of_sales.total_pence, was: prev?.cost_of_sales.total_pence ?? null, last: year?.cost_of_sales.total_pence ?? null },
    { name: "Gross profit", now: pl.gross_profit_pence, was: prev?.gross_profit_pence ?? null, last: year?.gross_profit_pence ?? null },
    { name: "Overheads", now: pl.overheads.total_pence, was: prev?.overheads.total_pence ?? null, last: year?.overheads.total_pence ?? null },
    { name: "Net profit", now: pl.net_profit_pence, was: prev?.net_profit_pence ?? null, last: year?.net_profit_pence ?? null },
  ];
  return (
    <>
      <h3 className="mt-5 text-[15px] font-extrabold">Compared with earlier periods</h3>
      <Scroll label={`Profit and loss compared with earlier periods, ${pl.label}`}>
        <table className="w-full min-w-[640px] border-collapse">
          <caption className="sr-only">
            Profit and loss compared with earlier periods: {pl.label} against {prev?.label ?? "the previous period"} and {year?.label ?? "the same period last year"}
          </caption>
          <thead>
            <tr className="border-b border-border">
              <th scope="col" className={th}>Measure</th>
              <th scope="col" className={th}>Trend</th>
              <th scope="col" className={`${th} text-right`}>{pl.label}</th>
              <th scope="col" className={`${th} text-right`}>{prev?.label ?? "Previous"}</th>
              <th scope="col" className={`${th} text-right`}>{year?.label ?? "Last year"}</th>
              <th scope="col" className={`${th} text-right`}>Change vs previous</th>
              <th scope="col" className={`${th} text-right`}>Change vs last year</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name} className="border-t border-border">
                <th scope="row" className={`${td} text-left font-semibold`}>{r.name}</th>
                <td className={td}>
                  <SectionBar label={r.name} values={[r.now, r.was ?? 0, r.last ?? 0]} />
                </td>
                <td className={`${td} text-right font-bold tabular-nums`}>{money(r.now)}</td>
                <td className={`${td} text-right tabular-nums`}>{r.was === null ? "…" : money(r.was)}</td>
                <td className={`${td} text-right tabular-nums`}>{r.last === null ? "…" : money(r.last)}</td>
                <td className={`${td} text-right tabular-nums`}><CompareCell current={r.now} base={r.was} /></td>
                <td className={`${td} text-right tabular-nums`}><CompareCell current={r.now} base={r.last} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Scroll>
      <p className="mt-1 text-[13px] text-muted">
        Previous is the {pl.label} period shifted back ({prev?.label ?? "loading…"});
        last year is the same dates a year earlier ({year?.label ?? "loading…"}).
      </p>
    </>
  );
}

function PlRows({ title, section }: { title: string; section: RtPlSection }) {
  return (
    <>
      <tr>
        <th scope="rowgroup" colSpan={2} className={`${td} pt-4 text-left font-extrabold`}>
          {title}
        </th>
      </tr>
      {section.rows.length === 0 ? (
        <tr>
          <td colSpan={2} className={`${td} pl-6 text-muted`}>Nothing in this period.</td>
        </tr>
      ) : (
        section.rows.map((r) => (
          <tr key={r.account} className="border-t border-border">
            <th scope="row" className={`${td} pl-6 text-left font-normal`}>{r.account}</th>
            <td className={`${td} text-right tabular-nums`}>{money(r.amount_pence)}</td>
          </tr>
        ))
      )}
      <tr className="border-t border-border">
        <th scope="row" className={`${td} text-left font-bold`}>Total {title.toLowerCase()}</th>
        <td className={`${td} text-right font-bold tabular-nums`}>{money(section.total_pence)}</td>
      </tr>
    </>
  );
}

function ProfitAndLoss({ pl, prev, year }: { pl: RtProfitAndLoss; prev: RtProfitAndLoss | null; year: RtProfitAndLoss | null }) {
  const loss = pl.net_profit_pence < 0;
  return (
    <section aria-labelledby="pl-heading" className={card}>
      <PrintHeader title={pl.accounting_basis === "cash" ? "Profit and loss (cash basis)" : "Profit and loss"} period={`${pl.label} · ${ukDate(pl.start)} – ${ukDate(pl.end)}`} />
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="pl-heading" className="text-lg font-extrabold">
          Profit and loss{pl.accounting_basis === "cash" ? " (cash basis)" : ""} · {pl.label} · {ukDate(pl.start)} – {ukDate(pl.end)}
        </h2>
        <span className="text-sm text-muted">
          {pl.entries} approved {pl.entries === 1 ? "entry" : "entries"} · calculated by code
        </span>
      </div>
      <p className="mt-1 text-[13px] text-muted">{pl.basis}</p>
      <PlCompare pl={pl} prev={prev} year={year} />
      <Scroll label={`Profit and loss table, ${pl.label}`}>
        <table className="w-full min-w-[420px] border-collapse">
          <caption className="sr-only">Profit and loss by account, {pl.label}</caption>
          <thead>
            <tr className="border-b border-border">
              <th scope="col" className={th}>Account</th>
              <th scope="col" className={`${th} text-right`}>Amount</th>
            </tr>
          </thead>
          <tbody>
            <PlRows title="Sales" section={pl.sales} />
            <PlRows title="Cost of sales" section={pl.cost_of_sales} />
            <tr className="border-t-2 border-ink bg-ground">
              <th scope="row" className={`${td} text-left font-extrabold`}>Gross profit</th>
              <td className={`${td} text-right font-extrabold tabular-nums`}>{money(pl.gross_profit_pence)}</td>
            </tr>
            <PlRows title="Overheads" section={pl.overheads} />
            <tr className="border-t-2 border-ink bg-teal-tint">
              <th scope="row" className={`${td} text-left text-[17px] font-extrabold`}>{loss ? "Net loss" : "Net profit"}</th>
              <td className={`${td} text-right text-[17px] font-extrabold tabular-nums ${loss ? "text-warn-ink" : ""}`}>
                {money(pl.net_profit_pence)}
              </td>
            </tr>
          </tbody>
        </table>
      </Scroll>
    </section>
  );
}

const AGED_FILLS: Record<RtAgedBucket, string> = {
  current: "#0f6e63",
  "0-30": "#b45309",
  "31-60": "#1d4ed8",
  "61-90": "#be123c",
  "90+": "#713f12",
};

/** What each contact owes as one stacked bar (not yet due / 1–30 / 31–60 / 61–90 / 90+ days late). */
function AgedBar({ row }: { row: RtAgedRow }) {
  const total = Math.max(row.total_pence, 1);
  const widths = BUCKETS.map((b) => (row.buckets[b] / total) * 120);
  const starts = widths.map((_, i) => widths.slice(0, i).reduce((a, w) => a + w, 0));
  const parts = BUCKETS.map((b, i) => ({ b, x: starts[i], w: widths[i], amount: row.buckets[b] }));
  return (
    <svg
      viewBox="0 0 120 10"
      role="img"
      aria-label={`${row.name}: ${BUCKETS.map((b) => `${money(row.buckets[b])} ${agedBucketLabel(b).toLowerCase()}`).join(", ")}`}
      className="h-[10px] w-[120px] max-w-none"
    >
      <rect x={0} width={120} height={10} rx={3} fill="#e3e1d8" />
      {parts.map((p) =>
        p.w > 0 ? <rect key={p.b} x={p.x} width={Math.max(p.w, 2)} height={10} fill={AGED_FILLS[p.b]}><title>{`${agedBucketLabel(p.b)}: ${money(p.amount)}`}</title></rect> : null,
      )}
    </svg>
  );
}

function AgedTable({ title, hint, table }: { title: string; hint: string; table: RtAgedTable }) {
  return (
    <section aria-label={title} className={`${card} min-w-0 flex-1`}>
      <h3 className="text-[15px] font-extrabold">{title}</h3>
      <p className="text-[13px] text-muted">{hint}</p>
      <p className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[12px] font-semibold text-muted">
        {BUCKETS.map((b) => (
          <span key={b} className="flex items-center gap-1">
            <span aria-hidden="true" className="h-2.5 w-2.5 rounded-sm" style={{ background: AGED_FILLS[b] }} />
            {agedBucketLabel(b)}
          </span>
        ))}
      </p>
      {table.rows.length === 0 ? (
        <p className="mt-3 text-sm font-semibold text-muted">Nothing unpaid.</p>
      ) : (
        <Scroll label={`${title} table`}>
          <table className="w-full min-w-[560px] border-collapse tabular-nums">
            <thead className="border-b border-border">
              <tr>
                <th scope="col" className={th}>Name</th>
                <th scope="col" className={th}>Age</th>
                {BUCKETS.map((b) => <th key={b} scope="col" className={`${th} text-right`}>{agedBucketLabel(b)}</th>)}
                <th scope="col" className={`${th} text-right`}>Total</th>
              </tr>
            </thead>
            <tbody>
              {table.rows.map((r) => (
                <tr key={r.contact_id} className="border-b border-border">
                  <th scope="row" className={`${td} text-left font-semibold`}>
                    <Link
                      href={`/contacts?id=${encodeURIComponent(r.contact_id)}`}
                      className="text-teal-dark underline underline-offset-2 hover:text-teal"
                    >
                      {r.name}
                    </Link>
                  </th>
                  <td className={td}><AgedBar row={r} /></td>
                  {BUCKETS.map((b) => (
                    <td key={b} className={`${td} text-right ${b === "90+" && r.buckets[b] ? "font-bold text-warn-ink" : ""}`}>
                      {r.buckets[b] ? money(r.buckets[b]) : "—"}
                    </td>
                  ))}
                  <td className={`${td} text-right font-bold`}>{money(r.total_pence)}</td>
                </tr>
              ))}
              <tr className="bg-ground">
                <th scope="row" className={`${td} text-left font-bold`}>Total</th>
                <td />
                {BUCKETS.map((b) => <td key={b} className={`${td} text-right font-bold`}>{money(table.buckets[b])}</td>)}
                <td className={`${td} text-right font-extrabold`}>{money(table.total_pence)}</td>
              </tr>
            </tbody>
          </table>
        </Scroll>
      )}
    </section>
  );
}

function Trend({ trend }: { trend: RtTrend }) {
  return (
    <section aria-labelledby="trend-heading" className={`${card} report-page-break`}>
      <PrintHeader title="Last 12 months" period={`${trend.months[0]?.label ?? ""} to ${trend.months.at(-1)?.label ?? ""}`} />
      <h2 id="trend-heading" className="text-lg font-extrabold">Last 12 months</h2>
      <p className="mb-3 text-[13px] text-muted">Each month&apos;s net is its net profit, from the same accounts as the profit and loss.</p>
      <TrendBars months={trend.months} />
      <h3 className="mt-4 text-[15px] font-extrabold">Monthly figures</h3>
      <Scroll label="Monthly figures table">
        <table className="w-full min-w-[420px] border-collapse tabular-nums">
          <caption className="sr-only">Sales, purchases and net per month, {trend.months[0]?.label} to {trend.months.at(-1)?.label}</caption>
          <thead className="border-b border-border">
            <tr>
              <th scope="col" className={th}>Month</th>
              <th scope="col" className={`${th} text-right`}>Sales</th>
              <th scope="col" className={`${th} text-right`}>Purchases</th>
              <th scope="col" className={`${th} text-right`}>Net</th>
            </tr>
          </thead>
          <tbody>
            {trend.months.map((m) => (
              <tr key={m.month} className="border-b border-border">
                <th scope="row" className={`${td} text-left font-normal`}>{m.label}</th>
                <td className={`${td} text-right`}>{money(m.sales_pence)}</td>
                <td className={`${td} text-right`}>{money(m.purchases_pence)}</td>
                <td className={`${td} text-right font-bold ${m.net_pence < 0 ? "text-warn-ink" : ""}`}>{money(m.net_pence)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Scroll>
    </section>
  );
}

function VatSummary({ vat }: { vat: RtVatSummary }) {
  return (
    <section aria-labelledby="vat-summary-heading" className={`${card} report-page-break`}>
      <PrintHeader title="VAT by period" period={`${vat.periods[0]?.label ?? ""} to ${vat.periods.at(-1)?.label ?? ""}`} />
      <h2 id="vat-summary-heading" className="text-lg font-extrabold">VAT by period</h2>
      <p className="text-[13px] text-muted">The 9-box calculation for each period, as on the VAT return page. Positive net VAT is to pay.</p>
      <Scroll label="VAT by period table">
        <table className="w-full min-w-[560px] border-collapse tabular-nums">
          <thead className="border-b border-border">
            <tr>
              <th scope="col" className={th}>Period</th>
              <th scope="col" className={`${th} text-right`}>VAT on sales (1)</th>
              <th scope="col" className={`${th} text-right`}>VAT reclaimed (4)</th>
              <th scope="col" className={`${th} text-right`}>Net VAT</th>
              <th scope="col" className={`${th} text-right`}>Sales ex VAT (6)</th>
              <th scope="col" className={`${th} text-right`}>Purchases ex VAT (7)</th>
            </tr>
          </thead>
          <tbody>
            {vat.periods.map((p) => (
              <tr key={p.period} className="border-b border-border">
                <th scope="row" className={`${td} text-left font-semibold`}>{p.label}</th>
                <td className={`${td} text-right`}>{money(p.vat_on_sales_pence)}</td>
                <td className={`${td} text-right`}>{money(p.vat_reclaimed_pence)}</td>
                <td className={`${td} text-right font-bold`}>
                  {p.net_vat_pence < 0 ? `${money(-p.net_vat_pence)} back` : money(p.net_vat_pence)}
                </td>
                <td className={`${td} text-right`}>£{p.sales_ex_vat_pounds.toLocaleString("en-GB")}</td>
                <td className={`${td} text-right`}>£{p.purchases_ex_vat_pounds.toLocaleString("en-GB")}</td>
              </tr>
            ))}
            <tr className="bg-ground">
              <th scope="row" className={`${td} text-left font-bold`}>Total</th>
              <td colSpan={2} />
              <td className={`${td} text-right font-extrabold`}>{money(vat.total_net_vat_pence)}</td>
              <td colSpan={2} />
            </tr>
          </tbody>
        </table>
      </Scroll>
    </section>
  );
}

function Reports({ pl, prev, year, aged, vat, trend }: {
  pl: RtProfitAndLoss | null;
  prev: RtProfitAndLoss | null;
  year: RtProfitAndLoss | null;
  aged: RtAged | null;
  vat: RtVatSummary | null;
  trend: RtTrend | null;
}) {
  return (
    <div className="flex flex-col gap-6">
      {pl ? <ProfitAndLoss pl={pl} prev={prev} year={year} /> : <LoadingSkeleton lines={6} label="Working out the profit and loss…" />}
      {trend && <Trend trend={trend} />}
      {aged && (
        <section aria-labelledby="aged-heading" className="flex flex-col gap-3 report-page-break">
          <PrintHeader title="Aged balances" period={`at ${ukDate(aged.as_of)}`} />
          <h2 id="aged-heading" className="text-lg font-extrabold">Aged balances · at {ukDate(aged.as_of)}</h2>
          <div className="flex flex-col gap-4 min-[1000px]:flex-row">
            <AgedTable title="Debtors" hint="Customers who owe you: what is still owed on each sales invoice after part payments and credit notes, by days past its due date." table={aged.debtors} />
            <AgedTable title="Creditors" hint="Suppliers you owe: what is left on bills on account, by days past due (the contact's terms, else 30 days)." table={aged.creditors} />
          </div>
        </section>
      )}
      {vat && <VatSummary vat={vat} />}
    </div>
  );
}

/** Reports from the runtime when signed in (period from the VAT picker); the labelled sample otherwise. */
export default function LiveReports() {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [state, setState] = useState<"checking" | "demo" | "live" | "error">("checking");
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState<{ period: string | null; pl: RtProfitAndLoss } | null>(null);
  const [compare, setCompare] = useState<{ period: string | null; prev: RtProfitAndLoss | null; year: RtProfitAndLoss | null } | null>(null);
  const [aged, setAged] = useState<RtAgedReport | null>(null);
  const [vat, setVat] = useState<RtVatSummary | null>(null);
  const [trend, setTrend] = useState<RtTrend | null>(null);
  const [exporting, setExporting] = useState(false);
  const [saved, setSaved] = useState<{ text: string; url: string | null } | null>(null);
  const picked = usePickedPeriod();
  const selfEmployed = useSelfEmployed();
  const [chosenBasis, setBasis] = useState<RtBasis>("traditional");
  const basis: RtBasis = selfEmployed ? chosenBasis : "traditional"; // the cash basis is for sole traders
  const span = picked ? { start: picked.start, end: picked.end } : null;
  const period = picked ? `${picked.period}:${basis}` : `:${basis}`;
  const pl = loaded && loaded.period === period ? loaded.pl : null; // null while the picked period (or basis) loads

  useEffect(() => {
    (async () => {
      try {
        if (!msalConfigured()) return setState("demo");
        const msal = await getMsal();
        await msal.handleRedirectPromise().catch(() => null);
        const acct = msal.getActiveAccount() ?? msal.getAllAccounts()[0] ?? null;
        if (!acct) return setState("demo");
        setAccount(acct);
        setState("live");
        const [a, v, t] = await Promise.all([runtime.reports.aged(acct), runtime.reports.vat(acct), runtime.reports.trend(acct)]);
        setAged(a);
        setVat(v);
        setTrend(t);
      } catch (e) {
        setError((e as Error).message);
        setState("error");
      }
    })();
  }, []);

  useEffect(() => {
    if (!account) return;
    let stale = false;
    runtime.reports.pl(account, span, basis).then(
      (r) => !stale && setLoaded({ period, pl: r }),
      (e: Error) => {
        if (stale) return;
        setError(e.message);
        setState("error");
      },
    );
    return () => {
      stale = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account, period]);

  // The two extra P&L calls: the previous period and the same period last
  // year, worked out from the loaded period's own dates. Reads only.
  useEffect(() => {
    if (!account || !pl) return; // the table gates on compare.period, so a stale compare never shows
    let stale = false;
    const [ps, ys] = [prevSpan(pl.start, pl.end), yearSpan(pl.start, pl.end)];
    Promise.all([runtime.reports.pl(account, ps, basis), runtime.reports.pl(account, ys, basis)]).then(
      ([p, y]) => {
        if (!stale) setCompare({ period, prev: p, year: y });
      },
      () => {
        if (!stale) setCompare({ period, prev: null, year: null }); // the P&L stands without its comparisons
      },
    );
    return () => {
      stale = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account, pl]);

  async function exportToOneDrive() {
    if (!account) return;
    setExporting(true);
    setSaved(null);
    try {
      const r = await runtime.reports.export(account, { report: "all", basis, ...(span ? { from: span.start, to: span.end } : {}) });
      setSaved({ text: `Saved to ${r.path} in your OneDrive (${r.sheets.filter((s) => s !== "About").join(", ")}).`, url: r.web_url });
    } catch (e) {
      setSaved({ text: `Could not save the report: ${parseRuntimeError((e as Error).message).detail || "try again."}`, url: null });
    } finally {
      setExporting(false);
    }
  }

  if (state === "checking") return <LoadingSkeleton lines={4} label="Loading reports…" />;

  if (state === "demo") {
    return (
      <div className="flex flex-col gap-6">
        <div className="flex flex-wrap items-center justify-between gap-3 print:hidden">
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] font-medium text-muted">
            <SamplePill />
            <span>A mock-up of a business&apos;s reports ({samplePl.label}). Fictional figures.</span>
            <SignInCta />
          </p>
          <PrintButton />
        </div>
        {/* Paper only: the banner does not print, and a printed sample must still say what it is. */}
        <p className="hidden text-sm font-bold print:block">SAMPLE — FICTIONAL COMPANY · fictional figures</p>
        <Reports pl={samplePl} prev={samplePlPrev} year={samplePlYear} aged={sampleAged} vat={sampleVat} trend={sampleTrend} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {account && (
        <div className="flex flex-wrap items-start justify-between gap-3 print:hidden">
          <div className="flex flex-col gap-3">
            <VatPeriodPicker account={account} />
            {selfEmployed && (
              <div role="radiogroup" aria-label="Profit and loss basis" className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-semibold text-muted">Profit and loss:</span>
                {(
                  [
                    ["traditional", "As approved"],
                    ["cash", "Cash basis"],
                  ] as const
                ).map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={basis === value}
                    onClick={() => setBasis(value)}
                    className={`h-9 rounded-xl border px-3 font-bold ${
                      basis === value ? "border-2 border-teal bg-teal-tint text-teal-dark" : "border-border text-ink"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="flex flex-col items-end gap-2">
            <span className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={exportToOneDrive}
                disabled={exporting}
                className="h-11 rounded-xl bg-teal px-4 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-60"
              >
                {exporting ? "Saving…" : "Export to OneDrive"}
              </button>
              <PrintButton />
            </span>
            <p role="status" className="max-w-sm text-right text-[13px] text-muted">
              {saved?.text}
              {saved?.url && (
                <>
                  {" "}
                  <a href={saved.url} target="_blank" rel="noreferrer" className="font-bold text-teal-dark underline underline-offset-2">
                    Open
                  </a>
                </>
              )}
            </p>
          </div>
        </div>
      )}
      {/* Signed in to the demo seed's books: the runtime flags them, and the page (and the paper) must say so. */}
      {[pl, aged, vat, trend].some((r) => r?.sample) && (
        <p className="text-sm font-bold text-warn-ink">SAMPLE — FICTIONAL COMPANY · these are the demo books</p>
      )}
      {state === "error" && error ? <RuntimeErrorNote message={error} title="Couldn't work out the reports" /> : null}
      {state === "live" && (
        <Reports
          pl={pl}
          prev={compare && compare.period === period ? compare.prev : null}
          year={compare && compare.period === period ? compare.year : null}
          aged={aged}
          vat={vat}
          trend={trend}
        />
      )}
    </div>
  );
}
