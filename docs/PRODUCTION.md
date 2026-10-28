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

## 4. What must NOT change

- **No production value as a default anywhere in the repo**: not in `Settings` (`services/hmrc-relay/relay/settings.py`),
  `deploy/docker-compose.yml` or `.env.example`. Defaults stay sandbox, so a server with no `.env` can only reach the sandbox.
- **No secret in the repo or the image**: HMRC client secret and the Companies House key come from the server's
  environment only. The relay never reads a `.env` file itself.
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
- At start-up the runtime seeds the day's sample books once, in a background thread (the whole `tools/seed_demo.py`
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
