/**
 * Which provider takes payment for Accnomos plans (the runtime's PAYMENTS_PROVIDER, app/billing/payments.py). `none`
 * by default: the plans, the free trial and promo codes show and work, and nothing offers to take money or names a
 * payment company. The runtime says which on GET /account (`payments_provider`); pages with no account to ask (the
 * pricing and privacy pages) use the build's NEXT_PUBLIC_PAYMENTS_PROVIDER. A new provider is one more name here and
 * in the runtime; the buttons only ask `takesPayments`. Not the invoice payment links (the user's own Stripe or
 * PayPal, components/settings/OnlinePayments.tsx), which are separate. Pure: no imports.
 */
export type PaymentsProvider = "none" | "stripe";
export const PAYMENTS_PROVIDERS: PaymentsProvider[] = ["none", "stripe"];

export const readProvider = (v: unknown): PaymentsProvider =>
  typeof v === "string" && (PAYMENTS_PROVIDERS as string[]).includes(v) ? (v as PaymentsProvider) : "none";

/** The build's setting, for pages without an account. Unknown or unset: none. */
export const BUILD_PAYMENTS_PROVIDER: PaymentsProvider = readProvider(process.env.NEXT_PUBLIC_PAYMENTS_PROVIDER);

export const takesPayments = (p: PaymentsProvider): boolean => p !== "none";

/** The provider's name, for the one line that says who holds the card (nothing when payments are off). */
export const PROVIDER_NAME: Record<PaymentsProvider, string | null> = { none: null, stripe: "Stripe" };

/** Shown where a paid upgrade would be when payments are off. Neutral: no date, no promise. */
export const PAYMENTS_OFF_NOTE = "Paid plans can't be bought here at the moment. Your free trial and promo codes work as usual.";
