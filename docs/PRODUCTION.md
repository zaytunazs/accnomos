# Going live: what to change, and what must not change

**Today everything HMRC is sandbox.** The owner decides when to switch; until then nothing in the repo, the compose file
or `.env.example` points at HMRC production, and no production credential exists anywhere in the repo. The switch is
environment variables only: no code change. Companies House has no sandbox, so its key is the same before and after.

Facts below were checked on 27 Oct 2026 against the pages cited in the root `REVIEW.md` of the `claude/company-lookup`
branch (HMRC Developer Hub, Companies House developer guides). Re-check them on the day: HMRC changes its process.

## 1. HMRC: a production application

Done by the owner on the HMRC Developer Hub (developer.service.hmrc.gov.uk), not in code.

1. **Sandbox first.** HMRC gives production credentials only after the sandbox application has been tested. Keep the
   sandbox application; it stays the test environment.
2. **Request production credentials** for the application, with these API subscriptions:
   - **VAT (MTD)**: obligations, submit return, view return, liabilities, payments (user-restricted, `read:vat write:vat`).
   - **Check a UK VAT number, version 2.0** (application-restricted, client credentials with the `read:vat` scope).
     Version 1.0 was removed on 17 February 2025; v2.0 needs registration, and HMRC says it takes around 2 weeks and
     needs Terms of Use 2.0 accepted.
3. **Fraud-prevention headers.** Before HMRC approves MTD VAT for production it reviews the `Gov-*` headers. Run the
   sandbox validator first and fix anything it reports:
   `POST /hmrc/validate-headers` and `GET /hmrc/validation-feedback?method=WEB_APP_VIA_SERVER` on the relay (both work
   only against the sandbox, on purpose). `docs/HMRC.md` lists every header and where it comes from.
4. **Production redirect URI.** Register exactly the relay's public callback, e.g. `https://api.accnomos.com/hmrc/callback`,
   on the production application. It must equal `HMRC_REDIRECT_URI` character for character.
5. Expect HMRC's production checklist (name, privacy policy and terms URLs, the declaration wording on `/vat`). Answer it
   from the product as it is; do not add claims it doesn't meet.

## 2. The environment change (relay only)

In the server's `.env` (never committed), on the **relay** service:

| Variable | Sandbox (today) | Production |
|---|---|---|
| `HMRC_CLIENT_ID` | sandbox client id | production client id |
| `HMRC_CLIENT_SECRET` | sandbox secret | production secret |
| `HMRC_BASE` | `https://test-api.service.hmrc.gov.uk` | `https://api.service.hmrc.gov.uk` |
| `HMRC_AUTH_BASE` | `https://test-www.tax.service.gov.uk` | `https://www.tax.service.gov.uk` |
| `HMRC_REDIRECT_URI` | the sandbox app's registered callback | the production app's registered callback |
| `RELAY_PUBLIC_IP` | the server's public IP | the same (needed for `Gov-Vendor-Public-IP`) |

Then `docker compose -f deploy/docker-compose.yml --env-file .env up -d relay`. Check `GET /health` on the relay:
`"sandbox": false`.

What follows automatically from `HMRC_BASE` (code reads it; nothing else to set):
- `/hmrc/test-user`, `/hmrc/validate-headers` and `/hmrc/validation-feedback` refuse with 403 (sandbox-only).
- `Gov-Test-Scenario` is never sent.
- The VAT check labels its answers `"source": "hmrc"` instead of `"hmrc-sandbox"`, and the app shows "(HMRC)".

**Not yet done for production in the web app:** the `/vat` page and its button still say "(sandbox)" in their text
(`apps/web/src/components/vat/ConnectHmrc.tsx`). Change that wording, from `/health`'s `sandbox` flag, before the
first live filing; it is copy, not behaviour.

## 3. Companies House (runtime)

| Variable | Value |
|---|---|
| `COMPANIES_HOUSE_API_KEY` | a key from developer.company-information.service.gov.uk (free; "REST" key). Empty = *Look up* is hidden |
| `HMRC_RELAY_URL` | how the runtime reaches the relay; `http://relay:8787` inside the compose network (the default) |

The key is sent as HTTP Basic (key as the username, empty password). Companies House allows 600 requests per 5 minutes
per key; the runtime asks for at most 60 a minute per process and caches answers for 24 hours.

## 3a. Online payments (runtime, optional)

Payment links on invoices through each user's own Stripe or PayPal account (`services/runtime/app/online_payments.py`;
the design and its sources are in that module's docstring and `app/payment_providers.py`). All empty by default: the feature is then off and Settings says so.
Only the platform's credentials live here; a user's link is just their account id in their own OneDrive.

| Variable | Value |
|---|---|
| `STRIPE_SECRET_KEY` | the platform account's **test** secret key (`sk_test_…`). A live key is refused unless `PAYMENTS_LIVE=1` |
| `STRIPE_CONNECT_CLIENT_ID` | Connect OAuth client id (`ca_…`), Dashboard › Settings › Connect › Onboarding options › OAuth (enable OAuth there) |
| `STRIPE_REDIRECT_URI` | `https://api.accnomos.com/payments/online/stripe/callback`, also added as a redirect URI in those OAuth settings |
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` | the REST app's **sandbox** credentials (developer.paypal.com › Apps & Credentials) |
| `PAYPAL_PARTNER_MERCHANT_ID` | the platform's own PayPal merchant id (the partner) |
| `PAYPAL_PARTNER_ATTRIBUTION_ID` | the partner BN code PayPal issues; required on partner calls |
| `PAYPAL_RETURN_URL` | `https://api.accnomos.com/payments/online/paypal/callback` |
| `PAYPAL_BASE` | `https://api-m.sandbox.paypal.com` (default). The live API is refused unless `PAYMENTS_LIVE=1` |
| `PAYMENTS_STATE_KEY` | optional; signs the connect `state` (default: derived from the provider's secret) |
| `PAYMENTS_LIVE` | leave empty. `1` allows live keys; not to be set until live payments have been reviewed and tested |

PayPal's partner onboarding and acting for a merchant (`PayPal-Auth-Assertion`) work only once PayPal has approved
the platform as a partner; until then leave the PayPal variables empty and users can still use a PayPal.me link.
Stripe and PayPal webhooks are **not** used (no endpoint to register): payments are found when the user opens Invoices.

## 3b. Live price search (runtime)

Cheaper options and the shopping list compare prices from the user's own books. A live price search can add offers
from elsewhere; it is a provider interface in `services/runtime/app/price_search.py`, chosen by one variable on the
**runtime** service:

| Variable | Value |
|---|---|
| `PRICE_SEARCH_PROVIDER` | empty or `none` (the default): **off**; the app says "Live price search is off" and shows history only. `fake`: the deterministic test fake, which is refused (stays off) unless `ACCNOMOS_TEST_MODE=1`. Any other name is unknown in this version: off, with a warning in the runtime log |

**No real provider ships in this version.** To switch one on later: implement `PriceSearchProvider.search(query, specs)`
returning `Offer`s (supplier, title, unit price in pence, pack, URL, `retrieved_at`, `source`), register it in
`PROVIDERS` under a name, put any API key in the server's `.env` (never the repo), set
`PRICE_SEARCH_PROVIDER=<name>`, and `docker compose -f deploy/docker-compose.yml --env-file .env up -d runtime`. Code
does all the unit-price maths on the offers, keeps them apart from the history, and labels each with its source and
time; a provider that fails or takes over 8 s only loses its offers. Check the provider's terms allow showing its
prices this way, and add its host to whatever egress allow-list the server uses. `tests/test_prices.py` and
`tests/test_shopping.py` cover the switch and the fake.

## 4. What must NOT change

- **No production value as a default anywhere in the repo**: not in `Settings` (`services/hmrc-relay/relay/settings.py`),
  `deploy/docker-compose.yml` or `.env.example`. Defaults stay sandbox, so a server with no `.env` can only reach the sandbox.
- **No secret in the repo or the image**: HMRC client secret and the Companies House key come from the server's
  environment only. The relay never reads a `.env` file itself.
- **No personal data in the repo or the image**: the early-adopter list lives only on the `runtime-data` volume
  (§ 6); `.gitignore` and `.dockerignore` exclude list files and exports.
- **The browser never holds the HMRC client secret**, and the runtime never calls HMRC directly: everything goes through
  the relay.
- **AI proposes, user approves, code calculates.** Going live changes where the relay sends requests, nothing else: the
  boxes are still calculated by code, nothing is filed without the declaration tick, and a VAT check or a Companies House
  match still only fills a form for the user to save.
- **One relay worker.** One-time OAuth state and the rate limit are in memory.
- **The demo stays a sandbox.** `DEMO_MODE` never touches a real OneDrive, mailbox or HMRC, and must not be given a
  way to: do not add a shared Microsoft account or refresh token "for the judges"; that is what the sandbox replaces.
  `DEMO_SECRET` is its own secret, never reused from `ACTIONS_SIGNING_KEY` or anything else.
- **Sandbox tests stay sandbox.** The test suites fake HMRC and Companies House; never point them at production.

## 5. Demo sandbox for judges (runtime)

Judges, and anyone else, can use the whole app on the sample books without a Microsoft sign-in: *Try the demo — no
sign-in* on the signed-out Home and on Connect, or the guide at `/judges`. Each visitor gets their own copy of the
fictional Bramblewood Joinery Ltd books in the runtime's memory (`services/runtime/app/demo.py`); nothing is stored
about them and no Microsoft or HMRC account is involved. Off by default; production turns it on.

| Variable | Value |
|---|---|
| `DEMO_MODE` | `1` turns it on (anything else: off, and `/demo/*` does not exist) |
| `DEMO_SECRET` | 32+ random characters, e.g. `openssl rand -hex 32`, used only to sign demo session ids. Required: with `DEMO_MODE=1` and no (or a short) secret the runtime refuses to start. Changing it ends every demo session |
| `DEMO_MAX_SESSIONS` | 200: past it, the least recently used session goes |
| `DEMO_IDLE_TTL_S` | 7200 (2 h without a request ends a session; the banner promises "changes reset after 2 hours") |
| `DEMO_MAX_SESSION_BYTES` / `DEMO_MAX_SESSION_FILES` / `DEMO_MAX_FILE_BYTES` | 20 MB / 300 new files per session; 10 MB a file (413 past any of them) |
| `DEMO_MAX_TOTAL_BYTES` | 512 MB added across all sessions; past it the least recently used go |
| `DEMO_SESSIONS_PER_IP_PER_MIN` | 5 session starts (and resets) a minute per IP; `0` turns the limit off |
| `DEMO_GRAPH_PER_MIN` | 600 calls a minute per session to the browser's Graph look-alike (`/demo/graph/`), which is exempt from `RATE_LIMIT_PER_MIN` |
| `DEMO_SEED_TIMEOUT_S` | 600: how long a session start waits for the day's books to be seeded |

How it behaves:
- On its first `/health` request (the container healthcheck, within seconds of start) the runtime seeds the day's sample books once, in a background thread (the whole `tools/seed_demo.py`
  plan, planned for today, then six inbox documents read into Review). `GET /health` says `"demo": {"enabled": true,
  "ready": …}`. A session start before it is ready waits ("Preparing the sample books…"); every session after that is
  a copy taking microseconds. The books are re-seeded on the first session of a new day.
- AI: a demo uses the AI this server is configured with (`AI_MODE`, `OLLAMA_*`, `MODEL_API_*`, or `AI_PROVIDERS` once
  it lands), exactly as for a signed-in user. The six documents waiting in Review were pre-read by the seed; scanning
  the 19 still in `00 Inbox`, Ask and the planner call the server's model, at the owner's cost.
- Never real: mail is recorded, not sent ("Sent (demo — not actually sent)"); HMRC is simulated in the browser (a
  receipt labelled "Demo — submission simulated", no relay call); Companies House and VAT-number look-ups answer 403.
- The edge must let `/demo/graph/` uploads through at 11 MB (`deploy/nginx.conf` has the location) and `CORS_ORIGINS`
  must include the web origin as before (`X-Demo-Session` is in the allowed headers).
- One runtime process (as the image runs): sessions live in that process's memory. A restart ends every demo.
- The web app shows the *Try the demo* entries only when `/health` reports the demo on, so turning it off hides them.

## 6. Not tested live

Nothing here has run against HMRC production. The VAT check and the MTD calls have been run only against fakes in the
test suites; HMRC's sandbox has not been called from this branch (no sandbox credentials in the session that built it).
Companies House has been called only through a faked transport. See `docs/HONESTY.md`.

## 6. Early-adopter list (runtime, operator data)

People who sign up before the public launch (November 2026) get 3 months free at launch and **one** email when the
app is ready. This is the only personal data the runtime keeps, and it is the operator's marketing list, not anyone's
books: the controller is Zaytuna Business Services Ltd. Lawful basis: consent (UK GDPR Art. 6(1)(a); PECR reg. 22
for sole traders and personal addresses). What the privacy page promises is binding on how you use it: see
[`/privacy`](../apps/web/src/app/privacy/page.tsx) and [`docs/SECURITY.md`](SECURITY.md) § Early-adopter list.

| Variable | Value |
|---|---|
| `EARLY_ACCESS_ENABLED` | `1` turns `POST /public/early-access` on. Anything else (the default `0`): it answers 503 and no file is ever created |
| `EARLY_ACCESS_FILE` | the list, JSON lines. Default `/data/early-access.jsonl`, on the `runtime-data` volume (`deploy/docker-compose.yml`), so it survives `up --build` |
| `EARLY_ACCESS_PER_MIN` | sign-ups per minute per IP, on top of `RATE_LIMIT_PER_MIN` (default 5; `0` off) |

The web form shows only in a build with `NEXT_PUBLIC_SUBMISSION_MODE=0` (default `1`: the hackathon submission build,
where it renders nothing). Turn both on together, or the form will say sign-ups are not open.

**Owner tools** (no web admin; run on the server, inside the runtime container):

```sh
docker compose -f deploy/docker-compose.yml exec runtime python -m app.early_access count
docker compose -f deploy/docker-compose.yml exec -T runtime python -m app.early_access export --csv - > early-access.csv
docker compose -f deploy/docker-compose.yml exec runtime python -m app.early_access delete --email someone@example.co.uk
```

- `count`: people on the list (one per email).
- `export --csv FILE|-`: the current list, one row per email (newest details, first sign-up time, the consent text
  they ticked). `-` writes to stdout, as above, because the container's root filesystem is read-only. Cells starting
  `=`, `+`, `-` or `@` are prefixed with `'` so a spreadsheet does not run them. The CSV is personal data: keep it
  off shared drives and out of the repo (`.gitignore` covers `early-access*.csv`), and delete it after the mail-out.
- `delete --email`: **right to erasure and unsubscribe.** Removes every line for that address (the one rewrite of
  an otherwise append-only file). Do it within a month of the request (sooner is better); reply to confirm.
- `--file PATH` before the command reads another file (e.g. a backup).

**Rules for the list** (these are what the privacy page says; changing them means changing it first):

1. **One email at launch**, from Accnomos / Zaytuna Business Services Ltd, saying who it is from, with the 3-months
   offer and a working unsubscribe (a reply-to address you read, or a link). No newsletters, no other products, no
   sharing or selling the list. Anything more needs fresh consent.
2. **Unsubscribe = delete.** Anyone who asks (reply, email to admin@zaytunauk.co.uk) is removed with `delete --email`.
3. **Retention:** delete the whole list 12 months after launch (November 2027), except people who became customers
   (their account then has its own basis). `export` first if you need the converted ones, then
   `docker compose exec runtime rm /data/early-access.jsonl`.
4. **Bulk email provider:** if you use one for the launch email, it is your processor: use one with a UK GDPR data
   processing agreement, upload only the email column, and delete the upload afterwards. Name it on the privacy
   page before you upload.
5. **Backups** of the volume hold the list too: keep them encrypted and apply the same 12-month deletion.

The record per sign-up: email (trimmed, lower-cased), name (optional), business type, how they heard (optional), the
consent flag and its exact wording, the page they signed up on, and the time in UTC. No IP address is stored (the
rate limit is in memory only). A repeat sign-up appends a newer line; the newest wins and the first time is kept.
The form gives the same answer for new and repeat addresses, so it cannot be used to test who is on the list.

## 7. The AI provider chain (runtime)

**Recommended production (and judges' demo) setting: `AI_PROVIDERS=modal,meta,spark`.** Every AI call that names no
backend of its own (no `X-AI-*` headers, or `X-AI-Mode: auto`) tries Muse Glimmer 30B on Modal first, then Muse Spark
on the Meta Model API with the server's key, and only then the DGX Spark's local Ollama, so the live demo does not depend
on the owner's home server. All three serve Meta models. A user who chose their own backend in Settings (their local
agent, or their own Meta key via `X-Meta-Api-Key`) gets exactly that backend, with no failover, as before.
Code: `services/runtime/app/ai/providers.py` (the chain), `app/ai/chain.py` (failover, circuit breaker, call record),
`app/routes_ai.py` (`GET /ai/health`, `GET /ai/calls`, `POST /ai/warm`).

| Variable | Value |
|---|---|
| `AI_PROVIDERS` | ordered, comma-separated: `modal`, `meta`, `spark`. Unset = no chain (the single `AI_MODE` default, as before) |
| `MODAL_GLIMMER_URL` | the URL `modal deploy tools/modal_glimmer.py` prints, `https://<workspace>--accnomos-glimmer-serve.<region>.modal.run`. Unset = Modal left out of the chain |
| `MODAL_MODEL` | default `muse-glimmer:30b` |
| `MODAL_PROXY_TOKEN_ID`, `MODAL_PROXY_TOKEN_SECRET` | a Modal proxy-auth token, sent as `Modal-Key` / `Modal-Secret`; needed when the endpoint was deployed with `MODAL_PROXY_AUTH=1` (recommended). Secrets: server environment only |
| `META_API_KEY`, `MODEL_API_BASE`, `MODEL_API_MODEL` | the Meta Model API provider (defaults `https://api.meta.ai/v1`, `muse-spark-1.3`). No key = Meta left out |
| `OLLAMA_BASE`, `OLLAMA_MODEL` | the DGX Spark (defaults `http://localhost:11434`, `muse-glimmer:30b`) |
| `<NAME>_CONNECT_S`, `<NAME>_FIRST_TOKEN_S`, `<NAME>_REQUEST_S` | per provider (`MODAL`, `META`, `SPARK`), seconds: connect; the longest wait for a reply to start; the longest one attempt may take. Defaults Modal 10 / 150 / 240 (a cold start is 60-120 s), Meta 10 / 90 / 120, Spark 5 / 180 / 200 |
| `AI_BREAKER_FAILURES`, `AI_BREAKER_COOLDOWN_S` | circuit breaker: after this many failures in a row a provider is skipped for this long (defaults 3 and 120) |
| `AI_HEALTH_PROBE_MODAL` | `1` = `/ai/health` probes Modal for real. Off by default: a probe would start a paid GPU container |
| `BASETEN_API_KEY` | unchanged: with the chain, the Verifier tries Muse Spark Open on Baseten first, then the chain |

Failover happens on a timeout, a connection error, HTTP 5xx, 402 or 429 (billing, rate limit), and 401/403/404/408
(that provider's own credentials, model or gateway); never on any other 4xx (our own bad request) or on a reply that does
not parse. A streamed Ask answer fails over only before its first token. Voice transcription stays Muse Voice Transcribe
on the Meta provider; it needs `META_API_KEY`.

Modal side (deploy-time options of `tools/modal_glimmer.py`): deploy with `MODAL_PROXY_AUTH=1`, so a stranger who learns
the URL gets a 401 before any GPU starts. `MODAL_KEEP_WARM=08:00-18:00` keeps one container up in that window (about
$2.00/h: the L40S is $0.000542/s = $1.95/h on modal.com/pricing, checked 28 Oct 2026, plus a few cents of CPU and
memory); without it the web app's `POST /ai/warm` (sent when someone signed in opens Home or Review without their own AI)
starts a cold container while they look at the page.

`/health` shows the chain and which providers are configured (names and models, never keys or URLs).
