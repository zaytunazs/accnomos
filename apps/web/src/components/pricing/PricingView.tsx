"use client";

import { BUILD_PAYMENTS_PROVIDER, PROVIDER_NAME } from "@/lib/payments";
import Link from "next/link";
import { useEffect, useState } from "react";
import LimitsTable from "@/components/pricing/LimitsTable";
import { fetchPlans } from "@/lib/billing-api";
import {
  DEFAULT_PLANS, TOPUP_DOCS, TOPUP_PENCE, WHO_FOR, annualSaving, money, perMonth, withVat,
  type BillingInterval, type RtPlan,
} from "@/lib/billing";

const TRIAL_CTA = "Start your 3-month free trial — no card needed";

/** /pricing: public. Prices and limits are the contract's until GET /plans answers with the live ones. */
export default function PricingView() {
  const [plans, setPlans] = useState<RtPlan[]>(DEFAULT_PLANS);
  const [interval, setInterval] = useState<BillingInterval>("month");
  useEffect(() => {
    fetchPlans().then((p) => p && p.length && setPlans(p));
  }, []);

  const btn = "inline-block rounded-xl bg-brass px-5 py-3 text-base font-extrabold text-ink hover:bg-brass-light";
  return (
    <div className="pb-10">
      <h1 className="text-3xl font-extrabold tracking-tight">Pricing</h1>
      <p className="mt-2 text-[17px] leading-7 text-ink">
        Every account starts with a 3-month free trial, no card needed. Prices are per month, ex VAT; UK VAT at 20% is added at checkout.
      </p>
      <p className="mt-4">
        <Link href="/connect?next=%2Fsettings%23plan-billing" className={btn}>{TRIAL_CTA}</Link>
      </p>

      <div role="radiogroup" aria-label="Billing period" className="mt-8 inline-flex rounded-xl border border-border bg-white p-1">
        {(["month", "year"] as const).map((i) => (
          <button
            key={i}
            type="button"
            role="radio"
            aria-checked={interval === i}
            onClick={() => setInterval(i)}
            className={`h-10 rounded-lg px-4 text-[15px] font-bold ${interval === i ? "bg-teal text-white" : "text-ink hover:bg-ground"}`}
          >
            {i === "month" ? "Monthly" : "Annual · 2 months free"}
          </button>
        ))}
      </div>

      <ul className="mt-4 grid gap-4 md:grid-cols-3" aria-label="Plans">
        {plans.map((p) => {
          const price = interval === "month" ? p.price_month_pence : p.price_year_pence;
          return (
            <li key={p.code} data-plan-card={p.code} className={`flex flex-col rounded-2xl border bg-white p-5 ${p.code === "comprehensive" ? "border-2 border-teal" : "border-border"}`}>
              <h2 className="text-xl font-extrabold">{p.name}</h2>
              <p className="mt-1 text-sm text-muted">{WHO_FOR[p.code]}</p>
              <p className="mt-4 text-3xl font-extrabold" data-price={interval}>
                {money(price)}
                <span className="text-base font-semibold text-muted"> {interval === "month" ? "a month" : "a year"}</span>
              </p>
              <p className="text-sm text-muted">
                ex VAT · {money(withVat(price))} with VAT
                {interval === "year" && ` · ${money(perMonth(p, "year"))} a month, ${money(annualSaving(p))} saved`}
              </p>
              <Link href="/connect?next=%2Fsettings%23plan-billing" className="mt-5 inline-flex h-11 items-center justify-center rounded-xl border-2 border-teal px-4 text-[15px] font-bold text-teal-dark hover:bg-teal-tint">
                {TRIAL_CTA}
              </Link>
            </li>
          );
        })}
      </ul>

      <h2 className="mt-10 text-2xl font-extrabold tracking-tight">What each plan includes</h2>
      <div className="mt-3">
        <LimitsTable plans={plans} />
      </div>

      <section aria-labelledby="pricing-notes" className="mt-10 space-y-3 text-[15px] leading-7">
        <h2 id="pricing-notes" className="text-2xl font-extrabold tracking-tight">Good to know</h2>
        <p>
          <strong>Bring your own AI.</strong> Use your own API key or a local model on any plan. AI-read documents and Ask then become fair use, with no
          monthly cap, and the price does not change.
        </p>
        <p>
          <strong>Top-ups.</strong> Need more documents in a busy month? {TOPUP_DOCS} extra AI-read documents cost {money(TOPUP_PENCE)}, valid for 12 months, on any plan.
        </p>
        <p>
          <strong>Nothing is ever locked away.</strong> At a limit, new reading pauses with a friendly note; approving, editing and exporting what is already in your books always works. If a trial ends without a card, your books become read-only and are never deleted.
        </p>
        <p>
          <strong>Your books stay yours.</strong> They live in your own OneDrive; we keep only your account, plan and usage counts.{PROVIDER_NAME[BUILD_PAYMENTS_PROVIDER] ? ` Payment is taken by ${PROVIDER_NAME[BUILD_PAYMENTS_PROVIDER]}.` : ""}
        </p>
        <p className="rounded-xl bg-teal-tint p-4" data-market-line="">
          For comparison, comparable plans from well-known UK accounting software cost about £14 to £56 a month ex VAT, and tools that only read documents charge roughly
          £0.21 to £0.31 a document. Accnomos Comprehensive is £20 a month and includes 300 (checked 9 November 2026).
        </p>
      </section>

      <p className="mt-8">
        <Link href="/connect?next=%2Fsettings%23plan-billing" className={btn}>{TRIAL_CTA}</Link>
      </p>
    </div>
  );
}
