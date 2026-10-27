# Task: Judge-facing documentation and demo script (no product code changes)

Accnomos monorepo (public; UK English). Read everything in `README.md`, `docs/*.md`, `evals/REPORT_*.md`, `services/*/README.md`,
and skim the code to make sure every claim you write is true today (run `pytest -q` in each package and `pnpm run build` to be sure
what works). The hackathon is the Meta Global AI Developer Hackathon (Indie track). Judging criteria to speak to: technical excellence,
use of Meta models (Muse Glimmer open weights locally, Muse Spark, Muse Image, Muse Voice Transcribe, SAM 3.1, Spark Open), agentic
use-case (autonomy + verification + human approval), real-world usefulness for UK small businesses, and honesty about limits.

Write/refresh, each ≤ 2 pages, dense tables where helpful:
1. `docs/ARCHITECTURE.md` — the stateless runtime, the HMRC relay, OneDrive-as-database (folder layout, ledger events, Books.xlsx
   projection), the agent pipeline (Intake → Extractor → Checker (code) → Reviewer → Verifier → Human → Poster → Filer), where each Meta
   model is used and why, what never leaves the device, threat model in five bullets.
2. `docs/META_MODELS.md` — a table: model, where, purpose, cost per unit we measured or quote from docs, fallback; plus the eval results
   from `evals/REPORT_*.md` (link, don't invent numbers).
3. `docs/DEMO.md` — a 3-minute demo script with exact clicks on https://accnomos.com and the Android app, the sample business
   (Bramblewood Joinery Ltd — fictional), what to say at each step, and a "what to show if X fails" fallback list.
4. `docs/HONESTY.md` — what is sandbox/demo/not yet (HMRC sandbox only, no production filing; sign-in build state; anything flagged TODO).
5. README: tighten the top to 12 lines (pitch + what works + how to run), link the four docs, keep the "What works today" table accurate.
Commit in small steps; do not push. Finish with `git log --oneline -8` and a list of claims you removed because they were not true.
