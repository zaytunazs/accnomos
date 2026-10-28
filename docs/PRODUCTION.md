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
- **Sandbox tests stay sandbox.** The test suites fake HMRC and Companies House; never point them at production.

## 5. Not tested live

Nothing here has run against HMRC production. The VAT check and the MTD calls have been run only against fakes in the
test suites; HMRC's sandbox has not been called from this branch (no sandbox credentials in the session that built it).
Companies House has been called only through a faked transport. See `docs/HONESTY.md`.

## 6. The AI provider chain (runtime)

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
