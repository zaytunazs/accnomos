# Review: payment links on invoices (Stripe, PayPal, PayPal.me)

Branch `claude/payment-links`. Customers can pay an invoice online into the **user's own** Stripe or PayPal account;
the payment is found the next time the user opens Invoices and posted only when they approve it. Test mode only.
Nothing in this branch has called Stripe or PayPal: every provider call in tests and test mode goes to fakes.

## Sources (all read 28 Oct 2026)

| What | Source |
|---|---|
| Stripe Connect OAuth: authorize URL and params, `POST /oauth/token` returns `stripe_user_id`, `livemode`; `access_token`, `refresh_token` marked **deprecated** ("Use the Stripe-Account header"); `POST /oauth/deauthorize` | https://docs.stripe.com/connect/oauth-reference |
| "OAuth isn't recommended for new Connect platforms"; Standard-account OAuth flow, `state` for CSRF, store `stripe_user_id` | https://docs.stripe.com/connect/oauth-standard-accounts |
| Connect Onboarding / Account Links (creates a **new** account); "If you're an extension or an application that needs access to an existing account … you can still use OAuth"; page marked legacy in favour of Accounts v2 | https://docs.stripe.com/connect/standard-accounts |
| Accounts v2 must use v1 for "OAuth to authenticate connected accounts" | https://docs.stripe.com/connect/accounts-v2/saas-platform-payments-billing |
| `Stripe-Account: acct_…` with the platform secret key | https://docs.stripe.com/connect/authentication |
| Prices: `unit_amount` "in the smallest currency unit", `product_data[name]` | https://docs.stripe.com/api/prices/create |
| Payment Links: `line_items`, `metadata` (copied to sessions), `payment_intent_data`, `restrictions.completed_sessions.limit`, `after_completion`, `inactive_message` | https://docs.stripe.com/api/payment-link/create |
| Checkout Sessions (create: `expires_at` 30 min to 24 h, so unsuitable for an invoice emailed with 30-day terms) | https://docs.stripe.com/api/checkout/sessions/create |
| List Checkout Sessions by `payment_link`, `status=complete` | https://docs.stripe.com/api/checkout/sessions/list |
| Expand up to four levels, `data.` prefix in lists | https://docs.stripe.com/expand |
| Balance transaction `fee` in pence | https://docs.stripe.com/api/balance_transactions/object |
| Connect webhooks: `account` on events, `payment_intent.succeeded` for direct charges; signature verification | https://docs.stripe.com/connect/webhooks, https://docs.stripe.com/webhooks/signature |
| UK pricing 1.5% + 20p standard UK cards; Connect "included at no additional charge" on standard pricing | https://stripe.com/gb/pricing |
| No VAT on Stripe fees for European account holders (UK not in the exception list; not stated explicitly) | https://support.stripe.com/questions/taxation-of-stripe-fees |
| PayPal multiparty: partner form, live access only after approval | https://developer.paypal.com/docs/multiparty/ |
| Partner Referrals (`THIRD_PARTY` features, `action_url`), return params `merchantIdInPayPal`, `permissionsGranted`, `consentStatus`; merchant-integrations status; "must be an approved PayPal partner" | https://developer.paypal.com/docs/multiparty/seller-onboarding/before-payment/ |
| `INVOICE_READ_WRITE` in `rest_endpoint_features_enum` (Partner Referrals schema 2.5) | https://developer.paypal.com/api/partner-referrals/v2/schema.json |
| Client-credentials token | https://developer.paypal.com/api/rest/authentication/ |
| `PayPal-Auth-Assertion` (unsigned JWT, `iss`, `payer_id`, Base64 parts), `PayPal-Request-Id`, `PayPal-Partner-Attribution-Id` | https://developer.paypal.com/api/rest/requests.md |
| Invoicing v2 (schema 2.12): create, send (`send_to_recipient`), `recipient_view_url`, `payments.transactions[]`, cancel, statuses | https://developer.paypal.com/api/invoicing/v2/schema.json |
| Orders v2 (schema 2.36): `seller_receivable_breakdown.paypal_fee`; approved orders must be captured, default window 3 hours | https://developer.paypal.com/api/orders/v2/schema.json, https://developer.paypal.com/payment-methods/uncaptured-payments.md |
| PayPal.me: `PayPal.Me/DiaRusso/25AUD`; `https://paypal.me/PayPal/10.50GBP` answered 301 to `paypal.com/paypalme/PayPal/10.50GBP` (path kept) | https://www.paypal.com/uk/cshelp/article/what-is-paypalme-help432, curl on 28 Oct 2026 |

## Design, and why

- **Stripe: Connect OAuth on Standard accounts, then Payment Links on the connected account.** The brief is the user's
  *own* account. Stripe's recommended onboarding (Account Links / Accounts v2) creates a new, platform-controlled
  account; OAuth is the documented path for "an application that needs access to an existing account". Stripe still
  returns `access_token`/`refresh_token` but calls them deprecated, so **no token is stored**: calls use the platform key
  plus `Stripe-Account`. A Payment Link (not a Checkout Session, which expires within 24 h) with
  `restrictions[completed_sessions][limit]=1`, so it is paid once and then switches itself off. The platform takes no
  fee (no `application_fee_amount`); charges are direct, so Stripe's fee is the user's. The link carries an opaque
  `accnomos_ref` (random) and the invoice number in metadata, nothing about the customer.
- **PayPal: partner onboarding + Invoicing v2 for the merchant.** Orders v2 needs a capture within about 3 hours of the
  customer approving, which a stateless server with no stored tokens cannot promise for a link sitting on an invoice;
  a PayPal invoice is paid on PayPal's page and needs no capture. We create it on the merchant's account
  (`PayPal-Auth-Assertion`), send it with `send_to_recipient: false` (the user emails our invoice), and give the
  customer its `recipient_view_url`. Merchant id only; no tokens.
- **PayPal.me fallback**: `https://paypal.me/<name>/<pounds>.<pence>GBP`, no API. Never matched by code; recorded by hand.
- **Connect flow** mirrors the HMRC relay: `POST /payments/online/{p}/start` → provider → runtime callback (checks a
  signed state, spends it) → `303` to `/settings#pay=…&code|merchant_id=…&state=…` → Settings posts back with the
  Graph token. The state (HMAC, 15 min, one use per step) carries the provider, Settings URL (must be on a
  `CORS_ORIGINS` origin), a hash of the signed-in user and the hash of a random secret held only in that tab's
  `sessionStorage`, so a code started in another browser cannot be linked to these books. PayPal's merchant is also
  checked with PayPal (`tracking_id` must be this sign-up's nonce, payments receivable, email confirmed, permissions given).
- **Stored in the user's books**: `_System/Payments/providers.json` (beside `payments.json`; OneDrive ignores case, so
  this is the brief's `_System/payments/`): `{stripe: {account_id, livemode, connected_at, connected_by}, paypal:
  {merchant_id, sandbox, …}, paypalme: {username, …}}`. No refresh token is needed by either provider, so nothing is
  encrypted and no server-side key is introduced.
- **Link on the invoice**: `payment_link` on the invoice JSON (`provider, url, amount_pence, test_mode, provider_ref,
  account_ref, ref`). Amount is the draft's total or the sent invoice's balance (after part payments and credit notes).
  It appears on the PDF (clickable, with "TEST MODE: this link takes no real money"), in the send email and appended
  by code to reminder drafts (the model is still never allowed to write a link). A new link switches the old one off
  first (Stripe `active=false`, PayPal cancel). A draft edited to another total is refused at send until the link is
  remade or removed.
- **Payment received — poll on open, not webhooks.** A webhook arrives with no Graph token, so the runtime cannot write
  to the user's OneDrive, and there is no database to park it in; it would add nothing a poll does not. Opening
  Invoices calls `GET /payments/online/check`: for each sent invoice with a Stripe/PayPal link (oldest due first, up to
  50, 4 at a time) it lists completed Checkout Sessions for the link (fee from the expanded balance transaction) or
  reads the PayPal invoice's transactions (fee from the capture). Payment ids already recorded are skipped. Each find
  is a proposal with the journal code would post. **Approve** (`confirm: true`) re-reads the provider (amounts never
  come from the browser), posts Dr 1200 Bank / Cr 1100 Debtors through `payments.record_payment` (reference
  `Stripe cs_…`) and the fee as a separate `purchase`: Dr 7900 Bank charges (VAT code E) / Cr 1200 Bank, then
  remembers the id on the invoice. A retry after a failure part way finds the payment by its reference and finishes
  without recording it twice. If the provider has not reported the fee yet the user types it (or waits).
- **Test mode only by default.** Live Stripe keys (`sk_live_`) and PayPal's live API are refused unless
  `PAYMENTS_LIVE=1`; a Stripe account linked in live mode is refused and deauthorised. TEST MODE badges in Settings,
  on the link, in the dialog, on found payments and on the PDF/email.
- **Off by default**: no env → each provider says "… payment links are not set up on this server yet." PayPal.me is
  always available.

## What the owner must set up (in the server `.env`; placeholders in `.env.example`, table in `docs/PRODUCTION.md` §3a)

1. **Stripe platform account** (UK). In **test mode**: Settings › Connect › enable Connect; Onboarding options › OAuth:
   enable OAuth, note the test `client_id` (`ca_…`), add the redirect URI
   `https://api.accnomos.com/payments/online/stripe/callback`; brand the Connect settings (name, icon). Set
   `STRIPE_SECRET_KEY` (test `sk_test_…`), `STRIPE_CONNECT_CLIENT_ID`, `STRIPE_REDIRECT_URI`. No webhook endpoint.
2. **PayPal**: a developer account, a REST app (Sandbox) → `PAYPAL_CLIENT_ID`/`PAYPAL_CLIENT_SECRET`; the partner's
   sandbox merchant id → `PAYPAL_PARTNER_MERCHANT_ID`; a BN code → `PAYPAL_PARTNER_ATTRIBUTION_ID`;
   `PAYPAL_RETURN_URL=https://api.accnomos.com/payments/online/paypal/callback`. Partner Referrals and acting for
   merchants need PayPal to **approve the platform as a partner** (the "Tell us about your platform" form); until then
   leave PayPal empty and users can use PayPal.me.
3. Leave `PAYMENTS_LIVE` empty. `CORS_ORIGINS` must include the web origin (already does).

## Tests

- `services/runtime/tests/test_online_payments.py`: **31 tests**: pence → Stripe minor units / PayPal `"372.00"` /
  PayPal.me and back (other currencies and three decimals refused); fake fees; auth-assertion format; off by default
  with the sentence; live keys refused unless `PAYMENTS_LIVE=1`; signed state (tamper, other provider, expiry, one use
  per step, redirect allow-list, other browser, other user); Stripe connect stores only `acct_…` (deprecated tokens
  dropped), consent error, live account refused and deauthorised; link creation request shapes (form fields,
  `Stripe-Account`, idempotency keys, nothing about the customer), PDF annotation, email and reminder text; part-paid
  balance and old link switched off; check → approve with exact journal and fee event, no double proposal or approve;
  fee pending typed in; already-paid invoice not checked; retry after a failure part way; disconnect needs `confirm`
  and deauthorises; stale draft link blocks sending; PayPal sign-up body, merchant check (`tracking_id`), consent not
  given, invoice create/send/cancel bodies, fee from capture or unknown; PayPal.me with no provider call; provider
  down is a "problem", not a failure.
- `tests/test_security_routes.py`: `payment_providers.py` / `online_fakes.py` added to the HTTP allow-list, plus
  `test_payment_provider_calls_go_only_to_the_configured_provider_bases`.
- e2e `apps/web/e2e/online-payments.spec.ts` (**2 tests**, test mode): Settings connects Stripe and PayPal through the
  fake consent pages, saves a PayPal.me name, disconnects; an invoice gets a Stripe link with Copy and TEST MODE, the
  customer pays on the fake page, Invoices shows "Paid online" with fee and journal, Approve records it and the
  invoice is Paid.
- Gate results are in the hand-off message of this branch.

## Risks and open points

- **Never run against Stripe or PayPal** (not even test/sandbox); fakes follow the documented shapes. The first real
  sandbox run may find field-level differences (most likely: PayPal invoice `payment_id` vs capture id for the fee,
  PayPal's handling of `PayPal-Auth-Assertion` on Invoicing, which its schema does not list).
- Stripe OAuth is "not recommended for new platforms"; if Stripe withdraws it, the alternative (Accounts v2) means the
  platform creates and controls the user's Stripe account, a different product decision.
- PayPal partner approval may not be granted to a small platform; PayPal.me is the fallback and is not matched.
- **Double counting with the bank feed**: gross and fee go through 1200 Bank when approved; the provider's later
  payout on the statement is the same money and must be marked as a transfer. A Stripe/PayPal clearing account with
  payout matching would be more correct; not built.
- Payments are seen only when the user opens Invoices; nothing nudges them otherwise. Paid invoices are not checked,
  so money received on an invoice already settled another way is not proposed.
- Fixed-amount links go stale when the balance changes; flagged in the list, not automatically remade.
- Fee VAT code E (exempt) is our reading of Stripe's page and UK practice for payment processing; the user approves
  each line.
- The `state` spent-set is in memory per process: run one runtime worker (as for the relay) or a replay across
  workers is possible within 15 minutes (it still needs the user's browser secret and Graph token).
