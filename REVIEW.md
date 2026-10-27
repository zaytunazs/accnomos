# Review: ledger2 gold tests

## What was built
- `evals/tests/test_gold_ledger2.py` (92 tests): label on every file; credit-note lines negative, VAT = round(net x rate) per line (1p tolerance), totals add up; part-paid `expected` agrees with its payments and case; bank pairs (b's first `overlap` rows equal a's last, balances run, unique lines, closing balance); CSVs have no label line, metas do.
- `services/runtime/tests/test_gold_ledger2_runtime.py` (90 tests, ~6 s, fake storage): (a) 40 invoices created and sent for their gross on their date, payments posted through `POST /invoices/{n}/payments`, paid / outstanding / status checked against `expected`, overpaid excess equals the contact credit; (b) 10 pairs imported a then b through `Books.import_bank_csv`, unique stored lines and the second import's new lines checked, re-import is a no-op; (c) 40 credit notes proposed and approved (as `test_payments.py` does) beside a whole-pound £5,000 + £1,000 VAT bill in the same quarter.
- `evals/gold/ledger2/README.md`.

## What I verified
- `python -m pytest evals/tests/test_gold_ledger2.py -q` : 92 passed.
- `python -m pytest services/runtime/tests/test_gold_ledger2_runtime.py -q` : 90 passed.
- `python -m pytest services/runtime packages evals -q` : see the final counts in the hand-off message.
- `ruff check` and `ruff format` clean on the new files.

## Bugs found
None; no xfail needed. One expectation worth knowing: box 7 is rounded down on the net total of the period, so a credit note of 12.50 takes £5,000 to £4,987 (not £4,987.50 or £4,988). The test asserts `(500000 - |net pence|) // 100`.
Not a bug but a mapping: for overpaid invoices the money object caps `paid_pence` at the gross and reports the excess in `overpaid_pence`; the gold's `paid` is the sum of the payments and `outstanding` is negative.

## What remains
- Gold invoices all use 20% lines, so zero-rated and 5% sales lines are untested here; credit notes do cover 0/5/20.
- Credit notes are posted through the approve path only; matching them to the original supplier bill is not covered.
- Bank pairs test import de-dup, not reconciliation matching.
