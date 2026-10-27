# Task: Bank statements in the web app — upload CSV, review matches, confirm, see unmatched

Accnomos monorepo (public; UK English; no secrets; stateless runtime). Read first: `services/runtime/app/routes_bank.py`,
`packages/ledger/src/accnomos_ledger/{bank.py,matching.py}`, `evals/gold/bank/` (if present, three UK CSV formats),
`apps/web/src/lib/{runtime.ts,graph.ts}`, `components/files/*`.

## Deliverables
1. Runtime: make sure `/books/bank/*` supports: upload a CSV (saved to `02 Bank/<yyyy-mm-dd>_<bank>.csv` in the user's folder), parse
   the three common formats (header sniffing: Barclays/Starling/Tide/Monzo-style; document which columns), propose matches to ledger
   events (amount ±1p, date ±5 days, counterparty similarity), confirm/unmatch endpoints, list unmatched lines with suggested actions
   ("create expense proposal", "mark as transfer", "ignore"). Idempotent re-upload of the same CSV (sha256). Tests on the gold CSVs.
2. Web `/bank` page: upload (drag/drop), statements list, matches table with confirm buttons, unmatched tab with the three actions,
   a "Reconciled to date" tile. Nav entry. `pnpm run build` passes. README row.
3. Books.xlsx `Bank` sheet (statement lines, matched event id, status).
Commit in small steps; do not push. Finish with `git log --oneline -8` and five lines a human must verify.
