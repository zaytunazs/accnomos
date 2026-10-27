# Synthetic gold set

60 fictional UK receipts/invoices used to grade the Meta extraction pipeline (Glimmer / Spark 1.3) in evals/harness.

- Generated during the hackathon by gen_gold.py (Qwen3.8-27B on our DGX Spark as a *test-data generator*; it is not part of the product runtime). Arithmetic is validated in code; invalid outputs were dropped.
- Cases: standard, mixed-rate, reduced (5%), zero-rated, exempt, cash/no VAT, no VAT number over GBP 250, full VAT invoice, sales invoice, deliberate arithmetic error, EUR reverse-charge.
- Every supplier and company is fictional. label = "SAMPLE - FICTIONAL COMPANY". Day 2 renders printed_text to receipt images (clean + messy photos) for the vision tests.

## Bank statements (`bank/`)

Four October 2026 statement CSVs for fictional businesses (label "SAMPLE - FICTIONAL COMPANY" in `expected.json`; the account numbers, customers, references and amounts are made up, while card-payment payees such as Screwfix or Shell are real UK merchants named only as they would appear on a statement) in the three layouts the bank reader handles (see `packages/ledger/src/accnomos_ledger/bank.py`): `barclays.csv` and `monzo.csv` (one signed Amount column), `starling.csv` (signed amount + counter party + balance), `tide.csv` (Paid in / Paid out). Hand-written, not generated. `expected.json` lists the posted ledger events they are matched against and, per line, the expected match (exact/suggested) or the suggested action for an unmatched line. Graded by `packages/ledger/tests/test_bank_gold.py` and `services/runtime/tests/test_bank_gold.py`. Column layouts are modelled on the banks' public export formats; check them against a real export before relying on the bank name.
