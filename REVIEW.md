# Review: `claude/evals-expand`

Brief: `TASK_BRIEF.md`. 140 more Qwen-generated gold documents (061-200), 6 bank CSVs, 20 mailbox fixtures, and a Glimmer eval
on all 200 with a Claude judge pass. Only `evals/` was changed on the branch, plus one parser alias added in review.

## What was checked

- **Tests**, run against *this* checkout's sources. The shared `~/spark/accnomos/.venv` has editable installs that point at
  `repo-lane-e`, so a plain `pytest` there tests lane-e's code: it showed a ledger failure that does not exist here. Results:
  ledger 16, connectors 17, runtime 129, hmrc-relay 39, evals 153 (new). All pass. No web files changed, so no web build.
- **Report reproducibility:** `python -m harness.report_200 runs/glimmer_messy_200 --diagnoses runs/diag.json --fixes runs/fixes.md`
  regenerates `evals/REPORT_glimmer_messy_200_2026-10-27.md` byte for byte from the local run (before my one-line note).
  Checked these claims against the run data: 8 documents have net equal to the gross plus 6 other net errors; the four
  `no_vat_number` documents (016/038/049/060) have VAT 0.00; four `full_invoice` documents are labelled `sales_invoice`.
- **Gold data (061-200):** each document has the `SAMPLE — FICTIONAL COMPANY` label in the JSON and on the printed text. Net + VAT = gross
  in pence, floats agree with pence, line nets sum to the net (±1p), and the side matches the issuer. Every new supplier GB VRN passes
  mod-97. The manifest has 200 entries matching the files. No committed file is over 2 MB (largest: the judge JSON, 454 KB). Committed
  PNGs are ≤ 300 KB. No API keys or workspace headers appear in any committed file.
- **Harness diff** (`render.py`, `run_extraction.py`, `render_gold.py`, `check_bank_mail.py`, `report_200.py`):
  - The `~` handwriting marker and its extra RNG draws apply only to marked lines. 001-060 have none, so their renders are unchanged.
  - Torn (RGBA) images are flattened on the clean path and composited on the messy path.
  - Side scoring is sound: `DocType` has no credit-note value.
  - No extraction code was changed, as the brief required.

## What I fixed

- `4752b17`: `accnomos_ledger.bank` now accepts Tide's `Transaction Information` description header. Before this, both Tide
  fixtures (2 of the 6 bank CSVs) were rejected. Added a parser test.
- `84e11c7`: `evals/tests/`: offline tests (no model calls, 0.5 s). They cover gold pence arithmetic and labels, VRN checksums,
  manifest consistency, `gold_side` / `expected_status` / `score` (side and status), faded/torn/handwritten renders (RGB,
  deterministic), and the bank CSVs and mail fixtures against the truth files.
- `7da9e63`: top-level README gets a "What works today" row for the 200-document eval, with the report's numbers and a statement that
  bank/mail fixtures are not yet run through those features. Also removed a stray blank line that split that table. The gold README
  and report suggested-fix 6 now say the Tide fix is done.
- This commit: corrected the gold README's note on oversized renders (only five merchant invoices, not "merchant and sales") and
  added this file.

## What remains

- Bramblewood's VRN `GB 123 4567 89` (on the 30 sales invoices and 2 sale-side credit notes) is not mod-97 valid, though the brief
  asked for valid-checksum VRNs. It was kept for continuity with 001-060 and the app's examples. This is documented in the gold
  README but not fixed.
- Documents 001-060 carry the `SAMPLE — FICTIONAL COMPANY` label only in the JSON `label` field, not on the rendered image.
  This predates this branch.
- Five messy renders (102, 105, 150, 170, 175, long merchant invoices) are 309-320 KB, just over the brief's 300 KB PNG limit.
  They are not committed, but `python -m harness.render_gold` exits non-zero on a full run.
- Gold-label issues in 001-060, listed in the report's suggested fix 7: the `no_vat_number` documents with VAT 0.00 expect
  `needs_a_look`, and four `full_invoice` documents are labelled `sales_invoice`. Not changed, so the published numbers stay
  reproducible.
- `176_edge_foreign_gbp`: a German cloud subscription is labelled outside scope (`T9`, lines `T0`). In practice a B2B service bought
  from abroad is reverse charge. This is an arguable gold label; it doesn't affect the scored fields.
- The judge result is weak: 27 replies were unparsed, 1 was null, and only 79/200 agree with the code comparison. The report says to
  treat code scoring as the headline. Raising the judge's reply cap is a follow-up.
- The extraction weaknesses in the report (VAT-inclusive net, qty applied twice, handwritten totals) are deliberately unfixed:
  the brief ruled out extraction changes.
- The bank CSVs and mail fixtures are validated for shape only. They have not been run through `suggest_matches` or the Outlook
  intake filter, so the "~70 % reconcile" figure (96/140) comes from the truth file, not from a matcher run.
- Environment: the shared venv's editable installs point at `repo-lane-e`. Run tests with this lane's `src` on `sys.path` first
  (see below).

## How to verify by hand

From `evals/`, run `python -m pytest -q tests`. Expect 153 passed; the Tide CSV cases only pass against this branch's ledger, so a
pass also proves the right sources were imported. Then run `python -m harness.check_bank_mail`: all six CSVs should print
"amounts and dates match" and the last line should be "mail fixtures consistent". For the ledger, from `packages/ledger`, run
`python -c "import sys; sys.path.insert(0,'src'); import pytest; sys.exit(pytest.main(['-q']))"` and expect 16 passed. Open
`evals/REPORT_glimmer_messy_200_2026-10-27.md` and check the headline: 88 % all fields, 100 % side, 93 % status. If the local run
directory `evals/runs/glimmer_messy_200` is present, regenerate the report with
`python -m harness.report_200 runs/glimmer_messy_200 --out runs/rep.md --diagnoses runs/diag.json --fixes runs/fixes.md` and diff it
against the committed one. The only expected difference is the "Done in review" note under fix 6. To look at the new damage
modes, run `python -m harness.render_gold runs/render_check --only 091_edge_handwritten 123_edge_torn_faded 167_edge_torn_faded`
and open the PNGs.
