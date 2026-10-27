# Task: Run the new fixtures through the real features and publish honest numbers (bank matching, mail intake, Ask, judge)

Accnomos monorepo (public; UK English; no secrets; models: Glimmer 30B on Ollama :11434, Qwen on vLLM :8000 for bulk, Claude only as judge).
Read first `docs/reviews/evals-expand/REVIEW.md` ("What remains"), `evals/gold/README.md`, `evals/gold/bank/expected_matches.json`,
`evals/gold/mail/*`, `evals/harness/*`, `evals/runs/glimmer_messy_200/*`, `packages/ledger/src/accnomos_ledger/matching.py`,
`services/runtime/app/intake.py` (Outlook filter), `services/runtime/app/facts.py` + `ai/ask.py`.

## Deliverables
1. **Bank**: load the six two-month CSVs plus the truth ledger events into a fake Books, run `suggest_matches`, and report precision /
   recall of suggested matches against `expected_matches.json` (`evals/runs/bank_matching/report.md` + JSON). Fix matcher bugs the run
   exposes (ledger package tests must stay green); do not tune on the truth file by hand.
2. **Mail**: run the 20 mailbox fixtures through the intake filter and the triage classifier (code parts; the model part with Glimmer)
   and report kept/dropped against the truth (`evals/runs/mail_intake/report.md`).
3. **Ask**: 40 questions over the seeded fictional books (`tools/seed_demo.py` plan, no OneDrive: build the ledger in memory) with gold
   answers computed by code (`facts.py`), run through Glimmer and Qwen; score numbers-exact, citation-present, no-invented-figure;
   `evals/runs/ask_40/report.md`. Include five instruction-style prompts and check they become action cards, not answers.
4. **Judge**: raise the judge reply cap so unparsed replies drop below 5 %, re-run the judge over the 200-doc extraction run, and
   update `evals/runs/glimmer_messy_200/report.md` with the new agreement figure; keep the code score as the headline.
5. README eval row and `docs/HONESTY.md` updated with the real numbers; everything reproducible with one documented command each.
No extraction-prompt changes. Commit in small steps; do not push. Finish with `git log --oneline -8` and the headline numbers.
