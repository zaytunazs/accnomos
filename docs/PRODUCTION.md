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
- **No personal data in the repo or the image**: the early-adopter list lives only on the `runtime-data` volume
  (§ 6); `.gitignore` and `.dockerignore` exclude list files and exports.
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
