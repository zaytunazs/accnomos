# Task: Files page live + Books.xlsx rebuild verified + VAT deadlines (F12-lite)

Accnomos monorepo (public; UK English; no secrets). Read first: `apps/web/src/app/files/page.tsx` and `components/files/*`,
`apps/web/src/lib/graph.ts`, `services/runtime/app/{projection.py,routes_bank.py,books.py}`, `packages/ledger/src/accnomos_ledger/vat.py`,
`apps/web/src/components/home/Deadlines.tsx`.

## Deliverables
1. **Files page live**: when signed in, list the books folder tree from Graph (folders `00 Inbox` … `05 VAT returns`, `_System` collapsed),
   with file counts, sizes, last modified, and "Open in OneDrive" links (`webUrl`). Keep the current sample as the signed-out demo.
2. **Books.xlsx**: confirm `projection.py` rebuilds `Books.xlsx` after approve/undo (call it from the approve path if not already);
   add a runtime `POST /books/rebuild` and a "Rebuild Books.xlsx" button on Files; the workbook needs sheets `Ledger`, `VAT`, `Suppliers`,
   `Summary` with UK formatting (£, dd/mm/yyyy), frozen headers, and a `README` sheet stating the file is generated. Tests with openpyxl on a
   synthetic ledger (totals per sheet match the events).
3. **VAT deadlines**: `GET /books/deadlines` computing, from the business's VAT quarter (settings: stagger group 1/2/3 or custom start month),
   the current period end, the filing/payment deadline (1 month + 7 days after period end), days remaining, and the Box 5 estimate so far;
   bind the Home `Deadlines` tile to it when signed in (fallback to sample). Add the stagger setting to `/connect/business` and Settings.
4. `pnpm run build` passes; README rows updated honestly.

Commit in small steps; do not push. Finish with `git log --oneline -8` and five lines a human must verify.
