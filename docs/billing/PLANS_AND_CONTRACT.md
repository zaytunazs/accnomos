# Plans, limits and the billing/admin API contract (11 Nov 2026)

Decision log
- Account registry in **Supabase Postgres** (UK/EU region). It holds account metadata only: email, sign-in kind,
  plan, billing status, trial dates, promo redemptions, monthly usage counts, admin notes and an admin audit log.
  Never books, documents, receipts or tokens for other services.
- Payments by **Stripe** (Checkout, Billing, Customer Portal, webhooks). Stripe is the source of truth for payment
  state; Supabase mirrors it from webhooks.
- **3-month free trial, no card.** Card asked before the trial ends (Stripe trial with
  `payment_method_collection=if_required`; reminder email 7 days before the end; if no card, the account drops to
  read-only "Trial ended", never deleted).
- **Promo codes** created in the admin: percent off, fixed off, or free months (e.g. `YEARFREE` = 12 months free),
  optional plan restriction, max redemptions, expiry date.
- Prices are **ex VAT** (UK VAT 20% added at checkout), shown with the inc-VAT figure for UK customers.
- Annual billing: 2 months free (Starter £100, Comprehensive £200, Ultimate £500 a year ex VAT).

## Plans

Market anchors (ex VAT, steady-state, checked 9 Nov 2026): Xero Ignite £18 (20 invoices, 10 bills), Grow £39,
Comprehensive £55; QuickBooks Simple Start £16, Essentials £38, Plus £56; Sage Start £14, Standard £28; FreeAgent
£19 / £33; Dext £24.17 for 250 documents; AutoEntry ~£0.21–£0.31 a document.

| Limit (per month unless stated) | Starter £10 | Comprehensive £20 | Ultimate £50 |
|---|---|---|---|
| Who it's for | Sole traders, side businesses | VAT-registered sole traders, small companies | Busier companies, online sellers, teams |
| Users (accountant access is free and extra) | 1 | 3 | 10 |
| AI-read documents (receipts, bills, statements) | 50 | 300 | 1,500 |
| Ask questions | 100 | 500 | 3,000 (fair use) |
| Live bank feeds | 1 | 3 | Unlimited |
| Sales invoices and quotes | 20 | Unlimited | Unlimited |
| Marketplace connections (eBay; Amazon later) | — | 1 | Unlimited |
| VAT returns (prepare, export, file once HMRC live) | ✓ | ✓ | ✓ |
| Income Tax: Self Assessment and quarterly figures | ✓ | ✓ | ✓ |
| Payroll (employees) | — | Up to 3 | Up to 20 |
| Autopilot rules | 5 | Unlimited | Unlimited |
| Multi-currency, projects/job costing | — | — | ✓ |
| Support | Email | Email | Priority email |

- **Bring your own AI** (own API key or local model): available on every plan; AI-read documents and Ask become fair
  use (no monthly cap). Price unchanged.
- **Top-up:** 100 extra AI-read documents for £3 (valid 12 months), any plan.
- Limits live in the `plans` table, editable in the admin without a deploy. Usage resets on the 1st of each month
  (UTC).
- At a limit: the action is refused with a friendly message offering a top-up or upgrade. Approving, editing and
  exporting existing work is never blocked; nothing already in the books is ever locked away.

## Data model (Supabase, schema `accnomos`)

- `accounts`: id (uuid), email, display_name, auth_kind (`personal`|`work`|`google`), auth_subject (stable id from
  Graph `/me` id or Google `sub`), created_at, last_seen_at, plan_code, status (`trialing`|`active`|`past_due`|
  `trial_ended`|`cancelled`|`comped`), trial_ends_at, comp_until, stripe_customer_id, stripe_subscription_id,
  billing_interval, country, notes. Unique (auth_kind, auth_subject).
- `plans`: code (`starter`|`comprehensive`|`ultimate`), name, price_month_pence, price_year_pence,
  stripe_price_month, stripe_price_year, limits jsonb, active, sort.
- `usage`: account_id, month (date, 1st), docs, ask, invoices, topup_docs_remaining; PK (account_id, month).
- `promo_codes`: code, kind (`percent`|`fixed`|`free_months`), value, plan_codes text[] null=any, max_redemptions,
  redeemed_count, expires_at, active, created_by, stripe_coupon_id.
- `redemptions`: code, account_id, redeemed_at.
- `admin_audit`: id, at, admin_email, account_id null, action, detail jsonb.
- Row-level security on; only the runtime's service role reads/writes. Nothing is exposed to browsers directly.

## API (runtime; JSON; auth = the existing `X-Graph-Token` + `X-Account-Kind` headers)

Public
- `GET /plans` → `[{code, name, price_month_pence, price_year_pence, limits}]`

Customer
- `GET /account` → `{id, email, plan_code, status, trial_ends_at, comp_until, billing_interval,
  usage: {docs, ask, invoices, bank_feeds, users, marketplaces, topup_docs_remaining}, limits: {...}, own_ai: bool}`.
  First call registers the account (status `trialing`, trial 90 days, plan `comprehensive` during the trial).
- `POST /billing/checkout` `{plan_code, interval: "month"|"year", promo_code?}` → `{url}` (Stripe Checkout)
- `POST /billing/portal` → `{url}` (Stripe Customer Portal: card, invoices, cancel)
- `POST /billing/redeem` `{code}` → `{ok, message, account}` (free-months codes apply without Stripe)
- `POST /billing/topup` → `{url}` (Checkout for 100 documents)
- `POST /billing/stripe/webhook` (Stripe signature verified; idempotent by event id)

Admin (allow-list `ADMIN_EMAILS`, identity verified server-side; every write goes to `admin_audit`)
- `GET /admin/metrics` → signups by day (30 d), trialing, active by plan, past_due, cancelled, MRR (pence),
  trials ending in 7 days
- `GET /admin/users?q=&plan=&status=&page=` → paged list with usage this month
- `GET /admin/users/{id}` → account, usage history, redemptions, Stripe summary (subscription, last invoices), notes,
  audit for that user
- `PATCH /admin/users/{id}` `{plan_code?, trial_ends_at?, comp_until?, status?, notes?}`
- `POST /admin/users/{id}/actions` `{action: "extend_trial"|"apply_code"|"cancel_at_period_end"|"resume"|
  "send_portal_link"|"grant_topup", ...}`
- `GET /admin/codes`, `POST /admin/codes`, `PATCH /admin/codes/{code}`
- `GET /admin/plans`, `PATCH /admin/plans/{code}` (limits, active; a price change creates a new Stripe price)
- `GET /admin/audit?account_id=&page=`

## Analytics, error reports and bug reports

Decision log
- **Product analytics are first-party:** events go to Supabase `events` through the runtime, no third-party tracker,
  no cookies, no fingerprinting. Events carry the account id, an event name and a few non-financial properties
  (counts, durations, page, plan); never amounts, supplier names, document text, emails or file names. Users can turn
  analytics off in Settings › Privacy (`analytics_opt_out` on the account).
- **Errors:** Sentry (EU data region) for web, runtime and Android, with `send_default_pii=false`, request bodies,
  cookies, headers and query strings stripped, and a `before_send` scrubber that drops anything matching money,
  email, VAT number or token patterns. Enabled only when `SENTRY_DSN` is set. The admin shows the latest issues by
  linking to Sentry, plus our own counts.
- **Bug reports from users:** a "Report a problem" item (web Help menu and Android More) sends a message, the page,
  app version, browser/OS and, if the user ticks it, a screenshot; stored in Supabase `bug_reports`; triaged in the
  admin.

Data model additions
- `events`: id, at, account_id null, name, props jsonb, app (`web`|`android`|`api`), version.
- `bug_reports`: id, at, account_id, email, message, page, app, version, ua, screenshot_path null, status
  (`new`|`triaged`|`fixed`|`wont_fix`), admin_notes.
- Retention: events 13 months, bug reports until closed + 12 months.

API additions
- `POST /events` `{name, props, app, version}` (customer auth; dropped silently if opted out; rate-limited)
- `POST /bug-reports` `{message, page, app, version, ua, screenshot_b64?}` → `{id}`
- `GET /admin/analytics?from=&to=` → daily active accounts, sign-up → first document → first approval funnel,
  feature use counts (documents scanned, approvals, bank syncs, Ask questions, VAT/ITSA exports, eBay syncs), plan
  conversion from trial, top error counts by route (from runtime error logging), churn
- `GET /admin/bug-reports?status=&page=`, `PATCH /admin/bug-reports/{id}` `{status?, admin_notes?}`
