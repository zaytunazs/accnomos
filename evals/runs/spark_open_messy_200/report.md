# Extraction eval: key / meta-models/muse-spark-open

Docs: 200 | errors: 0 | messy: True | all fields correct: 93% | mean 13.12 s (max 40.0 s)

## Accuracy per field

| Field | Accuracy |
|---|---:|
| supplier_name | 100% |
| vat_number | 98% |
| date | 100% |
| net_total | 99% |
| vat_total | 99% |
| gross_total | 100% |
| line_count | 98% |
| side | 100% |
| status | 97% |

## Per gold case

| Case | n | All fields | Status | Errors |
|---|---:|---:|---:|---:|
| cash_no_vat | 5 | 100% | 100% | 0 |
| credit_note | 10 | 100% | 100% | 0 |
| edge_foreign_gbp | 3 | 100% | 100% | 0 |
| edge_handwritten | 2 | 0% | 100% | 0 |
| edge_multi_rate | 3 | 100% | 100% | 0 |
| edge_reverse_charge | 2 | 100% | 100% | 0 |
| edge_torn_faded | 2 | 100% | 100% | 0 |
| edge_zero | 3 | 100% | 100% | 0 |
| exempt | 5 | 100% | 100% | 0 |
| foreign | 5 | 60% | 100% | 0 |
| full_invoice | 5 | 100% | 100% | 0 |
| mixed | 6 | 83% | 83% | 0 |
| no_vat_number | 6 | 67% | 67% | 0 |
| pi_merchant | 12 | 100% | 100% | 0 |
| pi_software | 8 | 88% | 100% | 0 |
| pi_subcontractor | 10 | 100% | 100% | 0 |
| r_cafe | 10 | 100% | 100% | 0 |
| r_fuel | 10 | 100% | 100% | 0 |
| r_parking | 8 | 88% | 100% | 0 |
| r_trade | 12 | 100% | 100% | 0 |
| reduced | 6 | 100% | 100% | 0 |
| sales | 30 | 100% | 100% | 0 |
| sales_invoice | 5 | 100% | 100% | 0 |
| standard | 11 | 91% | 100% | 0 |
| utility | 15 | 87% | 87% | 0 |
| zero | 6 | 67% | 83% | 0 |

## Verifier: baseten:meta-models/muse-spark-open

Docs: 200 | passed checks (so verified): 178 | verified OK: 178 | verifier errors: 0 | all fields agree: 98% | mean 7.99 s

| Doc outcome (graded against gold) | Docs |
|---|---:|
| Agreed, Extractor right (confirmed) | 172 |
| Agreed, Extractor wrong (missed) | 3 |
| Disagreed, Extractor wrong (caught) | 0 |
| Disagreed, Extractor right (false alarm) | 3 |

| Field | Agree | Extractor right | Verifier right | Agreed, both wrong | Disagreed, Extractor wrong | Disagreed, Extractor right |
|---|---:|---:|---:|---:|---:|---:|
| supplier_name | 99% | 100% | 100% | 0 | 0 | 2 |
| supplier_vat_number | 100% | 99% | 99% | 1 | 0 | 0 |
| date | 100% | 100% | 100% | 0 | 0 | 0 |
| net_total | 99% | 99% | 98% | 2 | 0 | 1 |
| vat_total | 100% | 99% | 99% | 2 | 0 | 0 |
| gross_total | 100% | 100% | 100% | 0 | 0 | 0 |

Proposed / needs-a-look decision: 98% without the verifier, 97% with it.
