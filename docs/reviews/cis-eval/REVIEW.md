# Review: muse/cis-eval (integrator)

Branch tip 15691214, merged into `integration` after `claude/batch-tax`. The branch carried no review of its own, so
this one is written at merge time.

## What it adds

* `evals/harness/cis_read.py`: every gold CIS document (`evals/gold/cis/`, 60 statements and 60 reverse-charge
  invoices) through the production `app.ai.cis_read.read_cis_document` and `app.cis_readings.from_reading`, scored
  per field plus the code-side check codes (`RATE`, `RC_WORDING`). Statement settings take the payment status from
  the gold rate only (ce6cde2c).
* `evals/harness/property_docs.py`: the generic extraction reader over the gold landlord statements and bills
  (category, property, amount, date). There is no property-specific reader yet; `muse/property-reader` adds one.
* `tools/spark_queue.sh`: two new Glimmer steps (`cis_read`, `property_docs`) after the extraction steps.
* Stub-model tests for both harnesses and the queue order (`evals/tests`).

## Checks made

* Only the local Ollama endpoint is called (`DEFAULT_OLLAMA_BASE`); no Meta, Baseten or Modal calls, and no
  secrets.
* `--stub` runs end to end offline (120 docs; the stub's canned replies deliberately include refusals, so its
  scores are not a model result).
* evals tests 352 passed; ruff 0.17.3 check and format clean.
* No runtime, ledger or web code is changed, so the submission-mode wording check does not apply.

## Verdict

Merged. Real model numbers arrive with `spark/cis-eval-runs`.
