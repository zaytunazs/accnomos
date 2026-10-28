# Review: bank feeds through an Open Banking provider (TrueLayer)

Branch `claude/bank-feeds`, 28 Oct 2026. A user can connect their bank through TrueLayer's Data API; its
transactions are fetched when the app opens and go into the same bank lines a statement CSV makes, with lines already
imported left out either way. Sandbox only by default, off unless the server is set up. **Nothing in this branch has
called TrueLayer**: every call in tests and test mode goes to a fake.

## Sources (searched 28 Oct 2026)

This session could search the web but not open the providers' or regulators' pages (their hosts did not resolve from
the container), so each source below was read as quoted in search results. `docs/research/BANK_FEEDS.md` has the full
comparison and the list of what to re-check.

| What | Source |
|---|---|
| Access token 1 hour; refresh token only with `offline_access`, 90 days (UK); `/data/v1/me` gives `consent_expires_at` | https://docs.truelayer.com/docs/general-data-api-concepts |
| Auth link and parameters; sandbox mock bank `uk-cs-mock` | https://docs.truelayer.com/docs/create-a-connection |
| Re-authentication: `/connections/extend` with the refresh token after the user reconfirms | https://support.truelayer.com/hc/en-us/articles/360017594238 |
| FCA PS21/19: the user reconfirms with the AISP every 90 days; in force 26 Mar 2022 | https://www.openbanking.org.uk/news/fca-publishes-changes-to-90-day-reauthentication-rules/, https://www.pwc.co.uk/financial-services/assets/pdf/fca-clarifies-safeguarding-and-sca-requirements-for-payment-and-e-money-firms.pdf |
| Consent dashboard: tell the user about reconfirmation, offer revoke and reconfirm | https://standards.openbanking.org.uk/customer-experience-guidelines/dashboards/ais-consent-dashboard-revocation-refresh/latest/ |
| 2025: Data (Use and Access) Act, FCA research note (no rule change found) | https://www.fca.org.uk/publication/research-notes/open-banking-open-finance-uk.pdf, https://www.fca.org.uk/news/press-releases/fca-sets-out-vision-open-finance |
| GoCardless Bank Account Data: agreements, statuses; reportedly closed to new customers since July 2025 | https://developer.gocardless.com/bank-account-data/quick-start-guide, https://developer.gocardless.com/bank-account-data/statuses/, https://actualbudget.org/docs/advanced/bank-sync/gocardless/ |
| Yapily consent lifecycle (90 days UK) | https://docs.yapily.com/concepts/consent-lifecycle |
| Plaid UK consent renewal (`consent_expiration_time`, update mode) | https://support.plaid.com/hc/en-us/articles/43359270181911 |

## Design

- **Provider:** TrueLayer (UK-first, open to new customers, free sandbox with a mock bank, documented extend call).
  GoCardless would need no user secret at all but reportedly takes no new customers. Reasons in the research note.
- **Server config** (`app/bank_feeds.config`): `TRUELAYER_CLIENT_ID`, `TRUELAYER_CLIENT_SECRET`,
  `BANKFEEDS_REDIRECT_URI`, `BANKFEEDS_TOKEN_KEY` (32 bytes base64). Any empty: off, "Bank feeds are not set up on this
  server yet. Upload a statement CSV instead." A key that is not 32 bytes: off, with its own sentence. Live needs
  `TRUELAYER_ENV=live` and `BANKFEEDS_LIVE=1`.
- **User state** (`_System/bankfeeds.json`): bank and account names, last four digits, consent created/expiry, last
  synced, the refresh token sealed with AES-256-GCM (connection id as associated data) and the key's id. Never the
  access token. Trade-off (short-lived tokens only would mean signing in at the bank on every visit) in the research note.
- **Connect** (`/books/bankfeeds/start` → TrueLayer → `/books/bankfeeds/callback` → `/bank#feed=…` →
  `/books/bankfeeds/connect`): the same pattern as payment links. The signed, 15-minute state carries a hash of a secret
  only the starting tab holds and a hash of the user; each step spends it once; it can only return to `/bank` on a
  `CORS_ORIGINS` origin.
- **Consent:** `ok` → `reconfirm` from 14 days before the end (prompt on the Bank page and a strip on every page) →
  `expired` (nothing is read, not even a token refresh; *Connect again*). `key_changed` when the server key no longer
  matches. Reconfirm needs `confirm: true` from the app and calls TrueLayer's extend; if the bank wants the user back
  the answer is "connect again".
- **Sync** (`POST /books/bankfeeds/sync`, on app open at most hourly per tab, and *Fetch now*): first sync reads 89 days
  back, later ones from the last sync less 7 days. Lines are keyed by TrueLayer's `transaction_id` (seen ones dropped)
  and paired one to one against statement-CSV lines by `accnomos_ledger.bank.pair_duplicates` (same amount, dates within
  2 days, same reference or a telling word in common). New lines are filed as `04 Bank statements/<last date>_feed.csv`
  (readable by the CSV parser) and stored like an import, so matching, rules, reconcile and Books.xlsx need no change. A
  CSV imported later skips lines a feed brought in (`BankImport.from_feed`). The sign comes from `transaction_type`; non-GBP
  and malformed lines are skipped and counted. One bank failing does not stop the others.
- **Disconnect:** ends the connection at TrueLayer (`DELETE /api/delete`) and forgets it; fetched lines stay.
- **Audit:** `bank_feed_connected`, `bank_feed_synced`, `bank_feed_reconfirmed`, `bank_feed_disconnected`, each with a
  sentence in `audit_view.SUMMARIES`.
- **Security tests:** `truelayer.py` and `bankfeed_fakes.py` added to the modules allowed to import httpx; every TrueLayer
  URL starts with a configured base; no redirects followed; ids read back from the books must match `ID_RE` (never `.`
  or `..`) before they go into a path; the callback is the one new public route.

## Tests

- `services/runtime/tests/test_bank_feeds.py`: **23** (off by default and its sentence; live switch; sandbox default;
  seal/unseal bound to key and connection; connect request shape and what is stored; another browser, another user,
  reused state; redirect only to /bank; callback errors; sync files once, then the overlap window; CSV-then-feed and
  feed-then-CSV dedupe on the gold Barclays CSV; consent withdrawn at the bank; one bank down; `same_payment` and
  one-to-one pairing; transaction parsing; reconfirm window and extend; bank wants re-auth; nothing read after expiry;
  changed key; disconnect; a hand-edited file).
- `services/runtime/tests/test_security_routes.py`: +1 test (TrueLayer bases), allow-lists updated.
- Runtime: **1425 passed, 2 skipped** (`python -m pytest -q`). Ledger 49 passed. `ruff check` and `ruff format --check`
  clean; `pyright` 0 errors.
- Web: `pnpm exec eslint .` clean; `pnpm run e2e:build && pnpm run e2e:test` **248 passed, 58 skipped** (the usual
  deliberate skips), including the new `e2e/bank-feeds.spec.ts` (3: connect in the sandbox → fetch → the 3 lines the
  Barclays CSV already had are left out; feed first, then the CSV imports only 3; reconfirm strip 9 days before the end →
  reconfirm → disconnect). Run locally against Playwright's Chromium 1243 build (this container's), not the 1248 the
  lockfile names.
- Flutter: not changed.

## Risks and what remains

- Never run against TrueLayer; the fake answers with the same assumed shapes the client sends, so a wrong assumption
  passes every test (`docs/HONESTY.md`, *Bank feeds*). Re-check `app/truelayer.py` against the docs and the sandbox first.
- The server key plus a user's file reads that user's transactions until the consent ends; no rotation with re-sealing.
- Dedupe can merge two real same-amount payments to one payee within 2 days when each is only in one source.
- Two tabs syncing at the same instant can add the same lines twice.
- Pending transactions are not read; GBP only; Android shows no bank feed yet.
- Pricing unknown for every provider; GoCardless's status unconfirmed.
