# Review: cash basis for sole traders (branch `claude/cash-basis`)

Built on `claude/self-employment` (MTD Income Tax, HMRC sandbox only). Nothing here calls HMRC, Meta, Baseten or
Modal. Never run against HMRC.

## Sources (checked 28 Oct 2026)

gov.uk, legislation.gov.uk and HMRC's developer site are refused by this machine's network proxy, so they were read
through the Exa fetcher. The quotes below are from what it returned. Full table in `docs/HMRC.md` › *Accounting basis*.

| Claim | Source |
|---|---|
| "From 6 April 2024, cash basis became the default method of accounting"; "you only record income or expenses when you receive money or pay a bill"; invoiced 15 March, paid 30 April → income on 30 April | https://www.gov.uk/simpler-income-tax-cash-basis (`/print`) |
| Equipment kept and used in the business is "a normal allowable business expense rather than … a capital allowance"; a car is a capital allowance | same page, *Cars and other equipment* |
| Income and expenses "either excluding or including VAT", the same way | same page, *VAT registered businesses* |
| No cash-basis deduction for capital on cars, land, non-depreciating assets, non-qualifying intangibles, financial assets, education or training, buying a business | s33A ITTOIA 2005, https://www.legislation.gov.uk/ukpga/2005/5/section/33A; BIM70035 |
| Box 29 (depreciation) "Only use this box if you use traditional accounting"; on the cash basis capital allowances only for cars | SA103F notes 2026, https://assets.publishing.service.gov.uk/media/69c26565cfa346b9d4704b35/SA103F_Notes_2026.pdf |
| HMRC holds the method per business: Business Details 2.0 *Retrieve / Update Accounting Type* (`…/{nino}/{businessId}/{taxYear}/accounting-type`), confirmed at year end, rolls over; no basis field in the cumulative summary | end-to-end service guide (*Capture and Change Accounting Method*); Business Details 2.0 OAS |

## What changed (one commit per step)

1. **Runtime: setting and cash figures** (`7b52f59`). `app/cash_basis.py` (new, pure): `cash_view(ledger)` derives
   entries dated when money moved, from `app/settlement.py`'s allocations (recorded payments, *Mark paid*, matched
   bank lines, applied overpayments, refunds of credit-note credits). It shares each document's income and expense
   lines out by the money paid, rounding on the running total so the shares of a fully paid document add up to it
   exactly. Entries not on account count on their own date. Journals that move debtors or creditors, and overpayments
   still on account, are listed as not counted. `app/itsa.py`: `se_summary(..., basis, refs, left_out)`.
   Capital lines (0xxx) go in box 30 on the cash basis. s33A exclusions are matched by name. Depreciation is never
   counted on the cash basis. Every contribution carries the payment behind it.
   `GET/PUT /books/self-employment/settings` (`_System/itsa/settings.json`, audited `itsa_basis_changed`). `?basis=`
   on summary and the SA103 report. Receipts record `accounting_basis` and are checked on that basis. The SA103 report
   gets *Payments behind each box* and *Not counted on the cash basis*. The quarterly report shows the basis.
2. **Runtime: P&L** (`9f6069d`). `GET /reports/pl?basis=cash`; `basis` on `POST /reports/export`; the sheet title says
   "cash basis".
3. **Web: P&L option** (`61697eb`). Reports shows *As approved / Cash basis* when *I am self-employed* is on.
4. **Web: setting and page** (`11d9669`). Settings › Business › I am self-employed › *Accounting basis* (radio, cash
   default, saved to the books). The self-employment page shows the basis badge with a *Change* link. The drill-down
   lists payments (date, how paid, invoice number, "£400.00 of £1,200.00 paid"). There is a *Not counted* list. The
   confirmation names the basis. Receipts list it.
5. **Docs**: `docs/HMRC.md` (new *Accounting basis* section), `docs/HONESTY.md`, README rows, HANDOVER line, this file.

## Tests

| Gate | Result |
|---|---|
| `cd services/runtime && python -m pytest -q` | 1288 passed, 1 skipped, 1 failed: `test_sample_books.py::test_a_second_press_while_running_or_after_is_the_same_run`. It is the timing-only test HANDOVER.md flags. It passes alone (with and without this branch's changes, 1 passed each) and in its own file (27 passed). New and changed tests after the last edit: `test_cash_basis.py` + `test_itsa.py` 63 passed |
| `ruff check . && ruff format --check .` (ruff 0.17.3) | clean |
| `pyright services/runtime/app` (1.1.414) | 0 errors, 0 warnings |
| `cd apps/web && pnpm install --frozen-lockfile && pnpm exec eslint .` | clean |
| `pnpm run e2e:build && pnpm run e2e:test` | see *E2E* below |

New: `services/runtime/tests/test_cash_basis.py` (17). It covers:

- an invoice raised in one period and paid in the next (first under accruals, second under cash, drill-down names the payment);
- part payments in three uneven parts adding up exactly;
- a part-paid invoice;
- a bill paid later;
- a receipt paid at purchase on both bases;
- a refund of a credit note after full payment;
- a credit note before payment;
- an overpayment listed, then counted on its receipt date when applied;
- a matched bank line;
- an undone invoice;
- capital: equipment counted, a car and depreciation left out;
- a bad-debt journal;
- the ledger is unchanged by `cash_view`, and VAT is excluded;
- the cash P&L;
- route tests:
  - switching basis back and forth leaves every `_System/Ledger` and `_System/Payments` file byte for byte the same,
    and returns identical figures;
  - `?basis=` is a look and does not change the setting;
  - the change is audited;
  - an invalid basis gets 422, and no `X-User` gets 400;
  - receipts record and check the basis;
  - SA103 and quarterly reports show it;
  - `GET /reports/pl?basis=cash` and the export.

`test_itsa.py`: the summary route test now expects the cash default (unpaid invoices give 0) and the old figure with
`basis=traditional`. e2e `self-employment.spec.ts`: a new test covers the setting being off without self-employment,
cash by default, traditional surviving a reload because it is kept in the books, and the Reports P&L option switching
to "(cash basis)". The existing flow test now checks the "Cash basis" badge.

E2E: browsers. `@playwright/test` 1.64.1 wants Chromium build 1248; this machine has 1243 in `/opt/pw-browsers`. The
suite was run with `PLAYWRIGHT_BROWSERS_PATH` pointing at symlinks from 1248 to 1243 (no `playwright install`).
`e2e:build` passed. `self-employment`, `reports` and `settings` specs: 13/13 passed. Full suite (`CI=1`, desktop, phone and demo projects): **227 passed, 58 skipped, 0 failed** in 11.1 min. The skips are the screenshot specs (`shots.spec.ts`, skipped unless `SHOTS=1`).

## Risks and decisions for a human

- **Box for equipment on the cash basis.** Box 30 (`otherExpenses`) is Accnomos's choice. gov.uk says it is "a normal
  allowable business expense" but no box is named. An accountant should confirm.
- **s33A exclusions are recognised by account name only** (car, land, building, property, freehold, leasehold,
  goodwill, patent, trade mark, copyright, investment, shares, education, training). "0050 Motor vehicles" holding a car
  would be claimed. The page warns when any asset line is counted.
- **Overpayments**: money not allocated to an invoice is listed, not counted, until it is applied (then it counts on the
  date it came in). Strictly it was received when it came in. Counting it then would put unallocated money in turnover
  with no invoice behind it, so this was a judgement call.
- **A credit note's refund** counts as that share of the credit note's lines. A refund of an *overpayment* counts
  nothing, because the overpayment was never counted.
- **Applied overpayment changes earlier periods.** It counts on the day the money came in, so applying it later can
  change an update already sent. Cumulative updates replace the earlier ones, but HMRC has the earlier figure.
- **Adjustments** (payroll, mileage journals) count on their own dates on both bases. Wages-when-paid is not modelled.
- **One basis per set of books.** HMRC allows one per business. Accnomos has one business per set of books today.
- **HMRC's record of the method is not touched.** The relay has no Accounting Type endpoints. The user must make HMRC
  match Settings at year end. Next step: `GET`/`PUT …/accounting-type` in `relay/itsa.py` and the page.
- **No transitional adjustments** when switching basis (SA103F box 30 "transitional adjustments if you've left cash
  basis"). Switching shows the whole year on the new basis.
- **VAT always excluded.** gov.uk also allows including VAT (with VAT paid and repaid as expenses and income); not
  offered.
- **Performance**: the cash view reads the whole ledger (payments can settle documents from earlier years) on each
  summary, P&L or receipt check.
- **Found, not fixed**: two receipts saved in the same second get the same file name and the second overwrites the
  first (`routes_itsa.save_receipt`, timestamp to the second). The index keeps both. Also, `_System/itsa/` (receipts and
  the new settings) is not in the data export (`app/data_export.py`). Both predate this branch.

## What a human must check

1. With an accountant: the box-30 choice, the name-based s33A list, the overpayment rule.
2. In HMRC's sandbox, `STATEFUL`, compare one cumulative update on each basis. Then use Business Details 2.0
   *Retrieve Accounting Type* to see what HMRC holds for the test business (expected: cash by default).
3. Real books: an invoice part paid across two quarters, a refund, a matched bank line. Check the page's drill-down
   against the bank statement.
