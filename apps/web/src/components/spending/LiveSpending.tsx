"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Markdown } from "@/components/ask/AnswerCard";
import { errorText, todayIso, useAccount } from "@/components/jobs/useAccount";
import SignInCta from "@/components/SignInCta";
import { LoadingSkeleton, RuntimeErrorNote } from "@/components/States";
import { runtime, type RtSpendRow, type RtSpending } from "@/lib/runtime";
import { change, money, spanFor, ukDay, type PeriodChoice, type Span } from "@/lib/spending";

const CHOICES: { id: PeriodChoice; label: string }[] = [
  { id: "month", label: "This month" },
  { id: "last_month", label: "Last month" },
  { id: "quarter", label: "This quarter" },
  { id: "custom", label: "Custom" },
];

const card = "rounded-2xl border border-border bg-white p-4 sm:p-5";
const input = "h-11 rounded-xl border border-border bg-white px-3 text-[15px]";

function Rows({ title, rows, previousLabel }: { title: string; rows: RtSpendRow[]; previousLabel: string }) {
  const id = `spend-${title.toLowerCase().replace(/\W+/g, "-")}`;
  return (
    <section aria-labelledby={id} className={card}>
      <h2 id={id} className="text-lg font-extrabold tracking-tight">
        {title}
      </h2>
      {rows.length === 0 ? (
        <p className="mt-2 text-sm text-muted">Nothing in this period.</p>
      ) : (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-[14px]" aria-label={title}>
            <thead>
              <tr className="text-left text-[12px] font-bold uppercase tracking-wide text-muted">
                <th className="py-1.5 pr-2 font-bold">Name</th>
                <th className="py-1.5 pr-2 text-right font-bold">Before VAT</th>
                <th className="py-1.5 text-right font-bold">vs {previousLabel}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((r) => (
                <tr key={r.name}>
                  <td className="py-1.5 pr-2">
                    {r.name} <span className="text-muted">· {r.count}</span>
                  </td>
                  <td className="py-1.5 pr-2 text-right tabular-nums">{money(r.net)}</td>
                  <td className="py-1.5 text-right tabular-nums text-muted">{change(r.change_vs_previous, r.change_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** /spending: where the money went, for a month, a quarter or any span. Figures by code; words by AI, checked. */
export default function LiveSpending() {
  const account = useAccount();
  const [choice, setChoice] = useState<PeriodChoice>("month");
  const [custom, setCustom] = useState<Span>(() => spanFor("month", todayIso()));
  const [data, setData] = useState<RtSpending | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    async (span: Span) => {
      if (!account) return;
      setBusy(true);
      setError(null);
      try {
        setData(await runtime.spending(account, span));
      } catch (e) {
        if ((e as Error).message !== "redirecting for consent") setError(errorText(e));
      } finally {
        setBusy(false);
      }
    },
    [account],
  );

  useEffect(() => {
    if (account && choice !== "custom") queueMicrotask(() => void load(spanFor(choice, todayIso())));
  }, [account, choice, load]);

  if (account === undefined) return <LoadingSkeleton lines={3} label="Loading your spending…" />;
  if (account === null)
    return (
      <div className={`${card} flex flex-col items-start gap-3`}>
        <p className="text-[15px] leading-7 text-muted">
          Once your OneDrive is connected, this page shows where your money went: by category, by supplier and by item,
          against the period before, with your regular costs and any unusual one-offs.
        </p>
        <SignInCta />
      </div>
    );

  const f = data?.facts;
  const t = f?.this_period;
  return (
    <div className="flex flex-col gap-4">
      <div role="radiogroup" aria-label="Period" className="flex flex-wrap gap-2">
        {CHOICES.map((c) => (
          <button
            key={c.id}
            type="button"
            role="radio"
            aria-checked={choice === c.id}
            onClick={() => setChoice(c.id)}
            className={`h-10 rounded-full border px-4 text-[14px] font-bold ${
              choice === c.id ? "border-teal bg-teal text-white" : "border-border bg-white text-ink hover:bg-ground"
            }`}
          >
            {c.label}
          </button>
        ))}
      </div>
      {choice === "custom" && (
        <form
          aria-label="Custom period"
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void load(custom);
          }}
        >
          <label className="flex flex-col text-[13px] font-bold text-muted">
            From
            <input type="date" className={input} value={custom.start} onChange={(e) => setCustom({ ...custom, start: e.target.value })} required />
          </label>
          <label className="flex flex-col text-[13px] font-bold text-muted">
            To
            <input type="date" className={input} value={custom.end} onChange={(e) => setCustom({ ...custom, end: e.target.value })} required />
          </label>
          <button type="submit" disabled={busy} className="h-11 rounded-xl bg-teal px-5 text-[15px] font-bold text-white disabled:opacity-60">
            Show
          </button>
        </form>
      )}
      {error && <RuntimeErrorNote message={error} />}
      {!data && !error && <LoadingSkeleton lines={3} label="Adding up your spending…" />}
      {data && f && t && (
        <>
          <section aria-labelledby="spend-summary" className={card} aria-busy={busy}>
            <h2 id="spend-summary" className="text-lg font-extrabold tracking-tight">
              {t.label}
            </h2>
            <div className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1">
              <p className="text-3xl font-extrabold tracking-tight tabular-nums">{money(t.spent)}</p>
              <p className="text-[14px] text-muted">
                before VAT · {t.purchases} purchase{t.purchases === 1 ? "" : "s"} · {change(f.change.spent_vs_previous, f.change.spent_change_pct)} on{" "}
                {f.previous_period.label}
              </p>
            </div>
            <div className="mt-3 text-[15px] leading-7">
              <Markdown md={data.summary_md} />
            </div>
            <p className="mt-2 text-[12px] font-semibold text-muted">
              {data.summary_by === "model"
                ? `Numbers by code · summary by ${data.model}, every figure checked against your books`
                : `Numbers and summary by code${data.fallback_reason ? `: ${data.fallback_reason}` : ""}`}
            </p>
          </section>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <Rows title="By category" rows={t.by_category} previousLabel={f.previous_period.label} />
            <Rows title="By supplier" rows={t.by_supplier} previousLabel={f.previous_period.label} />
            <section aria-labelledby="spend-items" className={card}>
              <h2 id="spend-items" className="text-lg font-extrabold tracking-tight">
                Top items
              </h2>
              {t.top_items.length === 0 ? (
                <p className="mt-2 text-sm text-muted">No line items read from receipts in this period.</p>
              ) : (
                <ul className="mt-2 divide-y divide-border text-[14px]">
                  {t.top_items.map((i) => (
                    <li key={i.item} className="flex justify-between gap-3 py-1.5">
                      <span className="min-w-0">
                        {i.item} <span className="text-muted">× {i.quantity} · {i.suppliers.join(", ")}</span>
                      </span>
                      <span className="shrink-0 tabular-nums">{money(i.net)}</span>
                    </li>
                  ))}
                </ul>
              )}
              <p className="mt-2 text-[12px] text-muted">
                From the line items of {t.with_line_items} of {t.purchases} purchases (entries posted by hand have none).
              </p>
            </section>
            <section aria-labelledby="spend-regular" className={card}>
              <h2 id="spend-regular" className="text-lg font-extrabold tracking-tight">
                Regular costs
              </h2>
              {f.recurring.length === 0 ? (
                <p className="mt-2 text-sm text-muted">No subscriptions, utilities or monthly suppliers spotted yet.</p>
              ) : (
                <ul className="mt-2 divide-y divide-border text-[14px]">
                  {f.recurring.map((r) => (
                    <li key={r.supplier} className="flex justify-between gap-3 py-1.5">
                      <span className="min-w-0">
                        {r.supplier} <span className="text-muted">· {r.kind} · seen in {r.months_seen} months</span>
                      </span>
                      <span className="shrink-0 tabular-nums">{money(r.usual_month)} a month</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section aria-labelledby="spend-unusual" className={`${card} md:col-span-2`}>
              <h2 id="spend-unusual" className="text-lg font-extrabold tracking-tight">
                Unusual one-offs
              </h2>
              {f.unusual.length === 0 ? (
                <p className="mt-2 text-sm text-muted">Nothing out of the ordinary.</p>
              ) : (
                <ul className="mt-2 divide-y divide-border text-[14px]">
                  {f.unusual.map((u) => (
                    <li key={u.source} className="flex justify-between gap-3 py-1.5">
                      <span className="min-w-0">
                        {ukDay(u.date)} · {u.supplier} <span className="text-muted">· {u.why} ({u.times_usual_purchase}×)</span>
                      </span>
                      <span className="shrink-0 tabular-nums">{money(u.net)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
          <p className="text-[14px] text-muted">
            Approved purchases only, before VAT. See <Link href="/prices" className="font-bold text-teal-dark hover:underline">cheaper options</Link> from
            your own history, or your <Link href="/shopping" className="font-bold text-teal-dark hover:underline">shopping list</Link>.
          </p>
        </>
      )}
    </div>
  );
}
