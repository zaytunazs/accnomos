# Robustness pass (branch `claude/robustness`)

## What was built

1. **Dashboard tile isolation.** `app/dashboard.py` runs each read through `_Reads`. A parse error still gives `null` + `unavailable`; any other failure (storage or Graph 5xx/4xx) marks only the tiles that needed that read `{"error": "Couldn't load this just now"}`, with no internals in the message. Graph 401/403 still propagates, so the whole request is a 401 (re-sign-in). Audit, Autopilot audit and last-scan reads are isolated too (activity becomes empty, named in `unavailable`). Web: `RtTileError`/`tileData` in `lib/runtime.ts`; Home tiles, Deadlines, the VAT strip and Ask suggestions show "Couldn't load this just now" instead of crashing.
2. **Mail size.** `GraphMailSender` now builds the JSON, checks the encoded request against `MAX_REQUEST_BYTES = 4,000,000` (a cautious reading of Graph's 4 MB) and sends exactly those bytes. Over it: a clear `ValueError`, nothing sent. The upload-session route (draft + attachment upload) is not built.
3. **Files count.** Home of the bug was `LiveFiles.loadTree`: it summed subfolder `childCount` (files + folders). It now lists each subfolder and counts files only; the row says "N files, M folders" when folders exist. Nothing in the runtime counted files (only the test-mode fake Graph reports `childCount`), so no runtime change was needed.
4. **Payroll rates.** `tests/test_payroll_rates.py` pins every constant and fails if a new numeric constant is added unpinned. Figures were checked against GOV.UK "Rates and thresholds for employers 2026 to 2027" and the income tax rates page on 27 Oct 2026: PT £12,570, ST £5,000, UEL £50,270, 8% / 2% employee, 15% employer, PA £12,570, basic band £37,700, additional threshold £125,140, 20/40/45%. All matched the code; nothing changed.
5. **`MarkInvoicedBody.entry_ids`** was already capped at 1000 (the docs said unlimited); now `MAX_MARK_ENTRIES = 500`, 422 above it, test at 500 and 501.
6. **Deadlines `assumed`.** `VatCycle.assumed` is true for quarterly returns with no `stagger`/`start_month` sent; `/books/deadlines` and the dashboard VAT block return `"assumed"`. Home now sends no query when no business is saved (it used to send `stagger=1`, which hid the assumption) and the Deadlines section shows "Assuming Mar/Jun/Sep/Dec quarters — set yours in Settings" (links to Settings).
7. **Tax year.** `app/taxyear.uk_tax_year_start` is the only definition; `mileage.tax_year_of` uses it, contacts/projection import it. Old `contacts.uk_tax_year_start` removed.

Also: `audit_view.py` had a `"07 Reports"` literal that failed `test_paths.py::test_no_folder_name_literal_outside_paths_py` on `main`; it now uses `paths.REPORTS`.

`docs/REMAINING.md` and `docs/HONESTY.md`: rows for items 3, 5, 7 removed; items 1, 2, 4, 6 reworded to what is still true (phone does not send a stagger so it never shows the note; phone does not read the tile error marker; big attachments unsupported).

## What I verified

From the worktree root, `source .v/bin/activate`, `PYTHONPATH=packages/ledger/src:packages/connectors/src:services/runtime`:

- `python -m pytest services/runtime packages -q` -> **1022 passed, 1 skipped** (was about 1,008; 1 pre-existing failure fixed).
- `ruff check services/runtime packages` clean; `ruff format --check services/runtime packages` clean (128 files).
- `cd apps/web`: `pnpm exec eslint .` clean; `pnpm run build` OK; `pnpm exec tsc --noEmit` clean after the build (before a build it reports only the generated `LayoutProps` type missing, unrelated).
- Playwright on ports 3400/9081 (`E2E_WEB_PORT=3400 E2E_RUNTIME_PORT=9081`, `pnpm run e2e:build`, then `pnpm exec playwright test e2e/files.spec.ts e2e/home.spec.ts e2e/settings.spec.ts --project=desktop`) -> 14 passed, including the new Files count test and two Home deadline tests.

## What remains

- The full Playwright suite was not run (only files, home, settings), nor the phone project.
- Mail: no upload-session path for attachments over about 3 MB; the 4,000,000 limit is a conservative reading of Graph's "4 MB", not tested against real Graph.
- Files: one extra Graph call per month folder on each load of /files (parallel); not tried against a real OneDrive.
- Android: no per-tile error handling, no stagger sent, so no "assumed" note. Flutter not run.
- The tile-error message is generic; the cause is only in the server log.
