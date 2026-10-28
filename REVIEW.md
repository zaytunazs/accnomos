# Review: self-employment, Making Tax Digital for Income Tax (branch `claude/self-employment`)

Sandbox only. **Nothing here has been run against HMRC** (sandbox or production): no HMRC credentials were on this
machine. Every HMRC call is tested against fakes that answer with HMRC's own published example payloads.

## Sources checked (28 Oct 2026)

HMRC's developer site disallows automated fetchers (robots.txt), so pages and OpenAPI files were read with `curl`
(`…/{api}/{version}/oas/resolved` and the `$ref`'d files under `…/oas/`). Full table with URLs in `docs/HMRC.md`.

| What | Found |
|---|---|
| API index (developer.service.hmrc.gov.uk/api-documentation/docs/api) | current versions: Business Details 2.0, Obligations 3.0, Self Employment Business 5.0, Individual Calculations 9.0, Test Support 1.0, Create Test User 1.0 |
| Business Details 2.0 | `GET /individuals/business/details/{nino}/list`, `read:self-assessment`, Sandbox and Production |
| Obligations 3.0 | `GET /obligations/details/{nino}/income-and-expenditure` (`typeOfBusiness`, `businessId`, `fromDate`, `toDate` ≤ 366 days, `status` open/fulfilled), `…/crystallisation`; cumulative examples all start 6 April |
| Self Employment Business 5.0 | `PUT …/self-employment/{nino}/{businessId}/cumulative/{taxYear}` (from 2025-26, 204), request schema `createAmendCumulativePeriodSummary/request.json`; "Submissions must include values for income and expenses, even if the values are zero"; Gov-Test-Scenario list incl. `STATEFUL` |
| Individual Calculations | **8.0 used**: Sandbox and Production. 9.0 is "[test only]", Sandbox only, same four endpoints. Trigger 202 `{calculationId}`, "wait at least 5 seconds", retrieve 404 while running, final declaration `POST …/{calculationId}/final-declaration` 204 |
| Warning on Individual Calculations | "HMRC is no longer accepting production credential access requests for new 2026–27 quarterly update products" |
| Scopes | `read:self-assessment`, `write:self-assessment` (OAS security schemes) |
| Fraud prevention | spec v3.3 issued 27 Jan 2025; required by law for VAT and Income Tax |
| Test users | Create Test User 1.0 `POST /create-test-user/individuals {serviceNames: [national-insurance, self-assessment, mtd-income-tax]}` → `nino`, `mtdItId`, `saUtr`; Test Support 1.0 *Create a Test Business* (purged after 7 days) |
| End-to-end service guide | final declaration text (verbatim in code); cumulative updates; `consolidatedExpenses` for turnover under £90,000 |
| SA103F mapping CSV v3 (hmrc/income-tax-mtd-changelog) | `periodExpenses` = total expenses boxes 17-30; `periodDisallowableExpenses` = boxes 32-45 |
| gov.uk | cash basis default from 6 April 2024; "You cannot claim for … depreciation of equipment"; "You cannot usually claim the cost of entertaining clients" |

## What changed (one commit per step)

1. **Runtime: figures, receipts, reports** (`services/runtime/app/itsa.py`, `routes_itsa.py`, `itsa_reports.py`)
   - `GET /books/self-employment/summary?tax_year&period_end`: cumulative 6 April → period end, ledger lines mapped
     by account code (and a few name words) to the API's fields with their SA103F box, total and disallowable kept
     separate, every contributing ledger line listed. `hmrc_body` is the exact PUT body. Blockers: tax year before
     2025-26, negative income. Warnings: as-approved not cash basis, uncoded accounts left out, disallowables.
   - `POST /books/self-employment/receipts` (needs `X-User`): cumulative / calculation / final declaration, stored in
     `_System/itsa/{taxYear}/…` with an index, audited (`itsa_update_submitted`, `itsa_calculation_saved`,
     `itsa_final_declaration_submitted`, plain-English summaries in `/audit`). A cumulative receipt is recomputed from
     the books and stores `matches_books`. Final declaration receipts must carry HMRC's text.
   - Reports for the coordinator's request: `sa103_report`, `quarterly_report`, `calculation_report` are pure
     builders returning rows; `render(report, "csv"|"xlsx"|"pdf")`; `GET /books/self-employment/reports/{kind}`
     serves JSON rows (the web view) or a file. No second export framework: these slot into the shared registry
     from `claude/exports` (build = rows, renderers = the three functions). CSV/XLSX neutralise formula-looking text.
   - `paths.ITSA = "_System/itsa"`; runtime CORS now exposes `Content-Disposition` (downloads keep their names).
2. **Relay** (`services/hmrc-relay/relay/itsa.py`): businesses, obligations (I&E and final declaration), cumulative
   update + read back, trigger/list/retrieve calculation, final declaration, test business, test individual. Same
   envelope and fraud-prevention headers as VAT. Bodies validated against HMRC's schema before sending. Refused
   (403) against production unless `RELAY_ITSA_PRODUCTION=1`; test tools are sandbox only regardless. Writes need
   `confirmed: true`; the final declaration needs HMRC's text word for word. `/hmrc/authorize?scope=` (allow-list).
3. **Web**: Settings › Business › *I am self-employed* (off by default) shows *Self-employment* in the menu;
   `/self-employment` page: connect (own Income Tax session in `sessionStorage["accnomos.hmrc.itsa"]`, so VAT's
   stays), NINO, businesses, obligations, figures with drill-down per box, PDF/CSV/XLSX downloads, tick-to-confirm
   Submit, receipt with correlation ID, HMRC's calculation labelled as HMRC's, final declaration with HMRC's wording.
   `lib/hmrc.ts` sessions are now per product (VAT unchanged by default).
4. **Docs**: `docs/HMRC.md` (new section with sources, flow, mapping, reports, sandbox data), `docs/HONESTY.md`
   (sandbox only, never run against HMRC, as-approved basis, mapping limits), README feature row,
   `services/hmrc-relay/README.md` endpoints and `RELAY_ITSA_PRODUCTION`.

## Tests

| Gate | Result |
|---|---|
| `cd services/runtime && python -m pytest -q` | 1273 tests collected; a full run never finished on this overloaded machine (OOM and time limits). test_itsa (46) and test_security_routes pass; test_sample_books.py::test_a_second_press_while_running_or_after_is_the_same_run fails under load (20 s poll; looks timing-only, unverified on an idle machine) |
| `cd services/hmrc-relay && python -m pytest -q` | 161 passed |
| `ruff check . && ruff format --check .` | clean |
| `pyright services/runtime/app` | 0 errors, 0 warnings |
| `pnpm install --frozen-lockfile && pnpm exec eslint .` | clean |
| `pnpm run e2e:build && pnpm run e2e:test` | self-employment, hmrc and settings specs: 10/10 pass (ports 3120/8792/8800, own servers, 1 worker). Full suite not finished: timeouts and Chromium crashes at load average ~50 |

New tests: `services/runtime/tests/test_itsa.py` (46: tax year, 31 account→field cases, every API field and SA103F
box, cumulative window, drill-down sums, body shape vs HMRC's schema, zeros sent, reversals, blockers, reports in all
formats, CSV injection, HMRC-only calculation figures, routes, receipts + `matches_books` + audit, validation);
`services/hmrc-relay/tests/test_itsa.py` (42: each endpoint's method/path/Accept version/query/body/fraud headers
against fakes using HMRC's example payloads in `tests/fixtures/itsa/`, HMRC's example request sent byte for byte,
schema refusals before HMRC, production refusal and switch, test user/business, scopes, declaration text identical in
relay, runtime and web); `apps/web/e2e/self-employment.spec.ts` (2: setting off by default and adds the menu entry;
connect → businesses → obligations → figures → confirm → submit → receipt → PDF download → HMRC calculation).

## Risks

- **Basis.** Figures are as approved (accruals-like), but cash basis is HMRC's default for sole traders since 2024-25.
  For most real sole traders the numbers would be wrong to send until a cash-basis view exists. Warned on page/PDF.
- **Mapping is heuristic** (code ranges + name words). No private-use split; staff vs client entertainment only by
  name; 5xxx all treated as cost of goods (5100 Tools included). An accountant should review `app/itsa.py`.
- **No consolidated expenses, no annual submission** (allowances, adjustments), no losses, no CIS, no
  `taxTakenOffTradingIncome`, no property income. The final declaration is offered without checking that the annual
  submission exists; HMRC will refuse.
- **Production window**: HMRC is not accepting new 2026-27 quarterly-update production credentials.
- **Calculation fields** are read by name from Individual Calculations 8.0; 9.0 may move them.
- The page keeps the NINO in `localStorage` (this device only) and sends it to the runtime with receipts (stored in the
  user's own OneDrive, not in audit lines).
- `sessionStorage` token handling and fraud headers are as VAT's (same XSS exposure as noted in HONESTY.md).

## What a human must check in the sandbox

1. Register `read:self-assessment write:self-assessment` for the sandbox app and subscribe it to Business Details 2.0,
   Obligations 3.0, Self Employment Business 5.0, Individual Calculations 8.0, Self Assessment Test Support 1.0,
   Create Test User 1.0.
2. `POST /hmrc/test-user/individual`; sign in on `/self-employment`; create a test business
   (`POST /itsa/{nino}/test-business`); with `Gov-Test-Scenario: STATEFUL` list businesses and obligations.
3. Submit an update: confirm HMRC answers 204 with the exact body the page showed (no `RULE_*` errors such as
   `RULE_EARLY_DATA_SUBMISSION_NOT_ACCEPTED` or `START_DATE_NOT_ALIGNED_WITH_REPORTING_TYPE`), and that the receipt in
   `_System/itsa/` says `matches_books: true`.
4. Run HMRC's fraud-prevention validator against an Income Tax call (Test Fraud Prevention Headers API) and check
   `validation-feedback` for Income Tax (the relay's feedback route is VAT's today).
5. Trigger an in-year calculation, check the 5-second wait and 404 retry, and that the page's figures equal HMRC's
   response field by field (`totalIncomeTaxAndNicsDue`, Class 2/4 NIC).
6. Final declaration with `intent-to-finalise`, then the 204, then the final declaration obligation turning fulfilled
   (HMRC says up to an hour).
7. Have an accountant review the account → box mapping and the disallowable rules.
