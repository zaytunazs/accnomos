"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import Modal, { primaryButton, secondaryButton } from "@/components/invoices/Modal";
import { useAccount } from "@/components/jobs/useAccount";
import { billingApi } from "@/lib/billing-api";
import { TOPUP_DOCS, TOPUP_PENCE, money } from "@/lib/billing";
import { PLAN_LIMIT_EVENT, currentPlanLimit, dismissPlanLimit, planLimitMessage, refusalTitle, topUpHelps, type BillingRefusal } from "@/lib/plan-limit";
import { track } from "@/lib/analytics";
import { takesPayments } from "@/lib/payments";

/**
 * The one dialog for HTTP 402 (lib/plan-limit.ts handlePlanLimit, called from lib/runtime.ts for every failed call):
 * `plan_limit` offers a top-up (documents only) or an upgrade; `read_only` (trial ended, plan cancelled) offers a
 * plan. Friendly either way; nothing already in the books is ever locked away.
 */
export default function PlanLimitDialog() {
  const account = useAccount();
  // A top-up is offered only when the runtime takes payments (lib/payments.ts); asked once, when the dialog first opens.
  const [pays, setPays] = useState(false);
  useEffect(() => {
    if (!account) return;
    billingApi
      .account(account)
      .then((a) => setPays(a.configured && takesPayments(a.payments_provider)))
      .catch(() => setPays(false));
  }, [account]);
  const [info, setInfoState] = useState<BillingRefusal | null>(() => currentPlanLimit());
  const setInfo = (v: BillingRefusal | null) => {
    if (v === null) dismissPlanLimit();
    setInfoState(v);
  };
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const on = (e: Event) => {
      setError(null);
      const detail = (e as CustomEvent<BillingRefusal>).detail;
      setInfo(detail);
      if (detail.code === "plan_limit") track("plan_limit_shown", { feature: detail.counter ?? "unknown" });
      else track("read_only_shown", { result: detail.status ?? "unknown" });
    };
    window.addEventListener(PLAN_LIMIT_EVENT, on);
    return () => window.removeEventListener(PLAN_LIMIT_EVENT, on);
  }, []);

  if (!info) return null;

  async function topUp() {
    if (!account) return;
    setBusy(true);
    setError(null);
    try {
      track("topup_click", { source: "limit_dialog" });
      const { url } = await billingApi.topup(account);
      window.location.assign(url);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <Modal id="plan-limit-title" title={refusalTitle(info)} onClose={() => setInfo(null)}>
      <div data-plan-limit={info.code}>
        <p className="mt-3 text-[15px] leading-7 text-ink">{planLimitMessage(info)}</p>
        {info.code === "read_only" && (
          <p className="mt-2 text-sm text-muted">
            {pays ? "Choose a plan to carry on adding and changing things." : "Redeem a promo code under Plan & billing to carry on adding and changing things."}
          </p>
        )}
        {info.code === "plan_limit" && (
          <p className="mt-2 text-sm text-muted">
            Usage resets on the 1st of each month. You can also use your own AI, which has no monthly cap on documents or questions.
          </p>
        )}
        {error && (
          <p role="alert" className="mt-3 text-sm font-bold text-red-700">
            {error}
          </p>
        )}
        <div className="mt-5 flex flex-wrap gap-2">
          {pays && topUpHelps(info) && (
            <button type="button" className={primaryButton} disabled={busy || !account} onClick={topUp}>
              Buy {TOPUP_DOCS} documents for {money(TOPUP_PENCE)}
            </button>
          )}
          <Link href="/settings#plan-billing" onClick={() => setInfo(null)} className={`${pays && topUpHelps(info) ? secondaryButton : primaryButton} inline-flex items-center`}>
            {info.code === "read_only" ? "Choose a plan" : pays ? "Upgrade or change plan" : "See your plan"}
          </Link>
          <button type="button" className={secondaryButton} onClick={() => setInfo(null)}>
            Not now
          </button>
        </div>
      </div>
    </Modal>
  );
}
