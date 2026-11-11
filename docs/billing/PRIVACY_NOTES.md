# What billing, admin and analytics keep, and where (for the privacy page)

For whoever writes the privacy page (the web app owns the wording). This lists exactly what the runtime's billing,
admin and analytics code (`services/runtime/app/billing`) stores, where, why and for how long. Everything else about
Accnomos is unchanged: a user's books, documents, receipts, bank data and tokens stay in their own OneDrive or Google
Drive, and the runtime keeps none of it.

Controller: Zaytuna Business Services Ltd. All three processors below are set up in a UK or EU region.

## 1. Supabase (account registry), UK/EU region

Postgres schema `accnomos`. Row-level security on with no policies: only the runtime's service-role key can read or
write; nothing is reachable from a browser.

| What | Fields | Why | Kept |
|---|---|---|---|
| Account | email, display name (from Microsoft or Google), sign-in kind (`personal`/`work`/`google`), the provider's stable account id (Graph `/me` id or Google `sub`), created, last seen (at most hourly), plan, billing status, trial end, comp end, Stripe customer and subscription ids, billing interval, current period end, cancel-at-period-end, country (if known), analytics opt-out, admin notes | to know who has which plan and what they may use | while the account exists; deleted on request (cascades to usage, redemptions and events) |
| Monthly usage | per month: number of AI-read documents, Ask questions, sales invoices and quotes; top-up documents left and their expiry | plan limits | while the account exists |
| Promo code redemptions | code, account, when | max-redemption counts, one use per account | while the account exists |
| Admin audit log | when, admin's email, account affected, action, the changed fields (plan, dates, status, notes, code, number of top-up documents) | accountability for every admin change | while the account exists (rows keep no account link after an account is deleted) |
| Product events | when, account id, event name, app (`web`/`android`/`api`), app version, and a few properties from a fixed list: page path, feature/action/step/result slugs, plan, interval, counts, durations, true/false flags | product analytics (first-party, no cookies, no fingerprinting, no third-party tracker) | 13 months |
| API error counts | when, route template (e.g. `/invoices/{number}`), method, status; **no account id, no message** | error counts by route in the admin | 13 months |
| Bug reports | when, account id, email, the message the user typed, page, app, version, browser/OS string, screenshot path (if the user ticked it), status, admin notes | triage of "Report a problem" | until closed, then 12 months |
| Bug screenshots | the image, in the private Storage bucket `bug-screenshots` (max 2 MB, PNG/JPEG/WebP) | only if the user ticks "include a screenshot"; may show whatever was on screen | with the report |
| Stripe event ids | event id, type, received | so a webhook is processed once | indefinitely (ids only) |

Events **never** contain amounts, supplier or customer names, document text, emails or file names: the runtime refuses
any property not on its list, and every value must be a number, true/false, a plan code or a lowercase slug or path
(no `@`, spaces, `£` or decimal points). Server-side event names: `signup`, `document_scanned`, `proposal_approved`,
`bank_synced`, `ask`, `vat_export`, `itsa_export`, `ebay_sync`, `checkout_started`, `subscription_active`,
`subscription_cancelled`, `trial_ended`, `topup_bought`, `code_redeemed`, `api_error`.

**Opt-out:** Settings › Privacy (`PATCH /account {"analytics_opt_out": true}`) stops every product event for that
account, from the app and from the server. Billing records (plan, usage counts) are still kept: they are needed to
provide the service, not analytics.

## 2. Stripe (payments)

Stripe is the source of truth for payment state. The runtime creates a Stripe **customer** with the account's email,
display name and our account id (metadata), then sends people to Stripe Checkout and the Stripe Customer Portal.
Card details, billing address, VAT number (if given) and invoices are collected and held **by Stripe**, never by the
runtime. Checkout and subscription metadata carry: account id, plan code, interval, promo code. Stripe Tax computes UK
VAT from the billing address. The runtime mirrors only status, plan, interval, trial end, period end and
cancel-at-period-end into Supabase.

## 3. Sentry (error reports), EU data region, only if `SENTRY_DSN` is set

Unhandled errors in the runtime, with the stack trace (no local variables), method and path (no query string).
`send_default_pii` is off; request bodies, headers, cookies and query strings are removed before sending; user and
server name are removed; and every remaining string is scrubbed of anything that looks like money (`£12.34`, `GBP 12`,
`12.34`), an email address, a GB VAT number, a bearer token, a JWT or a Stripe key. Retention is the Sentry project's setting
(check it in Sentry when the project is created).

## Not stored anywhere new

- Graph/Google access tokens: used per request, never kept (as before).
- AI keys (`X-Meta-Api-Key`): read per request only to tell whether the user's own AI did the work; never kept.
- Book contents, documents, amounts, supplier names: not in Supabase, Stripe metadata or Sentry.
- The runtime sends no emails for billing; Stripe sends receipts and the 7-days-before-trial-end reminder.

## AI processing (since 11 Nov 2026)

- The server's AI chain is `AI_PROVIDERS=spark,anthropic`: our own server reads documents and questions first; only
  when it cannot answer does the same request go to Anthropic's Messages API (`services/runtime/app/ai/anthropic.py`).
  Anthropic is then a processor in the United States under its Commercial Terms ("Anthropic may not train models on
  Customer Content from Services", anthropic.com/legal/commercial-terms, section B) and its Data Processing Addendum
  (section C). Without a zero-data-retention arrangement, which is not on by default and is not in place, Anthropic
  deletes API inputs and outputs within 30 days, longer only to enforce its usage policy or by law
  (privacy.claude.com, "How long do you store my organization's data", read 11 Nov 2026).
- Meta: our server no longer sends documents, questions or recordings to Meta's Model API (the live server's
  `muse-spark-1.3-contributor` model was one Meta may train on). Voice is transcribed on our own server
  (`STT_PROVIDER=local`); SAM crop (Meta) stays off (`SAM_CROP` unset or 0). A user's own Meta key still sends their
  own requests to Meta, as they chose.
- Logs: the runtime logs token counts per Anthropic call (`AI usage: provider=anthropic model=... prompt_tokens=...`),
  never the prompt, the document or the reply; the key is sent only in the `x-api-key` header.
