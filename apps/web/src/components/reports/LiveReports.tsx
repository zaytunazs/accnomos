"use client";

import { useEffect, useState, type ReactNode } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { getMsal, msalConfigured } from "@/lib/msal";
import PrintButton from "@/components/PrintButton";
import SignInCta from "@/components/SignInCta";
import { LoadingSkeleton, RuntimeErrorNote } from "@/components/States";
import VatPeriodPicker from "@/components/vat/VatPeriodPicker";
import {
  runtime,
  ukDate,
  type RtAged,
  type RtAgedReport,
  type RtAgedBucket,
  type RtAgedTable,
  type RtPlSection,
  type RtProfitAndLoss,
  type RtTrend,
  type RtVatSummary,
} from "@/lib/runtime";
import { sampleAged, samplePl, sampleTrend, sampleVat } from "@/lib/sample-reports";
import { usePickedPeriod } from "@/lib/vat-period";
import TrendBars from "./TrendBars";

const BUCKETS: RtAgedBucket[] = ["0-30", "31-60", "61-90", "90+"];
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

function ProfitAndLoss({ pl }: { pl: RtProfitAndLoss }) {
  const loss = pl.net_profit_pence < 0;
  return (
    <section aria-labelledby="pl-heading" className={card}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="pl-heading" className="text-lg font-extrabold">
          Profit and loss · {pl.label} · {ukDate(pl.start)} – {ukDate(pl.end)}
        </h2>
        <span className="text-sm text-muted">
          {pl.entries} approved {pl.entries === 1 ? "entry" : "entries"} · calculated by code
        </span>
      </div>
      <p className="mt-1 text-[13px] text-muted">{pl.basis}</p>
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

function AgedTable({ title, hint, table }: { title: string; hint: string; table: RtAgedTable }) {
  return (
    <section aria-label={title} className={`${card} min-w-0 flex-1`}>
      <h3 className="text-[15px] font-extrabold">{title}</h3>
      <p className="text-[13px] text-muted">{hint}</p>
      {table.rows.length === 0 ? (
        <p className="mt-3 text-sm font-semibold text-muted">Nothing unpaid.</p>
      ) : (
        <Scroll label={`${title} table`}>
          <table className="w-full min-w-[480px] border-collapse tabular-nums">
            <thead className="border-b border-border">
              <tr>
                <th scope="col" className={th}>Name</th>
                {BUCKETS.map((b) => <th key={b} scope="col" className={`${th} text-right`}>{b} days</th>)}
                <th scope="col" className={`${th} text-right`}>Total</th>
              </tr>
            </thead>
            <tbody>
              {table.rows.map((r) => (
                <tr key={r.contact_id} className="border-b border-border">
                  <th scope="row" className={`${td} text-left font-semibold`}>{r.name}</th>
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
    <section aria-labelledby="trend-heading" className={card}>
      <h2 id="trend-heading" className="text-lg font-extrabold">Last 12 months</h2>
      <p className="mb-3 text-[13px] text-muted">Each month&apos;s net is its net profit, from the same accounts as the profit and loss.</p>
      <TrendBars months={trend.months} />
      <details className="mt-3">
        <summary className="cursor-pointer text-[14px] font-bold text-teal-dark">Show the figures as a table</summary>
        <Scroll label="Monthly figures table">
          <table className="w-full min-w-[420px] border-collapse tabular-nums">
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
      </details>
    </section>
  );
}

function VatSummary({ vat }: { vat: RtVatSummary }) {
  return (
    <section aria-labelledby="vat-summary-heading" className={card}>
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

function Reports({ pl, aged, vat, trend }: { pl: RtProfitAndLoss | null; aged: RtAged | null; vat: RtVatSummary | null; trend: RtTrend | null }) {
  return (
    <div className="flex flex-col gap-6">
      {pl ? <ProfitAndLoss pl={pl} /> : <LoadingSkeleton lines={6} label="Working out the profit and loss…" />}
      {trend && <Trend trend={trend} />}
      {aged && (
        <section aria-labelledby="aged-heading" className="flex flex-col gap-3">
          <h2 id="aged-heading" className="text-lg font-extrabold">Aged balances · at {ukDate(aged.as_of)}</h2>
          <div className="flex flex-col gap-4 min-[1000px]:flex-row">
            <AgedTable title="Debtors" hint="Customers who owe you: sales invoices with no bank payment matched, by age from the invoice date." table={aged.debtors} />
            <AgedTable title="Creditors" hint="Suppliers you owe: bills on account with no bank payment matched, by age from the bill date." table={aged.creditors} />
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
  const [aged, setAged] = useState<RtAgedReport | null>(null);
  const [vat, setVat] = useState<RtVatSummary | null>(null);
  const [trend, setTrend] = useState<RtTrend | null>(null);
  const [exporting, setExporting] = useState(false);
  const [saved, setSaved] = useState<{ text: string; url: string | null } | null>(null);
  const picked = usePickedPeriod();
  const span = picked ? { start: picked.start, end: picked.end } : null;
  const period = picked?.period ?? null;
  const pl = loaded && loaded.period === period ? loaded.pl : null; // null while the picked period loads

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
    runtime.reports.pl(account, span).then(
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

  async function exportToOneDrive() {
    if (!account) return;
    setExporting(true);
    setSaved(null);
    try {
      const r = await runtime.reports.export(account, { report: "all", ...(span ? { from: span.start, to: span.end } : {}) });
      setSaved({ text: `Saved to ${r.path} in your OneDrive (${r.sheets.filter((s) => s !== "About").join(", ")}).`, url: r.web_url });
    } catch (e) {
      setSaved({ text: `Could not save the report: ${(e as Error).message}`, url: null });
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
            <span>A mock-up of a business&apos;s reports ({samplePl.label}). Fictional figures.</span>
            <SignInCta />
          </p>
          <PrintButton />
        </div>
        {/* Paper only: the banner does not print, and a printed sample must still say what it is. */}
        <p className="hidden text-sm font-bold print:block">SAMPLE — FICTIONAL COMPANY · fictional figures</p>
        <Reports pl={samplePl} aged={sampleAged} vat={sampleVat} trend={sampleTrend} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {account && (
        <div className="flex flex-wrap items-start justify-between gap-3 print:hidden">
          <VatPeriodPicker account={account} />
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
      {state === "live" && <Reports pl={pl} aged={aged} vat={vat} trend={trend} />}
    </div>
  );
}
