# Bank feeds: which Open Banking provider, and why

Branch `claude/bank-feeds`, 28 Oct 2026. Accnomos has no user database: whatever a bank feed needs between visits must
live in the user's own OneDrive, and the runtime keeps nothing. This note compares four UK providers for that shape of
app, says which one was built and why, and lists what is still unverified.

**How this was checked.** This session's network allowed web search but not opening the providers' pages
(docs.truelayer.com, developer.gocardless.com, docs.yapily.com, plaid.com, fca.org.uk and openbanking.org.uk all failed
to resolve from the container). Every fact below comes from search results quoting the page named, read on
28 Oct 2026. Treat each one as "the page said this in a search snippet", and re-read the page before going live. The
owner should allow these hosts, or check them by hand, before switching anything on.

## The rule that shapes everything: 90-day consent

- **FCA PS21/19** (published 29 Nov 2021, in force 26 Mar 2022, transition to 30 Sep 2022) replaced the bank-side
  90-day re-authentication for account information access with a requirement that the user **reconfirms consent with
  the AISP** (the app) at least every 90 days. If the user does not reconfirm, the AISP must stop reading. Sources:
  https://www.openbanking.org.uk/news/fca-publishes-changes-to-90-day-reauthentication-rules/,
  https://www.openbanking.org.uk/news/fca-update-guidance-on-90-day-strong-customer-authentication/,
  PwC's summary https://www.pwc.co.uk/financial-services/assets/pdf/fca-clarifies-safeguarding-and-sca-requirements-for-payment-and-e-money-firms.pdf
  (Article 36(6) UK SCA-RTS).
- The Open Banking customer experience guidelines say the AISP should tell the user about the 90-day reconfirmation and
  offer a way to revoke or reconfirm: https://standards.openbanking.org.uk/customer-experience-guidelines/dashboards/ais-consent-dashboard-revocation-refresh/latest/
- **"The 2025 FCA changes": we found no 2025 change to the 90-day rule.** What 2025 brought: the Data (Use and Access)
  Act 2025 (Royal Assent 19 Jun 2025; Part 1, smart data, in force 20 Aug 2025), which lets government make smart-data
  schemes and is the route to an FCA-led long-term open banking framework; and an FCA research note on open banking and
  open finance (6 Oct 2025, https://www.fca.org.uk/publication/research-notes/open-banking-open-finance-uk.pdf), which
  flags consent management as an area for new approaches but changes no rule. The FCA has said it will consult on the
  long-term framework's rules in 2026 (https://www.fca.org.uk/news/press-releases/fca-sets-out-vision-open-finance;
  secondary summaries: https://www.hsfkramer.com/notes/fsrandcorpcrime/2026-posts/uk-smart-data-strategy-building-on-open-bankings-momentum,
  https://www.regulationtomorrow.com/2026/01/open-banking-process-to-establish-a-future-entity/). Whether that
  consultation has been published by today, and whether it touches reconfirmation, is **not verified**. The code keeps
  the 90-day period in one constant (`CONSENT_DAYS`) and reads the real expiry from the provider, so a longer period
  needs no redesign.

## The four providers

| | GoCardless Bank Account Data | TrueLayer Data API | Yapily | Plaid (UK) |
|---|---|---|---|---|
| **Taking new customers** | **Reportedly not since July 2025** (Actual Budget's docs, https://actualbudget.org/docs/advanced/bank-sync/gocardless/; no GoCardless notice found) | Yes | Yes | Yes |
| **Small-volume pricing** | Historically a free tier (from memory; not checked) | Not public: sales-quoted, free sandbox (third-party reviews, e.g. https://blog.finexer.com/truelayer-pricing-uk/) | Not public; sandbox tier for testing only (third-party, Dec 2024) | Not public for the UK; contracts vary (third-party, https://blog.finexer.com/plaid-pricing/) |
| **Consent** | End-user agreement: default 90 days of access and 90 days of history; `access_valid_for_days` and `max_historical_days` per bank (https://developer.gocardless.com/bank-account-data/quick-start-guide) | 90 days (UK); `GET /data/v1/me` gives `consent_expires_at`; reconfirm through `/connections/extend` (https://docs.truelayer.com/docs/general-data-api-concepts, https://support.truelayer.com/hc/en-us/articles/360017594238) | 90 days UK, 180 EEA; reconfirm deadline fields (https://docs.yapily.com/concepts/consent-lifecycle) | 90 days UK; `consent_expiration_time` on the Item; renew through Link update mode (https://support.plaid.com/hc/en-us/articles/43359270181911) |
| **Sandbox** | Yes (sandbox institution) | Yes, free; mock bank `uk-cs-mock` plus banks' own sandboxes | Yes | Yes |
| **What a stateless app must keep per user** | **Only the requisition id**: the server's own secret gets an access token, the requisition id names the user's accounts | A **refresh token** (90 days; access tokens last 1 hour) | The consent token | The Item's `access_token` (long-lived) |
| **Statuses / expiry** | Requisition `CR GC UA RJ SA GA LN EX` (https://developer.gocardless.com/bank-account-data/statuses/) | `consent_status`, `consent_expires_at` | consent status, reconfirm-by | `consent_expiration_time`, Item errors |

### Decision: TrueLayer

GoCardless Bank Account Data fits a database-free app best, because the only thing a user's books would hold is a
requisition id: no user secret at all. But every sign we found says it stopped taking new customers in July 2025, and
we could not reach GoCardless to confirm otherwise. Building on it would give a feature nobody could switch on.

Of the three that are open to new customers, **TrueLayer** is UK-first, FCA-authorised as an AISP, has a free sandbox
with a mock bank, documents the 90-day UK consent and an extend call for in-app reconfirmation, and its refresh token
lasts exactly as long as the consent. Yapily and Plaid would need the same kind of per-user secret (a consent token, an
access token) with no advantage for us, and Plaid's UK pricing and onboarding are the least transparent. If GoCardless
does reopen, its lighter storage model is worth a second provider behind the same routes.

### Token handling: the trade-off

TrueLayer issues a 1-hour access token and, with the `offline_access` scope, a 90-day refresh token. The two choices:

1. **Short-lived only, re-fetched per session.** Ask for no `offline_access`; the user signs in at their bank every
   time they open Accnomos. Nothing secret is stored anywhere. In practice this is not a feed: bank SCA every visit,
   and nothing fetched on open.
2. **Keep the refresh token, encrypted with a server key (built).** The token is sealed with AES-256-GCM using
   `BANKFEEDS_TOKEN_KEY` (32 bytes, server env only), with the connection id as associated data, and written to the
   user's `_System/bankfeeds.json`. The file alone is useless without the key; the key alone is useless without the
   file, which only the user's own Microsoft token can read. Costs: the runtime now holds a key that, together with a
   user's file, gives read-only access to that user's bank transactions for up to 90 days; rotating the key makes
   every stored connection unreadable (shown as "connect again", not as an error); anyone who can already read the
   user's OneDrive and also obtains the server key can read the feed. The access token is never stored. Disconnect
   ends the connection at TrueLayer (`DELETE /api/delete`) as well as in the books.

What `_System/bankfeeds.json` holds: per connection the bank's display name, the accounts (TrueLayer's account id, name,
type, last four digits of the number), consent created and expiry times, connected / reconfirmed / last synced times,
the date synced to, the sealed refresh token and the id of the key that sealed it. No balances, no transactions (those
are in the bank lines, like a CSV's).

## What was built (summary; details in `docs/reviews/bank-feeds/REVIEW.md`)

- Env vars, empty by default (feature off with "Bank feeds are not set up on this server yet. Upload a statement CSV
  instead."): `TRUELAYER_CLIENT_ID`, `TRUELAYER_CLIENT_SECRET`, `BANKFEEDS_REDIRECT_URI`, `BANKFEEDS_TOKEN_KEY`.
  Sandbox by default; `TRUELAYER_ENV=live` needs `BANKFEEDS_LIVE=1` as well.
- Connect from the Bank page; fetch on app open (at most hourly per tab) and with *Fetch now*; reconfirm prompt from
  14 days before expiry, on the Bank page and as a strip on every page; *Connect again* after expiry; CSV import as
  the fallback, with duplicates left out in both directions.

## To check before switching it on

1. Allow docs.truelayer.com (or read by hand) and compare `app/truelayer.py`'s request and response shapes, line by
   line, especially `POST /connections/extend` (request fields and the `user_input_link` answer) and whether a
   refresh answers a new refresh token.
2. Register `BANKFEEDS_REDIRECT_URI` (the runtime's `/books/bankfeeds/callback`) in TrueLayer's console; run the
   sandbox's mock bank end to end.
3. Get a TrueLayer quote for low volumes; confirm GoCardless's position on new Bank Account Data customers.
4. Check the FCA's 2026 consultation on the long-term open banking framework for any change to reconfirmation.
