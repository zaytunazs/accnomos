# Review: claude/extraction-quality-2

Second-agent review of the receipt extraction-quality branch (brief: `TASK_BRIEF.md`).

## What was checked

- `services/runtime`: `pytest -q`. At first 696 passed and 2 failed (`test_paths.py`), only because the wip commit had recorded a
  scratch git worktree `.wt-before/` (main at efe0d67) inside the repo, and the path tests scanned its copy of `app/paths.py`.
  After the fixes below: **700 passed, 1 skipped**.
- `evals`: `pytest -q`: **158 passed**.
- `apps/web`: `pnpm run build`: passes.
- `apps/mobile`: no Flutter SDK on this machine, so the Dart change is **not compiled or tested**.
- `packages/*` and `services/hmrc-relay`: not touched by the branch, so not run.
- Diff read in full: `app/repair.py` (VAT-inclusive totals, doubled quantity, VAT-inclusive lines, line total in the unit-price
  column), `app/pipeline.py` (second read), `app/ai/crop.py` (`reread_image`), `schemas.Proposal.repaired_by_code`, the web and mobile
  card wording, and the eval harness (`run_extraction.py` single run, `report_200.py` `--note`, new `replay.py`).
- Product rules: arithmetic is in integer pence (`p()`), and repairs come only from the document's own figures. Every figure repair
  is recorded both as a check and as `repaired_by_code`, and the card shows "Figures repaired by code from the receipt's own
  arithmetic: …". Nothing is written server-side and no secrets appear. The new code calls only the Glimmer extractor.
- Measured offline: `python -m harness.replay runs/glimmer_messy_200` re-runs today's repairs and checks over the stored readings
  of the 27 Oct run (no model):

  | Field | before | after (replay) |
  |---|---:|---:|
  | net_total | 93.0 % | 97.0 % |
  | gross_total | 98.0 % | 98.5 % |
  | status | 93.0 % | 95.0 % |
  | all fields | 88.0 % | 91.0 % |
  | **false passes** | **9** | **11** |

  The replay cannot measure the second read: that needs the model.

## What I fixed

- `4275b16`: removed the `.wt-before` gitlink from the branch. I moved the worktree (not deleted it) to `../repo-lane-d-before`.
  It is main's code plus the single-run harness fix, so it is ready for the baseline run.
- `782eb0d`: `replay.py` imports `Check` instead of `type(checks[0])` (which would raise on an empty list). Also: a spacing
  slip in `crop.py`; the `report_200.py --note` help now says its default is the 27 Oct run's note (otherwise a new report would
  repeat "no extraction code was changed"); mobile's "Checks: N of M passed" counts now leave out note codes (`CROP`, `MILEAGE`,
  `VEHICLE`, `SECOND_READ`, `TOTALS_REPAIRED`, `LINES_REPAIRED`), as the web card does, so repairs no longer count as passed checks.
- `579fd7e`: two tests. A kept second reading brings its own `repaired_by_code`; a discarded one leaves none.
- `ce4a7f4`: README (receipts row) and `docs/HONESTY.md` now describe the repairs and the re-read. They say plainly that no live
  eval has run since, and give the replay numbers, including the false-pass increase.

## What remains

- **Blocker against the brief's target ("no increase in false `passed` status"): false passes go from 9 to 11 on replay.** The two
  new ones, 005 and 027 (`no_vat_number`), are receipts over £250 with no VAT number and no VAT charged. The doubled-quantity repair
  correctly sets the net to the printed total (005: £837.50 → £368.50). Before, they reached *Needs a look* only because their
  arithmetic was broken. Gold expects *Needs a look* for every `no_vat_number` case, but `check_vat_number_required` passes any
  document with zero VAT. This needs a product decision, which I did not make: either flag "no VAT number, over £250" as a fail
  (this would also fix the existing false pass on 049), or change the gold expectation for zero-VAT receipts.
- **No live eval was run.** Deliverable 1 (baseline under `evals/runs/glimmer_messy_200_before/`) and deliverable 3 (final run
  into `evals/runs/glimmer_messy_200/`, README eval row) are missing. At about 22 s per document, a pair of runs is about
  2.5 hours on Glimmer. The README eval row and `REPORT_glimmer_messy_200_2026-10-27.md` still show the pre-branch numbers, which
  is accurate for that run.
- **2c (prompt sentences) was not attempted**, and the commits for 2a/2b/2d carry no before/after eval numbers. `2e5e710` is a
  "wip" commit that mixes the second read, the card wording and harness changes; it was left as is, because history was not
  rewritten.
- The second read triggers at confidence **≤ 0.6**, not the brief's < 0.6, because Glimmer's "unsure" value is exactly 0.6 (see the
  comment in `pipeline.py`). Every unsure document therefore costs a second model call; the latency impact is unmeasured.
- The doubled-quantity repair rounds the new unit price to 2 dp, as the schema does. For awkward quantities (for example £100 over
  qty 7 = 14.29) qty × unit is then 3p off, and `ARITH_LINES` warns. This is only a warning while the totals hold, so status does not change.
- The mobile note-code filter (`apps/mobile/lib/models/proposal.dart`) is untested here (no Flutter).
- `TASK_BRIEF.md` and this `REVIEW.md` are committed at the repo root; drop them before merging if they should not land on main.

## How to verify by hand

From `services/runtime` run `pytest -q tests/test_repair.py tests/test_second_read.py` (fake extractor, under a second). From
`evals` run `python -m harness.replay runs/glimmer_messy_200 --show`: it lists every document the repairs change, with the note
the card would show, and the before/after table including false passes (005 and 027 are the two new ones). For a live check,
start the runtime against Ollama (Glimmer), upload `evals/gold` receipt 081 or 123 rendered messy, and confirm the card says
"Figures repaired by code from the receipt's own arithmetic: Net £… was the VAT-inclusive total …". For the eval itself, run
`python -m harness.run_extraction --mode local --messy --business-name 'Bramblewood Joinery Ltd'` once from
`../repo-lane-d-before/evals` (baseline) and once here, then compare with `harness.report_200 … --note '<what changed>'`.
