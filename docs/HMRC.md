# HMRC (sandbox): connect and submit a VAT return from the web app

Sandbox only. The `/vat` page shows the live 9-box return, calculated by code from the ledger events you approved
(`GET /books/vat` on the runtime). Under it, **Connect to HMRC (sandbox)** lets you submit that return. AI proposes the
entries, you approve them, code calculates the boxes, and nothing is sent until you tick the legal declaration and press Submit.

Code: `apps/web/src/lib/hmrc.ts`, `apps/web/src/components/vat/ConnectHmrc.tsx`, relay in `services/hmrc-relay`.

## Flow

1. **Connect.** The browser makes a PKCE verifier (64 chars) and its S256 challenge, then calls
   `GET {RELAY}/hmrc/authorize?redirect_to=<origin>/vat&code_challenge=…` → `{url, state}`. `verifier` and `state` go into
   `sessionStorage["accnomos.hmrc.pending"]`, and the browser goes to HMRC's consent page (`url`).
2. **Consent.** You sign in on HMRC's site with a sandbox test user and grant `read:vat write:vat`. HMRC redirects to the
   relay's `/hmrc/callback`. The relay sends a 303 back to `/vat#code=…&state=…`. The code travels in the URL fragment, so it
   never reaches a server log.
3. **Exchange.** On load, `/vat` reads the fragment and immediately removes it with `history.replaceState`. It checks that
   `state` matches the pending one, then calls `POST /hmrc/exchange {code, state, code_verifier}`. The relay adds the client
   secret, and the tokens come back to the browser. They are stored in `sessionStorage["accnomos.hmrc"]` with `expires_at`.
4. **Obligations.** You enter the VRN. It is prefilled from `localStorage["accnomos.business.vrn"]`, or else from the
   onboarding VAT number. The page then calls `POST /vat/{vrn}/obligations` for the last 12 months. If an open obligation
   has the same dates as the live return, it is preselected. Otherwise you pick one. The list is also posted to
   `POST /books/vat/obligations` on the runtime, so `/books/vat/periods` marks fulfilled periods submitted (source
   `hmrc`) even when they were filed elsewhere, and warns when HMRC's dates match none of your periods.
5. **Confirm.** The confirmation card shows the 11-field body that will be sent. It is the runtime's `hmrc_body` under the
   obligation's `periodKey`, with `finalised: true`. Boxes 1–5 are pence and 6–9 whole pounds. The card also shows HMRC's
   declaration text and a checkbox that must be ticked.
6. **Submit.** `POST /vat/{vrn}/returns`. The relay checks box 3 = 1 + 2 and box 5 = |3 − 4| before calling HMRC, and
   returns 422 if they don't add up. The receipt card shows `processingDate`, `formBundleNumber`, `paymentIndicator`,
   `chargeRefNumber` (when present) and HMRC's correlation ID.
7. **Keep a copy.** `return.json` (body, period, ledger event IDs, declaration time) and `receipt.json` (HMRC response,
   correlation/receipt IDs, the fraud-prevention headers actually sent) are written to
   `06 VAT returns/<periodKey>/` in your OneDrive books folder through Microsoft Graph.

Tokens are refreshed through `POST /hmrc/refresh` a minute before `expires_at`. If refresh fails, the page forgets the
session and asks you to connect again. **Disconnect** clears `sessionStorage`.

The **Advanced: sandbox test scenario** box sets `Gov-Test-Scenario` (for example `QUARTERLY_NONE_MET`) on obligations
and submission calls. Leave it empty for HMRC's default sandbox response.

## Who holds what

| Where | Holds | Lifetime |
|---|---|---|
| Relay (`api.accnomos.com/hmrc`, `/vat`) | HMRC client ID and **client secret** only. Short in-memory caches: the app-restricted token, and 30 s of refresh results so racing refreshes share one HMRC call | Process memory; never on disk or in logs |
| Browser `sessionStorage` | HMRC access + refresh token, `expires_at`; PKCE verifier + state while the redirect is in flight | Until the tab closes or you press Disconnect |
| Browser `localStorage` | `accnomos.device_id` (random UUID for Gov-Client-Device-ID), `accnomos.business.vrn` | Until you clear site data |
| Your OneDrive | `06 VAT returns/<periodKey>/return.json` and `receipt.json` | Yours |

User tokens reach the relay only in the `X-HMRC-Access-Token` header of each request. The relay accepts browser calls
(CORS) only from the origins in `RELAY_ALLOWED_REDIRECTS`, plus `http://localhost` for development.

## Fraud-prevention headers (`WEB_APP_VIA_SERVER`, spec v3.3)

Each VAT call sends a JSON envelope `{client_facts, method: "WEB_APP_VIA_SERVER", gov_test_scenario?, …}`. The relay turns
the facts into `Gov-*` headers. The full table is in `services/hmrc-relay/README.md`.

| Header | Collected by | Source |
|---|---|---|
| Gov-Client-Device-ID | browser | UUID made once, `localStorage["accnomos.device_id"]` |
| Gov-Client-Multi-Factor | browser | `[]` (HMRC sign-in MFA isn't visible to us; Microsoft MFA isn't reported) |
| Gov-Client-Screens | browser | `screen.width/height`, `devicePixelRatio`, `screen.colorDepth` |
| Gov-Client-Timezone | browser | `UTC±HH:MM` from `getTimezoneOffset()` |
| Gov-Client-User-IDs | browser | `accnomos=` SHA-256 hex of the MSAL `homeAccountId` (never the raw ID or e-mail) |
| Gov-Client-Window-Size | browser | `innerWidth` × `innerHeight`, read at each call |
| Gov-Client-Browser-JS-User-Agent | browser | `navigator.userAgent` |
| Gov-Vendor-Version | browser + relay | `accnomos-web=0.1.0` plus `accnomos-relay=<HMRC_VENDOR_VERSION>` |
| Gov-Client-Public-IP / -Timestamp / -Port | relay | `X-Forwarded-For` / `X-Client-Port` set by the edge nginx (`deploy/nginx.conf`) |
| Gov-Vendor-Public-IP / -Forwarded / -Product-Name / Connection-Method | relay | settings and `method` |

A fact is omitted when the browser genuinely can't provide it; the app never sends placeholders. If anything is missing,
the relay lists it in `fraud_headers_missing`, and the page shows a quiet note under the card.

## Trying it

```sh
# relay on :8787 (HMRC_* in the environment, sandbox), runtime on :8780, web on :3000
curl -X POST http://localhost:8787/hmrc/test-user        # → userId, password, vrn
```

Open `http://localhost:3000/vat` while signed in with Microsoft and press **Connect to HMRC (sandbox)**. Sign in with the
test user's `userId` / `password`, then enter its `vrn`.

# HMRC (sandbox): self-employment, Making Tax Digital for Income Tax

Sandbox only, like VAT, and stricter: every Income Tax route on the relay answers 403 against a production `HMRC_BASE`
unless `RELAY_ITSA_PRODUCTION=1` is set as well, and nothing in this repository sets it. Never run against HMRC from
this machine: everything below was built and tested on fakes that answer with HMRC's own example payloads
(`docs/HONESTY.md`).

Code: `apps/web/src/components/itsa/SelfEmployment.tsx`, `apps/web/src/lib/itsa.ts`, relay `services/hmrc-relay/relay/itsa.py`,
runtime `services/runtime/app/itsa.py` (figures), `services/runtime/app/routes_itsa.py` (receipts, reports) and
`services/runtime/app/itsa_reports.py` (SA103 summary, quarterly update, HMRC calculation as rows + CSV/XLSX/PDF).

The page is `/self-employment`. It is in the menu (Money) only when **Settings › Business › I am self-employed** is on;
that is off by default. When profile kinds arrive it belongs to `sole_trader` profiles.

## Sources checked (28 Oct 2026)

HMRC's developer site blocks automated fetchers in robots.txt, so the pages and their OpenAPI files were read with
`curl` (`…/oas/resolved` and the referenced `…/oas/<file>` YAML/JSON). The API list's links give the current versions.

| API | Version used | Status on the page | URL |
|---|---|---|---|
| Business Details (MTD) | 2.0 | beta, Sandbox and Production, updated 26 Oct 2026 | https://developer.service.hmrc.gov.uk/api-documentation/docs/api/service/business-details-api/2.0 |
| Obligations (MTD) | 3.0 | beta, Sandbox and Production, updated 16 Oct 2026 | https://developer.service.hmrc.gov.uk/api-documentation/docs/api/service/obligations-api/3.0 |
| Self Employment Business (MTD) | 5.0 | beta, Sandbox and Production, updated 23 Oct 2026 | https://developer.service.hmrc.gov.uk/api-documentation/docs/api/service/self-employment-business-api/5.0 |
| Individual Calculations (MTD) | **8.0** | beta, Sandbox and Production. 9.0 is newer but "[test only]", Sandbox only; the four endpoints used are the same | https://developer.service.hmrc.gov.uk/api-documentation/docs/api/service/individual-calculations-api/8.0 |
| Self Assessment Test Support (MTD) | 1.0 | beta, Sandbox | https://developer.service.hmrc.gov.uk/api-documentation/docs/api/service/mtd-sa-test-support-api/1.0 |
| Create Test User | 1.0 | beta, Sandbox | https://developer.service.hmrc.gov.uk/api-documentation/docs/api/service/api-platform-test-user/1.0 |
| Fraud prevention | spec 3.3 (27 Jan 2025) | required by law for VAT and Income Tax | https://developer.service.hmrc.gov.uk/guides/fraud-prevention/ |
| End-to-end service guide | (final declaration text, cumulative updates) | | https://developer.service.hmrc.gov.uk/guides/income-tax-mtd-end-to-end-service-guide/ |
| SA103F mapping CSV | v3 | expenses = totals (boxes 17-30), disallowable = boxes 32-45 | https://github.com/hmrc/income-tax-mtd-changelog/blob/main/mapping/csv/sa103f_mapping_v3.csv |
| Cash basis | default from 6 April 2024 | | https://www.gov.uk/simpler-income-tax-cash-basis |

Scopes (from each API's OAS security scheme): `read:self-assessment` for reads, `write:self-assessment` for the
cumulative update, triggering a calculation, the final declaration and test-business creation. The page asks
`/hmrc/authorize?scope=read:self-assessment write:self-assessment` and keeps that session apart from VAT's
(`sessionStorage["accnomos.hmrc.itsa"]`), so connecting one never drops the other.

HMRC warns on the Individual Calculations page: *"HMRC is no longer accepting production credential access requests
for new 2026–27 quarterly update products, as the market window for these products has now closed."*

## Flow

1. **Connect.** Same PKCE flow as VAT, back to `/self-employment#code=…&state=…`, Income Tax scopes.
2. **Businesses.** NINO in (kept in `localStorage["accnomos.itsa.nino"]`), `POST {RELAY}/itsa/{nino}/businesses` →
   Business Details 2.0 `GET /individuals/business/details/{nino}/list`. Only `self-employment` sources are listed.
3. **Obligations.** `POST /itsa/{nino}/obligations {from, to, business_id}` → Obligations 3.0
   `GET /obligations/details/{nino}/income-and-expenditure?typeOfBusiness=self-employment&businessId&fromDate&toDate`
   for the tax year (6 April to 5 April; HMRC allows at most 366 days). From 2025-26 every obligation starts on 6 April:
   updates are cumulative. The first open one is picked.
4. **Figures.** `GET {RUNTIME}/books/self-employment/summary?tax_year=2026-27&period_end=<obligation end>`: code adds
   up the approved ledger lines from 6 April to the period end (on the cash basis by default: dated when the money
   moved, see *Accounting basis* below) into the API's fields, with the SA103F box for each and
   the ledger lines behind it (drill-down on the page). Mapping (`app/itsa.py`): 4000-4899 turnover, 4900-4999 other
   income, 5xxx cost of goods, 6xxx advertising, 7000-7099 staff, 7100-7299 and 7700-7799 premises (rent, utilities,
   insurance), 7300-7499 car/van/travel, 7500-7599 admin, 7600-7699 professional fees, 7800-7899 repairs, 7900-7909
   bank charges, 7910-7949 interest, 7950-7989 bad debts, 7990-7999 other, 8000-8099 depreciation; name words override
   (entertain, depreciat, subcontract, bad debt, interest, repair). `periodExpenses` holds **totals** and
   `periodDisallowableExpenses` the disallowable part, as HMRC's SA103F mapping has it: client entertainment and
   depreciation in full, plus accounts named disallowable/private/personal. Every income and expense field is sent,
   zeros included (HMRC: "Submissions must include values for income and expenses, even if the values are zero").
5. **Confirm and submit.** A tick-box ("I have checked these figures. Send them to HMRC (sandbox) …") enables
   **Submit update to HMRC** → `POST /itsa/{nino}/self-employment/{businessId}/cumulative/{taxYear} {summary, confirmed: true}`
   → Self-Employment Business 5.0 `PUT /individuals/business/self-employment/{nino}/{businessId}/cumulative/{taxYear}`
   (HMRC answers 204). The relay validates the body against HMRC's schema first (2 dp, ranges, no unknown fields, not
   both consolidated and itemised expenses, dates in the tax year, tax year 2025-26 or later) and refuses without
   `confirmed: true`.
6. **Receipt.** The page posts what was sent and the relay's envelope (correlation ID, the `Gov-*` headers actually
   sent, any missing ones) to `POST {RUNTIME}/books/self-employment/receipts`. The runtime recomputes the figures and
   records `matches_books`, writes `_System/itsa/{taxYear}/{businessId}/update-to-{end}-{timestamp}.json`, adds it to
   `_System/itsa/{taxYear}/receipts.json` and writes an audit line (`itsa_update_submitted`).
7. **HMRC's calculation.** **Ask HMRC for a calculation** → `POST /itsa/{nino}/calculations/{taxYear}/trigger
   {calculation_type: in-year}` (Individual Calculations 8.0 `POST …/self-assessment/{taxYear}/trigger/in-year`, 202
   `{calculationId}`), waits 5 seconds as HMRC asks, then `POST …/{calculationId}/view` (retried on HMRC's 404 while it
   is still calculating). The response is saved as `_System/itsa/{taxYear}/calculations/{id}.json` and shown through
   `GET /books/self-employment/reports/calculation`: HMRC's income, Income Tax, Class 2/4 NIC and
   `totalIncomeTaxAndNicsDue`, its end-of-year estimate and its messages, labelled as HMRC's. Accnomos works out no tax.
8. **Final declaration** (after the tax year). `intent-to-finalise` calculation as above, HMRC's declaration shown word for
   word with a tick-box, then `POST …/{calculationId}/final-declaration {declaration, confirmed: true}` → `POST
   …/{calculationId}/final-declaration` (204). The relay and the runtime refuse any other declaration text.

## Accounting basis: cash (default) or traditional

**Sources (checked 28 Oct 2026).** gov.uk and HMRC's developer site cannot be reached from the build machine's network
(the proxy refuses them), so the pages below were read through the Exa fetcher; the quotes are verbatim from what it
returned.

| What | Found | URL |
|---|---|---|
| Cash basis is the default | "From 6 April 2024, cash basis became the default method of accounting." "With cash basis you only record income or expenses when you receive money or pay a bill." Traditional: "you record income and expenses by the date you invoiced or were billed." | https://www.gov.uk/simpler-income-tax-cash-basis (and `/print`) |
| When income counts | "Only record income you actually receive." Example: invoiced 15 March 2024, paid 30 April 2024 → "Record this income as received on 30 April 2024." "Only count the expenses you've actually paid." | same |
| Equipment | allowable: "things you use in your business - for example, machinery, computers and vans (there are different rules for cars)"; "you claim the cost of other equipment you buy to keep and use in your business as a normal allowable business expense rather than as a capital allowance"; a car: "claim the purchase as a capital allowance" | same |
| VAT | "You can record your business income and expenses either excluding or including VAT. However, you must treat income and expenses the same way." | same |
| Capital not allowed on the cash basis | no deduction for capital spent on buying a business, education or training, a non-depreciating asset, an asset not for continuing use, a car, land, a non-qualifying intangible, a financial asset (s33A ITTOIA 2005) | https://www.legislation.gov.uk/ukpga/2005/5/section/33A, https://www.gov.uk/hmrc-internal-manuals/business-income-manual/bim70035 |
| SA103F (2026) notes | box 29 depreciation: "Only use this box if you use traditional accounting"; "If you use cash basis, you can only claim capital allowances for the cost of buying cars" | https://assets.publishing.service.gov.uk/media/69c26565cfa346b9d4704b35/SA103F_Notes_2026.pdf |
| HMRC holds the method per business | end-to-end service guide, *Capture and Change Accounting Method*: show what HMRC holds with **Retrieve Accounting Type**, change it with **Update Accounting Type** (Business Details API 2.0, `GET`/`PUT /individuals/business/details/{nino}/{businessId}/{taxYear}/accounting-type`, `read:`/`write:self-assessment`); users confirm it at the end of the tax year; it rolls over. The cumulative period summary has no basis field. | https://developer.service.hmrc.gov.uk/guides/income-tax-mtd-end-to-end-service-guide/documentation/make-updates-at-tax-year-end.html, https://developer.service.hmrc.gov.uk/api-documentation/docs/api/service/business-details-api/2.0/oas/resolved |

**Setting.** Settings › Business › I am self-employed › **Accounting basis**: cash (default) or traditional (accruals).
Saved in the books, `_System/itsa/settings.json` (`GET`/`PUT /books/self-employment/settings`, `PUT` needs `X-User`),
so every device and every update uses the same basis; a change writes an audit line (`itsa_basis_changed`). One basis
per set of books (one business per books today); HMRC allows a different method per business.

**How the cash figures are made** (`services/runtime/app/cash_basis.py`, pure, writes nothing). The ledger is read as
it is; `cash_view` derives entries dated when the money moved, using the same payment allocation as Contacts and
Invoices (`app/settlement.py`):

- a sales invoice or bill on account (Dr 1100 Debtors / Cr 2100 Creditors) counts when paid: each payment (recorded,
  *Mark paid*, or a bank line matched to it) counts on its date as its share of each income or expense line. Shares are
  rounded on the running total paid, so the payments of a fully paid document add up to it exactly;
- a receipt paid when bought, a cash sale, an expense posted from a bank line, a credit note settled in cash: on its
  own date, as posted;
- a credit note against an invoice moves no money: it counts through what is then paid (£1,000 invoice, £200 credit
  note, £800 paid → £800). When a credit is **refunded**, the refund counts on its date as that share of the credit note;
- an overpayment is listed as not counted while it sits on the contact; applied to an invoice later, it counts on the
  day the money came in;
- journals that move debtors or creditors with a P&L line (a bad debt written off) and depreciation are not counted and
  are listed with the reason;
- capital (an asset account, code 0xxx): equipment counts in **box 30 (otherExpenses)** when paid; an asset named as a
  car, land, building, property, freehold/leasehold, goodwill, patent, trade mark, copyright, investment, shares,
  education or training is left out (s33A), with "claim capital allowances" for a car. The box is Accnomos's choice:
  neither the notes nor the API name one for cash-basis equipment;
- VAT is excluded (only income, expense and asset lines are carried), as traditional figures are.

`GET /books/self-employment/summary` and `GET …/reports/sa103` use the saved basis, or `?basis=cash|traditional` for a
look without changing it. The summary carries `accounting_basis`, `basis_label`, and for every line on the cash basis
the payment behind it (`paid_how`, `payment_id`, `document_ref`, `money_pence` of `document_gross_pence`) plus a
`left_out` list. The SA103 report's notes start "Accounting basis: …", its last sections are *Payments behind each
box* and *Not counted on the cash basis*. A cumulative receipt records the basis it was checked on (`basis` in the
request, else Settings) as `accounting_basis`, and the quarterly report shows it. Receipts saved before this change
have none and were traditional.

**P&L.** `GET /reports/pl?basis=cash` (and `basis` in `POST /reports/export`) reads the same cash view; the Reports page
offers *As approved / Cash basis* when *I am self-employed* is on. Assets bought (0xxx) are not P&L accounts, so the
cash P&L leaves equipment out while the self-employment summary claims it.

**Not built.** Telling HMRC the method (Business Details 2.0 Retrieve/Update Accounting Type) is not in the relay; the
user must make HMRC's record match Settings at the end of the year. No transitional adjustments when switching
between bases, no "including VAT" option, no capital allowances (cars, or anything on traditional accounting).

## Reports

`GET /books/self-employment/reports/{sa103|quarterly|calculation}?…&format=json|csv|xlsx|pdf` (`app/itsa_reports.py`):
the SA103-style summary (boxes, totals, every ledger line), a quarterly update as sent with its receipt, and HMRC's
calculation. Each is a pure function returning rows plus CSV/XLSX/PDF renderers, written to register in the shared
exports registry (branch `claude/exports`) when it merges. CSV cells that start with `= + - @` are prefixed with `'`.

## Sandbox test data

```sh
curl -X POST http://localhost:8787/hmrc/test-user/individual     # → userId, password, nino, mtdItId, saUtr
```

Sign in on `/self-employment` with that user, then make a self-employment test business (purged by HMRC after 7 days):
`POST {RELAY}/itsa/{nino}/test-business {tax_year, client_facts, method}` with the user's token (Test Support 1.0). Set
**Advanced: sandbox test scenario** to `STATEFUL` for stateful cumulative updates and business lists; other scenarios
are listed per endpoint in HMRC's docs (e.g. `CUMULATIVE` and `OPEN` for obligations, `NO_INCOME_SUBMISSIONS_EXIST` for
the trigger, `UK_SE_GIFTAID_EXAMPLE` for a retrieved calculation).
# HMRC (sandbox): UK property, Making Tax Digital for Income Tax

Landlords send a quarterly cumulative update for their UK property business (6 April to the end of each quarter,
each one replacing the last) and an annual submission of allowances. Accnomos makes both from the books
(`services/runtime/app/property.py`) and either saves them as a file to submit (`POST /property/mtd/{taxYear}/export`,
written to `07 Reports`) or sends them to HMRC's **sandbox** through the relay. Production submission is off: the
relay's routes answer 403 against a production `HMRC_BASE` unless `RELAY_ITSA_PRODUCTION=1`, which nothing sets.

## Sources checked (28 Oct 2026)

| What | Where |
| --- | --- |
| Property Business (MTD) API 6.0: paths, request schemas, examples; "BETA", endpoints released in production | github.com/hmrc/property-business-api `resources/public/api/conf/6.0/application.yaml`, `uk_property_cumulative_summary_create_or_amend.yaml`, `schemas/uk_property_cumulative_summary_create_and_amend/def1/request.json`, `conf/application.conf` (commit e57db0b, 20 Oct 2026) |
| SA105 boxes for each API field | github.com/hmrc/income-tax-mtd-changelog `mapping/csv/sa105_mapping_v1.csv` |
| Obligations 3.0 `typeOfBusiness=uk-property` | github.com/hmrc/obligations-api `resources/public/api/conf/3.0/common/queryParameters.yaml` |
| Test business of type `uk-property` (sandbox) | github.com/hmrc/mtd-sa-test-support-api `resources/public/api/conf/1.0/examples/businesses/create_request_uk_property.json` |
| Property Business 4.0 was the version in the end-to-end guide's API list | github.com/hmrc/income-tax-mtd-end-to-end-service-guide `api-list.md` (we use 6.0, the newest definition) |
| Tax rules (finance costs, domestic items, FHL abolition, joint ownership, Rent a Room, property allowance, MTD thresholds) | gov.uk pages cited in `property.py`'s docstring, read through search results: gov.uk itself was not reachable from this session |

These GitHub repositories are the source developer.service.hmrc.gov.uk renders; developer.service.hmrc.gov.uk was not
reachable from this session, so re-check the live documentation before the first real sandbox call.

## Calls (relay, `relay/itsa_property.py`)

| Relay route (POST, envelope as for VAT) | HMRC call | Version |
| --- | --- | --- |
| `/itsa/{nino}/property/businesses` | `GET /individuals/business/details/{nino}/list` | 2.0 |
| `/itsa/{nino}/property/obligations` | `GET /obligations/details/{nino}/income-and-expenditure?typeOfBusiness=uk-property` | 3.0 |
| `/itsa/{nino}/property/{businessId}/cumulative/{taxYear}` | `PUT /individuals/business/property/uk/{nino}/{businessId}/cumulative/{taxYear}` (204) | 6.0 |
| `/itsa/{nino}/property/{businessId}/cumulative/{taxYear}/view` | `GET` the same path | 6.0 |
| `/itsa/{nino}/property/{businessId}/annual/{taxYear}` | `PUT /individuals/business/property/uk/{nino}/{businessId}/annual/{taxYear}` (allowances: `costOfReplacingDomesticItems` only) | 6.0 |
| `/itsa/{nino}/property/test-business` (sandbox only) | `POST /individuals/self-assessment-test-support/business/{nino}` | 1.0 |

Scopes `read:self-assessment write:self-assessment`, asked for at `/hmrc/authorize?scope=…` (the same scope plumbing as
branch `claude/self-employment`). The web page keeps those tokens under the Income Tax session in `sessionStorage`
(shared with the self-employment page). Writes need `confirmed: true`, sent only after the user ticks that they have
checked the figures. After a sandbox update the web posts what it sent to `POST /property/submissions`; the runtime
compares it with what the books say now (`matched_books`).

## Figures

The user's share of each property (spouses 50:50 unless Form 17), cumulative from 6 April: `periodAmount` (rents),
`premiumsOfLeaseGrant`, `reversePremiums`, `otherIncome`, `rentARoom.rentsReceived`; expenses itemised
(`premisesRunningCosts`, `repairsAndMaintenance`, `financialCosts` for commercial lets, `professionalFees`,
`costOfServices`, `travelCosts`, `other`) or as `consolidatedExpenses` when the user chooses it and income is under
£90,000; `residentialFinancialCost` (residential mortgage interest, never in the expenses) and
`residentialFinancialCostsCarriedForward` (typed in by the user); `rentARoom.amountClaimed` (capped at £7,500, or
£3,750 when shared). Replacement of domestic items goes in the annual submission, not the quarterly one.
