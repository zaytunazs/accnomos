# Task: Reports — profit and loss, aged debtors/creditors, VAT summary: computed by code, written to `07 Reports/`, shown on /reports

Accnomos monorepo (public; UK English; no secrets; stateless runtime; money in integer pence; no model calls in this feature).
Read first `packages/ledger/src/accnomos_ledger/*` (accounts, VAT, bank), `services/runtime/app/{projection.py,contacts.py,facts.py,
paths.py,books.py}`, `apps/web/src/lib/runtime.ts`, `components/home/Tiles.tsx`, `docs/ARCHITECTURE.md` (chart of accounts), `tools/seed_demo.py`.

## Deliverables
1. `app/reports.py`: pure functions over the ledger events — **P&L** for a period (sales, cost of sales, overheads by account, net
   profit; cash-basis vs accrual toggle is NOT in scope: say "as approved"), **aged debtors/creditors** (reuse contacts' ageing),
   **VAT summary** (per period from `compute_vat_return`), **monthly trend** (12 months of sales/purchases/net). Tests with a hand-built
   ledger whose totals are worked out on paper in the test.
2. `GET /reports/pl?from=&to=`, `/reports/aged`, `/reports/vat?periods=4`, `/reports/trend`; `POST /reports/export` writes
   `07 Reports/<yyyy-mm-dd>-<name>.xlsx` (openpyxl, same style helpers as Books.xlsx, SAMPLE label when the books are the sample) and
   returns the file ref. Reports never post anything.
3. Web `/reports`: period picker (same component as VAT), P&L table with account rows, aged tables, 12-month bars (inline SVG, no
   library), "Export to OneDrive" and "Print" (print stylesheet); signed out shows the labelled sample. Nav entry under *Money*.
4. Books.xlsx gains a `P&L` sheet (the current VAT period) so the download has it; README row + ARCHITECTURE table; e2e spec.
Commit in small steps; do not push. Finish with `git log --oneline -8` and five lines a human must verify.
