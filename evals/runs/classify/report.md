# Document-type classifier eval

Model `muse-spark-1.3-contributor` at `https://api.meta.ai/v1`; 2026-11-01T08:23:32+00:00. Code under test: `app.ai.classify.classify` through the provider chain (Meta when `META_API_KEY` is set, else the Spark local model), with `app.ai.classify.by_words` on a model miss and code-only recognition for bank CSVs, exactly as the upload flow (`app/scan_jobs.py`) does.

- Documents: **434** (434 answered, **0 refusals**, 0.0%)
- Accuracy (predicted kind equals the gold label; a refusal counts as wrong): **96.5%**
- Who answered: model **428** (98.6%), code **6** (1.4%)
- Code's fallback guess used on **0** answered documents (0.0%)
- Bank CSVs recognised by code alone: 6
- Latency: mean 4.909 s, p50 4.407 s, p95 8.675 s, max 21.904 s (total 2130.7 s)

## Per-type precision and recall (answered documents)

| Type | Gold | Predicted | Correct | Precision | Recall |
|---|---:|---:|---:|---:|---:|
| receipt | 95 | 89 | 87 | 97.8% | 91.6% |
| purchase_invoice | 150 | 159 | 147 | 92.5% | 98.0% |
| sales_invoice | 35 | 35 | 35 | 100.0% | 100.0% |
| bank_statement | 12 | 6 | 6 | 100.0% | 50.0% |
| credit_note | 10 | 10 | 10 | 100.0% | 100.0% |
| payslip | 0 | 0 | 0 | None% | None% |
| other | 132 | 135 | 128 | 94.8% | 97.0% |

## Confusion matrix (rows: gold label, columns: predicted kind)

| Gold \ predicted | receipt | purchase_invoice | sales_invoice | bank_statement | credit_note | payslip | other |
|---|---|---|---|---|---|---|---|
| receipt | 87 | 8 | 0 | 0 | 0 | 0 | 0 |
| purchase_invoice | 2 | 147 | 0 | 0 | 0 | 0 | 1 |
| sales_invoice | 0 | 0 | 35 | 0 | 0 | 0 | 0 |
| bank_statement | 0 | 0 | 0 | 6 | 0 | 0 | 6 |
| credit_note | 0 | 0 | 0 | 0 | 10 | 0 | 0 |
| other | 0 | 4 | 0 | 0 | 0 | 0 | 128 |

## Accuracy by source (refusals count as wrong)

| Source | Docs | Answered | Correct | Accuracy |
|---|---:|---:|---:|---:|
| bank_csv | 6 | 6 | 6 | 100.0% |
| cis | 120 | 120 | 120 | 100.0% |
| landlord | 108 | 108 | 103 | 95.4% |
| receipts | 200 | 200 | 190 | 95.0% |

## First 10 misses

| Id | Gold label | Predicted | Reason |
|---|---|---|---|
| receipts/003_reduced | receipt | purchase_invoice | Supplier invoice from Nimbus Home Energy Ltd billing John Smith for electricity  |
| receipts/004_zero | purchase_invoice | receipt | Till-style slip from another firm showing card-paid goods, so our receipt despit |
| receipts/014_reduced | receipt | purchase_invoice | Supplier invoice from Northern Peaks Energy Ltd for energy supply, not issued by |
| receipts/015_zero | purchase_invoice | receipt | Till-style slip from another shop marked paid by card with thanks for shopping. |
| receipts/025_reduced | receipt | purchase_invoice | Bill from Zephyr Energy for electricity supply to be paid by direct debit. |
| receipts/032_foreign | receipt | purchase_invoice | Supplier bill from Van Dijk & Sons Ltd for fasteners explicitly described as an  |
| receipts/036_reduced | receipt | purchase_invoice | Bill from Northgate Energy Solutions to J. Smith with invoice reference and VAT  |
| receipts/043_foreign | receipt | purchase_invoice | Supplier invoice billing Thameside Office Supplies Ltd for goods. |
| receipts/054_foreign | receipt | purchase_invoice | Supplier Van der Berg Electronics billed Thames Digital Solutions for equipment  |
| receipts/058_reduced | receipt | purchase_invoice | A supplier invoice from Volt & Spark Energy Ltd billed to customer J. Doe. |

Refusals (the model gave nothing usable and code raised):


How it is scored: the predicted kind against the gold label, one of the classifier's own types. Receipts and invoices take their label from the gold `doc_type`/`side` (credit notes first); CIS statements are `other` and reverse-charge invoices `purchase_invoice`; letting statements are `other`, insurance and landlord bills `purchase_invoice`, mortgage statements `bank_statement` (`other` also counts: a PDF statement is kept unread in Needs a look either way); synthetic Starling-layout CSVs are `bank_statement`. Business name given to the model: each case's own owner (the named customer on a purchase, the issuer on a sale, the CIS contractor, the landlord).
