# Review: spark/cis-eval-runs (integrator)

Branch tip 0e306d8f, one commit on top of `muse/cis-eval` (15691214): result files only, under
`evals/runs/cis_read/` and `evals/runs/property_docs/`. No code changes. The branch had no review of its own.

## Claims checked against the raw results

`cis_read` (muse-glimmer:30b on the Spark, local Ollama, run at 13:10 UTC on the `muse/cis-eval` tip):

* `results.jsonl` has 120 rows, one per gold folder in `evals/gold/cis/` (ids match exactly, none repeated).
* 120 answered, 0 refusals, 0 errors.
* `all_exact` is true on 111 of 120 (**92.5%**) and `checks_exact` on 112 (93.3%). These were recounted
  from the rows, not taken from `summary.json`. Both agree with `summary.json` and `report.md`.
* Weakest fields: VAT rate on reverse-charge invoices (54/60), then supplier name, supplier VAT number and net
  amount (56/60 each). Statement fields are 58–60 of 60.

`property_docs` (same model, run at 13:46 UTC) scores the **generic** extraction reader on 108 landlord documents.
It manages 1.9% fully exact (category 24%, property 7%, amount 32%, date 100%). This is a baseline, as `report.md`
says, and is why `muse/property-reader` adds a property-specific reader. Nothing in the app or the docs presents
this number as product accuracy.

No secrets, tokens or model raw output are stored. Rows have `raw: null`, and the only URL is
`http://localhost:11434`.

## Verdict

Merged. Data only; the gates are unchanged from the `muse/cis-eval` merge.
