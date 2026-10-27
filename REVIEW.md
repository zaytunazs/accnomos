# Review: `claude/files-books`

Task (see `TASK_BRIEF.md`): live Files page, Books.xlsx sheets + rebuild, VAT deadlines (F12-lite).

## What was checked

- `pytest -q` in `services/runtime` (91 passed after review), `services/hmrc-relay` (39), `packages/ledger` (15), `packages/connectors` (17).
- `cd apps/web && pnpm run build`: passes (all 12 routes static, type-check clean).
- Read the full diff: `deadlines.py` date maths (1 month + 7 days, leap years, staggers, year-end periods), `GET /books/deadlines`
  validation (422/400/401), `projection.py` sheets and pence→£ conversion, approve/reject/bank-match → `rebuild_safely`,
  `POST /books/rebuild`, `LiveFiles.tsx` (read-only Graph calls, paging), `Deadlines.tsx`, stagger setting in onboarding and Settings
  (stored only in `localStorage`, nothing server-side), README rows.
- Product rules: no user data persisted by the runtime; Box 5 and totals are computed by code, not a model; sample data labelled.

## What I fixed

| Commit | Fix |
|---|---|
| `b3dc1e2` | `services/runtime/pyproject.toml`: pytest `pythonpath = ["."]`. Bare `pytest -q` failed to collect (it picked up another checkout's `app` package from the shared venv); only `python -m pytest` worked |
| `b15bc30` | Books.xlsx `Summary` counted a reversed purchase as still live (sales/purchase counts, net and VAT), so it disagreed with `Suppliers` and `VAT`. Reversals now net off against the original's kind; test extended |
| `c42e7b1` | Files: the sample fallback said "SAMPLE · FICTIONAL COMPANY" (not the house label), and the read-error fallback showed sample data with no label. Both now say "SAMPLE — FICTIONAL COMPANY" |
| `ef49eb2` | Home deadlines: the runtime fell back to its own `date.today()` (UTC on most hosts), so days-left was a day out from 00:00 to 01:00 BST. The web now sends today's `Europe/London` date |
| `ae74428` | README claimed the tests check "each sheet's totals"; they check `Ledger`, `Suppliers`, `Summary` and `VAT` |
| `26ef1e6` | New test: Books.xlsx is rebuilt after a reject (only approve was tested) |

## What remains

- **No undo approval exists**, so the brief's "rebuild after undo" has nothing to hook into; rebuild runs after approve, reject and bank match only.
- **Pre-existing, not from this branch:** `packages/ledger/.../vat.py` decides whether a reversal is of a sale with `ln.credit and "Sales" in ln.account`, but reversing a sale *debits* Sales, so a reversed sale would be subtracted from purchases instead of sales. It is latent (nothing creates reversals yet) but must be fixed before undo ships.
- Nothing has been run against a real OneDrive or runtime: Files tree, *Rebuild Books.xlsx*, Home deadlines and opening Books.xlsx in Excel are build-checked only.
- Signed in with no saved business settings, Home deadlines assume stagger 1 without saying so. Annual accounting shows the sample tiles (Settings says this).
- Files: a top-level folder's "N files" adds its sub-folders' `childCount`, which counts nested folders as well as files (one level only).
- `GET /books/deadlines` returns `start_month` normalised to 1–3 (the first period-start month of the stagger), not the custom month sent. It is consistent and tested, but the field name may surprise a reader.
- `TASK_BRIEF.md` is committed on the branch (`7170b0a`); drop it before merge if briefs should not land on `main`.

## How to verify by hand

Run the runtime (`uvicorn app.main:app` in `services/runtime`) and the web app (`pnpm dev` in `apps/web`), then sign in with a Microsoft
account that has finished onboarding. On **Files**, check the folders `00 Inbox` … `06 Reports` appear in order with file counts, sizes and
dates, that `_System` is collapsed until clicked, and that every *Open* link and the top *Open in OneDrive* button open the right OneDrive
folder. Press *Rebuild Books.xlsx*, open the file in Excel and check the `README` note, the frozen header rows, £ and dd/mm/yyyy formats, and
that the `Ledger` totals row matches `Summary`. In **Settings → VAT periods** pick stagger 2. On **Home**, *Deadlines* should show the
Aug–Oct 2026 period ending 31 Oct and due 7 Dec, and Box 5 should match `/vat` for the same quarter. Signed out, Files and Home should show
the labelled sample.
