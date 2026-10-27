# Task: Demo seed + judge walkthrough — one command fills a OneDrive with the fictional company's books

Accnomos monorepo (public; UK English; no secrets). Read first: `packages/connectors/.../msgraph.py`, `services/runtime/app/{books.py,
approve.py,projection.py}`, `evals/gold/receipts/manifest.json` (+ `evals/gold/bank`, `evals/gold/mail` if present), `apps/web/src/lib/graph.ts`
(folder layout), `docs/DEMO.md` if present.

## Deliverables
1. `tools/seed_demo.py` (runtime venv): given a Graph access token (pasted by the operator; never stored) and `--business "Bramblewood
   Joinery Ltd"`, creates the folder layout, uploads 25 gold documents into `00 Inbox` (mix of purchase/sales, two "needs a look"),
   posts 40 approved ledger events spanning the last two VAT quarters (deterministic, balanced, every document labelled
   "SAMPLE — FICTIONAL COMPANY"), two bank CSVs, contacts, two jobs with timesheets, one vehicle with mileage, three sales invoices
   (one overdue) — using the same code paths the app uses (no hand-written JSON), then rebuilds Books.xlsx. `--wipe` removes only the
   Accnomos folder first (with a y/N prompt). Dry-run mode prints the plan.
2. `tools/seed_demo.md`: how to get a token for a throwaway Microsoft account (Graph Explorer or the app's own sign-in → copy from
   DevTools is acceptable for a demo account only), the exact command, what the judge will see on each page afterwards.
3. Tests for the plan builder (counts, balance, date spread) with the fake provider; the Graph path is exercised only when a token env var is set.
Commit in small steps; do not push. Finish with `git log --oneline -8` and five lines a human must verify.
