# Review: accounting tools (Xero's Accounting menu gaps)

Branch `claude/accounting-tools`. Closes the Accounting-menu gaps against Xero: chart of accounts, manual journals,
fixed assets, find and recode, tracking categories, budgets and short-term cash flow. **Multi-currency (item 8) was
dropped by the owner on 28 Oct 2026**: no currency fields, exchange rates or FX code were added (a non-GBP receipt still
can't be posted). For the record, checked that day before the decision: HMRC publishes its monthly rates on the Trade
Tariff service (https://www.trade-tariff.service.gov.uk/exchange_rates/monthly, "currency units per £1", CSV/XML per
month, published the penultimate Thursday; the CSV is robots-disallowed), and VAT Notice 700 §7.6 allows the HMRC
period rate as an alternative to the UK market selling rate.

## Routes for the top menu (the other agent's redesign)

Web pages, all new, all behind sign-in (signed out they explain themselves and show *Sign in*):

| Route | Page |
|---|---|
| `/accounting/chart` | Chart of accounts |
| `/accounting/journals` | Manual journals (also where depreciation and disposal journals are approved) |
| `/accounting/assets` | Fixed assets |
| `/accounting/recode` | Find and recode |
| `/accounting/tracking` | Tracking categories and the Tracking Summary report |
| `/reports/budgets` | Budgets: editor, Budget Summary, Budget Variance |
| `/reports/cashflow` | Short-term cash flow (30/60/90 days) |

Until the menu links them, each page carries a row of links to the others (`ToolsNav` in
`apps/web/src/components/accounting/Shared.tsx`, a `nav` named "Accounting tools"); drop it once the menu has them.
`AppNav.tsx` was not touched.

Runtime API: `/accounting/accounts…`, `/accounting/journals…`, `/accounting/assets…`, `/accounting/recode…`,
`/accounting/tracking…` (`app/routes_accounting.py`); `/reports/budgets…`, `/reports/cashflow`,
`/reports/cashflow/explain`, `/reports/tracking` (`app/routes_reports.py`). Every write needs `X-User`.

## What changed

- **Ledger** (`packages/ledger`): optional `Line.tracking`; `LedgerEvent.vat_box` (an adjustment with it counts its signed
  net/VAT on that side in `compute_vat_return`); `LedgerEvent.recodes`; new `depreciation.py` (pure maths). All optional:
  existing event files read unchanged.
- **Chart** (`app/chart.py`): standard UK chart (every account code already posts to, plus fixed asset/depreciation,
  equity, disposals); types tied to the code ranges the reports use; code immutable; rename only while unused; system
  accounts never archived or deleted; accounts with postings archived, never deleted; CSV export and all-or-nothing import.
- **Manual journals** (`app/manual_journals.py`): draft → approve posts one `adjustment`; debits = credits enforced with a
  sentence; optional VAT line (needs a side; warns when the VAT line doesn't match the coded lines' rates); auto-reversal
  posted in the same approval, dated its day; attached document by path (sha256 as evidence); void by mirror entry; list
  filters (status, source, dates, account, text). Debtors, creditors and payroll liabilities are refused on journals.
- **Fixed assets** (`app/fixed_assets.py`): register (posts nothing); run depreciation → one journal draft for approval;
  disposal → journal draft with catch-up depreciation, cost out, accumulated depreciation out, proceeds (+ output VAT),
  gain/loss to 8010; schedule; register-vs-ledger reconciliation. Depreciated-to and disposal are derived from posted
  journals, so voiding a journal undoes them. Capital allowances note in the API and the UI.
- **Find and recode** (`app/recode.py`): search by account, contact, dates, amount, VAT code; preview, then `confirm`
  posts one adjusting entry per original, dated like it. VAT recodes keep the gross. Refused: bank/control lines, entries
  in a submitted VAT period (plain sentence), income ↔ spending moves. Undoing a recoded entry also unwinds its recodes
  (`approve.undo`), and undo refuses journal and recode entries (void / recode back instead).
- **Tracking** (`app/tracking.py`): two categories max; tags on invoice lines (sale lines split by VAT code and tag —
  untagged invoices post exactly as before), on bills at approval (edit `tracking`), on journal lines; Tracking Summary.
- **Budgets** (`app/budgets.py`), **cash flow** (`app/cashflow.py`, optional AI sentence checked with `KnownNumbers`; a
  test-mode stub answers it).
- Docs: `docs/ARCHITECTURE.md` (new `_System/Accounting/*` files, an Accounting tools section), `docs/HONESTY.md`,
  a README feature row.

## Tests

- Ledger: `packages/ledger/tests/test_depreciation.py` (golden cases: SL life yearly/monthly with cumulative rounding,
  SL rate with residual, RB yearly and monthly, RB stopping at residual, `upto`, bad policies, disposal gain/loss) and a
  VAT-boxed adjustment case in `test_vat.py`. Ledger suite: 51 passed.
- Runtime: `services/runtime/tests/test_accounting_tools.py` (21 tests: chart rules and CSV, journal balance enforcement,
  approval/auto-reversal/void with TB checks, VAT journal into the return, submitted-period refusal, depreciation run +
  reconciliation, disposal with catch-up and loss, RB yearly, account recode (history untouched, TB balanced, VAT
  unchanged), VAT recode S→Z→S with box figures, recode refusals, tracking + summary + archived options, invoice and bill
  tags, budget summary/variance, cash flow dates and buckets, the AI sentence check, undo/void interplay).
  Runtime suite, run in 7 batches (one big run is OOM-killed on this shared machine): 1241 passed, 1 skipped, 6 failed only from the environment: 4 `test_without_the_flag…` (the subprocess imports the shared venv's other checkout of `accnomos_ledger`; pass with this worktree's packages on `PYTHONPATH`) and 2 timing-sensitive `test_sample_books` tests under load (pass when re-run alone).
- Web e2e: `apps/web/e2e/accounting.spec.ts` (signed out; chart; journal balance → draft → approve with reversal; asset →
  depreciation → approve → schedule; recode preview → post; tracking; budget → variance; cash flow + checked sentence;
  every page at 360 px: no sideways scroll and no serious/critical axe issue). The seven routes were added to
  `e2e/pages.ts`, so the existing phone and axe sweeps cover them too. **Not run**: `next build` was SIGKILLed (out of memory) twice on the shared machine, and the owner stopped the work before a retry.
- Gates: `ruff check` and `ruff format --check` clean; `pyright services/runtime/app` 0 errors; eslint on the new web files clean; `tsc --noEmit` shows only the existing `LayoutProps` error (Next's generated types); e2e build and tests not run.

## Risks

- `vat_box` adjustments now reach the VAT boxes. The VAT page's lists of sales and purchases (`routes_vat.py`) still list
  only sales, purchases and reversals, so a VAT journal or VAT recode changes the boxes without appearing in those lists.
- Recode identifies "the VAT of a line" only when an entry has one VAT-coded line; mixed-rate entries are refused.
- Journals are stored in one `journals.json` rewritten with If-Match; heavy concurrent use from two devices retries once
  then fails (as other settings files).
- The sales-invoice ledger lines now group by (VAT code, tracking tags); with no tags the event is byte-for-byte the same
  as before (existing invoice tests pass), but tagged invoices produce more 4000 Sales lines.
- Bank matching may suggest a manual journal that touches 1200 Bank for a statement line (it is a live event).
- Disposal catch-up covers whole periods only; a yearly-depreciated asset sold mid-year gets no part-year charge.

## What an accountant should check

1. The default chart (codes, types, default VAT: insurance, bank charges and mileage allowance exempt) suits UK sole
   traders and limited companies, and that 3xxx equity accounts are adequate.
2. Depreciation conventions: full month in the month of purchase; yearly charges per 12 months from the purchase month
   (not aligned to the financial year end); SL by rate applied to cost less residual.
3. Disposal journal layout and whether proceeds of a vehicle sale should be outside the scope (the user decides by
   entering VAT or not).
4. VAT recode keeping the gross (as paid), and that dating the adjustment on the original's date is right for an open
   period.
5. Budget variance favourable/adverse convention and cash flow treating overdue items as due now.
