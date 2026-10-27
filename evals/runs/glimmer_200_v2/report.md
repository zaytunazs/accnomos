# Extraction eval: local / muse-glimmer:30b

Docs: 200 | errors: 0 | messy: False | all fields correct: 85% | mean 17.72 s (max 41.69 s)

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
| status | 88% |

## Per gold case

| Case | n | All fields | Status | Errors |
|---|---:|---:|---:|---:|
| cash_no_vat | 5 | 100% | 100% | 0 |
| credit_note | 10 | 90% | 90% | 0 |
| edge_foreign_gbp | 3 | 100% | 100% | 0 |
| edge_handwritten | 2 | 0% | 50% | 0 |
| edge_multi_rate | 3 | 0% | 0% | 0 |
| edge_reverse_charge | 2 | 100% | 100% | 0 |
| edge_torn_faded | 2 | 100% | 100% | 0 |
| edge_zero | 3 | 100% | 100% | 0 |
| exempt | 5 | 100% | 100% | 0 |
| foreign | 5 | 60% | 100% | 0 |
| full_invoice | 5 | 100% | 100% | 0 |
| mixed | 6 | 83% | 83% | 0 |
| no_vat_number | 6 | 67% | 67% | 0 |
| pi_merchant | 12 | 67% | 75% | 0 |
| pi_software | 8 | 88% | 88% | 0 |
| pi_subcontractor | 10 | 70% | 70% | 0 |
| r_cafe | 10 | 100% | 100% | 0 |
| r_fuel | 10 | 100% | 100% | 0 |
| r_parking | 8 | 100% | 100% | 0 |
| r_trade | 12 | 100% | 100% | 0 |
| reduced | 6 | 100% | 100% | 0 |
| sales | 30 | 67% | 67% | 0 |
| sales_invoice | 5 | 100% | 100% | 0 |
| standard | 11 | 100% | 100% | 0 |
| utility | 15 | 100% | 100% | 0 |
| zero | 6 | 83% | 100% | 0 |

## Verifier: ollama:muse-glimmer:30b

Docs: 200 | passed checks (so verified): 177 | verified OK: 177 | verifier errors: 0 | all fields agree: 88% | mean 4.32 s

| Doc outcome (graded against gold) | Docs |
|---|---:|
| Agreed, Extractor right (confirmed) | 154 |
| Agreed, Extractor wrong (missed) | 2 |
| Disagreed, Extractor wrong (caught) | 3 |
| Disagreed, Extractor right (false alarm) | 18 |

| Field | Agree | Extractor right | Verifier right | Agreed, both wrong | Disagreed, Extractor wrong | Disagreed, Extractor right |
|---|---:|---:|---:|---:|---:|---:|
| supplier_name | 100% | 100% | 100% | 0 | 0 | 0 |
| supplier_vat_number | 100% | 99% | 99% | 1 | 0 | 0 |
| date | 99% | 99% | 100% | 0 | 1 | 0 |
| net_total | 89% | 98% | 88% | 1 | 2 | 18 |
| vat_total | 96% | 98% | 97% | 1 | 2 | 5 |
| gross_total | 90% | 100% | 90% | 0 | 0 | 17 |

Proposed / needs-a-look decision: 98% without the verifier, 88% with it.
