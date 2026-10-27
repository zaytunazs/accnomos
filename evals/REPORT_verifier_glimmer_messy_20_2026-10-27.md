# Verifier eval: Glimmer extracts, Glimmer verifies (different prompt), 20 messy gold receipts

Run 27 Oct 2026 on our DGX Spark: `cd evals && python -m harness.run_extraction --mode local --limit 20 --messy --verify`.
Extractor and Verifier are both `muse-glimmer:30b` via Ollama (local mode never sends documents to Baseten). Baseten
Muse Spark Open and the Meta API verifier paths are unit-tested only, not run here.

## What it shows (read this first)

- **Agreement: 17 of 18 verified docs (94%) agreed on all 6 fields** (supplier, VAT number, date, net, VAT, total).
  2 docs had already failed code checks, so the verifier was correctly skipped (both were genuine extractor errors).
- **Caught: 0.** Every extractor error on this set was already caught by the code checks, so the verifier had nothing
  left to catch. 20 docs is too few to measure the catch rate. A run on the full 60 (and on harder, real photos) is needed.
- **False alarm: 1** (`013_mixed`). On a mixed-rate receipt the verifier read "amount before VAT" as £6.75 (likely the
  standard-rated subtotal) where the extractor's £17.14 is right. The proposal went to *Needs a look* showing both
  values, as designed. This is why the decision accuracy below drops from 95% to 90%. Next step: tell the verifier
  that mixed-rate receipts have one overall net.
- **"Agreed, Extractor wrong" (1) is a gold artefact, not a miss.** `015_zero`'s gold record has VAT number
  GB 987654321 but its `printed_text` does not print one. Both readings correctly said none.
- `016_no_vat_number` counts as a status miss because the harness expects every `no_vat_number` case to need a look,
  but this receipt charges £0.00 VAT, so there is nothing to reclaim. That is a harness rule issue, unrelated to the verifier.
- Cost: the second reading took 7.6 s on average (vs about 21 s for the full extraction), only on docs that passed checks.

---

## Raw harness report

Docs: 20 | errors: 0 | messy: True | all fields correct: 80% | mean 28.83 s (max 41.65 s)

## Accuracy per field

| Field | Accuracy |
|---|---:|
| supplier_name | 100% |
| vat_number | 95% |
| date | 100% |
| net_total | 95% |
| vat_total | 100% |
| gross_total | 100% |
| line_count | 100% |
| status | 90% |

## Per gold case

| Case | n | All fields | Status | Errors |
|---|---:|---:|---:|---:|
| cash_no_vat | 2 | 100% | 100% | 0 |
| exempt | 2 | 100% | 100% | 0 |
| foreign | 1 | 100% | 100% | 0 |
| full_invoice | 2 | 100% | 100% | 0 |
| mixed | 2 | 50% | 50% | 0 |
| no_vat_number | 2 | 0% | 50% | 0 |
| reduced | 2 | 100% | 100% | 0 |
| sales_invoice | 2 | 100% | 100% | 0 |
| standard | 3 | 100% | 100% | 0 |
| zero | 2 | 50% | 100% | 0 |

## Verifier: ollama:muse-glimmer:30b

Docs: 20 | passed checks (so verified): 18 | verified OK: 18 | verifier errors: 0 | all fields agree: 94% | mean 7.57 s

| Doc outcome (graded against gold) | Docs |
|---|---:|
| Agreed, Extractor right (confirmed) | 16 |
| Agreed, Extractor wrong (missed) | 1 |
| Disagreed, Extractor wrong (caught) | 0 |
| Disagreed, Extractor right (false alarm) | 1 |

| Field | Agree | Extractor right | Verifier right | Agreed, both wrong | Disagreed, Extractor wrong | Disagreed, Extractor right |
|---|---:|---:|---:|---:|---:|---:|
| supplier_name | 100% | 100% | 100% | 0 | 0 | 0 |
| supplier_vat_number | 100% | 94% | 94% | 1 | 0 | 0 |
| date | 100% | 100% | 100% | 0 | 0 | 0 |
| net_total | 94% | 100% | 94% | 0 | 0 | 1 |
| vat_total | 100% | 100% | 100% | 0 | 0 | 0 |
| gross_total | 100% | 100% | 100% | 0 | 0 | 0 |

Proposed / needs-a-look decision: 95% without the verifier, 90% with it.
