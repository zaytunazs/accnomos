# Handover: reports and exports (branch `claude/exports`)

**Done.** Export registry with one preview, download and save route (`services/runtime/app/exports/`,
`app/routes_exports.py`). About 40 reports in Xero's groups: financial statements; payables and receivables;
reconciliations; taxes and balances (including the HMRC 9-box return, VAT detail, MTD digital links and VAT
reconciliation); transactions. 23 vendor import files (Xero, QuickBooks Online, Sage 50, Sage Accounting, FreeAgent) with an
editable mapping in `_System/exports/mappings.json`. The Accountant pack zip, the open ledger JSON and favourites. Reserved ids
and optional plugins for payroll, Income Tax, accounting-tools and sales-purchases. Web page `/reports/exports`. Docs:
`docs/ARCHITECTURE.md`, `docs/HONESTY.md` and `REVIEW.md` (sources, risks, what an accountant should check).

**Gates so far.** `tests/test_exports.py`: 79 passed. The runtime suite, run in chunks, passes except
`test_sample_books.py::test_a_second_press_while_running_or_after_is_the_same_run`, which also fails on the untouched base
commit 206848c on this loaded machine (a timing race). ruff check and format are clean; pyright reports 0 errors; eslint is
clean on the changed files; `e2e:build` passes.

**Left.**
- e2e is not yet green. In `e2e/exports.spec.ts` the 360 px test passed. The signed-in test failed at the download file name
  (fixed in the last commit: the browser cannot read `Content-Disposition` cross-origin, so the page now uses the preview's
  name) and on load timeouts.
- Re-run that spec, then the full suite, with
  `CI=1 E2E_WEB_PORT=3150 E2E_RUNTIME_PORT=8795 E2E_RELAY_PORT=8803 E2E_PYTHON=../../.v/bin/python` set for both
  `pnpm run e2e:build` and `pnpm run e2e:test`. On a loaded machine the 60 s server start can time out.
- Fill in the gate counts at the end of `REVIEW.md`.
- Not pushed: the brief said not to push.

**Test.** `cd services/runtime && python -m pytest -q tests/test_exports.py`. The golden files are in
`tests/fixtures/exports/`; regenerate them with `UPDATE_GOLDEN=1` only after checking a vendor's template.
