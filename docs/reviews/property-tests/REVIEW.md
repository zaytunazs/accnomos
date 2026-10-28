# Review: `claude/property-tests`

Property-based and invariant tests for the money maths, with [Hypothesis](https://hypothesis.readthedocs.io/).
Inputs are built from the real Pydantic models (`LedgerEvent`, `Line`, `BankLine`, `LineIn`, `InvoiceDraft`,
`ExtractedDoc`, `Proposal`, `PaymentRecord`, `CreditUse`). Every property is checked through the real functions and
routes' actions, not re-implementations. The properties found **five real bugs**. Each one has a minimal failing
example test and the smallest fix I could make.

## Where the tests are

| File | What it holds | Default run |
|---|---|---|
| `packages/ledger/tests/test_properties.py` | 12 properties: event balance, VAT 9-box, bank amounts and CSVs, matching | 3.7 s |
| `services/runtime/tests/test_properties_money.py` | 18 properties: invoices, journals, undo, repairs, settlement, aged debtors, VAT periods, BST/GMT | 3.6 s |
| `services/runtime/tests/test_properties_books.py` | a stateful machine: random sequences of real actions on fake storage, invariants after every step | 4.0 s (40 runs × 25 steps) |
| `services/runtime/tests/test_property_regressions.py` | the minimal examples of the bugs below, as plain tests | 2.0 s |
| `packages/ledger/tests/test_vat.py` | one more minimal example (bug 1) | — |

The suite adds **about 13 s** in total (ledger 3.7 s, runtime 9.7 s, measured on the 4-core session machine, 28 Oct
2026). Hypothesis was already a dev dependency of `packages/ledger`; it is now one of `services/runtime` too
(`uv.lock` updated).

Deeper runs, on request:

```bash
HYPOTHESIS_PROFILE=deep python -m pytest -q tests/test_properties.py         # packages/ledger: 2,000 examples each, ~60 s
HYPOTHESIS_PROFILE=deep python -m pytest -q tests/test_properties_money.py   # services/runtime: ~60 s
python -m pytest -q -m slow tests/test_properties_books.py                   # services/runtime: 150 runs x 40 steps, ~27 s
```

`slow` is a marker that is registered in `services/runtime/tests/conftest.py`. Slow tests are skipped unless `-m slow`
is passed. Before writing this review I also ran the state machine for 600 runs × 40 steps several times. It found
the bugs below. After the fixes it ran clean: about 4,800 approvals, 815 undos, 334 payment removals, 286 credit-note
voids, 219 refunds, 145 credit applications and 109 bank lines posted as payments.

## Properties

**Ledger (`accnomos_ledger`)**
- Every set of balanced lines is a valid `LedgerEvent`. Any imbalance is refused. Fractional pence are refused.
  Debits and credits stay `int` through the JSON round trip that the books folder uses.
- An event plus its reversal puts every account back to zero.
- VAT 9-box: box 3 = box 1 + box 2, and box 5 = |box 3 − box 4|. Boxes 1–5 are to the penny and boxes 6–9 are whole
  pounds. Every box agrees with the events dated in the period, including credit notes with their signs. Undoing
  everything empties every box. Two back-to-back periods hold exactly what one period spanning both holds. The HMRC
  body's floats read back to the same 2 dp `Decimal`.
- Bank statements: every way a UK bank prints an amount (`£1,234.50`, `(£12.00)`, `12.00 DR`, `12.00CR`, `-…`) reads
  back to the same pence. A Tide-style export reads back line for line, with unique ids even for repeated rows.
- Matching: a bank line is never matched twice. An event is never paid by two lines, and an event that a line already
  pays is never offered again. Resolved lines are never suggested. Each match is within 1p, with the right sign.
  `reconciled_to` is the last day before anything is open.

**Runtime, one function at a time**
- Mixed-rate invoices: each line's net and VAT are rounded half up. The totals and the VAT summary are the exact sums
  of the lines. Rounding per line is never more than ½p a line away from the exact VAT.
- A sent invoice posts a balanced sale: Debtors = total, and VAT control = VAT. Its boxes are correct, and code O
  stays out of box 6. Crediting the whole invoice zeroes every account and box.
- `draft_journal` balances in whole, non-negative pence for any extracted document (purchase, receipt, sale, supplier
  credit note printed negative, any payment method or VAT number). `build_event` posts it, with net + VAT = gross.
- Posting then undoing returns every account and every box to zero. Undoing in a later period nets across the two
  periods.
- Repairs: a VAT-inclusive total read as the net, or VAT added on top of an inclusive total, is repaired to within 1p.
  A correct reading is left alone. A bank line's gross split into net + VAT loses no pence.
- Settlement (part payments, overpayments, matched bank lines, credit notes, applies, refunds): no invoice is ever
  settled beyond its total. Every recorded payment is accounted for to the penny. Credits never go negative.
- Aged debtors: the buckets add up to the row totals, which add up to the table. The table equals what is owed. The
  debtor control account equals the aged total less unused customer credits.
- Dates: every day falls in exactly one VAT period of whole months for all three staggers and monthly returns. The
  periods are back to back. `period_id` ↔ `period_from_id` round-trips. February periods end on the 29th in leap years
  (2000–2099). The return is due one month and seven days after the period. Across BST and GMT, the audit window holds
  exactly the instants whose London day is in it, and it reads the UTC-month file each instant was written to. Fixed
  cases cover both clock changes in 2026 and a quarter boundary at 23:30 UTC.

**Runtime, the whole books (stateful)**

The steps are: approve purchases (paid or on account), sales and supplier credit notes (linked to the bill or not);
send invoices with mixed VAT codes; record part, exact and over payments; Mark paid; issue and void credit notes;
apply and refund credits; remove payments; import bank lines and match them (exact, 1p short, 1p over, half, double);
post a bank line as a payment or unmatch it; undo; void invoices. A step the app refuses with its own 400/409 errors
is fine. Anything else fails the test. After **every** step:
- every event balances, and the trial balance balances, in integer pence;
- nothing is settled beyond its total, and every recorded payment is accounted for;
- **1100 Debtors = aged debtors − unused customer credits + what bank lines matched straight to invoices paid**, and the
  same for 2100 Creditors. A direct match posts nothing until *Post as payment*, so the control account still holds
  that money. The invariant says so explicitly;
- **−2200 VAT control = box 1 − box 4** over all time, and the 9-box identities hold;
- each sent invoice's file (status, paid, balance) agrees with the ledger.

The Books.xlsx rebuild is switched off in this test, because it is a convenience copy with its own tests. The clock
and the uuids are pinned per run. Without that, events posted in the same second are ordered by random ids and a
failure would not replay. (That is how the first two long-run failures were lost.)

## Bugs found and fixed

1. **Undoing a VAT-only sale counted in box 4** (`packages/ledger/src/accnomos_ledger/vat.py`). A sales invoice with
   net £0.00 and some VAT posts no Sales line. Its undo (Dr VAT control / Cr Debtors) gave `vat_side` nothing to place
   it on the sales side, so it was read as the undo of a supplier credit note. Box 4 went up by the VAT, instead of box
   1 going down. Fix: a reversal with no Sales line that touches 1100 Debtors is on the sales side. Example:
   `test_undoing_a_vat_only_sale_nets_off_box_1_not_box_4`. Found by
   `test_posting_then_undoing_returns_every_account_and_box_to_zero` (deep profile).
2. **Unmatching a bank line could strand a refunded or applied credit** (`app/books.py`, `app/credits.py`). A bank
   line that overpays an invoice leaves a credit. Once that credit was refunded (posted Dr Debtors / Cr Bank),
   *Unmatch* on the Bank page took the credit away and had no guard. The refund stayed in the ledger with nothing behind
   it, so 1100 Debtors and the contact's balance disagreed. (*Remove* on the Payments panel already refused this, but
   the Bank page did not.) The credit need not be the line's own: settlement runs in date order, so a line matched
   within a penny and dated before a recorded payment leaves that payment's money over as a credit. Fix:
   `credits.stranded()` settles the books as they would be after the change and refuses (409) when any use would take
   less than it took. Example: `test_a_bank_line_whose_credit_was_refunded_cannot_be_unmatched`.
3. **The same through credit notes, payments and undo** (`app/credit_notes.py`, `app/payments.py`, `app/approve.py`).
   A credit note, a payment or a supplier credit note dated before a recorded payment pushes that payment's money into
   a credit. Voiding the credit note, removing the earlier payment, or undoing the supplier credit note then took that
   credit back after it had been refunded or applied. The existing guards only looked at the item's own credit. The
   same `stranded()` check now runs on all three. Examples:
   `test_a_credit_note_whose_displaced_credit_was_refunded_cannot_be_voided`,
   `test_removing_a_payment_cannot_strand_another_payments_refunded_credit` and
   `test_undoing_a_supplier_credit_note_cannot_strand_a_refunded_credit`.
4. **Invoice files with a stale status** (`app/payments.py`). `sync_invoices` refreshed only the invoices named by the
   change. A credit applied to one invoice can come from another invoice's payment, so a credit note on the second
   could leave the first reading "sent" when it was paid, and so chased by a reminder, or "paid" when it was owed, and
   so never chased. Fix: other sent invoices with money against them, or with a stored copy, are refreshed too. Only
   changed files are written. Example: `test_every_invoice_file_is_refreshed_when_credit_applied_to_it_changes`.
5. **A 1p bank line could vanish** (`app/settlement.py`). A line matched to a document that a backdated credit note had
   since settled was "within a penny" of the £0.00 owed. It therefore paid nothing and left no credit. Fix: when
   nothing is owed, the whole line is money over. Example:
   `test_a_penny_bank_line_for_a_document_already_settled_is_left_as_a_credit`.

## Not changed (noted)

- **The penny rule is judged at the line's date, not at match time.** A line within 1p of what was owed on its own
  date pays that in full. When a recorded payment dated later was meant to pay the last penny, that payment's penny
  becomes a credit. This is by design (the matcher allows 1p of rounding). The stranding guard now covers it.
- `routes_vat.py` counts events per box with `reverses_sale`, which still files a VAT-only sale's undo under box 4.
  This affects the *count* shown beside the box only, never an amount.
- *Post as payment* on a line that was 1p short records the line's amount, so the invoice moves from paid (within a
  penny) to 1p owed. This is documented in `payment_from_bank_line` and left as is.
- Mail intake names saved files by the UTC day (`app/intake.py`), so a receipt arriving at 00:30 BST on the 1st is
  named for the 31st. This affects file names only. Ledger dates come from the document.
- `LedgerEvent` is lax about whole floats (`1.0` becomes `1`). Fractional pence are refused, and stored events are
  always integers.

## Also fixed: a flaky test

`test_sample_books.py::test_a_second_press_while_running_or_after_is_the_same_run` failed about 1 run in 8, on `main`
as well as on this branch. Loading the sample books set its in-memory status to "done" and then wrote the file. A
page polling in between saw "done" before the last write, which breaks the rule in the code's own comment ("a page
that sees 'done' must find every write finished"). `app/sample_books.py` now writes the "done" file first and then
updates the status in memory. Afterwards the test passed 10 runs out of 10.

## Gates

Run on this branch on 28 Oct 2026:

- `cd services/runtime && python -m pytest -q`: **1,251 passed, 2 skipped** (the `slow` state machine, and one skip
  already there) in 297 s. Before the branch it was 1,226 passed, 1 skipped, in 285 s.
- `cd packages/ledger && python -m pytest -q`: **49 passed** (36 before).
- `ruff check . && ruff format --check .` (ruff 0.17.3): clean.
- `pyright services/runtime/app` (1.1.414): 0 errors.
