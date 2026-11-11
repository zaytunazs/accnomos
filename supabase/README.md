# Supabase: the account registry

The runtime keeps account metadata (plan, billing status, trial dates, monthly usage counts, promo codes, the admin
audit log, product events and bug reports) in Supabase Postgres, schema `accnomos`. Never books, documents, receipts,
amounts or tokens for other services. Contract: `docs/billing/PLANS_AND_CONTRACT.md`; what is stored where:
`docs/billing/PRIVACY_NOTES.md`.

Without `SUPABASE_URL` the runtime runs with billing off: every feature without limits, and `GET /account` answers
`{"configured": false}`.

**Target project:** ref `usqwmybqjvldqjtaxsqi` (London, eu-west-2), so
`SUPABASE_URL=https://usqwmybqjvldqjtaxsqi.supabase.co`. Keys are never committed: the service-role key goes only
in the runtime host's environment.

## Owner steps (once)

1. **Project in a UK or EU region.** Already created: `usqwmybqjvldqjtaxsqi`, London (eu-west-2). (For a new one:
   supabase.com › New project › Region London, with a strong database password kept in the password manager.)
2. **Run the migration.** SQL Editor › New query › paste `migrations/0001_accounts.sql` › Run. (Or with the CLI:
   `supabase link --project-ref <ref>` then `supabase db push`.) It is idempotent: running it again changes nothing.
   It creates the tables with row-level security **on and no policies**, grants table and function rights to
   `service_role` only, revokes everything from `anon` and `authenticated`, seeds the three plans, and creates the
   private Storage bucket `bug-screenshots` (2 MB, PNG/JPEG/WebP).
3. **Expose the schema to the API.** Project Settings › Data API › *Exposed schemas*: add `accnomos` (keep `public`).
   The runtime talks to PostgREST with `Accept-Profile: accnomos`. This is safe: `anon` and `authenticated` have no
   rights on the schema, so the publishable/anon key sees nothing; only the service-role key can read or write.
4. **Check Storage.** Storage › Buckets: `bug-screenshots` exists and is **not public**. If it is missing (the
   migration only creates it when the `storage` schema is there), create it by hand: private, 2 MB limit, MIME types
   `image/png, image/jpeg, image/webp`.
5. **Retention (daily).** Database › Extensions › enable `pg_cron`, then in the SQL editor:

   ```sql
   select cron.schedule('accnomos-retention', '17 3 * * *', 'select accnomos.apply_retention()');
   ```

   Events are kept 13 months; bug reports 12 months after they are closed (fixed / won't fix).
6. **Set the runtime's environment** (the API host only, never the web app):

   ```
   SUPABASE_URL=https://usqwmybqjvldqjtaxsqi.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=<Project Settings › API keys › a secret key, sb_secret_…>
   ADMIN_EMAILS=you@example.co.uk
   ```

   `SUPABASE_SERVICE_ROLE_KEY` takes either kind of server key: a **secret key** (`sb_secret_…`, Project Settings ›
   API keys), the one to use, or a **legacy `service_role` JWT**, which works until Supabase retires the legacy keys
   in early 2027 (https://supabase.com/docs/guides/api/api-keys). The runtime sends the key as `apikey` and
   `Authorization: Bearer`; both kinds are accepted that way (checked against the project, 11 Nov 2026). The
   publishable key will not do: it is refused on the `accnomos` schema. The variable keeps its name either way.

   Restart the runtime. `GET /account` with a signed-in token now answers `"configured": true`.

## Stripe (same runtime host)

1. **Keys.** `STRIPE_SECRET_KEY` (already used for invoice payment links; a live `sk_live_…` key for real
   subscriptions) and `STRIPE_WEBHOOK_SECRET` from Developers › Webhooks › Add endpoint
   `https://api.accnomos.com/billing/stripe/webhook` with the events `checkout.session.completed`,
   `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`,
   `customer.subscription.paused`, `customer.subscription.resumed`, `invoice.payment_failed`.
2. **Stripe Tax.** Settings › Tax: add the UK VAT registration (the company's VAT number), set the origin address, and the default
   product tax code to *Software as a service (SaaS) – business use*. Prices are created **tax-exclusive** (ex VAT);
   Checkout adds 20% UK VAT and collects VAT numbers.
3. **Prices.** In the admin, Plans › *Sync prices to Stripe* (`POST /admin/plans/sync-stripe`) creates the product
   and monthly/yearly prices for each plan and stores their ids in `plans`. Or set `STRIPE_PRICE_<PLAN>_<MONTH|YEAR>`.
   A later price change in the admin creates a new Stripe price; existing subscribers keep theirs.
4. **Customer Portal.** Settings › Billing › Customer portal: allow updating payment methods, viewing invoices,
   cancelling (at period end) and switching between the three plans' prices.
5. **Trial emails.** Settings › Billing › Subscriptions and emails: turn on the reminder email **7 days before a free
   trial ends** (Stripe sends it; the runtime sends no email). Trials that end without a card are **paused** by
   Stripe, which the runtime shows as "Trial ended" (read-only, never deleted).
6. **Test it.** `stripe listen --forward-to localhost:8780/billing/stripe/webhook` prints a `whsec_…` for local use.

## Tables

| Table | What |
|---|---|
| `plans` | Starter / Comprehensive / Ultimate: prices (pence, ex VAT), Stripe price ids, `limits` jsonb, active |
| `accounts` | one per sign-in (auth_kind + auth_subject): email, plan, status, trial/comp dates, Stripe ids, notes, analytics opt-out |
| `usage` | per account per month (1st, UTC): docs, ask, invoices, top-up balance and expiry |
| `promo_codes`, `redemptions` | percent / fixed / free-months codes and who redeemed them |
| `admin_audit` | every admin write: who, when, which account, what |
| `events` | first-party product events (name, account, whitelisted non-financial props) |
| `bug_reports` | "Report a problem" messages and screenshot paths |
| `stripe_events` | webhook event ids already handled (idempotency) |

Functions (service role only): `bump_usage`, `add_topup`, `claim_code` (atomic counters and code claims),
`admin_metrics`, `analytics` (admin aggregates), `apply_retention`.
