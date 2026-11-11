"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAccount } from "@/components/jobs/useAccount";
import { analyticsOptedOut, setAnalyticsOptedOut } from "@/lib/analytics";
import { billingApi } from "@/lib/billing-api";

/** Settings › Privacy: the analytics opt-out. The choice is kept on the account (PATCH /account) and on this device. */
export default function PrivacySettings({ card, heading }: { card: string; heading: string }) {
  const account = useAccount();
  const [optOut, setOptOut] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    queueMicrotask(() => setOptOut(analyticsOptedOut()));
  }, []);

  useEffect(() => {
    if (!account) return;
    billingApi
      .account(account)
      .then((a) => {
        if (typeof a.analytics_opt_out === "boolean") {
          setOptOut(a.analytics_opt_out);
          setAnalyticsOptedOut(a.analytics_opt_out);
        }
      })
      .catch(() => undefined);
  }, [account]);

  async function toggle() {
    const next = !optOut;
    setOptOut(next);
    setAnalyticsOptedOut(next);
    setError(null);
    if (!account) return;
    setBusy(true);
    try {
      await billingApi.setAnalyticsOptOut(account, next);
    } catch (e) {
      setError(`Saved on this device, but not on your account yet: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="settings-privacy" className={card}>
      <h2 id="settings-privacy" className={heading}>Privacy</h2>
      <p className="mt-1 text-sm text-muted">
        We count how the product is used (which pages and features, how often) so we can fix what does not work. It is first-party: no cookies,
        no third-party trackers, and never amounts, supplier names, document text, emails or file names. Your books stay in your own storage.{" "}
        <Link href="/privacy#analytics" className="font-bold text-teal-dark underline underline-offset-2">What we keep and why</Link>
      </p>
      <div className="mt-3 flex items-center justify-between gap-3">
        <span id="analytics-optout-label" className="text-[15px] font-bold text-ink">Do not collect usage analytics</span>
        <button
          type="button"
          role="switch"
          aria-checked={optOut}
          aria-labelledby="analytics-optout-label"
          disabled={busy}
          onClick={toggle}
          className={`relative h-8 w-14 shrink-0 rounded-full border ${optOut ? "border-teal bg-teal" : "border-border bg-ground"}`}
        >
          <span className={`absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition-all ${optOut ? "left-[30px]" : "left-0.5"}`} />
        </button>
      </div>
      {error && <p role="alert" className="mt-2 text-sm font-bold text-red-700">{error}</p>}
    </section>
  );
}
