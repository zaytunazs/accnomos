# Review: `claude/reports`

Second-agent review of the Reports task (`TASK_BRIEF.md`): P&L, aged debtors/creditors, VAT summary and 12-month trend
by code, `07 Reports/` export, `/reports` page, Books.xlsx `P&L` sheet.

## What was checked

- `services/runtime`: `pytest -q`, 837 passed, 1 skipped (834 before the review). `ruff check` and `ruff format --check` are clean.
  No `packages/*` or `services/hmrc-relay` files changed, so those suites were not re-run.
- `apps/web`: `pnpm run build` passes, and `eslint` is clean on `src/components/reports` and `e2e/reports.spec.ts`.
- Read the whole diff for these points:
  - Pence and Decimal: VAT boxes come from `Decimal` and go through `int(... * 100)` exactly.
  - Span order: `recent_periods` is newest first, so the event read range in `/reports/vat` is right.
  - Undo: reversals count on their own date.
  - The GETs write nothing, not even audit lines (tested).
  - Export never overwrites (`free_path`), audits once and posts nothing (tested).
  - Strict body: unknown fields and kinds are refused.
  - No model call.
  - No secrets or user data kept server-side beyond the user's own OneDrive and audit.
  - UK English throughout.

## What I fixed

- `f83a668`: Signed in to the demo seed's books, `/reports` showed sample figures with no label, even though the runtime
  sends `sample: true`. The page now shows "SAMPLE — FICTIONAL COMPANY · these are the demo books", and it prints too.
  "1 approved entries" is now "1 approved entry" on the page and in the .xlsx, and the e2e spec expectation was updated.
- `394ebb3`: New tests:
  - `/reports/aged` equals `/contacts/aged` (the brief's "reuse contacts' ageing").
  - The VAT summary for monthly returns (`months=1`), figures worked out by hand, and `periods=10` refused.
  - Singular "entry" on the sheet.

## What remains

- **e2e not run.** `e2e/reports.spec.ts` (and the page sweeps) were not run in this review. Ports 3100/8781 are taken by
  servers from another checkout, and Playwright reuses them (`reuseExistingServer`), so a first attempt hit an old build
  (404 on `/reports`). Rebuilding on other ports (`E2E_WEB_PORT`/`E2E_RUNTIME_PORT`) needed a permission I did not have.
  Run `pnpm run e2e` on free ports before merging.
- **`sample` on `/reports/pl`, `/vat` and `/trend` is partial.** It only looks at the events in the requested range, so a
  period with no seeded entry says `false` (documented in `test_the_demo_books_are_the_sample`). The page now shows the
  label if any report says `sample`, and `/reports/aged` reads the whole ledger, so seeded books are still labelled. A
  direct API caller can still see `false`.
- The Books.xlsx `P&L` sheet uses calendar quarters whatever the stagger. README already says so.
- The exported .xlsx has never been opened in Excel, and there has been no real OneDrive run. Android has no Reports
  screen. README already says all of this.

## How to verify by hand

Run the runtime in test mode and `pnpm dev` in `apps/web`, then open `/reports` signed out. You should see the
"SAMPLE — FICTIONAL COMPANY" banner and the Jul–Sep 2026 P&L (gross £15,920.00, net £7,705.00). Check that bars, debtors,
creditors and VAT by period are all present, and that *Print* preview hides the nav and buttons but keeps the sample line.
Sign in with the fake account, create the books folder, and approve one receipt dated in Jul–Sep. Pick Jul–Sep 2026: the
receipt's net (not its VAT) should appear under Overheads, with "1 approved entry". Click *Export to OneDrive*. One new
`07 Reports/<today>-reports.xlsx` should appear and nothing new under `_System/Ledger/events`. Open the file and check the
About, P&L, Debtors, Creditors, VAT summary and Trend sheets. Finally, *Rebuild Books.xlsx* and check that its `P&L` sheet
shows the current calendar quarter.
