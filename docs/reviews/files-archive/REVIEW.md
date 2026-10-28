# Review: archiving and file management

Branch `claude/files-archive` (from `main` at 206848c). Archiving, backups and file tools for books with many files.
The design is in `docs/ARCHITECTURE.md` (*Files, archive and backups*); what is not proven is in `docs/HONESTY.md`.

## What changed

**Runtime** (`services/runtime/app`)
- `files.py`: the tree walk (each folder listed once per request), the storage overview (per folder, per tax year,
  10 largest, duplicate sets), the search index (date, tax year, type, archived, protected, and the linked ledger
  entry's net + VAT from the event), move, rename (`safe_name`), Clean up to `_Trash`, and the year rules
  (`year_of`: UK tax year or a financial year ending on any month end; `file_date`: linked document date, then name,
  then folder, then modified).
- `archive.py`: preview, run (optionally `Archive/<year>.zip` with `manifest.json`), list and undo.
- `backups.py`: back up (`_System` → zip + manifest + `.sha256`), retention to `_Trash`, verify, restore preview,
  restore (typed `RESTORE` unless the books are empty), settings, monthly check.
- `routes_files.py`: `/files/overview`, `/files/index`, `/files/move`, `/files/rename`, `/files/trash`,
  `/files/archive/preview`, `/files/archive`, `/files/archive/runs`, `/files/archive/runs/{id}/undo`, `/backups`
  (GET, POST), `/backups/auto`, `/backups/settings`, `/backups/verify`, `/backups/restore/preview`, `/backups/restore`.
- `books.py`: the redirect map `_System/archive/map.json` (`moved_paths`, `record_moves`, `follow`), applied in
  `get_proposal`, `list_proposals` and `stored_bank_lines`.
- `paths.py`: `ARCHIVE`, `BACKUPS`, `TRASH`, `ARCHIVE_SYSTEM`, and README.txt lines for them (regenerated
  `folders.json` and `folders.ts` with `tools/gen_folders.py`).
- `audit_view.py`: sentences for `files_moved`, `file_renamed`, `files_trashed`, `files_archived`, `archive_undone`,
  `backup_created`, `backup_verified`, `backup_restored`, `file_settings_saved`; agent labels `backup`, `files`.
- `testmode.py`: the fake OneDrive hands out the same `onedrive.test.invalid` links as the Graph look-alike, so
  *Show in OneDrive* is visible in e2e.

**Connectors**: `FileRef.content_hash` (`"<algorithm>:<hex>"`; Graph `sha256Hash`, else `quickXorHash`, else
`sha1Hash`; the fake gives sha256), and an optional `web_base` on `FakeStorageProvider`.

**Web** (`apps/web/src/components/files`): `FilesManager` (on the Files page under the tree) with `StorageOverview`
(including Clean up), `FileSearch` (search, filters, select all shown, bulk move, rename), `ArchiveYears` (tax or
financial year, preview, archive, zip option, runs with Undo) and `BackupsPanel` (Back up now, Check, Restore with
preview and the typed word, keep-last-N, monthly switch); `MonthlyBackup` in the app shell; `filesApi` in
`lib/runtime.ts`.

**Android**: `StorageCard` at the top of the Files screen (totals, biggest folders, tax years, duplicate count,
*Back up now*), `storageOverview()` and `backUpNow()` in `RuntimeClient`, `models/storage.dart`, a `PARITY.md` row.

## Decisions
- **Redirect map, not rewriting records.** Proposals and bank-line files are left as written; the map is applied when
  they are read back. Fewer writes per archive run, Undo is one more map update, and a path saved by an older app
  version still resolves. The cost is one read of `map.json` per request that lists proposals or bank lines (a miss
  when there is no map; misses are forgotten after a write in the same request, so a write-heavy request can pay it
  twice). Records the app saves anyway (an approval re-saves its proposal) pick up the new path naturally.
- **Archive scope.** Invoice and credit note records and PDFs, and VAT returns, are not archived: `invoicing.py`,
  `credit_notes.py` and `approve.py` (the submitted-period lock) read them at fixed paths. Inbox and Needs a look are
  not archived either (unfinished work). `07 Reports/Exports` zips are reports and do move.
- **"Older than a chosen year"** is read as "up to and including the chosen year"; the current year is refused.
- **The year zip is a copy.** The folder stays, so links keep working; deleting it is the user's call.
- **Restore never replaces append-only files.** A ledger event or audit file that differs from the backup is *kept*
  (shown in the preview); only missing ones are added. Other changed files go to `_Trash` before the backup's copy is
  written. "Empty books" means no ledger events and no proposals.
- **Monthly backup is off by default** and only runs from the web app shell on a device where it was switched on, so
  no other e2e test and no unsuspecting user gets an extra request or file.
- **Retention and Clean up move to `_Trash`**, never delete; `_Trash/<date>/` keeps the original path below it.
- Rename keeps the old extension only when the new name has none; a different extension typed by the user is allowed.
- Characters OneDrive refuses become spaces in a new name (`Novex: "August"?` → `Novex August.pdf`).

## Tests
- `services/runtime/tests/test_files_archive.py` (25, all on `FakeStorageProvider`): year and date rules; overview
  counts, largest, duplicates by listed hash and by reading same-size files; the index's ledger amount and protected
  flags; archive preview refuses the current year; archive leaves every ledger event byte for byte, and the proposal,
  bank line and bank statements list lead to the archived copies (link integrity), with the map stored; undo, undo
  twice refused, re-archive after undo with no cycle; a file moved since is skipped on undo; a run that fails part way
  records what it moved and can be undone; the year zip's manifest hashes; map chains and cycles; move and rename keep
  links and refuse protected files and `_System`; Clean up refuses linked documents; backup zip contents (events,
  proposals, audit, bank) and checksum; same-day `(2)`; verify catches a changed zip and a missing checksum; retention
  keeps the newest 2 and moves the rest with their `.sha256`; restore preview statuses, refusal without and with the
  wrong word, restore with `RESTORE` (audit appended to, not replaced); restore into empty books without confirmation;
  a zip-slip path refused; monthly backup once a month and only when on; routes, X-User on every write, 404/409/422.
- `test_security_routes.py`: the two preview routes listed as needing no X-User (they write nothing).
- `packages/connectors/tests/test_msgraph.py`: hashes read from Graph items.
- e2e `apps/web/e2e/files-manage.spec.ts` (5): Storage and Clean up; Find files with name, amount and type filters,
  *Show in OneDrive* href, rename, bulk move and the proposal's `file_path` after it; archive preview → archive with
  zip → search archived → undo, ledger events unchanged, audit sentences; backups: back up, check, restore refused
  until RESTORE is typed (button and API 409), the replaced file in `_Trash`, keep-last setting; the tools at 360 px.
- Android `test/storage_card_test.dart` (4): parsing, the card at 360 dp reading only, Back up now, a refused backup.

## Gates run here
- `cd services/runtime && python -m pytest -q`: all pass (1251 passed, 1 skipped). `packages/connectors`: 49 passed.
- `ruff check .` and `ruff format --check .` (0.17.3): clean. `pyright` (1.1.414) on `services/runtime/app` and the
  whole repo config: 0 errors.
- `cd apps/web && pnpm install --frozen-lockfile && pnpm exec eslint . && pnpm run e2e:build`: pass.
- `pnpm run e2e:test` with `CI=1 E2E_WEB_PORT=3250 E2E_RUNTIME_PORT=8820 E2E_RELAY_PORT=8821`: every test of this
  branch passes, including the five new ones and the phone, accessibility and 360 px sweeps of `/files`. **Five
  existing tests fail in this container, identically on a clean `main`**: `site-health.spec.ts` hardcodes port 3100
  (these ports are 3250), and `invoices.spec.ts`, two in `invoice-payments.spec.ts` and the `/vat` step of
  `keyboard.spec.ts` fail because the container's Chromium (1243) is not the build the pinned Playwright expects, so
  it ran full Chromium (via a local, uncommitted config's `executablePath`), whose built-in PDF viewer loads
  `chrome-extension://` URLs the local-only guard counts as leaving 127.0.0.1. On CI's own browser these should behave
  as on `main`; not verified here.
- Flutter 3.47.8 (Dart 3.13.7, fetched for this run): `flutter analyze` no issues; `flutter test` 267 passed.

## Untested / follow-ups
- Nothing has run against a real OneDrive or Graph (walk time, hashes per account type, throttling, upload of zips
  over 60 MiB; see HONESTY).
- The Files page reads the overview and the index separately, walking the tree twice; one endpoint could serve both.
- A restore over books that were archived since the backup brings back the older `map.json` (it is not append-only),
  so links to documents archived after the backup follow the older map until the next move. Rare; not handled.
- Android has no Clean up, archive or restore (web-only by design, see `PARITY.md`), and no monthly backup.
- The archive and backup panels are not offline-aware; a failed call shows the runtime's sentence.
