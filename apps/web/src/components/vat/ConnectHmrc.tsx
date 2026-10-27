"use client";

import { useEffect, useMemo, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import Explain from "@/components/Explain";
import { getMsal, msalConfigured } from "@/lib/msal";
import { fetchLiveVat, type RtVatView } from "@/lib/runtime";
import { usePickedPeriod } from "@/lib/vat-period";
import { FOLDER } from "@/lib/folders";
import { ensureFolder, listChildren, putSmallFile } from "@/lib/graph";
import {
  clientFacts,
  disconnect,
  finishConnect,
  hmrc,
  HmrcAuthError,
  loadTokens,
  rememberVrn,
  savedVrn,
  startConnect,
  takeCallback,
  toReturnBody,
  type Obligation,
  type RelayResult,
  type SubmitReceipt,
  type VatReturnBody,
} from "@/lib/hmrc";

type Phase = "loading" | "hidden" | "disconnected" | "connecting" | "connected";
type Step = "list" | "confirm" | "submitting" | "done";

const DECLARATION =
  "When you submit this VAT information you are making a legal declaration that the information is true and complete. A false declaration can result in prosecution.";

const FRAUD_NOTICE =
  "Submitting sends HMRC's fraud-prevention data with the return: a random ID for this device, your screen and window size, time zone, browser, a hashed ID for your Microsoft account, and your IP address. Nothing is sent until you press Submit.";

const STEPS = ["Declaration", "Submit", "Receipt"] as const;

/** Where the submission is: 0 = choose the period and declare, 1 = sending, 2 = receipt. */
function stepIndex(step: Step): number {
  return step === "list" ? 0 : step === "done" ? 2 : 1;
}

/** The 3-step strip (declaration → submit → receipt) shown once obligations are listed. */
function StepStrip({ step }: { step: Step }) {
  const current = stepIndex(step);
  return (
    <ol aria-label="Submission steps" className="flex flex-wrap items-center gap-2 text-[14px]">
      {STEPS.map((label, i) => (
        <li key={label} className="flex items-center gap-2" aria-current={i === current ? "step" : undefined}>
          <span
            aria-hidden="true"
            className={`flex h-6 w-6 items-center justify-center rounded-full text-[13px] font-extrabold ${
              i < current ? "bg-teal text-white" : i === current ? "bg-teal-tint text-teal-dark" : "bg-ground text-muted"
            }`}
          >
            {i + 1}
          </span>
          <span className={i === current ? "font-extrabold text-ink" : "font-semibold text-muted"}>{label}</span>
          {i < STEPS.length - 1 ? (
            <span aria-hidden="true" className="mx-1 text-muted">
              →
            </span>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

const BOXES: { box: number; key: keyof VatReturnBody; label: string }[] = [
  { box: 1, key: "vatDueSales", label: "VAT due on sales" },
  { box: 2, key: "vatDueAcquisitions", label: "VAT due on acquisitions from NI/EU" },
  { box: 3, key: "totalVatDue", label: "Total VAT due (1 + 2)" },
  { box: 4, key: "vatReclaimedCurrPeriod", label: "VAT reclaimed on purchases" },
  { box: 5, key: "netVatDue", label: "Net VAT to pay HMRC (3 − 4)" },
  { box: 6, key: "totalValueSalesExVAT", label: "Total sales excluding VAT" },
  { box: 7, key: "totalValuePurchasesExVAT", label: "Total purchases excluding VAT" },
  { box: 8, key: "totalValueGoodsSuppliedExVAT", label: "Supplies of goods to NI/EU" },
  { box: 9, key: "totalAcquisitionsExVAT", label: "Acquisitions of goods from NI/EU" },
];

const money = (box: number, n: number) =>
  box <= 5 ? `£${n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : `£${n.toLocaleString("en-GB")}`;
const uk = (iso: string) => {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
};
const isoDay = (d: Date) => d.toISOString().slice(0, 10);
const cleanVrn = (s: string) => s.replace(/\s+/g, "").toUpperCase().replace(/^GB/, "");

const btn = "h-11 whitespace-nowrap rounded-xl px-5 text-[15px] font-bold disabled:cursor-not-allowed disabled:opacity-50";
const primary = `${btn} bg-teal text-white hover:bg-teal-dark`;
const secondary = `${btn} border border-border bg-white hover:bg-ground`;

/** "Connect to HMRC (sandbox)": OAuth via the relay, open obligations, and submission of the live return. */
export default function ConnectHmrc() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [live, setLive] = useState<RtVatView | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [vrn, setVrn] = useState("");
  const [scenario, setScenario] = useState("");
  const [obligations, setObligations] = useState<Obligation[] | null>(null);
  const [loadingObs, setLoadingObs] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [missing, setMissing] = useState<string[]>([]);

  const [step, setStep] = useState<Step>("list");
  const [declared, setDeclared] = useState(false);
  const [result, setResult] = useState<RelayResult<SubmitReceipt> | null>(null);
  const [saved, setSaved] = useState<"saving" | "saved" | string>("saving");
  const [copied, setCopied] = useState(false);
  const [receipts, setReceipts] = useState<{ period: string; saved: boolean }[] | null>(null);
  const [receiptsKey, setReceiptsKey] = useState(0);
  const picked = usePickedPeriod();

  // Previous submissions, from the receipt files saved in OneDrive (`06 VAT returns/`).
  useEffect(() => {
    if (!account || phase !== "connected") return;
    let stale = false;
    (async () => {
      try {
        const kids = await listChildren(account, FOLDER.vat_returns);
        const folders = kids.filter((k) => k.folder).map((k) => k.name).sort().reverse().slice(0, 9);
        const rows = await Promise.all(
          folders.map(async (name) => {
            try {
              const inner = await listChildren(account, `${FOLDER.vat_returns}/${name}`);
              return { period: name, saved: inner.some((f) => f.name === "receipt.json") };
            } catch {
              return { period: name, saved: false };
            }
          }),
        );
        if (!stale) setReceipts(rows);
      } catch {
        if (!stale) setReceipts([]);
      }
    })();
    return () => {
      stale = true;
    };
  }, [account, phase, receiptsKey]);

  useEffect(() => {
    // Take the OAuth fragment before any await so nothing else (MSAL, a reload) sees or re-uses it.
    const cb = takeCallback();
    (async () => {
      try {
        if (!msalConfigured()) return setPhase("hidden");
        const msal = await getMsal();
        await msal.handleRedirectPromise().catch(() => null);
        const acct: AccountInfo | undefined = msal.getActiveAccount() ?? msal.getAllAccounts()[0];
        if (!acct) return setPhase("hidden");
        setAccount(acct);
        setVrn(savedVrn());
        if (cb && "error" in cb) {
          disconnect();
          setError(`HMRC sign-in didn't finish: ${cb.description || cb.error}`);
        } else if (cb) {
          setPhase("connecting");
          await finishConnect(cb).catch((e: Error) => setError(e.message));
        }
        setPhase(loadTokens() ? "connected" : "disconnected");
      } catch (e) {
        setError((e as Error).message);
        setPhase("disconnected");
      }
    })();
  }, []);

  // The return for the period picked above (the current one unless another is chosen).
  useEffect(() => {
    if (!account) return;
    let stale = false;
    fetchLiveVat(account, picked?.period ?? null).then(
      (v) => {
        if (stale) return;
        setLive(v);
        setStep((s) => (s === "confirm" ? "list" : s)); // a half-made declaration may be for the previous figures
      },
      () => !stale && setLive(null),
    );
    return () => {
      stale = true;
    };
  }, [account, picked?.period]);

  const obligation = obligations?.find((o) => o.periodKey === selected) ?? null;
  const body = useMemo(() => (live && obligation ? toReturnBody(live.hmrc_body, obligation.periodKey) : null), [live, obligation]);
  const vrnOk = /^\d{9}$/.test(cleanVrn(vrn));

  function fail(e: unknown) {
    if (e instanceof HmrcAuthError) {
      setPhase("disconnected");
      setObligations(null);
      setStep("list");
    }
    setError((e as Error).message);
  }

  async function connect() {
    setError(null);
    setPhase("connecting");
    try {
      await startConnect();
    } catch (e) {
      setError((e as Error).message);
      setPhase("disconnected");
    }
  }

  async function copyBundle() {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(result.hmrc.formBundleNumber);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  function signOut() {
    disconnect();
    setObligations(null);
    setSelected(null);
    setStep("list");
    setResult(null);
    setError(null);
    setPhase("disconnected");
  }

  async function loadObligations() {
    if (!account || !vrnOk) return;
    const v = cleanVrn(vrn);
    setError(null);
    setLoadingObs(true);
    setStep("list");
    setResult(null);
    try {
      rememberVrn(v);
      const to = new Date();
      const from = new Date(to.getTime() - 365 * 86_400_000);
      const res = await hmrc.obligations(v, await clientFacts(account.homeAccountId), { from: isoDay(from), to: isoDay(to) }, scenario);
      const list = res.hmrc?.obligations ?? [];
      setObligations(list);
      setMissing(res.fraud_headers_missing);
      const match = live && list.find((o) => o.status === "O" && o.start === live.start && o.end === live.end);
      setSelected(match ? match.periodKey : (list.find((o) => o.status === "O")?.periodKey ?? null));
    } catch (e) {
      fail(e);
    } finally {
      setLoadingObs(false);
    }
  }

  async function submit() {
    if (!account || !body || !obligation || !live?.can_submit || !declared) return;
    const v = cleanVrn(vrn);
    setError(null);
    setStep("submitting");
    try {
      const res = await hmrc.submit(v, await clientFacts(account.homeAccountId), body, scenario);
      setResult(res);
      setCopied(false);
      setMissing(res.fraud_headers_missing);
      setStep("done");
      setObligations((list) => list?.map((o) => (o.periodKey === obligation.periodKey ? { ...o, status: "F" } : o)) ?? null);
      setSaved("saving");
      const folder = `${FOLDER.vat_returns}/${obligation.periodKey}`;
      const submittedAt = new Date().toISOString();
      try {
        await ensureFolder(account, folder);
        await putSmallFile(
          account,
          `${folder}/return.json`,
          JSON.stringify(
            {
              vrn: v,
              periodKey: obligation.periodKey,
              obligation: { start: obligation.start, end: obligation.end, due: obligation.due },
              calculated_for: { period_key: live.period_key, start: live.start, end: live.end },
              calculated_by: "code (packages/ledger compute_vat_return) from approved ledger events",
              return: body,
              event_ids: live.event_ids,
              warnings: live.warnings,
              declaration: DECLARATION,
              declared_at: submittedAt,
              environment: "HMRC sandbox",
            },
            null,
            2,
          ),
          "application/json",
        );
        await putSmallFile(
          account,
          `${folder}/receipt.json`,
          JSON.stringify(
            {
              vrn: v,
              periodKey: obligation.periodKey,
              submitted_at: submittedAt,
              environment: "HMRC sandbox",
              hmrc: res.hmrc,
              correlation_id: res.correlation_id,
              receipt_id: res.receipt_id,
              receipt_timestamp: res.receipt_timestamp,
              sent_headers: res.sent_headers,
              fraud_headers_missing: res.fraud_headers_missing,
            },
            null,
            2,
          ),
          "application/json",
        );
        setSaved("saved");
        setReceiptsKey((k) => k + 1); // the new receipt joins the list below
      } catch (e) {
        setSaved(`Couldn't save to OneDrive: ${(e as Error).message}. The submission itself went through — keep this page open and note the receipt below.`);
      }
    } catch (e) {
      setStep("confirm");
      fail(e);
    }
  }

  if (phase === "loading" || phase === "hidden") return null;

  return (
    <section aria-labelledby="hmrc-heading" className="rounded-2xl border border-border bg-white p-5 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="hmrc-heading" className="text-lg font-extrabold">
          Connect to HMRC
        </h2>
        <span className="flex items-center gap-2">
          <span className="rounded-full border border-warn-border bg-warn-bg px-3 py-1 text-[13px] font-bold text-warn-ink">
            Sandbox · test data only
          </span>
          <Explain title="What sandbox means">
            <p>
              This talks to HMRC&apos;s test service, not the live tax system. You sign in with a
              sandbox Government Gateway test user, and nothing here files a real return — there
              are no production HMRC credentials anywhere in Accnomos.
            </p>
            <p>
              You sign in on HMRC&apos;s own site; we never see your HMRC password. The access
              token stays in this browser tab only and is gone when you close it. Our relay holds
              only the HMRC application secret and adds the fraud-prevention headers HMRC
              requires with each call.
            </p>
            <p>
              Nothing is sent until you tick the legal declaration and press Submit. The return
              and HMRC&apos;s receipt are then saved to {FOLDER.vat_returns} in your OneDrive.
            </p>
          </Explain>
        </span>
      </div>

      {error && (
        <p role="alert" className="mt-3 rounded-xl border border-warn-border bg-warn-bg p-3 text-sm text-warn-ink">
          {error}
        </p>
      )}

      {(phase === "disconnected" || phase === "connecting") && (
        <div className="mt-3">
          <p className="text-[15px] leading-7">
            Sign in with your HMRC (sandbox) Government Gateway test user to see your VAT obligations and submit the return above.
          </p>
          <ul className="mt-2 list-disc pl-5 text-sm leading-6 text-muted">
            <li>You sign in on HMRC&apos;s own site. We never see your HMRC password.</li>
            <li>The access token stays in this browser tab only and is gone when you close it. Nothing is stored on our servers.</li>
            <li>
              HMRC requires fraud-prevention data with each call: a random ID for this device, your screen and window size, time zone,
              browser, a hashed ID for your Microsoft account, and your IP address.
            </li>
          </ul>
          <button type="button" onClick={connect} disabled={phase === "connecting"} className={`${primary} mt-4`}>
            {phase === "connecting" ? "Connecting…" : "Connect to HMRC (sandbox)"}
          </button>
        </div>
      )}

      {phase === "connected" && (
        <div className="mt-3 flex flex-col gap-4">
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-sm font-semibold">
              VAT registration number
              <input
                value={vrn}
                onChange={(e) => setVrn(e.target.value)}
                inputMode="numeric"
                placeholder="e.g. 786189079"
                aria-invalid={vrn !== "" && !vrnOk}
                className="h-11 w-48 rounded-xl border border-border px-3 text-[15px] font-normal"
              />
            </label>
            <button type="button" onClick={loadObligations} disabled={!vrnOk || loadingObs} className={primary}>
              {loadingObs ? "Asking HMRC…" : obligations ? "Refresh obligations" : "Show obligations"}
            </button>
            <button type="button" onClick={signOut} className="h-11 text-sm font-bold text-teal-dark underline underline-offset-2">
              Disconnect
            </button>
          </div>

          <details className="text-sm">
            <summary className="cursor-pointer font-semibold text-muted">Advanced: sandbox test scenario</summary>
            <label className="mt-2 flex flex-col gap-1">
              <span className="text-muted">Gov-Test-Scenario (leave empty for HMRC&apos;s default)</span>
              <input
                value={scenario}
                onChange={(e) => setScenario(e.target.value)}
                placeholder="e.g. QUARTERLY_NONE_MET"
                className="h-10 w-72 max-w-full rounded-xl border border-border px-3"
              />
            </label>
          </details>

          {obligations && obligations.length === 0 && (
            <p className="text-sm text-muted">HMRC returned no obligations for the last 12 months. Try a test scenario such as QUARTERLY_NONE_MET.</p>
          )}

          {obligations && obligations.length > 0 && step === "list" && (
            <div>
              <div className="mb-3">
                <StepStrip step={step} />
                {live ? (
                  <p className="mt-2 text-[13px] font-medium text-muted">
                    Periods follow the picker above — the highlighted row matches your picked return ({live.label}).
                  </p>
                ) : null}
              </div>
              {/* Phone: one card per obligation. Wider screens: the obligations table. */}
              <ul className="flex flex-col gap-2 min-[640px]:hidden">
                {obligations.map((o) => {
                  const matches = live && o.start === live.start && o.end === live.end;
                  const chosen = o.periodKey === selected;
                  return (
                    <li key={o.periodKey}>
                      <label
                        className={`flex cursor-pointer items-start gap-3 rounded-xl border p-4 ${
                          chosen ? "border-teal bg-teal-tint" : "border-border bg-white"
                        }`}
                      >
                        {o.status === "O" ? (
                          <input
                            type="radio"
                            name="obligation"
                            aria-label={`Choose period ${o.periodKey}`}
                            checked={chosen}
                            onChange={() => setSelected(o.periodKey)}
                            className="mt-1 h-5 w-5 shrink-0 accent-teal"
                          />
                        ) : (
                          <span aria-hidden="true" className="mt-2 h-2 w-2 shrink-0 rounded-full bg-muted" />
                        )}
                        <span className="min-w-0">
                          <span className="text-[15px] font-bold tabular-nums">
                            {o.periodKey} · {o.status === "O" ? "Open" : `Filed${o.received ? ` ${uk(o.received)}` : ""}`}
                          </span>
                          <span className="mt-0.5 block text-sm text-muted">
                            {uk(o.start)} – {uk(o.end)} · due {uk(o.due)}
                          </span>
                          {matches && (
                            <span className="mt-0.5 block text-[13px] font-bold text-teal-dark">
                              matches your return
                            </span>
                          )}
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
              <div className="hidden overflow-x-auto min-[640px]:block">
                <table className="w-full text-left text-[15px]">
                  <thead>
                    <tr className="border-b border-border text-[13px] font-bold text-muted">
                      <th scope="col" className="w-10 py-2" />
                      <th scope="col" className="py-2 pr-2">Period key</th>
                      <th scope="col" className="py-2 pr-2">Period</th>
                      <th scope="col" className="py-2 pr-2">Due</th>
                      <th scope="col" className="py-2">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {obligations.map((o) => {
                      const matches = live && o.start === live.start && o.end === live.end;
                      return (
                        <tr key={o.periodKey} className={`border-t border-border ${o.periodKey === selected ? "bg-teal-tint" : ""}`}>
                          <td className="py-2">
                            {o.status === "O" && (
                              <input
                                type="radio"
                                name="obligation"
                                aria-label={`Choose period ${o.periodKey}`}
                                checked={o.periodKey === selected}
                                onChange={() => setSelected(o.periodKey)}
                                className="h-5 w-5 accent-teal"
                              />
                            )}
                          </td>
                          <td className="py-2 pr-2 font-bold tabular-nums">{o.periodKey}</td>
                          <td className="py-2 pr-2">
                            {uk(o.start)} – {uk(o.end)}
                            {matches && <span className="ml-2 text-[13px] font-bold text-teal-dark">matches your return</span>}
                          </td>
                          <td className="py-2 pr-2">{uk(o.due)}</td>
                          <td className="py-2">{o.status === "O" ? "Open" : `Filed${o.received ? ` ${uk(o.received)}` : ""}`}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <button type="button" disabled={!obligation || !live?.can_submit} onClick={() => {
                  setDeclared(false);
                  setStep("confirm");
                }} className={`${primary} mt-4`}>
                Prepare submission
              </button>
              {!live && <p className="mt-2 text-sm text-muted">Your live return isn&apos;t available (is the runtime running?), so there is nothing to submit yet.</p>}
              {live && !live.can_submit && (
                <p className="mt-2 text-sm text-muted">
                  {live.submitted
                    ? `${live.label} has already been submitted.`
                    : `${live.label} is too far back to submit here: pick the current or previous period above.`}
                </p>
              )}
            </div>
          )}

          {(step === "confirm" || step === "submitting") && body && obligation && live && (
            <div className="rounded-2xl border border-teal p-5">
              <div className="mb-3">
                <StepStrip step={step} />
              </div>
              <h3 className="text-[17px] font-extrabold">
                Confirm VAT return · {uk(obligation.start)} – {uk(obligation.end)} · key {obligation.periodKey}
              </h3>
              {(obligation.start !== live.start || obligation.end !== live.end) && (
                <p className="mt-2 rounded-xl border border-warn-border bg-warn-bg p-3 text-sm text-warn-ink">
                  These figures were calculated for {uk(live.start)} – {uk(live.end)}, which isn&apos;t the period of this obligation.
                  That&apos;s expected with sandbox test data; for a real return the dates must match.
                </p>
              )}
              <table className="mt-3 w-full text-[15px]">
                <tbody>
                  {BOXES.map((b) => (
                    <tr key={b.box} className={`border-t border-border ${b.box === 3 || b.box === 5 ? "bg-ground" : ""}`}>
                      <td className="w-10 py-2 pr-2 font-extrabold">{b.box}</td>
                      <td className="py-2 pr-2">{b.label}</td>
                      <td className="py-2 text-right font-bold tabular-nums">{money(b.box, body[b.key] as number)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-2 text-sm text-muted">Calculated by code, not AI, from the {live.events_in_period} entries you approved.</p>
              <p className="mt-3 rounded-xl bg-ground p-3 text-[13px] leading-6 text-muted">{FRAUD_NOTICE}</p>
              <p className="mt-4 text-[15px] leading-7">{DECLARATION}</p>
              <label className="mt-3 flex min-h-11 cursor-pointer items-center gap-3 text-[15px] font-semibold">
                <input type="checkbox" checked={declared} onChange={(e) => setDeclared(e.target.checked)} className="h-5 w-5 accent-teal" />
                I confirm the information is true and complete
              </label>
              <div className="mt-3 flex flex-col gap-3 sm:flex-row">
                <button type="button" onClick={submit} disabled={!declared || step === "submitting"} className={primary}>
                  {step === "submitting" ? "Submitting…" : "Submit to HMRC (sandbox)"}
                </button>
                <button type="button" onClick={() => setStep("list")} disabled={step === "submitting"} className={secondary}>
                  Back
                </button>
              </div>
            </div>
          )}

          {step === "done" && result && obligation && (
            <div className="rounded-2xl border border-teal bg-teal-tint p-5" aria-live="polite">
              <div className="mb-3">
                <StepStrip step={step} />
              </div>
              <h3 className="text-[17px] font-extrabold text-teal-dark">Submitted to HMRC (sandbox) · key {obligation.periodKey}</h3>
              <dl className="mt-3 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-[15px]">
                <dt className="text-muted">Processing date</dt>
                <dd className="font-bold">{result.hmrc.processingDate}</dd>
                <dt className="text-muted">Form bundle number</dt>
                <dd className="font-bold tabular-nums">
                  {result.hmrc.formBundleNumber}{" "}
                  <button
                    type="button"
                    onClick={copyBundle}
                    aria-label="Copy form bundle number"
                    className="ml-1 rounded-lg border border-border bg-white px-2 py-0.5 text-[13px] font-bold text-teal-dark hover:bg-ground"
                  >
                    Copy
                  </button>
                  <span aria-live="polite" className="ml-2 text-[13px] font-semibold text-teal-dark">
                    {copied ? "Copied" : ""}
                  </span>
                </dd>
                {result.hmrc.paymentIndicator && (
                  <>
                    <dt className="text-muted">Payment indicator</dt>
                    <dd className="font-bold">{result.hmrc.paymentIndicator}</dd>
                  </>
                )}
                {result.hmrc.chargeRefNumber && (
                  <>
                    <dt className="text-muted">Charge reference</dt>
                    <dd className="font-bold tabular-nums">{result.hmrc.chargeRefNumber}</dd>
                  </>
                )}
                {result.correlation_id && (
                  <>
                    <dt className="text-muted">Correlation ID</dt>
                    <dd className="break-all text-sm">{result.correlation_id}</dd>
                  </>
                )}
              </dl>
              <p className={`mt-3 text-sm ${saved === "saving" || saved === "saved" ? "text-ink" : "text-warn-ink"}`}>
                {saved === "saving"
                  ? "Saving to your OneDrive…"
                  : saved === "saved"
                    ? `Saved to your OneDrive: ${FOLDER.vat_returns}/${obligation.periodKey}/receipt.json and return.json.`
                    : saved}
              </p>
            </div>
          )}

          {receipts !== null && (
            <section aria-labelledby="past-receipts" className="rounded-2xl border border-border p-5">
              <h3 id="past-receipts" className="text-[15px] font-extrabold tracking-tight">
                Previous receipts
              </h3>
              {receipts.length === 0 ? (
                <p className="mt-2 text-sm text-muted">
                  No receipts saved yet. After you submit, the return and HMRC&apos;s receipt are kept in{" "}
                  {FOLDER.vat_returns} in your OneDrive.
                </p>
              ) : (
                <ul className="mt-2 flex flex-col gap-1 text-[15px]">
                  {receipts.map((r) => (
                    <li key={r.period} className="flex flex-wrap items-baseline gap-x-2">
                      <span className="font-bold tabular-nums">{r.period}</span>
                      <span className="text-sm text-muted">
                        {r.saved ? "receipt saved" : "return only"} · {FOLDER.vat_returns}/{r.period}/
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          {missing.length > 0 && (
            <p className="text-[13px] text-muted">
              Note: some fraud-prevention headers couldn&apos;t be sent ({missing.join(", ")}). HMRC accepts this in the sandbox; it needs fixing before going live.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
