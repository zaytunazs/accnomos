# CIS reader eval

Model `muse-glimmer:30b` at `http://localhost:11434`; 2026-10-28T13:10:49+00:00. Code under test: `app.ai.cis_read.read_cis_document` + `app.cis_readings.from_reading` (the same prompt, schema and code-side checks production uses).

- Documents: **120** (120 answered, **0 refusals**, 0.0%)
- Fully exact (every field right and the failing checks exactly `expect_check_fail`): **92.5%** of all documents (a refusal counts as wrong)
- Checks exactly right: 93.3% of answered documents
- Latency: mean 14.637 s, p50 14.737 s, p95 16.076 s, max 16.487 s (total 1756.4 s)

## Per-field accuracy (answered documents that have the field; refusals count as wrong nowhere here)

| Field | Scored | Correct | Accuracy |
|---|---:|---:|---:|
| kind | 120 | 118 | 98.3% |
| supplier_name | 60 | 56 | 93.3% |
| supplier_vat_number | 60 | 56 | 93.3% |
| invoice_number | 60 | 57 | 95.0% |
| invoice_date | 60 | 57 | 95.0% |
| net | 60 | 56 | 93.3% |
| vat_rate | 60 | 54 | 90.0% |
| reverse_charge_vat | 60 | 57 | 95.0% |
| reverse_charge_wording | 120 | 118 | 98.3% |
| contractor_name | 60 | 60 | 100.0% |
| subcontractor_name | 60 | 60 | 100.0% |
| subcontractor_utr | 60 | 60 | 100.0% |
| tax_month_end | 60 | 60 | 100.0% |
| gross_amount | 60 | 58 | 96.7% |
| materials | 60 | 59 | 98.3% |
| amount_liable | 60 | 59 | 98.3% |
| deduction | 60 | 59 | 98.3% |
| net_paid | 60 | 59 | 98.3% |

## Per-kind accuracy (refusals count as wrong)

| Kind | Docs | Answered | Fully exact | Accuracy | Checks exact (of answered) |
|---|---:|---:|---:|---:|---:|
| cis_statement | 60 | 60 | 58 | 96.7% | 98.3% |
| reverse_charge_invoice | 60 | 60 | 53 | 88.3% | 88.3% |

## Worst 10 misses

| Id | Kind | Wrong fields | Checks want -> got | Problems |
|---|---|---|---|---|
| R030 | reverse_charge_invoice | invoice_date, invoice_number, net, reverse_charge_wording, supplier_name, supplier_vat_number, vat_rate | ['RC_WORDING'] -> [] | No invoice date read; No net amount read; The VAT rate was not 20% or 5%; No sup |
| R040 | reverse_charge_invoice | invoice_date, invoice_number, kind, net, supplier_name, supplier_vat_number, vat_rate | ['RC_WORDING'] -> [] | This does not look like a CIS statement or a reverse-charge invoice |
| R060 | reverse_charge_invoice | invoice_date, invoice_number, kind, net, supplier_name, supplier_vat_number, vat_rate | ['RC_WORDING'] -> [] | This does not look like a CIS statement or a reverse-charge invoice |
| R010 | reverse_charge_invoice | reverse_charge_vat, supplier_name, supplier_vat_number, vat_rate | ['RC_WORDING'] -> [] | The VAT rate was not 20% or 5%; No supplier name read |
| S031 | cis_statement | amount_liable, deduction, gross_amount, materials, net_paid | [] -> [] | The gross amount or the deduction was not read |
| R020 | reverse_charge_invoice | reverse_charge_vat, reverse_charge_wording, vat_rate | ['RC_WORDING'] -> [] | The VAT rate was not 20% or 5% |
| R050 | reverse_charge_invoice | reverse_charge_vat, vat_rate | ['RC_WORDING'] -> [] | The VAT rate was not 20% or 5% |
| R016 | reverse_charge_invoice | net | [] -> ['RC_VAT'] |  |
| S019 | cis_statement | gross_amount | [] -> ['LIABLE', 'NET_PAID', 'RATE'] |  |

Refusals (the model gave nothing usable):


How it is scored: names fuzzily (>= 0.8, as in `harness.run_extraction`), amounts within a penny, UTRs digits-only, VAT numbers normalised by `app.checks.normalise_vat_number`; on statements the CIS settings take the payment status from the gold `rate` (0/20/30% -> gross/net/unverified), on invoices the gold `rate` is the VAT rate.
