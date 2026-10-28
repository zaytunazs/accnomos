# Review: VAT schemes: flat rate, cash accounting, annual accounting (`claude/vat-schemes`)

## Sources (all read on gov.uk on 28 Oct 2026)

gov.uk could not be fetched directly from the build session (the network policy blocks it), so the pages were read
through a search provider's copy of them; each copy showed the page's own "Last updated" date, given below.

| Rule | Source | Page last updated |
| --- | --- | --- |
| Flat Rate Scheme: joining (£150,000), leaving (£230,000 / £191,500), sectors, limited cost (2%, £1,000, 16.5%), relevant goods, first-year 1%, 2 calculations, capital goods £2,000, turnover methods, leaving rules | [VAT Notice 733](https://www.gov.uk/guidance/flat-rate-scheme-for-small-businesses-vat-notice-733--2) | 18 Dec 2025 |
| Flat rate percentages, with the dated catering, hotel and pub rates | [Work out your flat rate](https://www.gov.uk/vat-flat-rate-scheme/how-much-you-pay) | read 28 Oct 2026 |
| Cash accounting: £1.35m / £1.6m, exclusions (6-month terms, invoices in advance, HP, reverse charge), start at a period start, never twice, part payments, leaving and the 6-month option | [VAT Notice 731](https://www.gov.uk/guidance/vat-cash-accounting-scheme-notice-731) | 18 Dec 2023 |
| Annual accounting: £1.35m / £1.6m, start at the current period's first day, ≤ 12-month periods, return due 2 months after (1 under 4 months), 9 × 10% or 3 × 25% instalments, balancing payment | [VAT Notice 732](https://www.gov.uk/guidance/vat-annual-accounting-notice-732), [return and payment deadlines](https://www.gov.uk/vat-annual-accounting-scheme/return-and-payment-deadlines) | 22 Nov 2024 |
| Interim payments rounded down to the nearest £5 | [HMRC internal manual VATAAS4100](https://www.gov.uk/hmrc-internal-manuals/vat-annual-accounting-system/vataas4100) | read 28 Oct 2026 |
| Boxes 1, 4, 6 and 7 under each scheme; box 5 ignores instalments | [VAT Notice 700/12](https://www.gov.uk/guidance/how-to-fill-in-and-submit-your-vat-return-vat-notice-70012) §4.1-4.3 | read 28 Oct 2026 |

The same URLs and date are in the code (`packages/ledger/src/accnomos_ledger/vat_schemes.py`, `SOURCES` in
`services/runtime/app/vat_schemes.py`) and shown in Settings and on the VAT page.

## Design

**Engine (`packages/ledger`, pure, no I/O).** `accnomos_ledger.vat_schemes`:
- A business's schemes are a timeline of `SchemeSpan`s: `standard`, `cash`, or `flat_rate` (sector, basic or cash
  based turnover, limited cost auto / yes / no). Days with no span are standard accounting, so no saved schemes gives
  exactly what `compute_vat_return` gives (tested, including a Hypothesis property).
- Every sale, purchase and credit note becomes **tax moments**: dated shares of its net and VAT. On invoice basis the
  document's date. On cash basis (cash accounting, or the flat rate's cash based turnover for sales) each payment's date,
  as a share of the gross (Notice 731 §5.7, §8), with cumulative rounding so the parts add up to the whole. Which basis
  a document uses is set by the scheme on *its* date; where each moment lands sets how it counts.
- That one rule covers the switching rules: joining cash accounting leaves earlier invoices on their invoice dates
  (§3.1, never twice); leaving it brings what is unpaid to account on the last day on the scheme, or, with the
  6-month option, as paid over the next 6 months and the rest at their end (§6.4); cash accounting → flat rate cash
  turnover carries on and payments go into flat rate turnover (Notice 733 §9.3); leaving the cash method brings unpaid
  sales into the last flat rate period (§9.6). Credit notes are folded into the cash-basis document they reduce;
  an undo of a cash-basis document takes it out of the scheme.
- A period is **cut into segments** where the scheme changes (Notice 733 §12.7, 732 §9.8), each worked out under its
  rules and summed. A flat rate segment: turnover = VAT-inclusive moments of sales (standard, reduced, zero-rated,
  exempt; out of scope excluded); the limited cost test on that segment (relevant goods vs 2% of turnover and the
  pro rata £1,000, twelfths for whole months as §4.5 rounds: £83, £166, £250); then one calculation per stretch with one
  rate, split at sector rate changes and the first anniversary of VAT registration (1% off before it, §4.7, §4.12).
  Box 4 / 7 carry only purchases the user marked as capital goods of £2,000 or more (§15.2).
- Annual accounting: periods from the start (≤ 12 months, month ends), return due date, instalment schedule and
  balancing payment. The boxes for an annual period are the normal ones for the year (Notice 700/12 §4.3).

**Runtime.** `app/vat_schemes.py` keeps the timeline in the user's books (`_System/vat/schemes.json`, so per business,
no database), validates it (`check_timeline`: cash accounting changes only at a VAT period start, Notice 731 §3.1/§6.1;
no flat rate rejoin within 12 months, Notice 733 §3.6/§12.6; annual accounting starts on a period start and the
quarters after it line up, Notice 732 §3.2-3.4; past start dates warn, cash accounting cannot be backdated), and runs
the eligibility tests from the books (last 12 months, or the business's own estimate): flat rate £150,000 to join and
the £230,000 anniversary test with the period it must leave at; cash and annual £1.35m to join and £1.6m to leave.
`SchemeContext` turns the saved annual accounting into VAT periods (`2026-Y01` ids) alongside the quarterly cycle.
For cash basis it loads the whole ledger and takes payments from `app/settlement.py` (recorded payments, matched bank
lines, credits applied), so the scheme sees exactly what Contacts and Invoices show as paid.

Routes: `GET/PUT /books/vat/schemes` (new, audited as `vat_schemes_saved`). `GET /books/vat` adds `scheme` (segments,
flat rate calculations, limited cost figures, cash payments counted, VAT brought in on leaving, annual instalments and
balancing payment). `/books/vat/periods`, `/books/deadlines` and the dashboard follow annual periods and their due
dates and list instalments. `/reports/vat` and the export work out each period under the scheme and name it. The Ask
facts pack computes its boxes under the scheme and adds a `vat_scheme` block (rates used, limited cost result,
instalments); the default Ask period is the annual one under annual accounting.

**Web.** Settings › Business › *VAT scheme* (`VatSchemeSettings.tsx`): the scheme in use today, the saved timeline
(remove an entry), a change from a date (scheme, sector with today's rate, turnover method, limited cost, VAT
registration date, or the 6-month option when leaving cash accounting), annual accounting (start, monthly/quarterly,
the figure from HMRC's letter), capital goods to tick, the checks with links to the rule, and HMRC's sources. The VAT
page shows *How these boxes were worked out* (`SchemeNote.tsx`). The on-device "Annual" VAT period now sends the
stagger too, and Home shows real annual deadlines once annual accounting is saved in the books.

## Tests

- `packages/ledger/tests/test_vat_schemes.py`: **27 tests**, HMRC's worked examples where published: photographer
  £1,200 at 11% = £132; limited cost Examples 1-3 (Notice 733 §4.4); the pro rata £1,000 (§4.5: £83, £166); first-year
  1% (§4.7 Examples 1 and 3); catering 12.5% → 4.5% on 15 July 2020 as two calculations; capital goods; joining mid
  period; cash accounting part payment (Notice 731 §8.1: £130 of £200) and one payment over two invoices at mixed
  rates (§8.2: £380); purchases when paid; joining and leaving (both options); credit notes and undo; 6-month terms;
  flat rate cash turnover and §9.3/§9.6; instalments (Notice 732 §4.5 £1,000 × 9 / £2,500 × 3), rounding to £5,
  short periods, balancing payment (§6.2: £5,000), due dates and periods (§3.4 example). Plus a property test that a
  timeline of standard spans changes nothing.
- `services/runtime/tests/test_vat_schemes_routes.py`: **9 tests**: flat rate saved and used by `/books/vat`; audit
  and rule enforcement (400 naming Notice 731, unknown sector 422, rejoin within 12 months, a stagger 2 start);
  cash accounting from payments through `payments.json` and `/books/deadlines`; annual periods, instalments, return
  due and deadlines; `/reports/vat` and the Ask facts; eligibility from books vs estimate; the anniversary leaving
  test; an unreadable schemes file is standard accounting, never a 500; capital goods marked in Settings.
- `apps/web/e2e/vat-schemes.spec.ts`: **2 tests**: flat rate chosen through the Settings UI (a mid-quarter cash start
  refused first), then the VAT page shows £35.64 = 11% of £324.00 and box 6 £324; cash accounting shows half the VAT
  of a half-paid invoice.
- Gates on this branch (Linux, 28 Oct 2026): runtime 1410 passed, 2 skipped; packages 125 passed; `ruff check` and
  `ruff format --check` clean; `pyright` 0 errors; web `eslint` clean, `tsc` clean after the build.
- e2e, whole suite (`CI=1`, all projects): 241 passed, 58 skipped (the opt-in screenshot specs), 4 failed. The session's
  pre-installed Chromium is older than the pinned Playwright's, so the suite ran on full Chromium
  (`launchOptions.executablePath`, a local config not committed). On it, `invoices.spec.ts:3`, both
  `invoice-payments.spec.ts` tests (Chromium's built-in PDF viewer loads `chrome-extension://` files, which the
  "nothing leaves 127.0.0.1" guard counts) and `keyboard.spec.ts:143` (focus wraps on `/vat` after the footer) fail
  **the same way on `main`'s web code** built and run in the same session, so they are the browser, not this branch.
  The two demo specs failed only because a second run overlapped and cleared `test-results`; rerun alone with
  `vat-schemes`, `settings` and `home`: 16 of 16 passed. CI (headless shell) has not run this branch yet.

## Risks and what remains

- Nothing here has been run against real books or HMRC (`docs/HONESTY.md`, HMRC section, lists every gap).
- Not built: the retailer's turnover method, stock adjustments on leaving the flat rate, flat rate bad debt relief,
  capital goods disposals, reverse charge / postponed import VAT outside the flat rate, partial exemption.
- Relevant goods are guessed from account codes unless the business lists its own (`relevant_goods_accounts`), and the
  limited cost test can swing the rate from 11% to 16.5%; the VAT page shows the figures so the user can check them.
- A refund of an overpayment under cash accounting does not take VAT back off; an undo of a partly paid cash invoice
  from an already submitted period is dropped, not corrected.
- Instalment amounts depend on the figure the user types from HMRC's letter; HMRC's letter is what counts.
- The cash basis reads the whole ledger on each `/books/vat` call (as Contacts does); fine for a small business,
  not measured on a large book.
