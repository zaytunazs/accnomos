# The demo's bank feed uses TrueLayer's sandbox

In a demo session ("Try the demo"), **Bank › Bank feed** connects **TrueLayer's sandbox test bank** ("Mock Bank") through
the same Open Banking flow a signed-in user's real bank uses, and fetches its sample transactions into the demo's bank lines,
where matching and rules work on them as on a statement's. Everything about it is labelled
**"Bank sandbox (TrueLayer test bank) — no real bank data"**. Before this, a demo refused to connect a bank feed (403).

## The flow (runtime `services/runtime/app/routes_bankfeeds.py` + `app/bank_feeds.py`; web `apps/web/src/components/bank/BankFeeds.tsx`)

1. **The card.** `GET /books/bankfeeds` in a demo answers `demo: true`, the label, and `test_login`: TrueLayer's public
   Mock Bank login, **username `john`, password `doe`** (published at https://docs.truelayer.com/docs/mock-users for
   anyone's sandbox; not a secret and not ours). The card shows it with Copy buttons, like the HMRC sandbox test user, and
   a **Connect the test bank** button.
2. **Start.** `POST /books/bankfeeds/start` with `X-Demo-Session`: allowed only when this server's TrueLayer is the sandbox.
   The consent URL offers **only the mock bank** (`providers=uk-cs-mock`), never a real bank's own sandbox. The signed
   `state` (HMAC-SHA256 under a key derived from the server's bank-feed key; 15 minutes; one use per step) carries, as
   before, the Bank page to come back to, the hash of a secret only this browser tab holds, and the user, and now also
   `d`: a SHA-256 hash of the demo session id. The session id itself never goes to TrueLayer or into any URL.
3. **TrueLayer's pages.** Choose Mock Bank → sign in as `john` / `doe` → allow access. TrueLayer sends the browser to the
   runtime's `/books/bankfeeds/callback` (the redirect URI registered with TrueLayer), which checks the state and forwards
   code and state in the URL fragment to `https://accnomos.com/bank`.
4. **Connect.** The Bank page loads in the same browser, where the demo session is still in localStorage, and posts code,
   state and its secret to `POST /books/bankfeeds/connect` with `X-Demo-Session`. The runtime checks that the state's `d` is
   this session's hash (a state from another demo, from outside a demo, or a demo state used outside it is refused), then
   exchanges the code and saves the connection (refresh token sealed with the server's key, as for anyone) in **that demo's
   in-memory books** only. The demo's books are what `get_books` gives an `X-Demo-Session` request; the server's real data
   is never reached. It goes when the session does (2 hours idle, least recently used, reset, or a restart).
5. **Fetch.** The card fetches at once (and **Fetch now** again later): `POST /books/bankfeeds/sync` reads the mock bank's
   transactions into `04 Bank statements/…_feed.csv` and the bank lines of the demo, exactly as for a signed-in user.

**Fallback.** If this server has no TrueLayer credentials, or points bank feeds at live banks, a demo is refused as before
(403 on start, connect, sync and reconfirm) and the card says why in a sentence: "Bank sandbox is not set up on this
server, so the demo cannot connect a test bank. …" or "This server's bank feeds point at live banks, and the demo only
ever uses TrueLayer's test bank, …". Signed-in users are unchanged.

**Android.** The Bank screen's sync card (`apps/mobile/lib/widgets/bank_sync.dart`) shows the label in a demo and, once
the same demo session has a connection, the bank and **Sync now**. Connecting happens on the web; the web demo is its own
demo session, so a bank connected there shows there, not on the phone.

## Tests

* `services/runtime/tests/test_bank_feeds_demo.py` (fake TrueLayer, `app/bankfeed_fakes.py`): the demo card's status and
  test login; connect → callback → connect → sync into the demo's own books, mock bank only, no session id in the URL, the
  real books untouched, another demo sees nothing; the connection ends with the session; a state from another demo or
  from outside refused; the state's `d` signed; refused with the reason when TrueLayer is off or live.
* `apps/web/e2e/sandbox-bankfeed.spec.ts` (the test-mode TrueLayer stand-in): the card's label and test login, the whole
  round trip in a demo, the lines in the demo's books, Fetch now; and the "not set up" card.
* `apps/mobile/test/home_goals_bank_sync_test.dart`: the label and Sync now in a demo.

## Live check

**Run on 4 Nov 2026 on `accnomos.com`** (main `3c83782c`, which also taught the runtime to accept TrueLayer's base64 credentials
ids), as in the earlier demo video's bank feed take (the capture script is `tools/video/`): Try the demo
→ Bank → *Connect the test bank* → TrueLayer's sandbox page listed Mock Bank only → signed in as `john` / `doe` → *Allow* →
back on `/bank` connected ("mock · test bank, sample data only", *Last fetched 4 Nov 2026*). The take fetched 2,145 sample
lines, all left unmatched because TrueLayer's mock data does not match the demo's books; since `e0a61829` (on `main`
and deployed the same afternoon) the demo's feed is capped at the newest 40 lines of the first account so the Bank page
stays a page.
Earlier the same morning (about 07:45 UTC, before that deploy) the live runtime still refused a demo with 403
"Connecting a bank feed is switched off in the demo sandbox."

The final audit (4 Nov, 11:00 UK) saw the card on the live site with the label, `john` / `doe` and **Connect the test bank**
in a fresh demo session, and did not repeat the TrueLayer round trip.

What is still unproven: `POST /connections/extend` (reconfirm) and a token refresh against TrueLayer; a real bank's own
sandbox; anything outside the demo (a signed-in user's feed has not been connected to TrueLayer's sandbox from their own
books).
