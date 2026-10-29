# Reports

Every report the app outputs: where to find it, which file formats it comes in, which official or vendor format
it follows (with the citation), and the test that covers it. UK English; money is pence in CSV/XLSX and pounds
in the PDF text, unless the format says otherwise.

Wording check (October 2026): the VAT return's box names and numbers are HMRC's own headings from "How to fill in
and submit your VAT Return (VAT Notice 700/12)", sections 3.2–3.10, word for word — locked by
`test_vat_return_is_hmrc_s_boxes_and_wording` in `services/runtime/tests/test_exports.py`. The other HMRC-facing
files are labelled as what they are ("SA103-style", "P32-style", "readable rows", "prepared … NOT submitted"),
never as HMRC's own forms, so no layout or label fix was needed. Figures HMRC returned are always labelled
"HMRC"; Accnomos never presents its own working as HMRC's (`docs/HONESTY.md`).

## Export registry reports

`GET /exports/{id}` preview, `GET /exports/{id}/file?format=` download, `POST /exports/{id}/save` into
`07 Reports/` — `services/runtime/app/exports/registry.py`, `services/runtime/app/routes_exports.py`.
Web: Reports › Exports (`apps/web/src/app/reports/exports/page.tsx`), plus the pages named below.
Default formats are csv, xlsx, pdf; vendor files are csv (some also xlsx); packs are zip; the ledger is json.

| Report | Where in the app | Formats | Follows | Test |
| --- | --- | --- | --- | --- |
| `vat-return` — UK VAT return | VAT page (`apps/web/src/app/vat/page.tsx`), Reports › Exports | csv, xlsx, pdf | VAT Notice 700/12 ss 3.2–3.10, box names and numbers word for word | `test_vat_return_is_hmrc_s_boxes_and_wording` |
| `vat-detail` — VAT detail | VAT page, Reports › Exports | csv, xlsx, pdf | Same boxes as the return: sales (boxes 1+6), purchases (boxes 4+7), not on the return | `test_vat_detail_adds_up_to_the_boxes` |
| `vat-digital-links` — MTD digital links | VAT page, Reports › Exports | csv, xlsx, pdf | VAT Notice 700/22 para 3.2.1 and section 3.3 | `test_digital_links_trace_every_entry_on_the_return` |
| `vat-reconciliation` — VAT reconciliation | VAT page, Reports › Exports | csv, xlsx, pdf | Accnomos layout (no official format); must show no difference | `test_vat_reconciliation_has_no_difference` |
| `trial-balance` — Trial balance | Reports › Exports | csv, xlsx, pdf | Accnomos layout; must balance | `test_trial_balance_balances` |
| `trial-balance-range` — Trial balance by date range | Reports › Exports | csv, xlsx, pdf | Accnomos layout | `test_every_report_previews_and_renders` |
| `general-ledger` — General ledger detail | Reports › Exports | csv, xlsx, pdf | Accnomos layout; closes on the trial balance | `test_general_ledger_closes_on_the_trial_balance` |
| `general-ledger-summary` — General ledger summary | Reports › Exports | csv, xlsx, pdf | Accnomos layout | `test_every_report_previews_and_renders` |
| `general-ledger-exceptions` — General ledger exceptions | Reports › Exports | csv, xlsx, pdf | Accnomos layout; flags by rule | `test_ledger_exceptions_flag_by_rule` |
| `journal-report` — Journal report | Reports › Exports | csv, xlsx, pdf | Accnomos layout | `test_every_report_previews_and_renders` |
| `account-transactions` — Account transactions | Reports › Exports | csv, xlsx, pdf | Accnomos layout | `test_every_report_previews_and_renders` |
| `audit-trail` — Audit trail of postings | Reports › Exports | csv, xlsx, pdf | Accnomos layout | `test_every_report_previews_and_renders` |
| `cash-book` — Cash book | Reports › Exports | csv, xlsx, pdf | Accnomos layout; cash agrees everywhere | `test_cash_agrees_everywhere` |
| `balance-sheet` — Balance sheet | Reports › Exports | csv, xlsx, pdf | Accnomos layout; ties to the P&L | `test_balance_sheet_balances_and_ties_to_the_p_and_l` |
| `profit-and-loss` — Profit and loss | Reports › Profit and loss (`apps/web/src/app/reports/profit-and-loss`), Exports | csv, xlsx, pdf | Accnomos layout; comparatives | `test_p_and_l_comparatives` |
| `cash-flow` — Statement of cash flows (direct method) | Reports › Cash flow (`apps/web/src/app/reports/cashflow`), Exports | csv, xlsx, pdf | Accnomos layout, direct method | `test_cash_flow_lines_for_q3` |
| `cash-summary` — Cash summary | Reports › Cash flow, Exports | csv, xlsx, pdf | Accnomos layout | `test_every_report_previews_and_renders` |
| `changes-in-equity` — Statement of changes in equity | Reports › Exports | csv, xlsx, pdf | Accnomos layout; closes on the balance sheet | `test_changes_in_equity_close_on_the_balance_sheet` |
| `executive-summary` — Executive summary | Reports › Exports | csv, xlsx, pdf | Accnomos layout | `test_executive_summary_figures` |
| `management-report` — Management report | Reports › Exports | csv, xlsx, pdf | Accnomos layout (executive + P&L + balance sheet + aged + VAT) | `test_every_report_previews_and_renders` |
| `aged-receivables-detail` — Aged receivables detail | Reports › Aged (`apps/web/src/app/reports/aged`), Exports | csv, xlsx, pdf | Accnomos layout | `test_every_report_previews_and_renders` |
| `aged-receivables-summary` — Aged receivables summary | Reports › Aged, Exports | csv, xlsx, pdf | Accnomos layout | `test_every_report_previews_and_renders` |
| `aged-payables-detail` — Aged payables detail | Reports › Aged, Exports | csv, xlsx, pdf | Accnomos layout | `test_every_report_previews_and_renders` |
| `aged-payables-summary` — Aged payables summary | Reports › Aged, Exports | csv, xlsx, pdf | Accnomos layout | `test_every_report_previews_and_renders` |
| `receivable-invoice-detail` — Receivable invoice detail | Reports › Exports | csv, xlsx, pdf | Accnomos layout | `test_every_report_previews_and_renders` |
| `receivable-invoice-summary` — Receivable invoice summary | Reports › Exports | csv, xlsx, pdf | Accnomos layout | `test_every_report_previews_and_renders` |
| `payable-invoice-detail` — Payable invoice detail | Reports › Exports | csv, xlsx, pdf | Accnomos layout | `test_every_report_previews_and_renders` |
| `payable-invoice-summary` — Payable invoice summary | Reports › Exports | csv, xlsx, pdf | Accnomos layout | `test_every_report_previews_and_renders` |
| `contact-transactions` — Contact transactions summary | Reports › Exports | csv, xlsx, pdf | Accnomos layout | `test_every_report_previews_and_renders` |
| `income-expenses-by-contact` — Income and expenses by contact | Reports › Exports | csv, xlsx, pdf | Accnomos layout | `test_every_report_previews_and_renders` |
| `customer-invoice-activity` — Customer invoice activity | Reports › Exports | csv, xlsx, pdf | Accnomos layout | `test_every_report_previews_and_renders` |
| `supplier-bill-activity` — Supplier bill activity | Reports › Exports | csv, xlsx, pdf | Accnomos layout | `test_every_report_previews_and_renders` |
| `supplier-days-to-pay` — Supplier days to pay | Reports › Exports | csv, xlsx, pdf | Accnomos layout | `test_every_report_previews_and_renders` |
| `contact-list` — Contact list | Reports › Exports | csv, xlsx, pdf | Accnomos layout | `test_every_report_previews_and_renders` |
| `account-summary` — Account summary | Reports › Exports | csv, xlsx, pdf | Accnomos layout | `test_registry_has_every_report_in_its_group` |
| `bank-reconciliation` — Bank reconciliation | Reports › Exports | csv, xlsx, pdf | Accnomos layout | `test_bank_reconciliation_and_statement_lines` |
| `bank-summary` — Bank summary | Reports › Exports | csv, xlsx, pdf | Accnomos layout | `test_registry_has_every_report_in_its_group` |
| `uncoded-statement-lines` — Uncoded statement lines | Reports › Exports | csv, xlsx, pdf | Accnomos layout | `test_registry_has_every_report_in_its_group` |
| `duplicate-statement-lines` — Duplicate statement lines | Reports › Exports | csv, xlsx, pdf | Accnomos layout | `test_registry_has_every_report_in_its_group` |
| `accountant-pack` — Accountant pack | Reports › Exports | zip | Accnomos bundle: trial balance, ledger, balance sheet, P&L, aged, VAT, contacts, README | `test_accountant_pack_and_ledger_json` |
| `ledger-json` — Ledger (open JSON) | Reports › Exports | json | Accnomos open format | `test_accountant_pack_and_ledger_json` |

### Vendor import files

Headings, order and date/number formats follow each vendor's published import template; `SOURCES` in
`services/runtime/app/exports/vendors.py` gives the page each file was checked against (checked 28 October 2026).
None has been test-imported into the vendor's product — compare against a demo company before relying on it.
Bundles (`xero-all`, `qbo-all`, `sage50-all`, `sage-accounting-all`, `freeagent-all`) zip every file for the
package. Web: Reports › Exports.

| Report | Formats | Vendor template it follows |
| --- | --- | --- |
| `xero-manual-journals`, `xero-contacts`, `xero-sales-invoices`, `xero-bills`, `xero-bank-statement`, `xero-chart-of-accounts` (+ `xero-all`) | csv | Xero central import guides (contacts; customer invoices UK; bills and credit notes UK; CSV bank statement; manual journals; ChartOfAccounts.csv) |
| `qbo-journal-entries`, `qbo-customers`, `qbo-suppliers`, `qbo-invoices`, `qbo-bank-transactions`, `qbo-chart-of-accounts` (+ `qbo-all`) | csv, and xlsx for journals, customers, suppliers, chart | QuickBooks help: import data / invoices / bank transactions / chart of accounts |
| `sage50-audit-trail`, `sage50-customers`, `sage50-suppliers`, `sage50-nominals` (+ `sage50-all`) | csv | Sage 50 import layouts |
| `sage-accounting-journals`, `sage-accounting-customers`, `sage-accounting-suppliers`, `sage-accounting-chart-of-accounts` (+ `sage-accounting-all`) | csv | Sage knowledgebase: import journal entries; format your customers and suppliers import file; import your chart of accounts |
| `freeagent-bank-statement` (no header row), `freeagent-contacts`, `freeagent-invoices` (+ `freeagent-all`) | csv | FreeAgent support: bank statement upload; contacts; invoice template |

Covered by `test_mappings_change_the_import_file`, `test_catalogue_lists_groups_and_reports`,
`test_every_report_previews_and_renders` in `services/runtime/tests/test_exports.py`.

## Self-employment and property (MTD Income Tax)

`GET /books/self-employment/reports/{sa103,quarterly,calculation}?format=` — csv, xlsx, pdf —
`services/runtime/app/itsa_reports.py`, `services/runtime/app/routes_itsa.py`.
Web: Self-employment (`apps/web/src/app/self-employment/page.tsx`).

| Report | Follows | Test |
| --- | --- | --- |
| Self-employment summary (SA103-style), box by box with the ledger lines behind each box | SA103F box mapping: every API field maps to its SA103F box (`test_every_api_field_is_mapped_to_its_sa103f_box`); "SA103-style", never HMRC's form | `test_sa103_report_renders_every_format` |
| Quarterly update as submitted, with HMRC's receipt | The cumulative figures sent, plus HMRC's correlation and receipt IDs | `test_cumulative_receipt_is_checked_against_the_books_and_audited` |
| HMRC tax calculation | HMRC's Individual Calculations figures, copied as returned | `test_calculation_report_copies_hmrc_figures_only` |

Property income maps to its SA105 boxes for the MTD quarterly update (`services/runtime/app/property.py`, from
HMRC's `sa105_mapping_v1.csv`); there is no standalone SA105 form — the quarterly update carries the property
figures. There is no MTD ITSA submission file to download: updates are filed through HMRC's API and the receipts
are stored (`GET /books/self-employment/receipts`).

## CIS

CIS page (`apps/web/src/app/cis/page.tsx`); routes in `services/runtime/app/routes_cis.py`.

| Report | Where / format | Follows | Test |
| --- | --- | --- | --- |
| CIS300 monthly return, per subcontractor for the tax month | `GET /books/cis/returns/{tax-month-end}` (JSON view); `POST …/export` saves CSV + JSON to `07 Reports/CIS/` for filing elsewhere — Accnomos never submits it | CIS deduction rates (gross 0%, net 20%, unverified 30%), tax months 6th–5th, due by the 19th (`services/runtime/app/cis.py`) | `test_monthly_return_and_its_file` |

## Payroll, RTI and pensions

Payroll page (`apps/web/src/app/payroll/page.tsx`); routes in `services/runtime/app/routes_payrun.py`
(`GET /payroll/paye/reports/{key}`, `GET /payroll/paye/payruns/{rid}/fps`, `GET /payroll/paye/eps/{tax-month}`,
`GET /payroll/paye/payruns/{rid}/pension/{provider}`, payslips per employee).

| Report | Format | Follows | Test |
| --- | --- | --- | --- |
| `p32` — Employer payment record (P32-style) | json, csv, xlsx, pdf | HMRC payment deadlines (22nd electronically, 19th by post; `pay-paye-tax`) | `test_routes_end_to_end` in `services/runtime/tests/test_payroll_reports.py` |
| `payroll_summary`, `p11`, `p45`, `p60`, `journal` — readable rows | json, csv, xlsx, pdf | Readable workings of the run, not HMRC stationery | `test_routes_end_to_end` |
| `fps` — what the FPS XML says, in words, next to the XML | XML download + readable rows | HMRC RTI submissions: "How to use the RTI Internet service" v1.94 and the 2026–27 technical specifications (`services/runtime/app/rti.py`); files say NOT SUBMITTED and must be filed in HMRC software | `test_routes_end_to_end` |
| `eps` — Employer Payment Summary | XML download | Same RTI specifications; a month with no pay still needs an EPS | `test_routes_end_to_end` |
| `pension` — pension workings per run; provider files (e.g. Smart Pension) | csv per provider | Provider CSV specs (e.g. Smart Pension PAPDIS 1.0; `services/runtime/app/pension_ae.py`) | `test_routes_end_to_end` |
| Payslips | pdf (and json) | Accnomos layout | `services/runtime/tests/test_payroll.py` |

## What is deliberately not a report

- EC Sales List: not offered. Since 1 January 2021 only Northern Ireland businesses selling goods to the EU send
  one, and Accnomos records no NI/EU movements — VAT boxes 2, 8 and 9 are always 0 (`vat_reports.py`).
- Filed returns themselves: VAT, MTD ITSA, CIS and RTI submissions go through HMRC's APIs or HMRC software;
  Accnomos keeps the figures, the receipts and the files, and every prepared file says whether it was submitted.
