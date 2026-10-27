# Task: Honesty pass over every judge-facing document, against the code on main today

Accnomos monorepo (public; UK English; no secrets). Many features landed after the docs were written. Read first: `README.md`
("What works today" table — it has duplicate rows and blank lines that split the table), `docs/ARCHITECTURE.md`, `docs/HONESTY.md`,
`docs/DEMO.md`, `docs/REMAINING.md`, `docs/AUTOPILOT.md`, `docs/ACTIONS.md`, `docs/INBOX.md`, `docs/PLANNER.md`, `docs/SECURITY.md`,
`docs/DEV.md`, every `docs/reviews/*/REVIEW.md` ("What remains" sections are the truth about gaps), and the routers in
`services/runtime/app/main.py` (every `include_router`) plus `apps/web/src/components/AppNav.tsx` and `apps/mobile/lib/screens/*`.

## Deliverables
1. README "What works today": one row per feature actually on main (receipts → review → ledger, Books.xlsx, VAT return + periods + HMRC
   sandbox submit, Ask + voice, chat/voice actions, Autopilot L1/L2 + verifier, Outlook intake, inbox triage + to-dos, bank statements,
   contacts, invoicing, jobs/timesheets, vehicles/mileage, pay runs, day planner, dashboard, Files, Android app, e2e suite, security).
   Each row: what it does · how it is tested · what is NOT verified (real OneDrive / real model / real HMRC / real phone). No duplicates,
   one contiguous table, 8–12 lines of intro above it. Every claim must point at a file or test that proves it; delete any you cannot prove.
2. `docs/ARCHITECTURE.md`: folder layout (`_System/*`, `00 Inbox`, `03 Sales`, `03 Bank statements`, `04 Payroll`, `05 VAT returns` …) and
   the header table checked against `services/runtime/app/*.py`; the models table (Glimmer local, Spark key, Muse Voice, Muse Image for
   brand assets, SAM crop, Spark Open verifier via Baseten) with where each is called. Mark anything unverified.
3. `docs/HONESTY.md`: one bullet per known gap, pulled from every REVIEW.md "What remains" (deduplicated) plus: no HMRC obligations
   endpoint, UTC "today" on the runtime, single-worker rate limit, verifier needs a Baseten key, Play signing hash → Entra pending,
   estimates-only payroll (no RTI), bank formats modelled not verified. Keep it a flat list grouped by area.
4. `docs/DEMO.md`: a 4-minute on-stage script whose numbers are true for the quarter containing 4 Nov 2026 (check `apps/web/public/
   sample-receipt.png` and `docs/reviews/vat-periods/REVIEW.md`); a "if X fails, do Y" line per step; which account is signed in.
5. `docs/REMAINING.md` refreshed; `CHANGELOG`-style "what landed today" is NOT wanted here. No new features, no code changes except a
   doc-string that is plainly wrong. `pytest -q services/runtime` must still pass (docs tests exist).
Commit in small steps; do not push. Finish with `git log --oneline -8` and five claims you were unable to prove and therefore removed.
