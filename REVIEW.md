# Review: `claude/judges-docs`

Second-agent review of the judge-facing docs task (`TASK_BRIEF.md`). The branch changes documentation only
(`README.md`, `docs/ARCHITECTURE.md`, `docs/META_MODELS.md`, `docs/DEMO.md`, `docs/HONESTY.md`); no product code.

## What was checked

- `pytest -q`: `packages/ledger` 30 passed, `packages/connectors` 19 passed, `services/hmrc-relay` 39 passed,
  `services/runtime` 269 passed. These match the counts quoted in `docs/HONESTY.md`.
- `apps/web`: `pnpm run build` passes (19 static pages).
- Every UI label the demo script tells the presenter to click was found in the web or Flutter source (*Add a receipt*,
  *Scan 00 Inbox now*, *Approve (post to books)*, *Always do this for …*, *Test connection*, *Show obligations*,
  *Submit to HMRC (sandbox)* in both the live card and the mock-up, *Rebuild Books.xlsx*, *Photograph a receipt*, and others).
- `apps/web/public/sample-receipt.png` is Novex Office Supplies Ltd, £43.25 + £8.65 = £51.90, as the demo says.
- Technical claims checked against the code: relay validation (box 3 = 1 + 2, box 5 = |3 − 4|, `POST /hmrc/test-user`),
  Autopilot ≤ 2× the usual amount, verifier on six fields, `VERIFIER=off`, `BASETEN_API_KEY`, `SAM_CROP=1`, voice
  temporary directory, the Muse Image ($0.01/image) and SAM (~$2.50/1k) quotes, and the code-composed "Checker, code" line
  versus the static "Reviewer's note (Muse Spark)" mock-up.
- Every eval figure in `docs/META_MODELS.md` and the README matches `evals/REPORT_*.md` (73 % all fields, 80 % decision,
  22 s mean / 37 s max, 7.6 s verifier, 17 of 18 agree, 1 false alarm, IoU 0.882 vs 0.475, category misses).
- Product rules: no new server-side storage, no secrets, synthetic data labelled. UK English is fine.

## What I fixed

- `01e0d6a`. **The demo VAT step was wrong.** The VAT page always shows the current calendar quarter
  (`routes_vat.py` `quarter_bounds(date.today())`; the web and Android apps send no dates), and the ledger event takes the document's own
  date (`approve.py`). The sample receipt is dated 14 Aug 2026, so during judging (Oct–Dec quarter) it would **not** show
  "Box 4 £8.65, Box 7 £43" as the script promised. `DEMO.md` now explains this and gives two ways round it.
- `01e0d6a`. `ARCHITECTURE.md` listed "date in period" among the live checks. `check_date` supports it, but no caller
  passes a period, so it never runs. The doc now says so, and `HONESTY.md` gains a bullet (current quarter only, warning never fires).
- `01e0d6a`. The banner is hidden on `/privacy`. "Every web page" is now "every app page (except `/privacy`)".

## What remains

- **The demo receipt is in the wrong quarter.** For the VAT boxes to move on stage, either regenerate `sample-receipt.png`
  with a date this quarter or approve such a receipt during set-up. Docs only describe the gap; no asset was changed.
- **No VAT period picker, and the date-in-period warning is not wired** (no caller of `app/pipeline.py` passes `period_start`/`period_end`).
  This is a product gap and was out of scope for a docs task.
- **Not checked here:** the live site (accnomos.com / api.accnomos.com), the Flutter build, and any Meta API or Baseten call.
  The docs already say all of these are unverified.
- **README top is 8 lines**, not the 12 the brief allowed. It is shorter, which is fine; noted only for completeness.
- `TASK_BRIEF.md` was committed in `d65e105` ("wip: checkpoint"). Drop or squash it before merging if the brief should not ship.

## How to verify by hand

Run `pytest -q` in each of `packages/ledger`, `packages/connectors`, `services/hmrc-relay` and `services/runtime`, and
`pnpm run build` in `apps/web`. All should pass with the counts above. Then sign in on a throwaway account and follow
`docs/DEMO.md` up to *Approve*. Open **VAT return** and confirm the period shown is the current calendar quarter and that the
August-dated sample receipt does not appear in its entry counts. Approve a receipt dated inside the quarter and confirm Box 4
and Box 7 move by its VAT and net (Box 7 in whole pounds). Finally, read `docs/HONESTY.md` against the README "What works
today" table: nothing in the README should claim a live run that HONESTY lists as "not yet run for real".
