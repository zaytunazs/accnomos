# Review: `claude/submission-pack`

Second-agent review of the hackathon submission pack (brief: `TASK_BRIEF.md`). The branch is Markdown only: five drafts in
`docs/submission/`, no code changes, nothing pushed.

## What was checked

- **Tests, on this checkout** (the shared venv's `pytest`, because `uv run` needed approval; runtime also re-run with an absolute
  `-o pythonpath` to this lane's `services/runtime`, `packages/ledger/src` and `packages/connectors/src`, because the venv's
  editable installs can point at another lane): `services/runtime` 642 passed, 1 skipped; `services/hmrc-relay` 102;
  `packages/ledger` 33; `packages/connectors` 34; `evals` 153. Web was not built: no web files changed. Playwright was not run.
- **Every factual claim in the five drafts checked against code or the cited report**: file paths; eval figures (200-doc 88 %,
  field rates, 22.16 s mean / 39.81 s max; 60-doc 73 %; verifier 17/18, 0 catches, 1 false alarm; crop IoU 0.882 vs 0.475);
  `verify.py` slug, overrides and `VERIFIER=off`; `voice.py` endpoint, ffmpeg settings and the local-mode 400; `crop.py` `SAM_CROP`,
  `sam-3.1`, receipt then invoice; the ILLUSTRATIVE fixture; Muse Image $0.01 and commit `f39cb2d` (12 images, USD 0.12);
  `muse-wonder` not called in code; every UI label the video script names (web `apps/web/src`, "Photograph a receipt" in
  `apps/mobile/lib`); test-mode routes, port and today pin; compose variables; relay `/hmrc/test-user`, fraud headers v3.3, box
  checks; `pubspec.yaml` 0.2.0+2; `msal_config.json`; 24 review folders; the deadline conversion (21:00 EST = 02:00 GMT, 5 Nov).
- **Checklist secrets greps run** on working tree and all local history. Only expected hits, none real (listed in `CHECKLIST.md` §7).
- Product rules: the drafts keep to AI proposes / user approves / code calculates, no user database, synthetic data labelled
  "SAMPLE — FICTIONAL COMPANY", and they do not describe a reviewer LLM.

## What I fixed

- `7948fcd` **README contradictions.** Removed the stale second status table. It said Sales invoicing was "not started", that
  Books.xlsx had 11 sheets, that Home tiles were "UI only", and gave "runtime 271 tests", all contradicting the main table.
  Moved the six dated changelog rows that sat orphaned under *Invoicing* back into the changelog table. The main receipts row
  now quotes the 200-doc eval instead of the 60-doc one with its old scoring. Test counts in README, `docs/HONESTY.md` and
  `docs/DEMO.md` now match the run above. The e2e row now says 44 tests (20 desktop + 19 phone-width + 5 at 390 px, counted
  from the specs and the two Playwright projects), replacing a stale "23" that wrongly said `/invoices` and `/payroll` were
  not covered.
- `41fa10f` **Submission drafts.**
  - The 150-word description and the 30-second cut said a "second model" reads the receipt. On the demo the verifier is
    Glimmer checking Glimmer, so they now say a second, differently prompted reading.
  - Word counts re-measured: 147 and exactly 400.
  - JUDGING carries the real test counts and records which half of the run guide was executed.
  - CHECKLIST:
    - time-zone reasoning now also covers the US clock change on 1 Nov;
    - corrected the wrong "root `TASK_BRIEF.md` is untracked" (it is committed);
    - records the grep results and expected hits;
    - marks the README clean-up done.
  - META_MODELS: `/ai/test` is the one place without the `META_API_KEY` fallback.
- `c6f87e0` **Test:** `test_docs.py` now also checks that every file cited in `docs/submission/*.md` exists (12 pass).

## What remains

- The Playwright suite (`pnpm run e2e`) and the click-through route B in `JUDGING.md` have not been run by either agent. The
  "10 minutes" is untimed.
- The 400-word description is exactly 400 by whitespace count; the form's counter may disagree. Trim a sentence if it does.
- Everything owner-only in `docs/submission/CHECKLIST.md` is still open: Play listing status, Entra signature hash and
  `broker_redirect_uri_registered`, `flutter analyze`/`flutter test`, the demo account and seed run, `ACTIONS_SIGNING_KEY`,
  the `META_API_KEY` decision, HMRC sandbox credentials and the first end-to-end sandbox submission, the live
  `api.accnomos.com/health` check, the video, and check 4 of the secrets scan with your real values on a fresh clone.
- Personal details remain in the public tree, for the owner to decide on: Windows paths with the username in `tools/*.ps1`,
  and the LAN address `192.168.1.176` as the default AI URL in web, mobile, compose, docs and tests.
- `TASK_BRIEF.md` and `REVIEW.md` sit at the repo root. Move them to `docs/reviews/submission-pack/` when merging, like the
  other branches.
- The README's "What works today" section still holds a long dated changelog above the feature table. It is accurate but
  long; judges may prefer it trimmed or moved below the table. Not changed here.
- The hackathon's official judging rubric was not available. `JUDGING.md` uses five generic headings to be replaced.

## How to verify by hand

From the repo root, run `uv run pytest -q`, or `pytest -q` inside each of `services/runtime`, `services/hmrc-relay`,
`packages/ledger`, `packages/connectors` and `evals`. Expect 642 + 1 skipped, 102, 33, 34 and 153.
`services/runtime/tests/test_docs.py` alone checks that every path cited in the README, the main docs and `docs/submission/`
exists. Then open `README.md`: "What works today" should have exactly one status table, with no "not started" row for
Sales invoicing and no "271 tests". Read `docs/submission/DESCRIPTION.md` and check that no sentence claims a second *model*
or a live HMRC run. Finally, run the commands in `CHECKLIST.md` §7 on a fresh clone: the hits should be exactly the expected
ones listed there.
