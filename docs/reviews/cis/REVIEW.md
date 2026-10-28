# Review: CIS and the VAT domestic reverse charge (`claude/cis`)

Construction Industry Scheme for subcontractors first, then contractors' monthly returns (CIS300), and the VAT domestic
reverse charge for building and construction services. Written 28 Oct 2026, from `origin/main` at `9674a64`.

## Sources (all checked 28 Oct 2026)

`www.gov.uk` does not resolve from the build container (the proxy refuses the tunnel), so every page below was read
through a page-reading service rather than a browser. The URLs are also in the code comments.

| Rule | Source |
| --- | --- |
| Deduction rates 20% (registered, net payment status), 30% (unregistered or unverified), 0% (gross payment status); what is excluded before the deduction (VAT, consumable stores, fuel except travel, plant hire, prefabrication, materials the subcontractor paid for); statements within 14 days of the tax month end (the 19th); deductions paid by the 22nd (19th by post); records kept 3 years | https://www.gov.uk/what-you-must-do-as-a-cis-contractor/print |
| Subcontractor side: rates, what is not pay, statements, sole trader/partner (Self Assessment: income before deductions, CIS deductions), limited company (EPS beside the FPS, set against PAYE; "Do not use your Corporation Tax return") | https://www.gov.uk/what-you-must-do-as-a-cis-subcontractor/print |
| Travel and subsistence stay in the amount liable; materials and VAT never do; plant hire may count as materials | CIS 340, paragraphs 2.17, 3.11–3.14: https://www.gov.uk/government/publications/construction-industry-scheme-cis-340/construction-industry-scheme-a-guide-for-contractors-and-subcontractors-cis-340 |
| Monthly return: tax month 6th to 5th, due the 19th, nil returns, no negative values from software, penalties; per subcontractor name, UTR, verification number (only at the higher rate), total payments excl. VAT and CITB levy, materials, amount deducted; worked example £2,567 − £367 = £2,200 → £440 at 20%, £660 at 30% | https://www.gov.uk/what-you-must-do-as-a-cis-contractor/file-your-monthly-returns and HMRC manual CISR61190–CISR61230 (https://www.gov.uk/hmrc-internal-manuals/construction-industry-scheme-reform/cisr61230) |
| Year totals: SA103S box 9 (turnover before deductions) and box 38 (CIS deductions); SA103F box 15 and box 81; contractor's payments to subcontractors SA103F box 18 | https://assets.publishing.service.gov.uk/media/69ce15395cf899414a0bc69f/SA103S_Notes_2026.pdf, https://assets.publishing.service.gov.uk/media/69c26565cfa346b9d4704b35/SA103F_Notes_2026.pdf |
| Reverse charge: when it applies (both VAT-registered, standard or reduced rate, reported under CIS), what it excludes, end users and intermediaries (written notice; HMRC's wording), 5% disregard, invoice wording ("VAT Act 1994 Section 55A applies", "Customer to pay the VAT to HMRC"), supplier: net only, no output tax; customer: VAT to output and input on the same return, net not as a sale; Cash Accounting excluded; Flat Rate users leave RC sales out and account and reclaim on RC purchases | https://www.gov.uk/guidance/vat-domestic-reverse-charge-for-building-and-construction-services (updated 24 Sep 2020), https://www.gov.uk/guidance/vat-reverse-charge-technical-guide (updated 18 Sep 2024) |

**Not found in the sources:** how to round a deduction that is not a whole number of pence. We round down to the penny.

## Design

AI proposes, the user approves, code calculates; money is integer pence; no database (everything is in the user's
folder under `_System/CIS/`).

- **Ledger** (`packages/ledger`): `LedgerEvent.reverse_charge_vat`. `compute_vat_return` adds it to box 1 and box 4 on
  the purchases side (net already in box 7) and ignores it on the sales side (net in box 6, no output VAT). `reversal_of`
  copies it, so an undo nets to nothing. A reverse-charge purchase posts no VAT lines at all (input and output would
  cancel in 2200), which also keeps `vat_side` from mistaking its reversal for a cost being restored.
- **Settings › CIS** (`/cis`): subcontractor (status, UTR, sole trader / partnership / company), contractor (UTR,
  Accounts Office and employer references), and whether new invoices start reverse-charged.
- **Invoices and quotes** (`invoicing.py`, `pdf.py`): `cis` and `reverse_charge` on the draft, `materials` per line. The
  deduction is the business's rate on the net of every line not ticked materials (VAT never counts), rounded down; the
  PDF shows labour, materials, the deduction and *Payable after CIS*. A reverse-charge invoice moves each line's VAT to
  `reverse_charge_vat_pence`, charges none, prints HMRC's wording and posts its net only. Sending needs both VAT
  numbers. A quote (`POST /cis/quote`) is the same pricing in a QUOTE layout saved to `03 Sales/quotes/`, with no
  number taken and nothing posted.
- **Paid net of CIS** (`payments.py`, `settlement.py`): `cis_deduction_pence` on a payment. The record's amount is what
  it settles (money + deduction), so settlement is unchanged; the event posts Dr Bank (money) + Dr `1150 CIS suffered`
  / Cr Debtors, and the bank-line candidate is the money only. Capped at 30% of the CIS invoices' labour; refused on
  invoices with no CIS. The web dialog starts from the balance less the invoice's deduction.
- **Statements** (`cis.py`, `cis_readings.py`, `ai/cis_read.py`): typed in, or read from `00 Inbox` by the user's AI
  (one strict JSON schema, the document's text passed as data between markers, the same transport as receipts).
  Code checks the tax month (a 5th), which of 0/20/30% the deduction fits and the user's own rate, the printed amount
  liable and net payment, and the UTR; a failed check is a warning on the card, never a silent fix. Approving keeps the
  statement and posts nothing; each statement is reconciled against the `1150` deductions recorded for that
  contractor in that tax month.
- **Year totals**: from the statements (HMRC: "use the statements"), with the books' figure beside them, months that
  have deductions but no statement, and the sentence for the return (SA103S/SA103F boxes, or EPS for a company).
- **Reverse-charge bills**: read or typed; Dr `5300 Subcontractors` / Cr Creditors with `reverse_charge_vat` worked out
  by code (half up), so they appear in Contacts as bills to pay.
- **Contractor side**: subcontractors (UTR, status from verification, verification number; 30% needs the number),
  payments with the deduction from the subcontractor's status (Dr 5300 + VAT / Cr Bank + Cr `2220 CIS deductions
  owed`), or, against a bill already in the books, through `record_payment` (side purchase) so the bill shows paid.
  `monthly_return` builds the CIS300 lines per UTR (never negative, verification number only at 30%, nil return when
  empty, problems listed), and the export writes CSV (spreadsheet-safe text) and JSON. It says on the page, in the CSV
  and in the JSON that it is not submitted.
- **Gold generator** `evals/gold/gen_gold_cis.py`: Qwen (OpenAI-compatible, default
  `http://127.0.0.1:8000/v1/chat/completions`, `qwen3.8-27b`) names the fictional contractors and subcontractors;
  code fixes every figure and number, writes `document.txt` + `expected.json` per document, and adds distractors (a
  statement with a wrong deduction, an invoice with VAT left off and no reverse charge wording). Every file carries
  `SAMPLE — FICTIONAL COMPANY` (U+2014; `spark_gen.write_text` refuses a file without it). Resumable; `--stub`,
  `--dry-run`.
- **Audit**: every write is one line with a sentence in `audit_view.SUMMARIES` (`cis_*`, `reverse_charge_bill_posted`,
  `quote_saved`; the reader is `agent:cis-reader`).

## Tests

| Suite | Before | After | New |
| --- | --- | --- | --- |
| `services/runtime` | 1401 passed, 2 skipped | 1437 passed, 2 skipped | `test_cis.py` (36): rates and the CISR61230 worked example, rounding, tax months across year ends, deadlines, tax-year bounds; CIS invoices (labour only, travel counts, materials and VAT out, rate by status, needs CIS on), reverse-charge invoices (no VAT, box 6 only, VAT numbers, a rated line, PDF wording with pypdfium2 text, no credit note); paid net of CIS (posting, paid in full, bank-line amount, remove reverses), cap and CIS-only; statement checks, duplicates, reconciliation, year totals and missing months; the AI reading with a faked Ollama (strict schema sent, document as data, read once, approve, already-approved), wrong figures flagged not fixed, reverse-charge bill read and posted (boxes 1, 4, 7), reject; subcontractors, payments (RC, standard VAT, 30% with and without a verification number), paying a bill already posted, the CIS300 and its file, contractor switch; routes end to end; the invoice payment route with a deduction. Plus `test_security_routes.py`: the new HTTP module and the public guidance route registered |
| `packages/ledger` | 49 | 53 | reverse-charge sale and purchase boxes, reversal nets off, no negative RC VAT |
| `evals/tests` | 324 | 332 | `test_gen_gold_cis.py` (8): exact label in every file, statement and invoice figures agree with the runtime's own checks (and the distractors fail exactly the expected check), printed figures match the gold, real names re-asked, resuming, Spark defaults and dry run, unreachable Qwen |
| web e2e | not re-run before the change (owner's gate: 208) | 253 passed, 58 skipped (11.4 min, local default workers) | `cis.spec.ts` (3): subcontractor settings → CIS invoice in the form → payment net of CIS → statement → year totals; reverse-charge invoice; contractor subcontractor → payment → CIS300 saved. `/cis` added to the phone and axe page sweeps |

`ruff check .`, `ruff format --check .` and `pyright` (0 errors) are clean; `eslint .` is clean; `tsc --noEmit` reports
only the pre-existing `LayoutProps` error that `next build` generates the type for. Playwright here needed the
pre-installed headless shell linked under the build number the project's Playwright expects (outside the repo).

## Risks and what remains

- Untested against a real OneDrive, a real model reading a real statement, and HMRC (nothing is filed). The reader's
  accuracy is unmeasured: the gold generator is ready for the Spark but has run only with the stub, and no harness
  scores the reader against it yet.
- Rounding of deductions is our choice (down to the penny); the statement is the authority.
- Reverse charge applicability (customer CIS-registered, end-user notices, the 5% disregard) is the user's call; credit
  notes against reverse-charge invoices are refused; Flat Rate and Cash Accounting are explained, not modelled.
- Paying the deductions to HMRC, inactivity requests, CIS refunds for companies, CITB levy and the gross payment status
  turnover test are not built.
- Not on Android, not in Ask's facts pack, not in Books.xlsx.
- `PaymentRecord.amount_pence` now means "what it settles" for a CIS payment (money + deduction); the bank-line view
  uses the money. Code that reads `amount_pence` as money moved (none found outside `money_events`) would need the
  same care.
