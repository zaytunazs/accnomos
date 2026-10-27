# Review: claude/autopilot-eval (Autopilot L2 safety eval)

Reviewed and merged by hand on 27 Oct 2026. The lane's own review pass did not run: the Spark's Anthropic API key ran
out of credit while the last shard was running. The last shard (`verifier off`, messy 2/2) and the report were then
run on the Spark by `jobs/finish_autopilot_eval.sh` with the lane's own harness, unchanged, on Glimmer 30B (local).

## What was built

- `evals/harness/autopilot_sim.py`: seeds the demo books, saves Autopilot rules the way a user would ("Always do this"),
  feeds the 200 gold documents (clean and messy renders), the 25-document inbox and 42 duplicates through the real scan,
  and grades every Autopilot post against gold. `--shard k/n`, `--report`.
- `services/runtime/app/autopilot.py`: a new refusal. Autopilot does not post a document when an earlier proposal
  (waiting, posted or rejected) is from the same supplier with the same date and total, or has the same invoice number.
  A second photo of a receipt has a new file hash, so the DUPLICATE check alone missed it (21 of 32 re-photographed
  receipts were posted twice before this change; 0 after). A refused document waits in Review.
- Results in `evals/runs/autopilot_l2/` (`report.md`, `summary.json`, per-shard records, `NOTES.md`, `before_tightening/`).

## Headline (467 documents per mode, Glimmer 30B on the DGX Spark)

| | verifier on | verifier off |
|---|---:|---:|
| False posts, clean documents | 0 of 154 | 1 of 154 |
| False posts, messy renders | 0 of 139 | 0 of 139 |
| False posts, re-photographed / identical receipts | 0 of 42 | 0 of 42 |
| False posts, all | 17 (3.6 %) | 17 (3.6 %) |
| Expected posts missed (they wait in Review) | 75 of 200 | 58 of 200 |

All 17 false posts in each mode are *seeded copies*: a gold document the seed had already posted, fed again with a
different date. For a receipt with no invoice number that is indistinguishable from buying the same thing twice, so the
report counts them as false posts and also shows the rate without them: 0 in 407 (verifier on), 1 in 407 (off).

## What I checked

- The runtime diff: `same_document()` is a pure function; `inbox.py` reads the proposals once per scan, only when a
  rule could post. Conservative only: it can make Autopilot refuse more, never post more.
- Merged on main with `ruff`, `pyright` (0 errors), runtime/packages 1,163 passed, evals 258, relay 102; e2e below.

## What remains

- `NOTES.md` reports `approve()` failing with a pydantic `ValidationError` on supplier credit notes (negative debit).
  The part-payments work merged since then approves credit notes as reversals, and `test_gold_ledger2_runtime.py`
  approves 40 supplier credit notes; not re-run through this harness.
- With `VERIFIER=off` Autopilot can post on a single reading (`docs/AUTOPILOT.md` now says so). Whether L2 should
  require the verifier is a product decision; in this run the verifier removed one false post on clean documents and cost 16 correct posts (132 against 148).
- Times are inflated (other jobs shared the GPU); the cleanest measurement is about 26 s per document with the verifier.
- Only Glimmer was measured; Muse Spark 1.3 (key mode) and Spark Open (Baseten) have no numbers yet.
