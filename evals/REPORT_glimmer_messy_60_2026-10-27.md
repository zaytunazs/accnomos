# Extraction eval: local / muse-glimmer:30b

Docs: 60 | errors: 0 | messy: True | all fields correct: 73% | mean 22.15 s (max 37.21 s)

## Accuracy per field

| Field | Accuracy |
|---|---:|
| supplier_name | 100% |
| vat_number | 95% |
| date | 98% |
| net_total | 97% |
| vat_total | 100% |
| gross_total | 100% |
| line_count | 98% |
| status | 80% |

## Per gold case

| Case | n | All fields | Status | Errors |
|---|---:|---:|---:|---:|
| cash_no_vat | 5 | 100% | 100% | 0 |
| exempt | 5 | 80% | 100% | 0 |
| foreign | 5 | 60% | 80% | 0 |
| full_invoice | 5 | 100% | 100% | 0 |
| mixed | 6 | 0% | 0% | 0 |
| no_vat_number | 6 | 33% | 67% | 0 |
| reduced | 6 | 100% | 100% | 0 |
| sales_invoice | 5 | 80% | 80% | 0 |
| standard | 11 | 100% | 100% | 0 |
| zero | 6 | 67% | 67% | 0 |
