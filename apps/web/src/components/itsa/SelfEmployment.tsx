"use client";

import { useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import Explain from "@/components/Explain";
import { getMsal, msalConfigured } from "@/lib/msal";
import {
  clientFacts,
  disconnect,
  finishConnect,
  HmrcAuthError,
  loadTokens,
  RelayError,
  startConnect,
  takeCallback,
  type RelayResult,
} from "@/lib/hmrc";
import {
  cleanNino,
  FINAL_DECLARATION,
  gbp,
  hmrcPounds,
  itsa,
  itsaBooks,
  NINO_RE,
  rememberNino,
  savedNino,
  taxYearOf,
  type ItsaBusiness,
  type ItsaObligationDetail,
  type ReportFormat,
  type ReportKind,
  type RtItsaReceipt,
  type RtReport,
  type RtSeSummary,
} from "@/lib/itsa";

type Phase = "loading" | "hidden" | "disconnected" | "connecting" | "connected";

const btn = "h-11 whitespace-nowrap rounded-xl px-5 text-[15px] font-bold disabled:cursor-not-allowed disabled:opacity-50";
const primary = `${btn} bg-teal text-white hover:bg-teal-dark`;
const secondary = `${btn} border border-border bg-white hover:bg-ground`;
const card = "rounded-2xl border border-border bg-white p-5 sm:p-6";
/** HMRC: "wait at least 5 seconds before calling the retrieval endpoint" (Individual Calculations 8.0, Trigger). */
const CALC_WAIT_MS = 5000;

const day = (iso: string) => {
  const d = new Date(`${iso}T00:00:00`);
  return isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
};
const todayIso = () => new Date().toISOString().slice(0, 10);
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function Downloads({ account, kind, query, label }: { account: AccountInfo; kind: ReportKind; query: Record<string, string>; label: string }) {
  const [err, setErr] = useState<string | null>(null);
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className="font-semibold text-muted">Download {label}:</span>
      {(["pdf", "csv", "xlsx"] as ReportFormat[]).map((f) => (
        <button
          key={f}
          type="button"
          className="rounded-lg border border-border px-3 py-1 font-bold hover:bg-ground"
          onClick={() => itsaBooks.download(account, kind, query, f).catch((e: Error) => setErr(e.message))}
        >
          {f.toUpperCase()}
        </button>
      ))}
      {err && <span role="alert" className="text-warn-ink">{err}</span>}
    </div>
  );
}

function ReportTables({ report, label }: { report: RtReport; label: string }) {
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[13px] font-bold text-muted">{report.source}</p>
      {report.sections.map((s) => (
        <table key={s.title} aria-label={`${label}: ${s.title}`} className="w-full text-sm">
          <caption className="text-left font-bold">{s.title}</caption>
          <tbody>
            {s.rows.map((r, i) => (
              <tr key={i} className="border-t border-border">
                {r.map((v, j) => (
                  <td key={j} className={`py-1 pr-3 ${s.money.includes(j) ? "text-right tabular-nums" : ""}`}>
                    {v === null ? "—" : s.money.includes(j) && typeof v === "number" ? hmrcPounds(v) : String(v)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      ))}
      {report.notes.map((n) => (
        <p key={n} className="text-[13px] text-muted">{n}</p>
      ))}
    </div>
  );
}

/** /self-employment: MTD Income Tax quarterly updates from the books, through HMRC's sandbox. */
export default function SelfEmployment() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nino, setNino] = useState("");
  const [scenario, setScenario] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [businesses, setBusinesses] = useState<ItsaBusiness[] | null>(null);
  const [businessId, setBusinessId] = useState<string | null>(null);
  const [taxYear, setTaxYear] = useState(() => taxYearOf(todayIso()));
  const [obligations, setObligations] = useState<ItsaObligationDetail[] | null>(null);
  const [periodEnd, setPeriodEnd] = useState<string | null>(null);
  const [summary, setSummary] = useState<RtSeSummary | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [submitted, setSubmitted] = useState<{ env: RelayResult<null>; path: string | null; matches?: boolean; note?: string } | null>(null);
  const [calc, setCalc] = useState<{ id: string; report: RtReport | null; note?: string } | null>(null);
  const [declared, setDeclared] = useState(false);
  const [finalDone, setFinalDone] = useState<string | null>(null);
  const [receipts, setReceipts] = useState<RtItsaReceipt[]>([]);

  const ninoOk = NINO_RE.test(cleanNino(nino));
  const facts = () => clientFacts(account?.homeAccountId ?? "");

  useEffect(() => {
    const cb = takeCallback(); // before any await: nothing else may see or re-use the code
    (async () => {
      try {
        if (!msalConfigured()) return setPhase("hidden");
        const msal = await getMsal();
        await msal.handleRedirectPromise().catch(() => null);
        const acct: AccountInfo | undefined = msal.getActiveAccount() ?? msal.getAllAccounts()[0];
        if (!acct) return setPhase("hidden");
        setAccount(acct);
        setNino(savedNino());
        if (cb && "error" in cb) {
          disconnect("itsa");
          setError(`HMRC sign-in didn't finish: ${cb.description || cb.error}`);
        } else if (cb) {
          setPhase("connecting");
          await finishConnect(cb, "itsa").catch((e: Error) => setError(e.message));
        }
        setPhase(loadTokens("itsa") ? "connected" : "disconnected");
      } catch (e) {
        setError((e as Error).message);
        setPhase("disconnected");
      }
    })();
  }, []);

  // The receipts saved for this tax year, so earlier updates are listed with their downloads.
  useEffect(() => {
    if (!account) return;
    let stale = false;
    itsaBooks.receipts(account, taxYear).then((r) => !stale && setReceipts(r.receipts), () => !stale && setReceipts([]));
    return () => {
      stale = true;
    };
  }, [account, taxYear, submitted, calc, finalDone]);

  // The figures for the picked obligation's end date (cumulative from 6 April), worked out by code.
  useEffect(() => {
    if (!account || !periodEnd) return;
    let stale = false;
    itsaBooks.summary(account, taxYear, periodEnd).then(
      (s) => {
        if (stale) return;
        setSummary(s);
        setConfirmed(false); // a tick is for the figures shown, not for new ones
      },
      (e: Error) => !stale && setError(e.message),
    );
    return () => {
      stale = true;
    };
  }, [account, taxYear, periodEnd]);

  function fail(e: unknown) {
    if (e instanceof HmrcAuthError) setPhase("disconnected");
    setError((e as Error).message);
  }

  async function run(what: string, f: () => Promise<void>) {
    setError(null);
    setBusy(what);
    try {
      await f();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  }

  async function connect() {
    setError(null);
    setPhase("connecting");
    try {
      await startConnect("itsa");
    } catch (e) {
      setError((e as Error).message);
      setPhase("disconnected");
    }
  }

  function signOut() {
    disconnect("itsa");
    setBusinesses(null);
    setObligations(null);
    setSummary(null);
    setPhase("disconnected");
  }

  const loadBusinesses = () =>
    run("businesses", async () => {
      const n = cleanNino(nino);
      rememberNino(n);
      const res = await itsa.businesses(n, await facts(), scenario);
      const se = res.hmrc.listOfBusinesses.filter((b) => b.typeOfBusiness === "self-employment");
      setBusinesses(se);
      if (se.length === 1) await chooseBusiness(se[0].businessId);
    });

  async function chooseBusiness(id: string, year = taxYear) {
    setBusinessId(id);
    setSubmitted(null);
    const [y] = year.split("-").map(Number);
    const res = await itsa.obligations(cleanNino(nino), await facts(), { from: `${y}-04-06`, to: `${y + 1}-04-05`, business_id: id }, scenario);
    const details = res.hmrc.obligations.filter((o) => o.businessId === id).flatMap((o) => o.obligationDetails);
    details.sort((a, b) => a.periodEndDate.localeCompare(b.periodEndDate));
    setObligations(details);
    setPeriodEnd(details.find((d) => d.status === "open")?.periodEndDate ?? null);
  }

  const submit = () =>
    run("submit", async () => {
      if (!summary || !businessId || !account) return;
      const n = cleanNino(nino);
      const confirmedAt = new Date().toISOString();
      const env = await itsa.submit(n, businessId, taxYear, await facts(), summary.hmrc_body, scenario);
      try {
        const saved = await itsaBooks.saveReceipt(account, {
          kind: "cumulative", tax_year: taxYear, nino: n, business_id: businessId, period_end: summary.period_end,
          sent: summary.hmrc_body, hmrc: env, confirmed_at: confirmedAt,
        });
        setSubmitted({ env, path: saved.path, matches: saved.matches_books });
      } catch (e) {
        setSubmitted({ env, path: null, note: `HMRC has the update, but the receipt couldn't be saved to your books: ${(e as Error).message}. Note the correlation ID below.` });
      }
      setConfirmed(false);
    });

  async function calculate(type: "in-year" | "intent-to-finalise") {
    if (!account) return;
    const n = cleanNino(nino);
    const t = await itsa.trigger(n, taxYear, await facts(), type, scenario);
    const id = t.hmrc.calculationId;
    setCalc({ id, report: null, note: "HMRC is working it out…" });
    await sleep(CALC_WAIT_MS);
    let got: RelayResult<unknown> | null = null;
    for (let i = 0; i < 3 && !got; i++) {
      try {
        got = await itsa.calculation(n, taxYear, id, await facts(), scenario);
      } catch (e) {
        if (i === 2 || !(e instanceof RelayError && e.status === 404)) throw e; // 404: HMRC is still calculating
        await sleep(CALC_WAIT_MS);
      }
    }
    if (!got) return;
    await itsaBooks.saveReceipt(account, { kind: "calculation", tax_year: taxYear, nino: n, calculation_id: id, hmrc: got });
    const report = await itsaBooks.report(account, "calculation", { tax_year: taxYear, calculation_id: id });
    setCalc({ id, report });
    setDeclared(false);
  }

  const declare = () =>
    run("final", async () => {
      if (!calc || !account) return;
      const n = cleanNino(nino);
      const confirmedAt = new Date().toISOString();
      const env = await itsa.finalDeclaration(n, taxYear, calc.id, await facts(), scenario);
      await itsaBooks.saveReceipt(account, {
        kind: "final_declaration", tax_year: taxYear, nino: n, calculation_id: calc.id, hmrc: env,
        confirmed_at: confirmedAt, declaration: FINAL_DECLARATION,
      });
      setFinalDone(env.correlation_id ?? "received");
    });

  if (phase === "loading") return null;
  if (phase === "hidden")
    return <p className="text-[15px] text-muted">Sign in with Microsoft to connect your books, then connect HMRC here.</p>;

  const obligation = obligations?.find((o) => o.periodEndDate === periodEnd) ?? null;
  const yearEnded = todayIso() > `${Number(taxYear.slice(0, 4)) + 1}-04-05`;

  return (
    <div className="flex flex-col gap-6">
      <section aria-labelledby="itsa-hmrc" className={card}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="itsa-hmrc" className="text-lg font-extrabold">HMRC: Making Tax Digital for Income Tax</h2>
          <span className="flex items-center gap-2">
            <span className="rounded-full border border-warn-border bg-warn-bg px-3 py-1 text-[13px] font-bold text-warn-ink">
              Sandbox · test data only
            </span>
            <Explain title="How this works">
              <p>
                This talks to HMRC&apos;s test service, not the live tax system. You sign in on HMRC&apos;s own site with a sandbox
                test user; the access token stays in this browser tab only.
              </p>
              <p>
                Each quarterly update covers the tax year so far (from 6 April), and replaces the one before. The figures are worked
                out by code from the entries you approved. Nothing goes to HMRC until you tick the confirmation and press Submit.
              </p>
              <p>Tax and National Insurance figures shown here are HMRC&apos;s, as HMRC returned them. Accnomos does not work out your tax.</p>
            </Explain>
          </span>
        </div>

        {error && (
          <p role="alert" className="mt-3 rounded-xl border border-warn-border bg-warn-bg p-3 text-sm text-warn-ink">{error}</p>
        )}

        {(phase === "disconnected" || phase === "connecting") && (
          <div className="mt-3">
            <p className="text-[15px] leading-7">
              Sign in with your HMRC (sandbox) test user to see your self-employment obligations and send quarterly updates.
            </p>
            <p className="mt-1 text-sm text-muted">
              HMRC requires fraud-prevention data with each call, the same as for VAT: a random ID for this device, your screen and
              window size, time zone, browser, a hashed ID for your Microsoft account, and your IP address.
            </p>
            <button type="button" onClick={connect} disabled={phase === "connecting"} className={`${primary} mt-4`}>
              {phase === "connecting" ? "Connecting…" : "Connect to HMRC for Income Tax (sandbox)"}
            </button>
          </div>
        )}

        {phase === "connected" && (
          <div className="mt-3 flex flex-col gap-4">
            <div className="flex flex-wrap items-end gap-3">
              <label className="flex flex-col gap-1 text-sm font-semibold">
                National Insurance number
                <input
                  value={nino}
                  onChange={(e) => setNino(e.target.value)}
                  placeholder="e.g. TC663795B"
                  aria-invalid={nino !== "" && !ninoOk}
                  className="h-11 w-48 rounded-xl border border-border px-3 text-[15px] font-normal uppercase"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm font-semibold">
                Tax year
                <select
                  value={taxYear}
                  onChange={(e) => {
                    setTaxYear(e.target.value);
                    setObligations(null);
                    setSummary(null);
                    setPeriodEnd(null);
                    if (businessId) run("obligations", () => chooseBusiness(businessId, e.target.value));
                  }}
                  className="h-11 rounded-xl border border-border px-3 text-[15px] font-normal"
                >
                  {[0, -1].map((k) => {
                    const y = Number(taxYearOf(todayIso()).slice(0, 4)) + k;
                    const ty = `${y}-${String((y + 1) % 100).padStart(2, "0")}`;
                    return <option key={ty} value={ty}>{ty}</option>;
                  })}
                </select>
              </label>
              <button type="button" onClick={loadBusinesses} disabled={!ninoOk || !!busy} className={primary}>
                {busy === "businesses" ? "Asking HMRC…" : "Show my businesses"}
              </button>
              <button type="button" onClick={signOut} className="h-11 text-sm font-bold text-teal-dark underline underline-offset-2">
                Disconnect
              </button>
            </div>

            <details className="text-sm">
              <summary className="cursor-pointer font-semibold text-muted">Advanced: sandbox test scenario</summary>
              <label className="mt-2 flex flex-col gap-1">
                <span className="text-muted">Gov-Test-Scenario (leave empty for HMRC&apos;s default)</span>
                <input value={scenario} onChange={(e) => setScenario(e.target.value)} placeholder="e.g. STATEFUL"
                  className="h-10 w-72 max-w-full rounded-xl border border-border px-3" />
              </label>
            </details>

            {businesses && businesses.length === 0 && (
              <p className="text-sm text-muted">HMRC has no self-employment business for this National Insurance number.</p>
            )}
            {businesses && businesses.length > 0 && (
              <fieldset className="flex flex-col gap-2">
                <legend className="text-sm font-bold">Your self-employment businesses (from HMRC)</legend>
                {businesses.map((b) => (
                  <label key={b.businessId} className="flex items-center gap-2 text-[15px]">
                    <input type="radio" name="business" checked={businessId === b.businessId}
                      onChange={() => run("obligations", () => chooseBusiness(b.businessId))} />
                    {b.tradingName ?? "Unnamed business"} · {b.tradingType ?? "trade not given"} · {b.businessId}
                  </label>
                ))}
              </fieldset>
            )}

            {obligations && (
              <table aria-label="Quarterly obligations" className="w-full text-sm">
                <thead>
                  <tr className="text-left text-muted">
                    <th className="py-1">Update</th><th>Covers</th><th>Due</th><th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {obligations.map((o) => (
                    <tr key={o.periodEndDate} className="border-t border-border">
                      <td className="py-2">
                        {o.status === "open" ? (
                          <input type="radio" name="obligation" aria-label={`Choose the update to ${day(o.periodEndDate)}`}
                            checked={periodEnd === o.periodEndDate} onChange={() => setPeriodEnd(o.periodEndDate)} />
                        ) : null}
                      </td>
                      <td>{day(o.periodStartDate)} to {day(o.periodEndDate)}</td>
                      <td>{day(o.dueDate)}</td>
                      <td>{o.status === "fulfilled" ? `Sent${o.receivedDate ? ` ${day(o.receivedDate)}` : ""}` : "Open"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {obligations && obligations.length === 0 && <p className="text-sm text-muted">HMRC returned no obligations for {taxYear}.</p>}
          </div>
        )}
      </section>

      {account && summary && (
        <section aria-labelledby="itsa-figures" className={card}>
          <h2 id="itsa-figures" className="text-lg font-extrabold">
            Your figures, {day(summary.period_start)} to {day(summary.period_end)}
          </h2>
          <p className="mt-1 text-sm text-muted">Worked out by code from the entries you approved. {summary.basis}</p>
          <table aria-label="Self-employment figures" className="mt-3 w-full text-sm">
            <thead>
              <tr className="text-left text-muted">
                <th className="py-1">Box</th><th>What</th><th className="text-right">Total</th><th className="text-right">Disallowable</th>
              </tr>
            </thead>
            <tbody>
              {summary.figures.map((f) => (
                <tr key={f.key} className="border-t border-border align-top">
                  <td className="py-2">{f.box}</td>
                  <td className="py-2">
                    {f.lines.length ? (
                      <details>
                        <summary className="cursor-pointer">{f.label} <span className="text-muted">({f.lines.length} {f.lines.length === 1 ? "entry" : "entries"})</span></summary>
                        <ul aria-label={`Entries behind ${f.label}`} className="mt-1 flex flex-col gap-1 text-[13px] text-muted">
                          {f.lines.map((c, i) => (
                            <li key={`${c.event_id}-${i}`}>
                              {day(c.date)} · {c.counterparty ?? c.kind} · {c.account} · {gbp(c.pence)}{c.disallowable ? " · disallowable" : ""}
                            </li>
                          ))}
                        </ul>
                      </details>
                    ) : (
                      f.label
                    )}
                  </td>
                  <td className="py-2 text-right tabular-nums">{gbp(f.pence)}</td>
                  <td className="py-2 text-right tabular-nums">{f.group === "expenses" ? gbp(f.disallowable_pence) : ""}</td>
                </tr>
              ))}
            </tbody>
            <tfoot className="font-bold">
              <tr className="border-t-2 border-ink"><td /><td className="py-1">Income</td><td className="text-right">{gbp(summary.income_pence)}</td><td /></tr>
              <tr><td /><td className="py-1">Expenses</td><td className="text-right">{gbp(summary.expenses_pence)}</td><td className="text-right">{gbp(summary.disallowable_pence)}</td></tr>
              <tr><td /><td className="py-1">Profit (income less allowable expenses)</td><td className="text-right">{gbp(summary.net_profit_pence)}</td><td /></tr>
            </tfoot>
          </table>
          {summary.warnings.map((w) => (
            <p key={w} className="mt-2 text-[13px] text-muted">{w}</p>
          ))}
          <div className="mt-3">
            <Downloads account={account} kind="sa103" query={{ tax_year: summary.tax_year, period_end: summary.period_end }} label="this summary" />
          </div>

          {phase === "connected" && businessId && obligation?.status === "open" && (
            <div className="mt-4 border-t border-border pt-4">
              {summary.blockers.map((b) => (
                <p key={b} role="alert" className="mb-2 text-sm font-bold text-warn-ink">{b}</p>
              ))}
              <label className="flex items-start gap-2 text-[15px]">
                <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} className="mt-1" />
                <span>
                  I have checked these figures. Send them to HMRC (sandbox) as my update for {day(summary.period_start)} to{" "}
                  {day(summary.period_end)}.
                </span>
              </label>
              <button type="button" onClick={submit} disabled={!confirmed || !summary.can_submit || !!busy} className={`${primary} mt-3`}>
                {busy === "submit" ? "Sending…" : "Submit update to HMRC"}
              </button>
            </div>
          )}
          {submitted && (
            <div role="status" aria-label="Update receipt" className="mt-4 rounded-xl border border-teal bg-teal-tint p-4 text-sm">
              <p className="font-bold">HMRC accepted the update.</p>
              <p>HMRC correlation ID: {submitted.env.correlation_id ?? "not given"}</p>
              {submitted.path && <p>Saved to your books: {submitted.path}</p>}
              {submitted.matches === false && <p className="font-bold text-warn-ink">What was sent differs from the books now. Check the entries.</p>}
              {submitted.note && <p className="font-bold text-warn-ink">{submitted.note}</p>}
              {submitted.env.fraud_headers_missing.length > 0 && (
                <p className="text-muted">Fraud-prevention data not available: {submitted.env.fraud_headers_missing.join(", ")}</p>
              )}
              {submitted.path && (
                <div className="mt-2">
                  <Downloads account={account} kind="quarterly" query={{ tax_year: taxYear, path: submitted.path }} label="the update as sent" />
                </div>
              )}
            </div>
          )}
        </section>
      )}

      {account && phase === "connected" && ninoOk && businesses && (
        <section aria-labelledby="itsa-calc" className={card}>
          <h2 id="itsa-calc" className="text-lg font-extrabold">HMRC&apos;s tax calculation</h2>
          <p className="mt-1 text-sm text-muted">
            HMRC works out an estimate of your Income Tax and National Insurance from what it holds. These are HMRC&apos;s figures, not
            Accnomos&apos;s.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" className={secondary} disabled={!!busy} onClick={() => run("calc", () => calculate("in-year"))}>
              {busy === "calc" ? "HMRC is working it out…" : "Ask HMRC for a calculation"}
            </button>
          </div>
          {calc?.report && (
            <div className="mt-4">
              <ReportTables report={calc.report} label="HMRC calculation" />
              <div className="mt-2">
                <Downloads account={account} kind="calculation" query={{ tax_year: taxYear, calculation_id: calc.id }} label="HMRC's calculation" />
              </div>
            </div>
          )}

          <details className="mt-4 border-t border-border pt-4" open={yearEnded}>
            <summary className="cursor-pointer font-bold">End of the tax year: final declaration</summary>
            <p className="mt-2 text-sm text-muted">
              After the tax year ends and every update is in, ask HMRC for the final calculation, read it, then agree to HMRC&apos;s
              declaration. {yearEnded ? "" : `The ${taxYear} tax year has not ended yet, so HMRC will normally refuse.`}
            </p>
            <button type="button" className={`${secondary} mt-3`} disabled={!!busy} onClick={() => run("calc", () => calculate("intent-to-finalise"))}>
              Ask HMRC for the final calculation
            </button>
            {calc?.report && (
              <div className="mt-3">
                <p className="text-sm font-bold">Before you can submit the information displayed here in response to your notice to file from HM Revenue &amp; Customs, you must read and agree to the following statement:</p>
                <label className="mt-2 flex items-start gap-2 text-[15px]">
                  <input type="checkbox" checked={declared} onChange={(e) => setDeclared(e.target.checked)} className="mt-1" />
                  <span>{FINAL_DECLARATION}</span>
                </label>
                <button type="button" className={`${primary} mt-3`} disabled={!declared || !!busy} onClick={declare}>
                  {busy === "final" ? "Sending…" : "Make the final declaration"}
                </button>
              </div>
            )}
            {finalDone && <p role="status" className="mt-3 font-bold text-teal-dark">HMRC received the final declaration (correlation ID {finalDone}).</p>}
          </details>
        </section>
      )}

      {account && receipts.length > 0 && (
        <section aria-labelledby="itsa-receipts" className={card}>
          <h2 id="itsa-receipts" className="text-lg font-extrabold">Saved for {taxYear}</h2>
          <ul className="mt-2 flex flex-col gap-3 text-sm">
            {receipts.map((r) => (
              <li key={r.path} className="flex flex-col gap-1">
                <span>
                  {r.kind === "cumulative" ? `Update to ${day(r.period_end ?? "")}` : r.kind === "calculation" ? "HMRC calculation" : "Final declaration"}
                  {" · "}saved {new Date(r.saved_at).toLocaleString("en-GB")}
                  {r.matches_books === false ? " · differed from the books" : ""}
                </span>
                {r.kind === "cumulative" && <Downloads account={account} kind="quarterly" query={{ tax_year: taxYear, path: r.path }} label="update" />}
                {r.kind === "calculation" && r.calculation_id && (
                  <Downloads account={account} kind="calculation" query={{ tax_year: taxYear, calculation_id: r.calculation_id }} label="calculation" />
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
