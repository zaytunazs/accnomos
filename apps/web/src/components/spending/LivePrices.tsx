"use client";

import { useCallback, useEffect, useState } from "react";
import { errorText, useAccount } from "@/components/jobs/useAccount";
import SignInCta from "@/components/SignInCta";
import { LoadingSkeleton, RuntimeErrorNote } from "@/components/States";
import { runtime, type RtLiveOffer, type RtPriceGroup, type RtPriceReport, type RtSearchStatus } from "@/lib/runtime";
import { money, perMeasure, ukDay } from "@/lib/spending";

const card = "rounded-2xl border border-border bg-white p-4 sm:p-5";
const quiet = "h-10 rounded-xl border border-border bg-white px-4 text-[14px] font-bold hover:bg-ground disabled:opacity-60";

/** Live price search on or off, said plainly. Off is the default in this version. */
export function SearchBanner({ status }: { status: RtSearchStatus }) {
  return (
    <p
      role="note"
      aria-label="Live price search"
      className={`rounded-xl border px-4 py-2.5 text-[14px] leading-6 ${
        status.enabled ? "border-teal bg-teal-tint text-teal-dark" : "border-border bg-ground text-muted"
      }`}
    >
      <strong>{status.enabled ? `Live price search is on (${status.provider})` : "Live price search is off"}.</strong>{" "}
      {status.enabled ? status.note : "Only prices from receipts and bills in your books are shown."}
    </p>
  );
}

/** One live offer, always with where and when it was found. */
export function LiveOfferRow({ offer }: { offer: RtLiveOffer }) {
  const when = new Date(offer.retrieved_at).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/London" });
  return (
    <li className="flex flex-wrap justify-between gap-x-3 gap-y-0.5 py-1.5">
      <span className="min-w-0">
        <a href={offer.url} target="_blank" rel="noopener noreferrer" className="font-semibold text-teal-dark hover:underline">
          {offer.title}
        </a>{" "}
        <span className="text-muted">
          · {offer.supplier} · {money(offer.unit_price)}
          {offer.pack > 1 ? ` for ${offer.pack}` : ""}
        </span>
        <span className="block text-[12px] text-muted">
          Live offer from {offer.source}, {when} · {offer.note}
        </span>
      </span>
    </li>
  );
}

function Group({ g }: { g: RtPriceGroup }) {
  return (
    <li className={card}>
      <article aria-label={g.name}>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-[16px] font-extrabold">{g.name}</h3>
          {g.saving && (
            <p className="text-[14px] font-bold text-teal-dark">
              Could save {money(g.saving.per_year)} a year
            </p>
          )}
        </div>
        <p className="mt-1 text-[13px] text-muted">
          {g.observations} purchase{g.observations === 1 ? "" : "s"} · {g.suppliers.join(", ")}
          {g.match === "equivalent" && ` · ${g.keys.length} names joined (${g.joined_by.join(", ") || "same product"})`}
        </p>
        <dl className="mt-2 grid grid-cols-1 gap-x-4 gap-y-1 text-[14px] sm:grid-cols-2">
          <div>
            <dt className="text-muted">Last paid</dt>
            <dd>
              {money(g.latest.unit_price)} at {g.latest.supplier}, {ukDay(g.latest.date)}
            </dd>
          </div>
          <div>
            <dt className="text-muted">Lowest in your books</dt>
            <dd>
              {perMeasure(g.cheapest.per_measure, g.measure_word)} · {g.cheapest.supplier}, {ukDay(g.cheapest.date)}
            </dd>
          </div>
        </dl>
        {g.saving && <p className="mt-2 rounded-xl bg-teal-tint px-3 py-2 text-[14px] leading-6 text-teal-dark">{g.saving.explanation}</p>}
        {g.by_supplier.length > 1 && (
          <ul className="mt-2 divide-y divide-border text-[14px]" aria-label={`Prices by supplier for ${g.name}`}>
            {g.by_supplier.map((p) => (
              <li key={p.supplier} className="flex justify-between gap-3 py-1">
                <span className="min-w-0">
                  {p.supplier} <span className="text-muted">· {p.description}</span>
                </span>
                <span className="shrink-0 tabular-nums">{perMeasure(p.per_measure, g.measure_word)}</span>
              </li>
            ))}
          </ul>
        )}
        {g.live_offers.length > 0 && (
          <div className="mt-2">
            <p className="text-[12px] font-bold uppercase tracking-wide text-muted">Live offers (not from your books)</p>
            <ul className="divide-y divide-border text-[14px]">
              {g.live_offers.map((o) => (
                <LiveOfferRow key={o.url} offer={o} />
              ))}
            </ul>
            {g.live_saving && <p className="mt-1 text-[13px] text-muted">{g.live_saving.explanation}</p>}
          </div>
        )}
      </article>
    </li>
  );
}

/** /prices: cheaper options from the user's own purchase history. */
export default function LivePrices() {
  const account = useAccount();
  const [report, setReport] = useState<RtPriceReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!account) return;
    try {
      setReport(await runtime.prices(account));
      setError(null);
    } catch (e) {
      if ((e as Error).message !== "redirecting for consent") setError(errorText(e));
    }
  }, [account]);

  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  async function run(key: string, fn: () => Promise<RtPriceReport | unknown>) {
    setBusy(key);
    setError(null);
    try {
      const out = await fn();
      if (out && typeof out === "object" && "groups" in out) setReport(out as RtPriceReport);
      else await load();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(null);
    }
  }

  if (account === undefined) return <LoadingSkeleton lines={3} label="Loading your prices…" />;
  if (account === null)
    return (
      <div className={`${card} flex flex-col items-start gap-3`}>
        <p className="text-[15px] leading-7 text-muted">
          Once your OneDrive is connected, this page compares what you paid for the same item at different times and
          from different suppliers in your own books, and what buying at the lowest price would save at your usual volume.
        </p>
        <SignInCta />
      </div>
    );
  if (error && !report) return <RuntimeErrorNote message={error} onRetry={() => void load()} />;
  if (!report) return <LoadingSkeleton lines={3} label="Reading your receipts' line items…" />;

  return (
    <div className="flex flex-col gap-4">
      <SearchBanner status={report.web_search} />
      <p className="text-[14px] leading-6 text-muted">{report.coverage_note}</p>
      {error && <RuntimeErrorNote message={error} />}
      <section aria-labelledby="prices-total" className={card}>
        <h2 id="prices-total" className="text-lg font-extrabold tracking-tight">
          Potential saving
        </h2>
        <p className="mt-1 text-3xl font-extrabold tracking-tight tabular-nums">{money(report.total_saving_per_year)} a year</p>
        <p className="text-[13px] text-muted">
          From {report.lines_read} line items since {ukDay(report.since)}, if you had always paid the lowest price in your books.
          Worked out by code.
        </p>
      </section>
      {report.possible_matches.length > 0 && (
        <section aria-labelledby="prices-matches" className={card}>
          <h2 id="prices-matches" className="text-lg font-extrabold tracking-tight">
            Same product?
          </h2>
          <p className="mt-1 text-[14px] text-muted">
            These have different names but might be the same thing. Only a yes from you, or your AI together with code&apos;s
            size rules, joins them.
          </p>
          <ul className="mt-2 divide-y divide-border">
            {report.possible_matches.map((m) => (
              <li key={`${m.a}|${m.b}`} className="flex flex-col gap-2 py-2 text-[14px]">
                <span>
                  <strong>{m.a_name}</strong> and <strong>{m.b_name}</strong>
                  <span className="block text-[13px] text-muted">
                    Code: {m.rules_ok ? "could be the same" : "not the same"} ({m.rules_note})
                    {m.ai_says_same !== null && ` · your AI says ${m.ai_says_same ? "same" : "different"}`}
                  </span>
                </span>
                <span className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    className={quiet}
                    disabled={busy !== null}
                    onClick={() => void run(`yes-${m.a}`, () => runtime.decideMatch(account, { a: m.a, b: m.b, same: true }))}
                  >
                    Same product
                  </button>
                  <button
                    type="button"
                    className={quiet}
                    disabled={busy !== null}
                    onClick={() => void run(`no-${m.a}`, () => runtime.decideMatch(account, { a: m.a, b: m.b, same: false }))}
                  >
                    Not the same
                  </button>
                </span>
              </li>
            ))}
          </ul>
          <button
            type="button"
            className={`${quiet} mt-2`}
            disabled={busy !== null}
            onClick={() => void run("ai", () => runtime.suggestPrices(account))}
          >
            {busy === "ai" ? "Asking your AI…" : "Ask your AI which match"}
          </button>
        </section>
      )}
      {report.ai_note && (
        <p className="rounded-xl bg-ground px-4 py-2 text-[13px] text-muted" role="status">
          {report.ai_note}
        </p>
      )}
      {report.groups.length === 0 ? (
        <p className={`${card} text-[15px] text-muted`}>No line items in your approved receipts yet. Approve a few in Review and come back.</p>
      ) : (
        <ul className="flex flex-col gap-3" aria-label="Items">
          {report.groups.map((g) => (
            <Group key={g.id} g={g} />
          ))}
        </ul>
      )}
    </div>
  );
}
