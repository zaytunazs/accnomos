# Web and Android billing, admin and analytics: what the apps read (11 Nov 2026)

Companion to `PLANS_AND_CONTRACT.md`. The JSON shapes are pinned, key by key, in **`docs/billing/api_shapes.json`**:

- `services/runtime/tests/test_billing_contract.py` calls every billing, account, analytics and admin endpoint (in-memory
  registry, Stripe fake) and fails when an answer's keys differ from the file. After a deliberate change:
  `UPDATE_API_SHAPES=1 uv run pytest services/runtime/tests/test_billing_contract.py`, then commit the file.
- `apps/web/tests/unit/api-shapes.test.ts` (`pnpm test:unit`) fails when the web's types (`src/lib/billing.ts`,
  `admin.ts`, `plan-limit.ts`, listed key by key in `src/lib/billing-wire.ts`, which tsc ties to the types) are missing
  a key the runtime sends or name one it does not, and runs each reader over a response built from the shape.

So a key renamed on either side fails CI. The readers (`admin.ts`) still never throw: a missing number is 0, a list empty.

## Decisions (where the first UI guessed differently)

1. **402 bodies** are the runtime's (`app/billing/service.py`): `{code: "plan_limit", counter, limit, used,
   upgrade_url, detail}` and `{code: "read_only", status: "trial_ended"|"cancelled", upgrade_url, detail}`, top level
   (the middleware) or under FastAPI's `detail`. The web (`lib/plan-limit.ts`, `PlanLimitDialog`) and Android
   (`lib/services/plan_limit.dart`) show one dialog for both: a plan limit offers a top-up (documents only) or an
   upgrade; read-only says the trial ended / the plan was cancelled, that everything can still be viewed and exported,
   and links to choose a plan. **iOS** shows the same words with no link, price or "on the web"
   (`StorePolicy.purchaseLinksAllowed`, which also hides More › Plan & billing).
2. **`GET /account`** without billing on the runtime is `{configured: false, detail}`: Settings › Plan & billing shows
   only that sentence (no plans, meters or buttons), and Privacy keeps the analytics choice on the device only.
   Configured, it also carries `read_only`, `current_period_end`, `cancel_at_period_end`, `has_payment_account`
   (Manage card & invoices is off without a Stripe customer), `upgrade_url` and `analytics_opt_out`. A set-up count in
   `usage` (`bank_feeds`, `users`, `marketplaces`, `autopilot_rules`) is null when the books could not be read: no meter.
3. **Limit keys** are the runtime's counters: `docs`, `ask`, `invoices`, `bank_feeds`, `users`, `marketplaces`,
   `payroll_employees`, `autopilot_rules` (a number; 0 not on the plan; null unlimited), `multi_currency` and
   `projects` (booleans), `support` (`email` | `priority_email`, shown as Email / Priority email).
4. **`POST /events`** takes one event or a batch `{events: [...]}` (1 to 20). In a batch each event is checked on its
   own (one the rules refuse is dropped, the rest kept) and the answer is `202 {accepted, dropped}`; every event takes a
   token from the same per-account rate limit (429 when it runs out). The web sends batches only, and drops client-side
   any property or event name the runtime's rules would refuse (`lib/analytics-core.ts` mirrors `PROP_RULES` and
   `SERVER_ONLY`).
5. **Admin lists** (`/admin/users`, `/admin/audit`, `/admin/bug-reports`) are `{items, page, per_page, total}`; codes and
   plans are bare lists. Audit and redemption ids are numbers.
6. **Bug-report screenshots**: the admin asks `GET /admin/bug-reports/{id}/screenshot` → `{url, expires_in}` (a
   signed storage link) when "Show screenshot" is pressed. Reports are never returned with the image inline.
7. **Stripe summary** on `GET /admin/users/{id}`: `{customer, subscription: {id, status, cancel_at_period_end,
   current_period_end, trial_end} | null, invoices: [{id, number, status, total, currency, created,
   hosted_invoice_url}], error?}`; times are Stripe's seconds since 1970, totals pence. `stripe` is null without a
   Stripe customer.
8. **Admin writes**: `PATCH /admin/codes/{code}` takes only `active`, `max_redemptions`, `expires_at`, `plan_codes`
   (kind and value are fixed once made). An action answers `{ok, account, message?, url?}`: `send_portal_link` returns
   the portal `url` for the admin to pass on; nothing is emailed.
9. **Back from Stripe**: Checkout and the portal return to `$ACCNOMOS_WEB_URL/settings/billing?checkout=…|topup=…`
   (also the 402 `upgrade_url`); the web's `/settings/billing` page forwards to Settings › Plan & billing, which says
   how it went.

10. **Payments are off by default** (`PAYMENTS_PROVIDER`, runtime `app/billing/payments.py`; web `src/lib/payments.ts`):
    `none` unless set to `stripe`. `GET /account` carries `payments_provider`; with `none` Plan & billing shows the
    plans, the trial and promo codes with a neutral note instead of Upgrade, Manage card & invoices, the checkout promo
    field and the top-up; the 402 dialog offers no top-up; 402 `detail` sentences give no buying advice; checkout,
    portal and top-up answer 503; no page names a payment company (`/pricing` and `/privacy` follow
    `NEXT_PUBLIC_PAYMENTS_PROVIDER`). The Stripe code is unchanged behind the flag; another provider is one more name
    in both `payments` modules plus its own module beside `stripe_api.py`.

The admin link shows in the account menu only when `GET /admin/metrics` succeeds; every `/admin/*` page checks it again.

## Test mode

A `NEXT_PUBLIC_TEST_MODE=1` build answers all of the above in the browser (`apps/web/src/lib/billing-fake.ts`, in the
runtime's shapes), so the e2e specs need no backend support. `localStorage["accnomos.test.admin"] = "1"` makes the fake
account an administrator; `accnomos.test.billing` (`{account: {...}}`, or `{configured: false}` for billing off)
overrides the fake account; calls are recorded in `accnomos.test.billing.calls`.

## Web error reporting (Sentry), when used

Set `NEXT_PUBLIC_SENTRY_DSN` at build time (an EU-region project); unset, the SDK is not in the bundle. It runs with
personal data off, no cookies, headers, bodies or query strings, no breadcrumbs, and a scrubber over every event
(`apps/web/src/lib/sentry.ts`). When used, add the ingest host to `connect-src` in `apps/web/public/.htaccess` (both the
enforced and the report-only policy), for example `https://o0000000.ingest.de.sentry.io`; leave it out when the DSN is unset.

## Android

More has "Plan & billing" (opens `https://accnomos.com/settings#plan-billing` in the browser: nothing is sold in the app;
not shown on iOS) and "Report a problem" (`POST /bug-reports`, `app: "android"`, no screenshot). A 402 `plan_limit` or
`read_only` from any call opens the dialog described above.
