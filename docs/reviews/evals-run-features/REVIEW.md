# Review: `claude/evals-run-features`

Second-agent review of the feature-evals branch (brief: `TASK_BRIEF.md`): bank matching, mail intake, Ask on 40 prompts,
judge re-run, README / HONESTY numbers.

## What was checked

- **Tests, all green after the fixes:** `packages/ledger` 35, `packages/connectors` 34, `services/runtime` 633 (+1 skipped),
  `services/hmrc-relay` 100, `evals` 158. No web files changed, so no `pnpm run build`. `ruff` was not run (it needed an
  approval this session did not have).
- **Reproduced numbers without a model:** `python -m harness.bank_match` gives precision 83/83, recall 83/106, the same as
  the committed report. `python -m harness.mail_intake --no-model` gives 12/17 documents kept, 11/11 decoys dropped, the
  duplicate caught, triage filter 13/13, the same as the report. `python -m harness.ask_40 --report-only` on a copy of the
  committed `result.json` writes a report identical to the committed one. `evals/runs/glimmer_messy_200/report.md` is identical
  to `evals/REPORT_glimmer_messy_200_2026-10-27.md`. The judge's 79/200 agreement figure is the same as before the reply-cap
  change. That is consistent rather than suspicious: both runs have 60 `none` verdicts on documents the code scores right,
  plus 19 non-`none` verdicts on the 19 documents it scores wrong.
- **Read the diff:** the matcher change (60-day window for payments on terms, nearer document wins a tie), grounding that
  accepts figures from the user's own question, the judge cap (4,000 tokens) and `stop_reason`, the three harnesses, the
  `.gitignore` exceptions, the seed and its doc. Looked for secrets: none found (`api_key="local-vllm"` is the local vLLM
  placeholder). Nothing is written server-side and no user data is involved: everything is synthetic, built on fake storage.
  Wording is UK English. Pence handling in the matcher is unchanged (integer pence, ±1p).
- **Docs against the code:** README rows, `docs/HONESTY.md`, `docs/META_MODELS.md`, `tools/seed_demo.md` and the
  `routes_bank.py` docstring match the reports and the code. HONESTY's "*Confirm* refuses a second line for the same entry"
  is true (`Books.confirm_match` raises "already matched to another bank line").

## What I fixed

- `9719eea`: **bank matcher.** The docstring says that past 5 days the counterparty's name has to carry the match, but card
  digits alone (0.5 + 0.1 = 0.6) still produced a `suggested` match for a late DD or transfer line with no name. Such a match
  now needs the name. A test fails without the fix and passes with it. Eval numbers are unchanged.
- `993fb26`: **eval reports.** The bank report said "before the matcher fix in this branch (`d706f04`)", but `d706f04` is the
  main base commit; it now says so plainly and states the name rule. The mail report computed the unscored "either" count as
  `20 - scored` and now counts the rows. The mail report itself was not regenerated, because that needs Glimmer; its current
  figure, 7, is correct.
- `27cd834`: **missing tests** (`evals/tests/test_ask_and_judge_harness.py`, about 4 s, fake model and HTTP):
  - `has_gold` matching;
  - Ask scoring through the real `routes_ask._answer` path on the seeded books. A correct answer scores exact, cited and
    nothing invented. An invented figure is counted against the raw reply and replaced by grounding, so it never reaches the
    user.
  - The judge sends `max_tokens` 4000 and records `stop_reason` when a reply is cut off at the cap.
- `bda9a0c`: **README.** A duplicate 60-receipt row (88 %; the report says 80 %) and a blank line inside the dated table cut the
  table short, so the branch's new eval rows rendered as plain text. Both removed.

## What remains

- The model parts were **not re-run in this review**: Ask on Glimmer and Qwen, triage categories on Glimmer, and the Claude judge
  (no API key here). Their numbers are checked only by regenerating the reports from the committed result files.
- `ruff` not run on the changed files.
- Product gaps the evals expose, documented in HONESTY and not fixed here:
  - part payments are never suggested (20/106 gold pairs);
  - supplier refunds into Tide more than 5 days after the credit note are missed (the parser drops `Transaction Type`);
  - photos a colleague forwards from the user's own domain score 0.3 against the 0.4 intake threshold (5/17 documents);
  - Glimmer hits the 120 s Ask timeout on 4/35 questions;
  - grounding cannot catch a real figure from the wrong period.
- Matcher risk with no gold case: a card purchase already settled through the bank can still be suggested against a later
  DD / FP / BACS line with the same amount and name within 60 days. That gives a `suggested` match (never `exact`) that the
  user must reject. Worth a test case in the gold bank set.
- `TASK_BRIEF.md` sits at the repo root in the `wip: checkpoint` commit. Move it (and this file) to `docs/reviews/evals-run-features/`
  at merge, as earlier branches did.

## How to verify by hand

From `evals/`, run `python -m pytest -q tests`; it should report 158 passed. Then run `python -m harness.bank_match`; it should
print precision 83/83 and recall 83/106, and `git diff runs/bank_matching` should be empty. Run
`python -m harness.mail_intake --no-model --out /tmp/mail`; it should print 12/17 documents kept, 11/11 decoys dropped and triage
keep/drop 13/13. With Ollama (Glimmer on :11434) and vLLM (Qwen on :8000) up, `python -m harness.ask_40` re-runs the 40 prompts
in about 40 minutes. Expect numbers exact near 28/32 for Glimmer and 31/32 for Qwen; the model output varies. In the app, seed the demo books
(`tools/seed_demo.md`) and open `/bank`. Jul–Sep should show 16 suggested matches. Two of them are customer payments 10 days
after the invoice, each marked *suggested* with "paid 10 days after the document", never as exact.
