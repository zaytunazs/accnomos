# Review: muse/property-reader + spark/property-eval-runs (integrator)

Merged as one: `spark/property-eval-runs` (457d7e6b) is `muse/property-reader` (9ff32f80, Steps 1–4) plus the Spark run
of the eval against exactly that code. Neither branch had a review of its own, so this one is written at merge time.

## What it adds

* `app/ai/property_read.py`: reads a letting statement, property bill, insurance schedule or mortgage statement.
  It is modelled on `ai/cis_read.py`, with the same strict JSON schema and the user's own AI (`cfg.base_url`,
  listed in `TALKS_HTTP`).
* `app/property_readings.py`: the code side. It turns pounds into pence, matches the property by postcode or address
  in code, and checks the lines against the printed totals. A reading waits for the user and nothing is posted until
  they approve it. Reading is refused unless the business has a property profile (landlord mode on, or properties on
  the register).
* Routes: `POST /property/read`, `GET /property/readings`, and `POST /property/readings/{id}/approve|reject`. Each
  goes through `get_books` and `require_user`, the same pattern as `/cis/read`. Audit sentences are in
  `audit_view.py`.
* `evals/harness/property_docs.py` now scores the new reader per line and keeps the generic reader as a baseline
  column. Stub tests are in `tests/test_property_read.py`.
* There are no web or Android changes, so there is no new page for the submission-mode wording check.

## Merge

The branch had merged older `main` states into itself. Its copies of `AppNav.tsx`, `TopBar.tsx`, `nav.ts` and
`paths.py` are the raw `claude/batch-tax` and research-design versions, which `integration` had already resolved, so
the integration side was kept for those files. `evals/runs/property_docs/*` takes the branch's run. That run is newer
than `spark/cis-eval-runs`' generic-only baseline and carries the same baseline as a column.

## Claims checked against the raw results

* `results.jsonl` has 108 rows with unique ids: 108 answered, 0 refusals, 0 errors, and no raw model output stored.
* `all_exact` is true on 89 of 108 rows (**82.4%**), recounted from the rows. The generic baseline is 1.9%.
* By kind: letting statements 72/72 and invoices 17/24, but insurance 0/6 and mortgage statements 0/6.
  `muse/property-reader-2` targets those two kinds, so the weakness is real and not hidden.

## Gates

See `docs/reviews/integration/REVIEW.md`.

## Not merged with it

`muse/property-reader-2` (d4b10930) changes the reader prompt and code checks *after* this Spark run. Its
`report.md` still shows the numbers of the code merged here, so it waits for its own Spark re-run.
