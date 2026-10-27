# Review: `claude/extraction-quality`

**Verdict: not mergeable as a feature.** The implement pass made no changes. The branch's
only commit (`73bc9f3 wip: checkpoint after implement pass`) adds `TASK_BRIEF.md` and
nothing else. There's no stash, no uncommitted work, and no code, eval run or doc change
anywhere in the tree for the brief.

## What was checked

- `git log origin/main..HEAD` and `git diff origin/main...HEAD --stat`: one commit, one file (`TASK_BRIEF.md`, +22).
- `git status` and `git stash list`: both clean.
- Searched the whole repo for `repaired_by_code`. It appears only in `TASK_BRIEF.md`, so neither the repair code nor the card wording exists.
- `evals/runs/`: there is no `glimmer_messy_200_before/` baseline, and `glimmer_messy_200/` is unchanged from `main`.
- `services/runtime`: `pytest -q` gives **677 passed, 1 skipped** (same as `main`, since there are no code changes).
- `packages/*`, `services/hmrc-relay`, `apps/web`: not touched by the branch, so they weren't re-run.

## What was fixed

Nothing. The diff has no code in it to fix. I didn't write the feature myself because this
pass is for review, not re-implementation. Most of the brief also depends on a 200-document
Glimmer eval for before/after numbers, which is a long model run and belongs in the
implement pass.

## What remains

Every deliverable in `TASK_BRIEF.md` is still open:

1. Baseline 200-doc eval report under `evals/runs/glimmer_messy_200_before/` (numbers only, no PNGs).
2a. Deterministic repair of VAT-inclusive confusion before the checks (gross − VAT = net ± 1p or net × 1.2 = gross ± 1p), recorded as `repaired_by_code` in the proposal, with tests.
2b. Per-line quantity × unit price repair (lines must sum to net; don't multiply twice), with the same `repaired_by_code` note and tests.
2c. One or two prompt sentences in `app/ai/extract.py`, kept only if the eval improves on every class.
2d. Second read of the cropped image at higher resolution (via `crop_document`) when confidence < 0.6 or arithmetic fails. One retry at most; keep the read that passes more checks. Tests with a fake provider.
3. Final eval run into `evals/runs/glimmer_messy_200/`, README eval row, `docs/HONESTY.md`, and the card wording "Figures repaired by code from the receipt's own arithmetic". Target: higher field accuracy with no increase in false `passed`.

Suggested order when the work restarts: 2a and 2b first. They're pure arithmetic in
`app/checks.py`/`app/pipeline.py` and can be fully unit-tested without the model. Then the
baseline and final eval runs on Glimmer (Ollama :11434), then 2c and 2d measured against
the baseline.

## How to verify by hand

Run `git diff origin/main...HEAD --stat` and you'll see only `TASK_BRIEF.md` (plus this
`REVIEW.md`). Running `grep -rn repaired_by_code services apps` returns nothing. Running
`cd services/runtime && pytest -q` still passes (677 passed, 1 skipped), because runtime
behaviour is identical to `main`. Once the feature has actually been built, a by-hand check
would be: upload a SAMPLE receipt where the model reads net = gross (VAT-inclusive
confusion). The review card should show the repaired net and VAT with the "Figures repaired
by code from the receipt's own arithmetic" note, and the status shouldn't be `passed`
unless the repaired figures pass every check.
