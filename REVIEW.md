# Review: company and VAT look-ups (`claude/company-lookup`)

Look up UK businesses from official sources, built and tested on sandbox and fakes; switched to production later by
environment variables only (`docs/PRODUCTION.md`). HMRC stays **sandbox** until the owner flips it: no production
credential and no default pointing at production was added anywhere.

## What was built

**Relay** (`services/hmrc-relay`)
- `GET /hmrc/vat-check/{vrn}?requester=` (`relay/routes.py`): accepts `GB` + 9 or 12 digits (spaces, dots, hyphens
  allowed), 400 without calling HMRC otherwise; gets an application-restricted token by client credentials **with the
  `read:vat` scope** (`relay/oauth.py`: the app-token cache is now per scope, until 60 s before expiry); calls Check a UK
  VAT number **v2.0** on `HMRC_BASE`; returns `{vrn, registered, name, address, consultation_number, checked_at,
  checksum_ok, source, hmrc_processing_date}` with `source` `hmrc-sandbox` or `hmrc` from `HMRC_BASE`. HMRC 404 →
  `registered: false`; HMRC 403 with a requester → 400 "HMRC doesn't recognise your own VAT number". Rate-limited per
  client IP by the existing middleware; no bodies logged. The raw `/vat/check/...` routes now also use the `read:vat` token.
- `checksum_ok` (mod-97, old and 1999+ schemes) is **informational only**: HMRC's own sandbox test number 553557881 fails
  it, so enforcing it would block the sandbox. No mod-97 helper existed in the runtime/ledger (only in `evals` tests).

**Runtime** (`services/runtime`)
- `app/company_lookup.py`: `search(q)` / `profile(number)` against the Companies House Public Data API (HTTP Basic,
  key as username, empty password); key from `COMPANIES_HOUSE_API_KEY`; 24 h in-process cache (1,024 entries); polite
  per-process limit of 60 a minute (half CH's 600 per 5 min); company numbers normalised (`6` → `00000006`,
  `sc 123456` → `SC123456`); a number typed into search goes to the profile. `check_vat(vrn)` calls the relay at
  `HMRC_RELAY_URL`. Test mode: fictional SAMPLE companies (numbers `ZZ000001`–`ZZ000004`; `ZZ` is not a CH prefix) and the
  gold receipts' fictional suppliers for VAT; no network.
- `app/routes_lookup.py`: `GET /lookup/status` (no sign-in; says only what is configured), `GET /lookup/companies?q=`,
  `GET /lookup/companies/{number}`, `GET /lookup/vat/{vrn}` (signed-in: `X-Graph-Token`, so the CH key is not an open
  proxy). Errors are `{"error": code, "detail": message}` via one handler in `app/main.py`: 503
  `companies_house_not_configured` / `vat_check_not_configured`, 400 `bad_query`, 404 `not_found`, 429 `rate_limited`
  with Retry-After, 502 `lookup_unavailable`.
- Contacts: `company_number` (editable, normalised, validated) and `vat_check` (the last HMRC result for the contact's
  VRN; dropped when the VRN is edited) on `Contact`; old `contacts.json` files load (both default to null).
  `Contact.verified_vat_name()` gives HMRC's name for the current VRN, for the AI-merge branch. `POST /contacts/vat-check`
  checks on a tap and keeps the answer on the contact with that VRN (no contact → nothing created; process cache only);
  a second tap answers from the contact (`cached: true`). `name_differs` is a warning, never a block. VAT status is left
  to the user. Audit: `contact_vat_checked`.
- `deploy/docker-compose.yml` passes `COMPANIES_HOUSE_API_KEY` (empty default) and `HMRC_RELAY_URL`
  (`http://relay:8787`); `.env.example` documents both with empty/local values.

**Web** (`apps/web`)
- `components/contacts/Lookups.tsx`: `CompanyLookup` (Contacts › Edit: name or number → matches → pick fills legal name,
  company number, registered address; the user saves), `VatCheckButton` ("Registered to <name>, <address> (HMRC sandbox)"
  or "Not VAT-registered…", "Checked <date>", HMRC reference when present, a warning when the name differs). Both hidden
  unless `/lookup/status` says configured.
- Contacts side panel: *Company number* row and *Check VAT number*. Review cards: *Check VAT number* for a purchase with a
  supplier VAT number (only on a tap; Approve never waits for it). New invoice: under the existing contacts combobox, a
  separate "Look up “…” on Companies House" button and a separate suggestions list (the combobox/listbox ARIA is
  unchanged; suggestions are not `role=option`).

**Also fixed:** `test_unhandled_error_is_safe_json_with_correlation_id` failed whenever the runtime and relay suites ran
in one pytest process (the brief's gate command). Both services install a log-record scrubbing factory; the outer one
skipped `exc_text` the inner one had filled without the request's secrets. Both now always re-scrub `exc_text`
(`app/security.py`, `relay/security.py`). Reproduced on a snapshot of `main` with
`pytest services/runtime/tests/test_security.py services/hmrc-relay` → 1 failed; fixed here → 161 passed.

**Docs:** `docs/PRODUCTION.md` (new: production application + subscriptions, `HMRC_BASE`/auth base/redirect URI,
fraud-header validation, Companies House key, and what must not change), README feature row and docs list,
`docs/HONESTY.md` (fakes only, sandbox-only, untested live), `docs/REMAINING.md` (three rows), relay README endpoint row.

## What I verified

Commands from the worktree root with `source .v/bin/activate` and the absolute `PYTHONPATH` from the brief:

| Gate | Result |
|---|---|
| `python -m pytest services/runtime packages services/hmrc-relay evals -q` | **1561 passed, 1 skipped** (runtime 1101 + 1 skipped, packages 83, relay 119, evals 258). Relay was 102; +17 in `tests/test_vat_check.py`. Runtime +21 in `tests/test_company_lookup.py` |
| `ruff check services packages evals`; `ruff format --check` on every touched `.py` | clean (13 files) |
| `pyright services/runtime/app` | 0 errors, 0 warnings |
| `apps/web`: `pnpm exec eslint .`, `pnpm run build`, `pnpm exec tsc --noEmit` (after the build) | clean |
| e2e (`E2E_WEB_PORT=3600 E2E_RUNTIME_PORT=9281 E2E_RELAY_PORT=9289`), `lookups.spec.ts` + contacts, invoices, review, review-vat, credits-bills, home, audit | 24/24 pass |
| e2e full suite, all projects | **195 passed, 1 failed**: `site-health.spec.ts:10` (hard-codes port 3100; expected on other ports) |

The first full e2e run caught two regressions (strict-mode "2 status elements" in `home.spec.ts` and
`credits-bills.spec.ts`, from the VAT check's `role="status"`); it now uses `aria-live` only, and both pass.

### External facts (checked 27 Oct 2026)

Companies House Public Data API — **verified**:
- Auth: HTTP Basic, API key as username, password ignored/blank; example host `https://api.company-information.service.gov.uk`
  — https://developer.company-information.service.gov.uk/authentication
- Rate limit: 600 requests per 5 minutes, then `429 Too Many Requests` —
  https://developer.company-information.service.gov.uk/developer-guidelines
- Endpoints `GET /search/companies` (`q`, `items_per_page`, `start_index`, `restrictions`), `GET /company/{companyNumber}`,
  `GET /company/{companyNumber}/registered-office-address` —
  https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/reference ,
  https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/reference/search/search-companies ,
  https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/reference/company-profile/company-profile
  (profile fields incl. `registered_office_address` with `premises`, `address_line_1/2`, `locality`, `region`,
  `postal_code`, `country`; 404 with no body). **Not verified:** the field names of search `items[]` (the page links to
  a `CompanySearch` resource I did not open); the code reads `title`, `company_number`, `company_status`,
  `company_type`, `address`, `address_snippet`, `date_of_creation` and tolerates any being absent.

HMRC Check a UK VAT number — **verified** from HMRC's OAS (the HTML pages are robots-blocked for WebFetch; read through
a search index of https://developer.service.hmrc.gov.uk/api-documentation/docs/api/service/vat-registered-companies-api/2.0/oas/resolved
and the overview page https://developer.service.hmrc.gov.uk/api-documentation/docs/api/service/vat-registered-companies-api/2.0):
- Current: **version 2.0** ("Version 2.0 – beta", last updated 14 Oct 2026); "Version 1 was removed on 17 February 2025.
  You need to register to have access to Version 2"; registering takes around 2 weeks; production credentials after
  sandbox testing and accepting Terms of Use 2.0.
- Authorisation: `applicationRestricted` (OAuth 2.0 client credentials), bearer token **with the `read:vat` scope**;
  `Accept: application/vnd.hmrc.2.0+json`.
- Base URLs: sandbox `https://test-api.service.hmrc.gov.uk`, production `https://api.service.hmrc.gov.uk`.
- `GET /organisations/vat/check-vat-number/lookup/{targetVrn}` → `{target: {name, vatNumber, address: {line1, postcode,
  countryCode, …}}, processingDate}`; `…/{targetVrn}/{requesterVrn}` adds `requester` and `consultationNumber`. VRNs are
  9 or 12 digits. Errors: 400 `INVALID_REQUEST`, 403 requester not registered, 404 `NOT_FOUND` "targetVrn does not match
  a registered company", 500.
- Sandbox test data: OAS example target `553557881`, requester `146295999727`; HMRC links a list of mock VRNs
  (github.com/hmrc/vat-registered-companies-api, `…/test-data`); I saw the 1.0 `vrn.csv` list via search, not the 2.0 one.
- Client credentials, `scope` parameter, 4-hour token: https://developer.service.hmrc.gov.uk/api-documentation/docs/authorisation/application-restricted-endpoints
- Production authorise host `https://www.tax.service.gov.uk`: https://developer.service.hmrc.gov.uk/api-documentation/docs/authorisation/user-restricted-endpoints

**Not verified:** whether HMRC expects fraud-prevention headers on this application-restricted API (none are sent);
the exact production-approval checklist for MTD VAT. No call was made to HMRC's sandbox or to Companies House: the
session had no credentials or key.

## What remains

- Run once against HMRC's sandbox with real sandbox credentials (`curl $RELAY/hmrc/vat-check/553557881`) and against
  Companies House with a real key; confirm the search `items[]` field names.
- `/vat` copy still says "(sandbox)"; make it follow `/health`'s `sandbox` flag before going live (`docs/PRODUCTION.md`).
- All users' VAT checks share the relay's per-IP limit (the runtime is one IP).
- A Review-card VAT check for a supplier with no contact yet is only cached in process (24 h).
- Android has neither look-up. The AI-merge branch can read `company_number` and `verified_vat_name()`; merging is not
  built here.
- Not pushed (as instructed).
