"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useAccount } from "@/components/jobs/useAccount";
import { fieldInput, fieldLabel, primaryButton, secondaryButton } from "@/components/invoices/Modal";
import { track } from "@/lib/analytics";
import { billingApi, fetchPlans } from "@/lib/billing-api";
import {
  DEFAULT_PLANS, PLAN_NAMES, STATUS_LABEL, TOPUP_DOCS, TOPUP_PENCE, longDate, money, perMonth, trialReminder, usageMeters, withVat,
  type BillingInterval, type PlanCode, type RtAccount, type RtPlan,
} from "@/lib/billing";
import { demoSession } from "@/lib/demo";

/** Settings › Plan & billing: where the plan stands, this month's use, and every way to change it. Payment is Stripe's. */
export default function PlanBilling({ card, heading }: { card: string; heading: string }) {
  const account = useAccount();
  const [acct, setAcct] = useState<RtAccount | null>(null);
  const [plans, setPlans] = useState<RtPlan[]>(DEFAULT_PLANS);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [pick, setPick] = useState<PlanCode>("comprehensive");
  const [interval, setInterval] = useState<BillingInterval>("month");
  const [promo, setPromo] = useState("");
  const [code, setCode] = useState("");
  const [demo, setDemo] = useState(false);

  useEffect(() => {
    queueMicrotask(() => setDemo(!!demoSession()));
    fetchPlans().then((p) => p && setPlans(p));
  }, []);

  const load = useCallback(async () => {
    if (!account) return;
    try {
      const a = await billingApi.account(account);
      setAcct(a);
      setPick(a.plan_code);
      if (a.billing_interval) setInterval(a.billing_interval);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [account]);

  useEffect(() => {
    // Defer so state is not set synchronously in the effect body.
    queueMicrotask(() => void load());
  }, [load]);

  async function go(what: string, run: () => Promise<{ url: string }>) {
    setBusy(what);
    setError(null);
    try {
      const { url } = await run();
      window.location.assign(url);
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  }

  async function redeem() {
    if (!account || !code.trim()) return;
    setBusy("redeem");
    setError(null);
    setMessage(null);
    try {
      track("redeem_click");
      const r = await billingApi.redeem(account, code.trim());
      if (r.ok) {
        setMessage(r.message);
        setCode("");
        if (r.account) setAcct(r.account);
        else await load();
      } else setError(r.message);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  if (demo) {
    return (
      <section aria-labelledby="plan-billing" className={card}>
        <h2 id="plan-billing" className={heading}>Plan &amp; billing</h2>
        <p className="mt-1 text-sm text-muted">The demo has no plan. Your own books start with a 3-month free trial and no card.</p>
        <Link href="/pricing" className="mt-2 inline-block text-sm font-bold text-teal-dark underline underline-offset-2">See the plans</Link>
      </section>
    );
  }
  if (account === null) {
    return (
      <section aria-labelledby="plan-billing" className={card}>
        <h2 id="plan-billing" className={heading}>Plan &amp; billing</h2>
        <p className="mt-1 text-sm text-muted">Sign in to see your plan.</p>
      </section>
    );
  }

  const reminder = acct ? trialReminder(acct) : null;
  const meters = acct ? usageMeters(acct) : [];
  const current = plans.find((p) => p.code === acct?.plan_code);
  const picked = plans.find((p) => p.code === pick) ?? plans[0];
  const paying = acct?.status === "active" || acct?.status === "past_due";

  return (
    <div className="space-y-4" data-plan-billing="">
      {reminder && (
        <div role="status" className="rounded-2xl border-2 border-brass bg-brass/10 p-4 text-[15px] text-ink">
          <strong>Your free trial ends {reminder.days === 0 ? "today" : reminder.days === 1 ? "tomorrow" : `in ${reminder.days} days`}</strong> ({longDate(acct?.trial_ends_at)}).
          Choose a plan below and add a card before then to keep going. If you do not, your books become read-only; nothing is deleted.
        </div>
      )}

      <section aria-labelledby="plan-billing" className={card}>
        <h2 id="plan-billing" className={heading}>Plan &amp; billing</h2>
        {error && <p role="alert" className="mt-2 text-sm font-bold text-red-700">{error}</p>}
        {message && <p role="status" className="mt-2 text-sm font-bold text-teal-dark">{message}</p>}
        {!acct && !error && <p className="mt-2 text-sm text-muted">Loading your plan…</p>}
        {acct && (
          <dl className="mt-3 divide-y divide-border">
            <Row label="Plan" value={PLAN_NAMES[acct.plan_code]} />
            <Row label="Status" value={STATUS_LABEL[acct.status]} />
            {acct.status === "trialing" && <Row label="Free trial ends" value={longDate(acct.trial_ends_at)} />}
            {acct.status === "comped" && <Row label="Free until" value={acct.comp_until ? longDate(acct.comp_until) : "No end date"} />}
            {paying && acct.billing_interval && <Row label="Billed" value={acct.billing_interval === "year" ? "Yearly" : "Monthly"} />}
            {current && (
              <Row label="Price" value={`${money(acct.billing_interval === "year" ? current.price_year_pence : current.price_month_pence)} ${acct.billing_interval === "year" ? "a year" : "a month"} plus VAT`} />
            )}
          </dl>
        )}
        {acct?.status === "trial_ended" && (
          <p className="mt-3 rounded-xl bg-ground p-3 text-sm text-ink">Your trial has ended, so your books are read-only. Choose a plan to carry on; nothing has been deleted.</p>
        )}
        {acct?.status === "past_due" && (
          <p className="mt-3 rounded-xl bg-ground p-3 text-sm text-ink">The last payment did not go through. Update your card under Manage card &amp; invoices.</p>
        )}
      </section>

      {acct && (
        <section aria-labelledby="plan-usage" className={card}>
          <h2 id="plan-usage" className={heading}>This month&apos;s use</h2>
          <p className="mt-1 text-sm text-muted">Resets on the 1st of each month. Approving, editing and exporting what is already in your books is never blocked.</p>
          <ul className="mt-3 space-y-3">
            {meters.map((m) => (
              <li key={m.key}>
                <div className="flex items-baseline justify-between gap-3 text-sm">
                  <span className="font-bold text-ink">{m.label}</span>
                  <span className="text-muted" data-meter-value={m.key}>
                    {m.used.toLocaleString("en-GB")} of {m.limit === null ? "unlimited" : m.limit.toLocaleString("en-GB")}
                  </span>
                </div>
                <div
                  role="meter"
                  aria-label={m.label}
                  aria-valuemin={0}
                  aria-valuemax={m.limit ?? m.used}
                  aria-valuenow={m.used}
                  className="mt-1 h-2.5 overflow-hidden rounded-full bg-ground"
                >
                  <div
                    className={`h-full rounded-full ${m.state === "full" ? "bg-red-700" : m.state === "near" ? "bg-brass" : "bg-teal"}`}
                    style={{ width: `${m.limit === null ? 6 : Math.max(m.used > 0 ? 3 : 0, Math.round(m.ratio * 100))}%` }}
                  />
                </div>
                {m.extra && <p className="mt-0.5 text-xs text-muted">{m.extra}</p>}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-labelledby="plan-change" className={card}>
        <h2 id="plan-change" className={heading}>{paying ? "Change plan" : "Choose a plan"}</h2>
        <div role="radiogroup" aria-label="Plan" className="mt-3 grid gap-2 min-[560px]:grid-cols-3">
          {plans.map((p) => (
            <button
              key={p.code}
              type="button"
              role="radio"
              aria-checked={pick === p.code}
              onClick={() => setPick(p.code)}
              className={`rounded-xl border px-3 py-2 text-left ${pick === p.code ? "border-2 border-teal bg-teal-tint" : "border-border bg-white hover:bg-ground"}`}
            >
              <span className="block text-[15px] font-extrabold text-ink">{p.name}</span>
              <span className="block text-sm text-muted">
                {money(perMonth(p, interval))} a month + VAT
              </span>
            </button>
          ))}
        </div>
        <div role="radiogroup" aria-label="Billing" className="mt-3 flex flex-wrap gap-2">
          {(["month", "year"] as const).map((i) => (
            <button
              key={i}
              type="button"
              role="radio"
              aria-checked={interval === i}
              onClick={() => setInterval(i)}
              className={`h-10 rounded-xl border px-4 text-sm font-bold ${interval === i ? "border-2 border-teal bg-teal-tint text-teal-dark" : "border-border bg-white text-ink"}`}
            >
              {i === "month" ? "Monthly" : "Yearly, 2 months free"}
            </button>
          ))}
        </div>
        {picked && (
          <p className="mt-2 text-sm text-muted">
            {PLAN_NAMES[picked.code]}: {money(interval === "month" ? picked.price_month_pence : picked.price_year_pence)} {interval === "month" ? "a month" : "a year"} plus VAT
            ({money(withVat(interval === "month" ? picked.price_month_pence : picked.price_year_pence))} with UK VAT).
          </p>
        )}
        <label className="mt-3 block">
          <span className={fieldLabel}>Promo code (optional)</span>
          <input className={fieldInput} value={promo} onChange={(e) => setPromo(e.target.value)} autoComplete="off" />
        </label>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            className={primaryButton}
            disabled={!account || busy !== null}
            onClick={() => {
              track("upgrade_click", { plan: pick, interval });
              void go("checkout", () => billingApi.checkout(account!, { plan_code: pick, interval, ...(promo.trim() ? { promo_code: promo.trim() } : {}) }));
            }}
          >
            {paying ? "Change plan" : "Upgrade"}
          </button>
          <button type="button" className={secondaryButton} disabled={!account || busy !== null} onClick={() => void go("portal", () => billingApi.portal(account!))}>
            Manage card &amp; invoices
          </button>
        </div>
        <p className="mt-2 text-xs text-muted">Payment is taken by Stripe; we never see or store your card. Cancel any time from Manage card &amp; invoices.</p>
      </section>

      <section aria-labelledby="plan-extras" className={card}>
        <h2 id="plan-extras" className={heading}>Top up, codes and your own AI</h2>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            type="button"
            className={secondaryButton}
            disabled={!account || busy !== null}
            onClick={() => {
              track("topup_click", { from: "settings" });
              void go("topup", () => billingApi.topup(account!));
            }}
          >
            Buy {TOPUP_DOCS} documents
          </button>
          <span className="text-sm text-muted">{money(TOPUP_PENCE)}, valid for 12 months, on any plan.</span>
        </div>
        <form
          className="mt-4 flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void redeem();
          }}
        >
          <label className="min-w-0 flex-1">
            <span className={fieldLabel}>Redeem a code</span>
            <input className={fieldInput} value={code} onChange={(e) => setCode(e.target.value)} autoComplete="off" />
          </label>
          <button type="submit" className={secondaryButton} disabled={!account || busy !== null || !code.trim()}>
            Redeem
          </button>
        </form>
        <p className="mt-4 text-sm text-muted">
          <strong className="text-ink">Bring your own AI.</strong> Use your own API key or a local model on any plan: AI-read documents and Ask
          become fair use with no monthly cap, and the price does not change. Set it up under{" "}
          <a href="#settings-ai" className="font-bold text-teal-dark underline underline-offset-2" onClick={() => { window.location.hash = "settings-ai"; }}>
            Settings › AI
          </a>.
        </p>
        <p className="mt-2 text-sm text-muted">
          <Link href="/pricing" className="font-bold text-teal-dark underline underline-offset-2">Compare the plans</Link>
        </p>
      </section>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 py-3">
      <dt className="text-[15px] font-bold text-ink">{label}</dt>
      <dd className="text-sm text-ink">{value}</dd>
    </div>
  );
}
