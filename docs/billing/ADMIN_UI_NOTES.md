# Web and Android billing, admin and analytics: what the UI expects (11 Nov 2026)

Companion to `PLANS_AND_CONTRACT.md`. The contract names the data and the endpoints but not every JSON key; these are
the shapes the web client (`apps/web/src/lib/billing.ts`, `admin.ts`, `billing-api.ts`) and the Android app read. The web
readers (`admin.ts`) are tolerant (missing numbers are 0, missing lists empty, a few alternative key names accepted), so
a near miss shows blanks, not errors.

## Contract additions the UI needs

1. `PATCH /account {analytics_opt_out: bool}` (customer auth) -> the account. The contract has the field on the account
   but no customer write endpoint. `GET /account` should also return `analytics_opt_out: bool` so the toggle shows it.
2. `POST /events` also accepts `{events: [{name, props, app, version}, ...]}` (up to 20) so the browser can batch. The
   web client falls back to one event per request (the contract's shape) if the runtime answers 400 or 422.
3. HTTP 402 body: `{code: "plan_limit", limit?: "docs"|"ask"|"invoices"|"bank_feeds"|"users"|"marketplaces"|
   "payroll_employees"|"autopilot_rules", message?: string, plan_code?: string}`, either top level or under FastAPI's
   `detail`. Any 402 without `code: "plan_limit"` is treated as an ordinary error.
4. `GET /account` `limits` keys are the same names as `usage` (`docs`, `ask`, `invoices`, `bank_feeds`, `users`,
   `marketplaces`) plus `payroll_employees`, `autopilot_rules`, `multicurrency` (bool) and `support` (text). `null` means
   unlimited, `0` or `false` means not included. `GET /plans` `limits` uses the same keys.
5. `POST /bug-reports` takes `screenshot_b64` (raw base64 image, no data-URL prefix, under about 1.5 MB). The web admin
   shows `screenshot_b64` on a bug report when the admin list returns it, else the `screenshot_path`.

## Admin response shapes

- `GET /admin/metrics`: `{signups: [{day, count}], trialing, active_by_plan: {starter, comprehensive, ultimate},
  past_due, cancelled, mrr_pence, trials_ending_7d}` (`signups_by_day`, an object of day to count, is accepted).
- `GET /admin/users?q=&plan=&status=&page=`: `{items: [row], total, page, page_size}` (a bare array is accepted). A row is
  the `accounts` columns plus `usage: {docs, ask, invoices, topup_docs_remaining}` for this month.
- `GET /admin/users/{id}`: `{account: row + notes, usage_history: [{month, docs, ask, invoices, topup_docs_remaining}],
  redemptions: [{code, redeemed_at}], stripe: {customer_id, subscription: {id, status, current_period_end,
  cancel_at_period_end}, invoices: [{id, created, amount_pence, status, url}]} | null, audit: [audit row]}`.
- `PATCH /admin/users/{id}` is sent `{plan_code}`, `{comp_until, status: "comped"}` or `{notes}`.
- `POST /admin/users/{id}/actions`: `{action: "extend_trial", days}`, `{action: "apply_code", code}`,
  `{action: "cancel_at_period_end"}`, `{action: "resume"}`, `{action: "send_portal_link"}`,
  `{action: "grant_topup", docs: 100}`; the answer's `message` is shown to the admin.
- `/admin/codes`, `/admin/plans`, `/admin/audit`: the table columns as listed in the contract; codes are written
  `{code, kind, value (percent 1-100, pence, or months), plan_codes|null, max_redemptions|null, expires_at|null, active}`.
  Plans are patched `{limits, active, price_month_pence?, price_year_pence?}`.
- `GET /admin/analytics?from=&to=`: `{daily_active: [{day, count}], funnel: {signed_up, first_document, first_approval},
  features: {documents_scanned, approvals, bank_syncs, ask_questions, vat_itsa_exports, ebay_syncs},
  conversion: {trials, converted, rate}, churn: {cancelled, rate}, errors: [{route, count}]}`.
- `GET /admin/bug-reports?status=&page=`: a list of `bug_reports` rows; `PATCH` takes `{status, admin_notes}`.

The admin link shows in the account menu only when `GET /admin/metrics` succeeds; every `/admin/*` page checks it again.

## Test mode

A `NEXT_PUBLIC_TEST_MODE=1` build answers all of the above in the browser (`apps/web/src/lib/billing-fake.ts`), so the
e2e specs need no backend support. `localStorage["accnomos.test.admin"] = "1"` makes the fake account an administrator;
`accnomos.test.billing` (`{account: {...}}`) overrides the fake account; calls are recorded in
`accnomos.test.billing.calls`.

## Web error reporting (Sentry), when used

Set `NEXT_PUBLIC_SENTRY_DSN` at build time (an EU-region project); unset, the SDK is not in the bundle. It runs with
personal data off, no cookies, headers, bodies or query strings, no breadcrumbs, and a scrubber over every event
(`apps/web/src/lib/sentry.ts`). When used, add the ingest host to `connect-src` in `apps/web/public/.htaccess` (both the
enforced and the report-only policy), for example `https://o0000000.ingest.de.sentry.io`; leave it out when the DSN is unset.

## Android

More has "Plan & billing" (opens `https://accnomos.com/settings#plan-billing` in the browser: nothing is sold in the app)
and "Report a problem" (`POST /bug-reports`, `app: "android"`, no screenshot). A 402 `plan_limit` from any call opens a
dialog pointing at the same web page.
