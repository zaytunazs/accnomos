# Review: early-adopter sign-up list

Branch `claude/early-adopters` (from `main`). People who sign up before the public launch (November 2026) get 3 months
free at launch and one email when the app is ready. The product has no user database, so this list is the operator's
marketing data (controller: Zaytuna Business Services Ltd) and the only personal data the runtime keeps.

## ICO guidance checked (28 October 2026)

`ico.org.uk` is not reachable from this session's network (WebFetch: host not resolvable), so the pages were found
with WebSearch and read in full through a third-party fetcher (Exa). Quotes are from those copies on 28 Oct 2026.
Two of the pages carry the banner *"Due to changes made by the Data (Use and Access) Act, this guidance is under
review and may be subject to change"*: re-check before launch.

1. **How do we comply with the PECR electronic mail marketing rules?**
   <https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/guidance-on-direct-marketing-using-electronic-mail/how-do-we-comply-with-the-pecr-electronic-mail-marketing-rules/>
   - Unsolicited marketing email to *individual subscribers* needs consent (or a soft opt-in, which does not apply
     before anyone is a customer). PECR takes the UK GDPR standard: freely given, specific, informed, unambiguous.
   - "make it clear that the consent covers your electronic mail marketing messages and give your name in the consent
     request"; "you must not use pre-ticked opt-in boxes, silence or inactivity"; consent kept "separate from other
     things"; ask per channel ("marketing emails", not just "marketing").
   - "keep a record of the consent (eg who, when, how) so that you can demonstrate it is valid".
   - "You must not disguise or hide your identity … You must provide a valid contact address for recipients to opt
     out or unsubscribe", whether solicited or unsolicited. "You must make it easy for people to withdraw their consent."
   - Solicited messages (the person "specifically asked you to send that message") need no consent; the launch email
     arguably is solicited, but the design treats it as consent-based to be safe.
2. **Business-to-business marketing**
   <https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/business-to-business-marketing/>
   - Companies and LLPs are *corporate subscribers* (PECR's email consent rule does not apply); **sole traders and
     non-limited partnerships are individual subscribers**, treated like individuals. UK GDPR still applies to a named
     business contact, who must be told and needs a lawful basis. Our audience is mostly sole traders, so consent for all.
3. **What privacy information should we provide?** (right to be informed)
   <https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/individual-rights/the-right-to-be-informed/what-privacy-information-should-we-provide/>
   - Always, at collection: organisation name and contact details; purposes; lawful basis; retention period (or
     criteria); the individual's rights; the right to complain to a supervisory authority (UK: the ICO, with contact
     details). If applicable: recipients, international transfers, the right to withdraw consent ("as easy to withdraw
     as it is to give. Tell people how"), statutory/contractual obligation, automated decision-making, DPO.
4. Found in search results, not read in full: *Electronic mail marketing* (guide to PECR),
   <https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/guide-to-pecr/electronic-and-telephone-marketing/electronic-mail-marketing/>,
   and the *Direct marketing advice generator* (updated 28 April 2026 for the DUAA charity soft opt-in, not relevant here).

How the build maps to it: the checkbox is unticked, separate, names Accnomos and the channel ("Email me"); the record
stores who (email), when (UTC time), how (source page) and what (the exact wording, which the runtime refuses to
accept if it differs); the notice under the form gives the controller, purpose, retention, how to unsubscribe and a
link to `/privacy#early-access`, which lists every "always" item above plus withdrawal and the ICO complaint route.

## What changed

- **Runtime** `services/runtime/app/early_access.py`, mounted in `main.py`:
  `POST /public/early-access` (no sign-in) with `email`, `name?`, `business_type` (`company|sole_trader|personal|accountant`),
  `heard?`, `consent`, `consent_text`, `source`, `website` (honeypot). Off (503, no file) unless `EARLY_ACCESS_ENABLED=1`.
  Per-IP `TokenBucket` from `app/security.py` (`EARLY_ACCESS_PER_MIN`, default 5) on top of the global 60/min.
  Appends a JSON line to `EARLY_ACCESS_FILE` (default `/data/early-access.jsonl`, file mode 0600, fsync, `flock`
  shared with the CLI). Repeat sign-ups append; the newest line wins and `first_at` keeps the first time.
  Same 200 answer for new, repeat and honeypot submissions.
- **Owner CLI** `python -m app.early_access count | export --csv FILE|- | delete --email X` (`--file` to point
  elsewhere). Export defuses `= + - @` cells; delete rewrites the file atomically without that address.
- **Deploy:** `runtime-data` named volume at `/data` (created uid 10001, 0700 in `Dockerfile.runtime`), env defaults
  in `docker-compose.yml`; new root `.dockerignore`; `.gitignore` covers list files and exports. `deploy/README.md`
  checklist and `test_deploy_hardening.py` updated. `test_security_routes.py`: the route is listed as needing no `X-User`.
- **Web:** `src/lib/submission-mode.ts` (`NEXT_PUBLIC_SUBMISSION_MODE`, anything but `0` = submission mode;
  test-mode builds only can override per page via localStorage so one e2e build covers both modes),
  `src/lib/early-access.ts` (consent text, client, errors), `src/components/early-access/EarlyAccessForm.tsx`
  on the signed-out landing page (`/`). Labelled fields, radio group for business type, inline errors with
  `aria-invalid` and focus to the first problem, `role="alert"` for failures, focused `role="status"` success
  ("You're on the list — we'll email you once at launch"), 44 px targets, single column at 360 px.
- **Docs:** `/privacy` (new `#early-access` section, data-map row, softened "nothing personal" claims, ICO complaint
  route), `docs/SECURITY.md` (threat-model note, protection row, a section on the list), `docs/PRODUCTION.md` § 6
  (variables, owner commands, rules for using the list, retention steps).
- **Tests:** `tests/test_early_access.py` (38 cases: storage and consent text, validation, consent required, wording
  must match, honeypot, rate limit, duplicates, newline collapsing, disabled never writes, CORS preflight, torn line,
  CLI count/export/stdout/delete/missing file/`-m` entry point); `e2e/early-access.spec.ts` (sign-up at 360 px
  checked in the runtime's file, axe on the form incl. error state, a 503 shown, absent in submission mode).

## Gates (this branch, Linux)

`pytest -q` in `services/runtime`, `ruff check .`, `ruff format --check .`, `pyright services/runtime/app`,
`pnpm install --frozen-lockfile`, `pnpm exec eslint .`, `pnpm run e2e:build`, `pnpm run e2e:test` with
`CI=1 E2E_WEB_PORT=3260 E2E_RUNTIME_PORT=8822 E2E_RELAY_PORT=8823`. Results on 28 Oct 2026: pytest 1265 passed,
1 skipped; ruff 0.17.3 check and format clean; pyright 1.1.414 0 errors; eslint clean; e2e 229 passed, 58 skipped
(all `shots.spec.ts`, opt-in), 0 failed. `early-access.spec.ts` also ran 25/25 with `--repeat-each=5 --retries=0`.
`e2e/site-health.spec.ts` had `127.0.0.1:3100` hard-coded and failed on any other `E2E_WEB_PORT` (also on `main`);
it now uses `WEB_URL` from `e2e/env.mjs`. Playwright
here needed `PLAYWRIGHT_BROWSERS_PATH` pointing at symlinks to the pre-installed Chromium build (the project pins a
newer Playwright than the container's browser); no repo change for that.

## Not done / for the owner

- **`/judges` page does not exist on `main`** (nor on any branch I could see). The form takes `source="/judges"`; add
  `<EarlyAccessForm source="/judges" />` to that page when it lands. In the submission build it renders nothing anyway.
- **The flag helper is mine** (`src/lib/submission-mode.ts`, default 1). If the other agent's landing-page work adds
  its own helper, merge to one: keep the "anything but 0 is submission mode" default.
- **Server location / transfers:** the privacy page says "a server we run ourselves" without a country. If the host
  is outside the UK, add the transfer details (adequacy or safeguards) before switching the feature on.
- **The launch email itself** is not built: send it by hand or via a provider (then name the provider on `/privacy`
  first, sign a DPA, upload only emails). Every message must say who it is from and carry an unsubscribe route.
- **Not run against the Docker image** (no Docker here): the volume ownership relies on Docker copying `/data`'s
  owner into a fresh named volume. Check with `docker compose exec runtime touch /data/x` after the first deploy.

## Risks

- **Abuse:** a bot that skips the honeypot can still add addresses (5/min per IP, unlimited IPs). There is no
  double opt-in, so someone can add another person's address. Mitigation: one email only, unsubscribe deletes, and
  the export is reviewed by a person. A confirmation email (double opt-in) would need mail sending from the server.
- **Single process state:** the rate limit is in memory; the file lock is `flock` (POSIX). Fine for one runtime
  container; several replicas would need shared storage and a real lock.
- **Erasure and backups:** `delete` cannot reach volume backups; the retention rule in PRODUCTION.md applies to them.
- **Drift of the consent wording:** the runtime refuses a mismatch (400 "reload the page"), so a web change without the
  matching runtime change fails loudly instead of storing the wrong wording.
- **ICO guidance under review** for the Data (Use and Access) Act 2025; re-check the three pages above before launch.
