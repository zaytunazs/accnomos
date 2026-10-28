# Review: reports and exports for accountants (branch `claude/exports`)

## What changed

**Runtime** (`services/runtime/app/exports/`, `app/routes_exports.py`, registered in `app/main.py`)

- **One registry** (`registry.py`): every report is an `ExportSpec` (id, group, formats, params `period` / `as_of` /
  `mode`, `build(ctx) -> ReportDoc`). `writers.py` turns any ReportDoc into CSV, XLSX and PDF, so figures are written once.
  `RESERVED` keeps ids for other features (fixed-asset and depreciation schedules, budgets, tracking, cash-flow forecast:
  accounting-tools; sales by item: sales-purchases); `OPTIONAL_PLUGINS` imports their modules when they exist (payroll and
  Income Tax have slots too). Duplicate or squatted ids raise.
- **Routes**: `GET /exports` (catalogue, favourites), `GET /exports/{id}` (preview JSON), `GET /exports/{id}/file?format=`
  (download, reads only), `POST /exports/{id}/save` (07 Reports, never overwrites, audited `report_saved`),
  `GET|PUT /exports/mappings/{package}` (`_System/exports/mappings.json`), `GET|PUT /exports/favourites`
  (`_System/exports/favourites.json`). Nothing posts to the ledger.
- **Reports, grouped as Xero's All reports** (per the coordinator's list):
  - Financial statements: balance sheet, P&L with comparatives (previous period, same period last year), statement of cash
    flows (direct), statement of changes in equity, executive summary, cash summary, management report (pack of the above
    plus aged and VAT).
  - Payables and receivables: aged receivables/payables detail and summary, receivable/payable invoice detail and summary,
    contact transactions summary, income and expenses by contact, customer invoice activity, supplier bill activity, supplier
    days to pay, contact list.
  - Reconciliations: account summary, bank reconciliation, bank summary, uncoded statement lines, duplicate statement lines,
    cash book.
  - Taxes and balances: general ledger detail and summary, general ledger exceptions (round amounts, weekend dates, late
    approval, no account code, unexpected sign), journal report, trial balance, trial balance by date range, UK VAT return,
    VAT detail, MTD digital links, VAT reconciliation.
  - Transactions: account transactions, audit trail of postings.
  - For your accountant: the Accountant pack (zip: TB, GL, BS, P&L, aged detail, journal, audit trail, bank rec, contacts as
    CSV and PDF; VAT return, detail and digital links for each VAT period that has ended in the range; ledger.json; README
    with period, basis, what to check and warnings) and the open ledger JSON.
  - Export to another package: 23 import files (Xero 6, QuickBooks Online 6, Sage 50 4, Sage Accounting 4, FreeAgent 3) and
    one zip per package with a README.
  - Left out as asked: EC Sales List (NI goods only since 2021; said in docs) and the accounting-tools / sales-purchases reports.
- **Period basis**: the books close no year-end, so a period report takes balance-sheet accounts to the end, P&L accounts
  for the period, and earlier profit as one line, `3200 Profit and loss brought forward`.
- **Mapping** (`mapping.py`): books' accounts and VAT codes to each package with UK defaults and a quality per account
  (user, default, suggested, check, own, unmapped); unmapped and check accounts are warnings in every preview, the package zips
  and the pack README. Journals carry no VAT code (already on Accnomos's returns); invoices and bills carry the package's
  rate names.

**Web** (`apps/web`): new page `/reports/exports` "Reports & exports" (`src/components/reports/ReportsExports.tsx`): period
and as-at pickers, a search box, groups with a Starred group, star toggles, a preview with every table, format buttons
(download), *Save as* + *Save to 07 Reports*, warnings and the template source for import files, and an account-mapping panel.
Signed out: a labelled sample. Linked from `/reports`. Client calls in `src/lib/runtime.ts` (`runtime.exports.*`).

**Docs**: `docs/ARCHITECTURE.md` (routes, the registry, the ledger JSON format, the new `_System/exports/*` and `07 Reports`
rows), `docs/HONESTY.md` (a "Reports and exports" section with the verification table).

## Sources (all read 28 October 2026)

- HMRC box wording: VAT Notice 700/12, sections 3.2–3.10, https://www.gov.uk/guidance/how-to-fill-in-and-submit-your-vat-return-vat-notice-70012 (page updated 19 Dec 2025).
- Digital links: VAT Notice 700/22, paragraph 3.2.1 and section 3.3, https://www.gov.uk/government/publications/vat-notice-70022-making-tax-digital-for-vat/vat-notice-70022-making-tax-digital-for-vat (updated 1 Apr 2022).
- Xero: central.xero.com/0/article/Import-customer-invoices-UK, Import-contacts-into-Xero, Import-a-CSV-bank-statement
  (official, read through a crawler; the /s/article pages need a login). Manual journal, invoice, bill and chart headings from
  copies of Xero's templates (docs.sequencehq.com, notestoself.dev, syslumelab.com, kedgework.com, gigsorted.com,
  accountantmaster.com); UK default codes from tenpercentfinancial.co.uk and linggardandthomas.co.uk.
- QuickBooks Online: quickbooks.intuit.com/learn-support — import journal entries (L4tQBwbs7_US_en_US), import multiple
  invoices (L7E9Xrd8l_GB_en_GB), import chart of accounts (L9Res1eb1_GB_en_GB), account types (L9IuTxhDc_GB_en_GB), VAT codes
  (L9v5htbsT_GB_en_GB), manual bank upload (L0rE9OXBz_US_en_US), import data from other software (L6LbxyKFZ_ROW_en).
- Sage 50: gb-kb.sage.com solutions 250321114601443 (audit trail fields, 21 Mar 2025), 250321114606157 (nominal records),
  200427112601918 (import journals), 220225121155067 (customer/supplier columns), 200427112546692 (default control accounts);
  numericsolutions.co.uk default nominal codes (v26); Sage 50 help "Tax codes for UK users".
- Sage Accounting: gb-kb.sage.com 222001000100916 (journals, 13 Feb 2025), 240701101019900 (contacts, 8 Oct 2026),
  222001000100820 / 222001000100121 (chart of accounts, control accounts); ie-kb.sage.com 222001000100819 (chart headings).
- FreeAgent: support.freeagent.com articles 115001222564 (bank CSV), 115001222864 (contacts), 36670919996050 (invoices).

## Tests

- `services/runtime/tests/test_exports.py`: 79 tests. Reconciliation over five periods (TB balances; BS net assets =
  capital and reserves; BS profit = P&L net profit; retained earnings move by the P&L; GL closing = TB; TB by date range
  totals; cash agrees across cash book, cash flow, cash summary and bank summary; changes in equity close on the BS); worked
  figures (Q3 balance sheet, cash-flow lines, comparatives, executive summary, exceptions rules, 9 boxes and HMRC wording,
  VAT detail = boxes, VAT reconciliation nil difference, digital links, bank reconciliation and duplicates); writers (CSV, XLSX,
  PDF agree; formula-injection guard via `_safe_text` in CSV and XLSX; sample label); registry (groups, reserved and
  duplicate ids, a source with a date for every vendor file); **golden files** for all 23 vendor files (headings and first
  rows byte for byte, CRLF kept by `.gitattributes`); vendor rules (Xero journals net to nil with No VAT, Sage 50 JD/JC with
  T9, invoice lines add up, FreeAgent bank CSV has no header or quotes); routes (catalogue, preview and download write
  nothing, save to 07 Reports with audit and no ledger change, bad requests, favourites, mappings change the file, the pack
  and ledger JSON, every report previews and renders in every format).
- `apps/web/e2e/exports.spec.ts`: signed out (sample, groups, downloads off), 360 px (no sideways scroll), signed in (preview,
  download filename, save to 07 Reports, HMRC Box 4 wording and figure, star survives reload, Xero journal headings and mode,
  mapping default 461, ledger untouched). `/reports/exports` is in `e2e/pages.ts`, so the phone smoke and axe specs cover it.
- Gate results: see the end of this file.

## Risks

- **Nothing was test-imported into any package.** The files follow published templates; where a vendor page was behind a
  login (Xero's manual journals, the template downloads) the headings come from copies of the template, named above.
- Sage Accounting's UK tax-rate words in the chart file, two QuickBooks detail types and some Xero tax names are standard
  names we did not see on a vendor page (docs/HONESTY.md lists them).
- Bank files come from the ledger's 1200 Bank entries, not the bank's statement; the bank reconciliation reads the Bank page's
  matches against 1200 Bank only.
- A large book makes big previews: preview tables are cut at 300 rows by default (2,000 at most); files are complete and built
  in memory per request.
- The `raw_pack` builder temporarily changes the context's period while it builds each VAT period's reports (restored in a
  `finally`).

## What an accountant should check

1. The trial balance and balance sheet at the cut-off date; the brought-forward profit line stands in for retained earnings
   and any year-end entries.
2. Accruals, prepayments, depreciation, stock and fixed assets: the books record none of these.
3. Bank and cash against the bank's own statements (bank reconciliation, uncoded and duplicate lines).
4. The VAT return, VAT detail and VAT reconciliation for each period against what was filed with HMRC.
5. Before importing anywhere: the account mapping for that package (every Check and Unmapped row), and choose **either** the
   journals **or** the invoices and bills for a period, never both. Journals carry no VAT code on purpose.
6. General ledger exceptions: each flag is a prompt to look, not an error.
