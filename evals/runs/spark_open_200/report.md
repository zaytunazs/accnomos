# Extraction eval: key / meta-models/muse-spark-open

Docs: 200 | errors: 0 | messy: False | all fields correct: 91% | mean 12.9 s (max 27.45 s)

## Accuracy per field

| Field | Accuracy |
|---|---:|
| supplier_name | 100% |
| vat_number | 98% |
| date | 100% |
| net_total | 98% |
| vat_total | 98% |
| gross_total | 100% |
| line_count | 100% |
| side | 100% |
| status | 94% |

## Per gold case

| Case | n | All fields | Status | Errors |
|---|---:|---:|---:|---:|
| cash_no_vat | 5 | 100% | 100% | 0 |
| credit_note | 10 | 70% | 70% | 0 |
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
| pi_software | 8 | 88% | 88% | 0 |
| pi_subcontractor | 10 | 90% | 90% | 0 |
| r_cafe | 10 | 100% | 100% | 0 |
| r_fuel | 10 | 90% | 100% | 0 |
| r_parking | 8 | 100% | 100% | 0 |
| r_trade | 12 | 100% | 100% | 0 |
| reduced | 6 | 83% | 83% | 0 |
| sales | 30 | 97% | 97% | 0 |
| sales_invoice | 5 | 100% | 100% | 0 |
| standard | 11 | 100% | 100% | 0 |
| utility | 15 | 93% | 93% | 0 |
| zero | 6 | 67% | 83% | 0 |

## Verifier: baseten:meta-models/muse-spark-open

Docs: 200 | passed checks (so verified): 178 | verified OK: 178 | verifier errors: 0 | all fields agree: 95% | mean 8.18 s

| Doc outcome (graded against gold) | Docs |
|---|---:|
| Agreed, Extractor right (confirmed) | 166 |
| Agreed, Extractor wrong (missed) | 3 |
| Disagreed, Extractor wrong (caught) | 1 |
| Disagreed, Extractor right (false alarm) | 8 |

| Field | Agree | Extractor right | Verifier right | Agreed, both wrong | Disagreed, Extractor wrong | Disagreed, Extractor right |
|---|---:|---:|---:|---:|---:|---:|
| supplier_name | 98% | 100% | 100% | 0 | 0 | 4 |
| supplier_vat_number | 100% | 99% | 99% | 1 | 0 | 0 |
| date | 99% | 99% | 100% | 0 | 1 | 0 |
| net_total | 98% | 98% | 98% | 2 | 1 | 2 |
| vat_total | 99% | 98% | 98% | 2 | 1 | 1 |
| gross_total | 98% | 99% | 98% | 0 | 1 | 3 |

Proposed / needs-a-look decision: 98% without the verifier, 94% with it.
