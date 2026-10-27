# Extraction eval: local / muse-glimmer:30b

Docs: 200 | errors: 0 | messy: True | all fields correct: 80% | mean 24.14 s (max 111.3 s)

## Accuracy per field

| Field | Accuracy |
|---|---:|
| supplier_name | 100% |
| vat_number | 98% |
| date | 100% |
| net_total | 97% |
| vat_total | 97% |
| gross_total | 99% |
| line_count | 100% |
| side | 100% |
| status | 83% |

## Per gold case

| Case | n | All fields | Status | Errors |
|---|---:|---:|---:|---:|
| cash_no_vat | 5 | 100% | 100% | 0 |
| credit_note | 10 | 90% | 90% | 0 |
| edge_foreign_gbp | 3 | 100% | 100% | 0 |
| edge_handwritten | 2 | 0% | 50% | 0 |
| edge_multi_rate | 3 | 0% | 0% | 0 |
| edge_reverse_charge | 2 | 50% | 50% | 0 |
| edge_torn_faded | 2 | 100% | 100% | 0 |
| edge_zero | 3 | 100% | 100% | 0 |
| exempt | 5 | 100% | 100% | 0 |
| foreign | 5 | 40% | 100% | 0 |
| full_invoice | 5 | 80% | 80% | 0 |
| mixed | 6 | 83% | 83% | 0 |
| no_vat_number | 6 | 67% | 67% | 0 |
| pi_merchant | 12 | 83% | 83% | 0 |
| pi_software | 8 | 75% | 75% | 0 |
| pi_subcontractor | 10 | 80% | 80% | 0 |
| r_cafe | 10 | 100% | 100% | 0 |
| r_fuel | 10 | 90% | 100% | 0 |
| r_parking | 8 | 100% | 100% | 0 |
| r_trade | 12 | 92% | 92% | 0 |
| reduced | 6 | 100% | 100% | 0 |
| sales | 30 | 47% | 47% | 0 |
| sales_invoice | 5 | 80% | 80% | 0 |
| standard | 11 | 100% | 100% | 0 |
| utility | 15 | 100% | 100% | 0 |
| zero | 6 | 83% | 100% | 0 |

## Verifier: ollama:muse-glimmer:30b

Docs: 200 | passed checks (so verified): 178 | verified OK: 178 | verifier errors: 0 | all fields agree: 83% | mean 5.13 s

| Doc outcome (graded against gold) | Docs |
|---|---:|
| Agreed, Extractor right (confirmed) | 145 |
| Agreed, Extractor wrong (missed) | 2 |
| Disagreed, Extractor wrong (caught) | 5 |
| Disagreed, Extractor right (false alarm) | 26 |

| Field | Agree | Extractor right | Verifier right | Agreed, both wrong | Disagreed, Extractor wrong | Disagreed, Extractor right |
|---|---:|---:|---:|---:|---:|---:|
| supplier_name | 100% | 100% | 100% | 0 | 0 | 0 |
| supplier_vat_number | 100% | 99% | 99% | 1 | 0 | 0 |
| date | 99% | 100% | 99% | 0 | 0 | 2 |
| net_total | 84% | 97% | 83% | 3 | 3 | 25 |
| vat_total | 93% | 97% | 94% | 2 | 4 | 8 |
| gross_total | 84% | 99% | 85% | 0 | 2 | 26 |

Proposed / needs-a-look decision: 98% without the verifier, 83% with it.
