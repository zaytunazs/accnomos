import BillingReturn from "@/components/settings/BillingReturn";

export const metadata = { title: "Plan & billing · Accnomos", robots: { index: false, follow: false } };

/**
 * Where Stripe Checkout and the Customer Portal send people back, and the runtime's `upgrade_url`
 * (services/runtime/app/billing/stripe_api.py: $ACCNOMOS_WEB_URL/settings/billing). It opens Settings › Plan & billing,
 * keeping `?checkout=…` / `?topup=…` so the panel can say how it went.
 */
export default function BillingReturnPage() {
  return <BillingReturn />;
}
