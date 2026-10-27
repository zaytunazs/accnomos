# ledger2 gold set

Fictional test documents for part payments, supplier credit notes and bank re-exports. Every JSON carries
`label: "SAMPLE — FICTIONAL COMPANY"`; no real business, person or account appears.

- `credit_notes/` (40): supplier credit notes. Lines are negative, with `original_invoice_number`, a VAT rate and VAT per line.
- `part_paid/` (40): sales invoices with `payments[]` and an `expected` block (`paid`, `outstanding`, `status`). The case is in the file name:
  `part` (two payments settle it), `part_open` (still owing), `over` (overpaid, so `outstanding` is negative), `exact`.
- `bank_pairs/` (10): `NNN_a.csv` is a statement, `NNN_b.csv` an overlapping re-export, `NNN_meta.json` says how many
  rows overlap (`overlap`: the last rows of a are the first rows of b), `expected_unique_lines` and `closing_balance`.
  The CSVs have no label line by design (they must parse as a real bank export); their meta files carry the label.

Made by Qwen on the local Spark with `evals/gold/gen_gold2.py`: Qwen invents the businesses and lines, code checks every
VAT figure, total, payment case and bank balance, and works out the overlap, so the expected answers are right by
construction. Tests: `evals/tests/test_gold_ledger2.py` (integrity) and `services/runtime/tests/test_gold_ledger2_runtime.py`.
