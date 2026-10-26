# Synthetic gold set

60 fictional UK receipts/invoices used to grade the Meta extraction pipeline (Glimmer / Spark 1.3) in evals/harness.

- Generated during the hackathon by gen_gold.py (Qwen3.8-27B on our DGX Spark as a *test-data generator*; it is not part of the product runtime). Arithmetic is validated in code; invalid outputs were dropped.
- Cases: standard, mixed-rate, reduced (5%), zero-rated, exempt, cash/no VAT, no VAT number over GBP 250, full VAT invoice, sales invoice, deliberate arithmetic error, EUR reverse-charge.
- Every supplier and company is fictional. label = "SAMPLE - FICTIONAL COMPANY". Day 2 renders printed_text to receipt images (clean + messy photos) for the vision tests.
