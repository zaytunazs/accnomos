"use client";

import Link from "next/link";
import { useEffect } from "react";

/** Where the payment provider sends the browser back (BILLING_RETURN_URL = /settings/billing): PayPal after approving
 *  or cancelling a subscription (?checkout=…), a plan change (?change=…) or a top-up order (?topup=…), plus PayPal's
 *  own `subscription_id` / `ba_token` / `token`; Stripe after Checkout or its portal. Forwarded to Plan & billing,
 *  which reads `checkout`, `change` and `topup`; the rest is ignored (the webhook is what changes the plan). */
export default function BillingReturn() {
  useEffect(() => {
    window.location.replace(`/settings${window.location.search}#plan-billing`);
  }, []);
  return (
    <p className="mx-auto max-w-xl p-6 text-sm text-muted">
      Opening <Link href="/settings#plan-billing" className="font-bold text-teal-dark underline underline-offset-2">Plan &amp; billing</Link>…
    </p>
  );
}
