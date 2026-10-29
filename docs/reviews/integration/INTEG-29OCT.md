# Integration 29 Oct 2026: upload-flow + app-shell + meta-models-page + video-capture

Branch `integ/29oct`, from `origin/main` (`d8155a12`), no push. One merge commit per
branch, in order, each with `git merge --no-ff --no-edit`.

## 1. `claude/upload-flow` — head `105e9457`

Owns the scan/upload pipeline: background scan jobs (`POST /books/scan/jobs`,
`app/scan_jobs.py`, `app/routes_scan.py`), per-file progress, type classification
plus confirmation. Merged cleanly (`f271c218`).

## 2. `claude/app-shell` — head `63de4f65`

Merge commit `17f616f0`. Conflicts in the five files named in the plan, resolved
for the scan pipeline in favour of upload-flow (HEAD side) everywhere:

- `services/runtime/app/inbox.py`: kept `ScanContext` / `scan_context` /
  `read_one` / `commit` / `finish` / `scan_inbox_detailed(..., skip=)`. Kept
  app-shell's `Waiting` / `waiting()` (they only list Inbox files). Dropped
  app-shell's `scan_inbox_detailed(..., only=)` variant.
- `services/runtime/app/routes_books.py`: kept the `busy = claimed(...)` scan
  route; removed the app-shell `path` query parameter. Kept the `/books/inbox`
  route on `waiting()`.
- `apps/web/src/lib/runtime.ts`: kept `startScan` / `scanJob` / `scanJobs` /
  `confirmScan`; dropped `inboxWaiting` / `scanOne`.
- `apps/web/src/components/review/ScanProgress.tsx` and `LiveReview.tsx`: took
  upload-flow's versions whole (the diff between the two sides was scan-only).
- Deleted `apps/web/src/lib/scan-queue.ts` (the per-file `only=` loop) and
  `apps/web/src/components/AppShell.tsx`'s `ScanStatus` strip (the top bar's
  `ScanBadge` already shows job progress on every page).
- Deleted `apps/web/e2e/scan-progress.spec.ts`: it tested only the dropped
  per-file UI ("Reading 1 of 2", per-document timeouts, carry-on). The same
  behaviour is covered by `upload-flow.spec.ts` (per-file progress rows,
  "the reading carries on when you leave the page; the top bar shows the count",
  Outlook intake starting the same reading).
- `services/runtime/tests/test_books.py`: the `only=` test became
  `test_scan_skip_leaves_a_named_file_to_its_job`, asserting the same
  single-file scoping through the kept `skip=` mechanism (adapted, not deleted).

Every non-scan part of app-shell was kept: top bar, footer, menu pages, previous
files, full backups / Back up now, accountant gating, coming-soon removal.

## 3. `claude/meta-models-page` — head `aaca220d`

Merge commit `d8a66e1c`. Eight conflicts, each kept both sides:

- `apps/web/e2e/pages.ts`: `/meta-models` was already listed (added by
  app-shell); kept HEAD rows including `/join` (added by app-shell; the incoming
  branch never had it — no deletion, just divergence).
- `apps/web/e2e/signed-out.spec.ts`, `site-layout.spec.ts`,
  `apps/web/src/lib/public-site.ts`: `PUBLIC` sets are now the union, with both
  `/meta-models` and `/join`.
- `apps/web/src/app/meta-models/page.tsx` (add/add): took the incoming
  dedicated page (the HEAD side was a two-line re-export of `/models`).
- `apps/web/src/components/AppShell.tsx`: took the HEAD structure (incoming was
  the pre-app-shell layout); the incoming footer link to `/meta-models` was
  preserved by adding it to `AppFooter` (nav "About"), which the
  `meta-models-page.spec.ts` test clicks.
- `apps/web/scripts/prelaunch-words.mjs` + `submission-mode.spec.ts`: kept the
  `NOT_YET_WORDS` / `prelaunchHits(text, extra)` shape and added the incoming
  `THIRD_PARTY_NAMES` check to every page sweep, the Settings-tabs sweep, the
  phone menu and the account menu.

## 4. `claude/video-capture` — head `dfe32320`

Merged cleanly (`d27f2b6f`), no conflicts.

## Fixes found by the gates (all pre-existing on `origin/main` on this Windows box, or introduced by a merged branch)

- `test_paths.py` (introduced by upload-flow): twelve `"00 Inbox"` literals in
  user-facing messages (`inbox.py`, `scan_jobs.py`, `routes_scan.py`) now use
  the `INBOX` constant, as `month_end.py` / `routes_cis.py` already do. Same
  rendered text.
- `UnicodeDecodeError` on Windows (cp1252) reading UTF-8 repo files: added
  `encoding="utf-8"` to `read_text()` in `test_security.py`,
  `test_security_routes.py`, `test_audit.py`, `test_docs.py`, following
  `test_paths.py` which already does this. Assertions unchanged.
- `home_overview.py`: `%-d` in two date formats is not portable to Windows;
  now `f"{x.day} {x:%b %Y}"`, the convention `vat_schemes.py` documents.
- `test_import_history.py`: path keys now `.as_posix()` (backslashes on Windows
  broke the expected-dict comparison). Same assertion on Linux.
- `test_early_access.py`: the three `0o600` permission assertions are guarded
  by `sys.platform != "win32"` (Windows has no Unix permission bits; the files
  stay `0o666` there). They still run on Linux CI.
- `app-shell.spec.ts`: the AI-line test now expects the merged `/meta-models`
  heading ("Meta models in Accnomos", was "Meta models at work").
- `menu-pages.spec.ts`: wait for the first Main-menu button before collecting
  items — `.all()` does not wait, so under parallel load it read the menu
  before hydration and found zero buttons.

Environment notes: a bare `uv sync --frozen` pruned the workspace venv, so it
was restored with the CI command (`uv sync --frozen --all-packages
--all-extras`); e2e used `E2E_PYTHON` pointing at the workspace venv, as CI does.

## Gate totals (all green)

- `uv run pytest services/runtime -q`: **2428 passed, 6 skipped**
- `uv run pytest packages/ledger -q`: **101 passed**
- `uv run ruff check .`: clean; `uv run ruff format --check .`: 620 files clean
- `uv run pyright services/runtime/app`: **0 errors** (with `--pythonplatform
  Linux`, as CI runs; on Windows two pre-existing `fcntl` hits appear in
  `early_access.py`, a file no branch touched)
- `pnpm exec eslint .`: clean; `pnpm exec tsc --noEmit`: clean
- e2e (`e2e:build` + `e2e:test`): **523 passed, 94 skipped, 2 flaky
  (both `cis.spec.ts`, passed on retry), 0 failed**
