# Review: sales-purchases and exports, fixed and merged (branch `claude/sales-exports-fix`)

Two finished features that never reached `main` because their own e2e specs failed (`docs/reviews/integration/REVIEW.md`,
*Not merged, and why*): `claude/sales-purchases` (items, quotes, purchase orders, repeating invoices and bills, Sales and
Purchases overviews, customer statements) and `claude/exports` (Reports & exports: accountant reports, HMRC-style VAT
reports, import files for Xero, QuickBooks Online, Sage 50, Sage Accounting and FreeAgent). Both are merged here into
`origin/main` at `947e61a`, conflicts resolved, their failures fixed, and every gate run green. The branches' own review
and handover notes moved from the repository root to `docs/reviews/sales-purchases/` and `docs/reviews/exports/`.

## Merge conflicts (against batch-tax, accountant, import-history, bank-feeds, payroll-finish, profiles, CIS, shopping)

- **Ask actions** (`app/actions.py`, `app/schemas.py`, `ActionCard.tsx`, `docs/ACTIONS.md`): `create_quote` and
  `convert_quote_to_invoice` sit beside main's `pay_overtime`, `add_to_shopping_list`, `match_bank_line` and
  `close_month`. One intent prompt names all of them; one action-word pattern holds both sets of words. The invoice card's
  "emailed to" note keeps main's `sentNote` and the branch's create-invoice-only condition.
- **Invoice lines**: CIS `materials` (main) and the catalogue `item_code` (branch) both kept, in the model, the form and
  the payload. Invoices keep main's payment link, CIS and reverse-charge fields and the branch's `repeating` tag.
- **`bills.py`** called main's `approve.final_journal` with the old signature; it now awaits `final_journal(books, p)`.
  This was the cause of 19 runtime failures right after the merge.
- **Route security tests** (added to `main` after the branches forked): the three new PDF routes are listed as writes
  that need no `X-User` (they render, as the invoice and credit-note PDFs do); `GET /repeating/dates` is public date
  arithmetic.
- `runtime.ts`, `main.py`, `audit_view.py`, `facts.py`, `pages.ts`, `HONESTY.md`: both sides kept. `ARCHITECTURE.md`'s
  router list, already garbled by an earlier merge on `main`, is rewritten once.

## The failures, root causes and fixes

| Failure | Root cause | Fix |
|---|---|---|
| Purchase order converted to a bill lands in *needs a look*, not *proposed* | Not a code bug. The e2e gave the supplier no VAT number, and a £431.52 bill with VAT and no supplier VAT number fails `VAT_NUMBER_REQUIRED` (a full VAT invoice over £250 must carry it). `test_purchase_orders.py` already asserted exactly that. | The spec fills the supplier's VAT number. The order form now says, under *Their VAT number*, that without it a bill over £250 waits as *needs a look*. |
| The statement *Customer* picker never becomes selectable | `StatementPicker` listed only contacts saved in `contacts.json`, so a customer known only from an invoice (the usual case, and exactly the one who owes money) was missing; with none it rendered nothing. | The picker reads the contact book (`GET /contacts`: saved contacts plus everyone the ledger names), the same list the Contacts page shows and the statement route resolves. |
| `profiles.spec` menu test | It asserted the sales pages were absent. | ↓ now lands on *Sales overview*, then *Invoices*; the five sales links are checked in order. |
| `exports.spec`: the Xero manual-journals preview never shows `*Narration` | The spec stars a report and reloads; the reload dropped the period, so the journal previewed the current quarter (Oct–Dec), which is empty, and an empty section draws no table. | The report and period live in the address (`?report=&from=&to=&as_of=&mode=`): a reload or a shared link opens the same preview. The spec checks the URL and the From date after the reload. |
| axe **critical** `aria-valid-attr-value` on `/reports/exports` | Every report button has `aria-controls="report-preview"`, but before a report is chosen the placeholder panel had no id. | The placeholder panel carries `id="report-preview"`. A new test checks it before any choice. |
| The disabled *This VAT period* button gives no reason | No text. | A visible line (`#period-why`) says why: a fixed sample when signed out, or "at one date, not for a period" for an as-at report. *This VAT period*, From, To and the stars point to it with `aria-describedby`; Download and Save point to their existing "Sign in to download or save" line. Asserted with `toHaveAccessibleDescription`. |

## Found while merging (not in the brief, fixed because the merge made them wrong)

- **Cash flow said "Accnomos has no repeating invoices or bills yet".** Once repeating templates exist, that is false.
  `app/cashflow.py` now forecasts every occurrence not made yet within the 90 days, at one occurrence's total:
  - an invoice is due its own days to pay after the occurrence, else the profile's terms;
  - a bill is due the supplier's terms after it, else 30 days (as the aged report dates bills);
  - an occurrence already due counts from today.

  These items are in the totals, the item list and `repeating`. 2 tests.
- **The exported UK VAT return ignored VAT schemes.** Batch-tax added cash accounting, the flat rate scheme and annual
  accounting after `claude/exports` forked. Under a scheme, the export used the standard calculation, so it disagreed with
  the return the VAT page files.
  - The export now uses the same scheme engine (`app/vat_schemes.py`) and names the scheme in its basis line.
  - VAT detail, digital links and the VAT reconciliation warn that they list entries on the invoice basis.
  - 2 tests: under the flat rate the export gives £132.00 in box 1 and £1,200 in box 6, as the VAT page does, and the
    standard case is unchanged.

## Vendor import formats, re-checked (28 Oct 2026)

Every template was read again against the vendor's own help page. The container cannot reach the vendors' sites
(proxy), so the pages were read through a page-reading service. Xero Central's `/s/` articles are JavaScript-only and
several `/0/` articles came back empty. The table below has the full URLs; the per-file table is in `docs/HONESTY.md`
*Reports and exports*.

| Template | Vendor page read 28 Oct 2026 | Result |
|---|---|---|
| Xero bank statement | https://central.xero.com/0/article/Import-a-CSV-bank-statement | matches |
| Xero contacts | https://central.xero.com/0/article/Import-contacts-into-Xero | matches what the page names (full row only in the logged-in download) |
| Xero sales invoices | https://central.xero.com/0/article/Import-customer-invoices-UK | rules and every column named there match; row order secondary |
| Xero bills | https://central.xero.com/0/article/Import-bills-and-credit-notes-UK | **would not render**; headings secondary (BillTemplate.csv as downloaded by kedgework.com) |
| Xero manual journals | https://central.xero.com/0/article/Add-import-and-post-manual-journals (all regional slugs) | **would not render**; headings agree with every secondary copy; marked "not confirmed by Xero" in the file's source line |
| Xero chart of accounts | https://central.xero.com/0/article/Import-a-chart-of-accounts-UK | **would not render**; nine columns agree with a Xero training manual; UK tax names from Chart-of-accounts-templates-in-Xero-HQ-UK (read) |
| QuickBooks journal entries | https://quickbooks.intuit.com/learn-support/en-uk/help-article/import-export-files/import-journal-entries-quickbooks-online/L4tQBwbs7_GB_en_GB | matches (citation moved from the US page) |
| QuickBooks invoices | https://quickbooks.intuit.com/learn-support/en-uk/help-article/import-export-files/import-multiple-invoices/L7E9Xrd8l_GB_en_GB | matches the six required fields |
| QuickBooks chart of accounts | https://quickbooks.intuit.com/learn-support/en-uk/help-article/import-export-files/import-chart-accounts-quickbooks-online/L9Res1eb1_GB_en_GB | matches |
| QuickBooks customers, suppliers | https://quickbooks.intuit.com/learn-support/en-uk/help-article/list-management/contact-fields-imported-excel/L0fwkOCms_GB_en_GB | matches (mapped at import) |
| QuickBooks bank | https://quickbooks.intuit.com/learn-support/en-us/help-article/import-transactions/manually-upload-transactions-quickbooks-online/L0rE9OXBz_US_en_US | matches (no UK page found) |
| Sage 50 audit trail, journals, nominals | https://gb-kb.sage.com/portal/app/portlets/results/viewsolution.jsp?solutionid=250321114601443, …=200427112601918, …=250321114606157 | match (Exchange Rate is written as 1, never blank) |
| Sage 50 customers, suppliers | https://gb-kb.sage.com/portal/app/portlets/results/viewsolution.jsp?solutionid=220225121155067 | **differed in names**: renamed to the current labels (Reference, Customer Name, Main Address Line 1 …); Sage maps columns at import, so the old labels also imported. Golden files updated. |
| Sage Accounting journals | https://gb-kb.sage.com/portal/app/portlets/results/viewsolution.jsp?solutionid=222001000100916 | matches A–L exactly |
| Sage Accounting contacts | https://gb-kb.sage.com/portal/app/portlets/results/viewsolution.jsp?solutionid=240701101019900 (modified 8 Oct 2026) and https://help.sbc.sage.com/en-gb/partner-edition/Accounting/EnterCustomerRecords.html | matches A–AI; Reference is at most 8 characters, within both pages' limits |
| Sage Accounting chart of accounts | https://gb-kb.sage.com/portal/app/portlets/results/viewsolution.jsp?solutionid=222001000100820 (UK) and …=222001000100819 (IE, exact headings) | headings match; the UK tax-rate words are still unverified |
| FreeAgent bank, contacts, invoices | https://support.freeagent.com/hc/en-gb/articles/115001222564, https://support.freeagent.com/hc/en-us/articles/115001222864, https://support.freeagent.com/hc/en-gb/articles/36670919996050 | match (no header row on the bank file; zero-rated lines say "0"; the optional `property` column for landlord accounts is not written) |

## Tests and gates (Linux, Python 3.13, `uv sync --all-packages --all-extras`, 28 Oct 2026)

- pytest:

  | Suite | Passed | Skipped |
  |---|---|---|
  | runtime | 2336 | 2 |
  | ledger | 101 | 0 |
  | connectors | 63 | 0 |
  | hmrc-relay | 181 | 0 |
  | evals | 353 | 0 |

  New since the merges:
  - 2 cash-flow tests (`test_repeating.py`);
  - 2 VAT-scheme export tests (`test_vat_schemes_routes.py`);
  - route security lists updated;
  - `test_accounting_tools.py`'s cash-flow note assertion updated.
- `ruff check` and `ruff format --check` (0.17.3) are clean, and `pyright` 1.1.414 reports 0 errors.
- `eslint`, `tsc --noEmit`, `next build` and the production export's test-mode check are clean.
- e2e (`pnpm run e2e:build`, then `CI=1 playwright test`, all projects): **455 passed, 94 skipped (deliberate), 0 failed, 1 flaky** in 13.2 min (3 workers). The flaky one is `review.spec.ts:164` (U pressed while an approve is in flight), in a spec this branch does not touch; it passed on its CI retry, and passed outright in the run before (456 passed). Exit code 0.
  - New or changed specs: `sales-purchases.spec`, `profiles.spec` and `exports.spec`. `exports.spec` gained a test and
    assertions.
  - `submission-wording.spec` now also covers `/sales`, `/sales/quotes`, `/sales/items`, `/sales/repeating`, `/purchases`,
    `/purchases/orders` and `/reports/exports`, signed out and signed in. Their sources were also grepped for launch words;
    there are none.
  - `a11y.spec` and `phone.spec` cover the seven new pages through `pages.ts`.
- Local note: the installed Playwright wants headless shell build 1248 and the machine has 1243. The run used a symlink
  outside the repository; nothing in the repository changed for it.
- Flutter is not touched.

## Risks and follow-ups

- **Nothing has been test-imported into any accounting package.** The Xero journal, bill and chart-of-accounts headings are
  not confirmed on a Xero page; download the templates from a Xero demo company before relying on them.
- **The registry's optional report hooks are dead.** `app.accounting_tools.reports`, `app.sales_purchases.reports`,
  `app.payroll_reports` (which says it will register later) and `app.income_tax.reports` name modules those features did
  not create, so fixed assets, budgets, tracking, the cash-flow forecast, sales by item, payroll and Income Tax reports are
  not in Reports & exports. Registering them is new work, left out of this fix.
- The cash-flow forecast dates a repeating bill by the supplier's terms; the real due date is whatever the supplier's bill
  says.
- Under a VAT scheme, VAT detail, digital links and the VAT reconciliation still list entries on the invoice basis. They say
  so, but they are not scheme-aware.
- `docs/reviews/integration/REVIEW.md` still lists both branches under *Not merged*; the integrator updates it when this
  branch lands.
