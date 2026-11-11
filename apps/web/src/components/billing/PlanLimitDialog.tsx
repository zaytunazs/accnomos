"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import Modal, { primaryButton, secondaryButton } from "@/components/invoices/Modal";
import { useAccount } from "@/components/jobs/useAccount";
import { billingApi } from "@/lib/billing-api";
import { TOPUP_DOCS, TOPUP_PENCE, money } from "@/lib/billing";
import { PLAN_LIMIT_EVENT, planLimitMessage, takeLastPlanLimit, topUpHelps, type PlanLimitInfo } from "@/lib/plan-limit";
import { track } from "@/lib/analytics";

/**
 * The one dialog for HTTP 402 {code:"plan_limit"} (lib/billing.ts handlePlanLimit, called from lib/runtime.ts for every
 * failed call). Friendly, with a top-up (documents only) or an upgrade; nothing already in the books is ever locked.
 */
export default function PlanLimitDialog() {
  const account = useAccount();
  const [info, setInfo] = useState<PlanLimitInfo | null>(() => takeLastPlanLimit());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const on = (e: Event) => {
      takeLastPlanLimit();
      setError(null);
      setInfo((e as CustomEvent<PlanLimitInfo>).detail);
      track("plan_limit_shown", { limit: (e as CustomEvent<PlanLimitInfo>).detail.limit_key ?? "unknown" });
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
      track("topup_click", { from: "limit_dialog" });
      const { url } = await billingApi.topup(account);
      window.location.assign(url);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <Modal id="plan-limit-title" title="You have reached your plan's limit" onClose={() => setInfo(null)}>
      <div data-plan-limit="">
        <p className="mt-3 text-[15px] leading-7 text-ink">{planLimitMessage(info)}</p>
        {info.message && <p className="mt-2 text-sm text-muted">{info.message}</p>}
        <p className="mt-2 text-sm text-muted">
          Usage resets on the 1st of each month. You can also use your own AI, which has no monthly cap on documents or questions.
        </p>
        {error && (
          <p role="alert" className="mt-3 text-sm font-bold text-red-700">
            {error}
          </p>
        )}
        <div className="mt-5 flex flex-wrap gap-2">
          {topUpHelps(info) && (
            <button type="button" className={primaryButton} disabled={busy || !account} onClick={topUp}>
              Buy {TOPUP_DOCS} documents for {money(TOPUP_PENCE)}
            </button>
          )}
          <Link href="/settings#plan-billing" onClick={() => setInfo(null)} className={`${topUpHelps(info) ? secondaryButton : primaryButton} inline-flex items-center`}>
            Upgrade or change plan
          </Link>
          <button type="button" className={secondaryButton} onClick={() => setInfo(null)}>
            Not now
          </button>
        </div>
      </div>
    </Modal>
  );
}
