# Review: part payments, overpayments and credit notes (`claude/part-payments-3`)

## What was built

**Ledger (`packages/ledger`)**
- `LedgerEvent.credits` (optional): a credit note is a `reversal` with no `reverses` and `credits` = the sale/purchase
  it reduces (`is_credit_note`). Undo of an entry is unchanged.
- `vat_side(ev)` places any event on the sales/purchases side with a sign from its lines alone: undo of a sale or a
  customer credit note −1, undo of a credit note +1 (Sales credited / expense or VAT debited again). `compute_vat_return`
  and `app/facts.py` use it. Payment events (no VAT codes) never reach the return.

**Runtime**
- `app/settlement.py` (pure): allocates, oldest first, credit notes → the invoice they credit; recorded payments →
  the split the user chose; bank lines matched straight to documents on the Bank page → in match order (within 1p a
  document counts as paid in full, as the matcher allows). Anything over is a `Credit` on the contact. Per document:
  `paid`, `credited`, `outstanding`, status open | part_paid | paid | overpaid.
- `app/payments.py`: `record_payment` checks the split against what is still owed (one contact per payment), posts a
  `bank` event by code — sale: Dr 1200 Bank (or 1210 Cash) / Cr 1100 Debtors; purchase: Dr 2100 Creditors / Cr 1200
  Bank — saves it in `_System/Payments/payments.json`, and if a statement line was chosen matches the line to that
  event. `remove_payment` reverses the event (and unmatches its line), or unmatches a Bank-page match.
  `sync_invoices` refreshes the copy on the invoice file (`paid_pence`, `credited_pence`, `balance_pence`,
  `payment_status`, status sent ↔ paid); called after payments, credit notes and every bank match/unmatch.
- `invoicing.mark_paid` now records a payment (the balance by default, or `amount_pence`, or the bank line's amount).
  `void_invoice` refuses while payments, a matched line or issued credit notes stand, with a message naming them;
  a paid invoice can be voided once they are removed. Invoices marked paid by the old Mark paid (no amount) still count
  as paid; *Remove* (`marked`) puts them back to sent.
- `app/credit_notes.py`: CN-0001… (`_System/Invoicing/credit_sequence.json`) from a sent invoice, whole or chosen lines
  and quantities, capped at what is left per line; priced like the invoice; posted at once (route needs
  `confirm: true`) as Dr 4000 Sales per VAT code / Dr 2200 VAT / Cr 1100 Debtors on the credit note's own date. PDF is
  `render_invoice(..., credit_for=)`; email reuses the invoice mail path; void appends a reversal.
- Intake: `doc_type: "credit_note"` added to the extraction schema and prompt; `draft_journal` turns the purchase
  journal round (amounts taken as positive, so negative-printed credit notes work); `approve` posts it as a reversal;
  Autopilot never approves or learns from one; undo works on it; the business's own credit note read from the inbox
  fails a new `OWN_CREDIT_NOTE` check.
- Contacts: documents include credit notes (statement "Credit note" / "Supplier credit note" lines) and one line per
  payment; totals use outstanding amounts plus `customer_credit_pence` / `supplier_credit_pence`; ageing uses what is
  still owed and days past the due date (invoice's due date, else `Contact.terms_days`, else 30 days), with a new
  `current` (not yet due) bucket. `/reports/aged`, Books.xlsx and the Home dashboard follow.
- Routes: `POST /invoices/{n}/payments`, `DELETE /invoices/{n}/payments/{id}`, `POST /invoices/{n}/credit-notes`,
  `GET /credit-notes`, `GET|POST /credit-notes/{n}[/pdf|/send|/void]`, `GET|POST /payments`, `GET /payments/open`,
  `DELETE /payments/{id}`. Invoice rows carry `money` (payments, credit notes, balance) worked out on every read.
  Audit summaries for every new kind. Fixed the pre-existing `test_paths` failure ("07 Reports" literal in audit_view).

**Web**: invoice rows show part paid / balance; *Record payment* dialog (amount, date, bank or cash, statement line);
*Payments and history* lists payments with *Remove* / *Unmatch*; *Create credit note* (whole or chosen lines, behind a
tick); *Credit notes* list with PDF, email behind a tick and void. Contacts statement marks payment/credit lines and
shows credit on account; aged tables (Contacts, Reports) gain *Not yet due* and say "days late".
**Android**: invoice detail shows Paid / Credited / Balance from `money`; the aged card handles `current`.

## What I verified

Environment: `source .v/bin/activate`, `PYTHONPATH` set to the **absolute** paths of this worktree's
`packages/ledger/src:packages/connectors/src:services/runtime` (a relative PYTHONPATH breaks
`test_security_routes`' subprocess probe, which runs from `services/runtime`).

- `python -m pytest services/runtime packages -q` → **1026 passed, 1 skipped** (baseline on this branch before the work:
  1008 passed, 1 failed — the `test_paths` literal — 1 skipped). New: `services/runtime/tests/test_payments.py` (15 tests:
  part payment, removal/reversal, void refused while paid then allowed, legacy marked-paid, one bank line paying two
  invoices, one recorded payment split from a bank line, split checks, overpayment credit, paying a bill, supplier
  credit note posted as reversal + undo, credit note VAT in the following quarter, credit note on a paid invoice and
  its void, drafts refused, routes incl. confirm/422/400, statement route), ageing-by-due-date tests in
  `test_contacts.py`, `vat_side` test in `packages/ledger/tests/test_vat.py`. Updated by design: aged buckets in
  `test_contacts.py`/`test_reports.py`, Mark paid now posting in `test_invoicing.py`, demo seed 40 → 41 events.
- `ruff check services/runtime packages` → all checks passed; `ruff format` applied.
- `pyright` → 5 errors, all in untouched code (`audit_view.py` 328–336, `reports.py` 341, `routes_reports.py` 122).
- Web: `pnpm exec eslint .` clean; `pnpm run build` OK; `pnpm exec tsc --noEmit` clean (after the build generates
  `LayoutProps`).
- E2E (`E2E_WEB_PORT=3300 E2E_RUNTIME_PORT=8981 E2E_RELAY_PORT=8989`, `pnpm run e2e:build` then `playwright test`):
  **183 passed, 2 failed** of 185. New `e2e/invoice-payments.spec.ts` passes. Failures: `site-health.spec.ts:10`
  hard-codes `127.0.0.1:3100` in its expected text (fails on any other port; not touched); `audit.spec.ts:4` failed under
  full-suite load and **passes alone** (it is already marked slow for that reason).
- Not run: Flutter (`flutter analyze`/`test` — no SDK here); nothing against a real OneDrive, mailbox or PDF viewer.

## What remains (honest)

- A credit on a contact (overpayment, credit note over what was owed) is shown but cannot be applied to another
  invoice or refunded in the app.
- Bank-page matches of a line straight to invoices still post nothing; only recorded payments move 1200 Bank / 1100
  Debtors in the ledger. If a recorded payment and a Bank-page match both cover one invoice, the second is an
  overpayment (no guard).
- Supplier credit notes from intake are not linked to a bill (they are a credit on the supplier); credit notes are not
  offered as bank matches, so supplier refunds cannot be matched to them. Extraction eval not re-run with the new type.
- Paying bills has no web/Android screen (runtime `POST /payments` only); payment terms (`terms_days`) settable via
  `PUT /contacts/{id}` only; Android cannot record payments or make credit notes.
- Credit notes only from a sent invoice, with the invoice's own lines; PDF/email never tried for real.
- Old "Mark paid" invoices count as paid on Invoices/Home but open in Contacts/ageing (as before this change).
- `payments.json` is rewritten whole (last write wins). The invoice file's payment copy is refreshed by payments,
  credit notes and bank matches only; the figures shown are always recomputed.
- Docs updated: README (Sales invoices / Contacts rows and feature table), `docs/REMAINING.md`, `docs/HONESTY.md`,
  `docs/ARCHITECTURE.md` (new files).
