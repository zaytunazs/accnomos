# Review: import history and opening balances (branch `claude/import-history`)

Switching from Xero, QuickBooks Online, Sage 50, Sage Accounting, FreeAgent or a spreadsheet: read the old
system's exports, map its accounts, post one balanced opening entry after the user approves it, carry the
customers, suppliers and unpaid invoices and bills over, and prove with a reconciliation that the books equal the
source trial balance. Written 28 Oct 2026, from `origin/main` at 9674a64.

## Sources (checked 28 Oct 2026)

The vendors' help sites (central.xero.com, quickbooks.intuit.com, help.sbc.sage.com, support.freeagent.com) and
gov.uk could not be opened from the build machine: every fetch failed name resolution under the session's network
policy. What each export contains was taken from web search summaries of these pages, some of them third-party
guides; the exact header spellings are therefore **not confirmed** against a real export (docs/HONESTY.md).

| Vendor | Export | Page |
|---|---|---|
| Xero | Trial Balance report → Export (Excel): account code, account, account type, Debit, Credit, YTD Debit, YTD Credit | https://central.xero.com/s/article/Trial-Balance-report; layout from https://tinytax.co.uk/support/export-xero-trial-balance (third party) |
| Xero | Chart of accounts CSV: `*Code`, `*Name`, `*Type`, `*Tax Code`, Description (starred mandatory) | https://central.xero.com/s/article/Import-a-chart-of-accounts |
| QuickBooks Online | Reports › Trial Balance › Export to Excel: account names under an empty header, Debit, Credit, title rows above | https://quickbooks.intuit.com/learn-support/en-uk/reports-and-accounting/i-export-my-trial-balance-to-excel-to-prepare-management-reports/00/269621 |
| QuickBooks Online | Chart of accounts: Account #, Account, Type, Detail type (sub-accounts "Parent:Child"); Open Invoices report (Reports › Who owes you) | https://quickbooks.intuit.com/learn-support/en-us/help-article/chart-accounts/import-chart-accounts/L9Res1eb1_US_en_US |
| Sage 50 Accounts | Reports › Financials › Trial Balance › Export › To File: N/C, Name, Debit, Credit; default nominal codes in the same four-digit layout as Accnomos | https://tinytax.co.uk/guides/sage-ct600-integration (third party) |
| Sage Accounting | Reporting › More › Aged Debtors / Creditors › Detailed › Export CSV lists the unpaid invoices; Contacts › Customers / Suppliers › Export CSV | https://help.sbc.sage.com/en-gb/accounting/reporting/financial_reports/extra-aged-creditors-report.html |
| FreeAgent | Accounting › Reports › Trial Balance › Export Report › Summary CSV or Chart of Accounts CSV; codes 001–599 P&L, 600–999 balance sheet | https://support.freeagent.com/hc/en-gb/articles/115001222384, https://support.freeagent.com/hc/en-gb/articles/4412362325394 |
| HMRC | Opening balances are not supplies, so no VAT return counts them (VAT Notice 700/12, what goes in each box) | https://www.gov.uk/guidance/how-to-fill-in-and-submit-your-vat-return-vat-notice-70012 |

## Design

- **No state outside the user's books.** The wizard's draft is `_System/Import/draft.json`; every upload is kept as
  it came in `_System/Import/sources/<sha256>-<name>`; the posted import is `_System/Import/opening.json`.
- **Reading** (`services/runtime/app/import_formats.py`): CSV (comma, semicolon or tab; UTF-8 or Windows-1252) or the
  first sheet of an .xlsx. The header row is found in the first 40 rows by column names (`FIELDS`: every spelling the
  vendors use for each field), so title blocks, section headings and total rows are skipped. The kind of file (trial
  balance, chart of accounts, contacts, open items, bank balances) is worked out from the header, or picked by the
  user. Xero's YTD columns win over the period ones; "Sales (200)" and "1200 Bank" give up their codes. Money is
  read as pounds to at most two decimal places into integer pence (brackets, `CR`, trailing minus are credits); a
  third decimal place is refused, never rounded. Dates are UK day-first or ISO. Credit notes and receipts in an aged
  list are listed as skipped.
- **Mapping** (`services/runtime/app/import_history.py`, `suggest`): Sage keeps its four-digit nominal codes (ours
  when we have the code, else ours by name, else its own code and name); otherwise name rules (receivable → 1100
  Debtors, PAYE → 2210, VAT → 2200, director's loan → 2300 …) checked against the account's class; otherwise a new
  account in the range for its type (fixed assets 0010+, other banks 1220+, …). An account whose type we cannot tell
  is unmapped and blocks posting. The user can change any target to a four-digit code and a name.
- **Posting**: one `LedgerEvent` of kind `adjustment`, dated the day before the conversion date, one line per
  Accnomos account, no VAT code on any line, `net` and `vat` 0, `evidence` = the sha256 of every source file,
  approved by the user. `compute_vat_return` only counts sales, purchases and reversals, so no return ever sees it
  (and its undo, a reversal with no VAT code, is out of scope too). Year-to-date P&L balances are kept as they are,
  or folded into 3200 Retained profit for a year-end conversion.
- **Open items** are not posted: the debtors and creditors are already one line each in the opening entry.
  `app/contacts.py` reads them from `opening.json` and shows each as a document on account (`Doc.opening`), so aged
  balances, statements, Books.xlsx, the dashboard's "owed to you" and *Record payment* include them; a payment posts
  Dr 1200 Bank / Cr 1100 Debtors as for any invoice.
- **Checks** before posting: trial balance present and balanced to the penny, every account mapped, a conversion
  date, no entries already on or before the balance date, no import already in force (errors); open invoices = the
  debtors balance, open bills = the creditors balance, bank balances = the bank accounts, open items dated after the
  balance date (warnings, which the user must accept).
- **Reconciliation**: after posting, the Accnomos trial balance at the balance date is worked out again from every
  event on or before it (`projection.trial_balance`) and compared with what the source says each account should
  hold; plus the aged debtors and creditors from the open items and the bank balances. `proved` only when every row
  agrees. Saved as CSV in `07 Reports`; `GET /import/opening/report.csv` serves it again.
- **Undo** posts the reversal of the opening entry and marks the import undone (the open items disappear); refused
  while a payment, credit use or credit note points at an open item. Contacts added stay.
- **Web**: `/import` (`apps/web/src/components/import/ImportWizard.tsx`), linked from Settings › Your data. Five
  steps on one page: old system and conversion date; uploads; mapping (editable, unmapped highlighted); checks and the
  opening entry; approve (a tick, plus a second tick when there are warnings) and post. Afterwards: the
  reconciliation table, *Download reconciliation (CSV)* and *Undo import*.
- **Audit**: `import_file_added`, `import_discarded`, `opening_balances_posted`, `opening_balances_undone`, each
  with a sentence in `audit_view.SUMMARIES`.

## Tests

- `services/runtime/tests/test_import_history.py`: **64 tests**. Sample exports in
  `services/runtime/tests/fixtures/import/` (one fictional company, Hollybank Joinery Ltd, labelled
  SAMPLE — FICTIONAL COMPANY, in six vendor layouts; figures in its README). Money (12 cases) and dates (7) read
  exactly; impossible dates and three-decimal amounts refused; all six trial balances read 16 accounts and balance
  at £66,185.10; vendor and kind detection for all 21 files; Xero YTD columns; Sage receipts skipped; an .xlsx with
  title rows and date cells; unreadable files give sentences. Mapping: every sample account reaches the expected
  Accnomos account for all six vendors; unplaceable accounts stay unmapped; a second bank gets 1220. End to end
  through the routes, for each vendor: one balanced adjustment with no VAT code dated 31 Mar 2026, nothing posted
  before approval, the reconciliation proved and saved, VAT return for the quarter all zero with no warnings, aged
  debtors £4,560.00 in the right buckets and creditors £2,130.50, contacts created with their details, audit lines.
  Then: a payment against an opening invoice reduces 1100 Debtors and aged; undo refused while it stands, works once
  it is removed, and a fresh import is allowed after; warnings must be accepted; a debtors list that does not add up;
  an unbalanced trial balance (1p) refused; unmapped accounts block until mapped (a bad target 422; a key not in the
  trial balance 422); earlier entries refused; a second import waits for undo; year-end fold into retained profit
  (still proved); a new trial balance replaces the old; uploads kept as they came; templates read back as their kind;
  bad and over-long CSVs, unsafe names, missing `X-User`.
- Whole runtime suite: see the gate results below. `tests/test_security_routes.py` found the template route without
  a Graph token on the first run; it now needs one like every other route.
- e2e `apps/web/e2e/import.spec.ts`: **2 tests** (desktop): Sage 50 upload of three files → mapping shown and one
  changed → checks green → Post disabled until ticked → reconciled → CSV in `07 Reports`, uploads in
  `_System/Import/sources` → aged balances via the API → undo; and the Settings › Your data link. `/import` added to
  `e2e/pages.ts`, so the phone sweep and axe (signed out and signed in) cover it.

## Gate results (28 Oct 2026, this container)

- `cd services/runtime && python -m pytest -q`: GATE_PYTEST
- `ruff check .` and `ruff format --check .` (0.17.3): clean. `pyright services/runtime/app` (1.1.414): 0 errors.
- `cd apps/web && pnpm install --frozen-lockfile && pnpm exec eslint .`: clean. `pnpm run e2e:build`: built.
- `pnpm run e2e:test`: GATE_E2E Run with `executablePath` pointed at the container's preinstalled Chromium through
  an uncommitted local config, because the pinned Playwright's own browser build is not installed here and cannot
  be downloaded.
- No Flutter change (Android has no import screen), so no widget tests.

## Risks

- Header spellings and the FreeAgent Summary CSV layout are unconfirmed against real exports (above). A real export
  that the parser does not recognise is refused with a sentence, never half-read; one it misreads would show in the
  mapping table and the checks before anything is posted, and a trial balance that does not balance is refused.
- Two Post clicks racing past the "no import in force" check could post two opening entries (the button is disabled
  while posting; there is no lock across requests). The reconciliation would then show every account doubled.
- Open items cannot be matched straight to a bank line, and a credit note cannot be raised against one from
  Invoices; *Record payment* is the route.
- A mid-year conversion puts the year's income and costs so far on one date, so a P&L for a VAT period that contains
  the balance date is not that period's alone.
- Opening VAT control comes across as one balance; the next VAT return does not include the old period's figures,
  which is right, but the user must pay what the old system's last return said.
