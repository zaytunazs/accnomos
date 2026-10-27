# Review: `claude/folder-names`

Second-agent review of the "one source of truth for the books folder layout" task (`TASK_BRIEF.md`), 27 Oct 2026.

## What was checked

- `services/runtime`: `pytest -q` → 668 passed, 1 skipped (667 + 1 before this review; one test added).
- `packages/connectors`: `pytest -q` → 37 passed.
- `packages/ledger` and `services/hmrc-relay` were not touched by the branch and were not re-run.
- `apps/web`: `pnpm run build` passes.
- `apps/web`: `pnpm run e2e` (test mode) → 41 passed, 4 failed. All four (`invoices`, `jobs`, `payroll`, `review-vat`) fail at
  the same step and with the same message as on `main` 18dd9f4, on copy that has nothing to do with folders ("No invoices yet.",
  "set in Settings › Business › Staff", "Nothing waiting", "Create invoice from unbilled hours"). The folder specs pass:
  `files.spec.ts` (live tree in canonical order; old name renamed, old + new side by side warned) and `bank.spec.ts`
  (`04 Bank statements/`). In `payroll.spec.ts`, the `05 Payroll/2026-10.csv` assertion comes after the step that fails, so it
  never runs.
- `flutter analyze` not run (no SDK). The Dart change is the generated list only.
- I read the whole diff against the brief: `app/paths.py`, `app/layout.py`, the connector folder move (fake and Graph), every
  runtime import switch, `tools/gen_folders.py`, `folders.json` / `lib/folders.ts` / `graph.dart`, the web onboarding and Files
  warning, e2e, docs. There are no secrets, nothing about the user is stored server-side (`/health` reports counts only; the
  per-token cache keys are SHA-256 hashes), and nothing is copied or deleted.

## What I fixed

- `5737658` runtime:
  - Home's cash tile named a bank statement by its pre-rename path (`03 Bank statements/…`). It now goes through
    `paths.upgrade()`, as the Bank page already did, with a test.
  - `/books/vat/periods` `status_source` spelt `06 VAT returns` as a literal. It now uses `paths.VAT_RETURNS`.
  - `test_paths.py` only caught a name at the start of a string or after `/`, which is how the literal above got through.
    It now also catches any current or old folder name anywhere in a non-docstring string. The self-test covers this, and a
    date like "05 Oct" does not trigger it.
- `1261c77` docs:
  - In `docs/ARCHITECTURE.md`, the "Old folder names" paragraph had been put in the middle of the layout table, cutting off
    the `Books.xlsx` row. The table is whole again.
  - The paragraph now says which saved paths are *not* rewritten (Books.xlsx `Bank`/`Proposals` sheets). It also says that
    anyone who raised an invoice before will see the `02 Sales invoices` / `03 Sales` side-by-side warning.
  - Added a README "What works today" row for the folder layout, marked not yet run against a real OneDrive.

## What remains

- **Never run against a real OneDrive.** The folder rename (Graph PATCH of a folder's `name` + `parentReference`), its 409 when
  the target exists, and a folder open in the OneDrive sync client are tested only against a mock transport and fake storage.
  Personal and work accounts both need a run.
- **Expected warning for most existing users:** invoicing already wrote `03 Sales/invoices`, so anyone who invoiced has an
  (empty) `02 Sales invoices` beside `03 Sales`. The Files page says that the old folder is empty and can be deleted; nothing
  removes it automatically, as the brief requires.
- Saved paths are not rewritten. A proposal's `file_path` and a bank line's `source_file` are mapped through
  `paths.upgrade()` only when a document is filed and when statements are listed (Bank, Home). Three places still show the
  old path: the Books.xlsx `Bank` and `Proposals` sheets, and the message on a proposal made from a bank line
  (`bank_actions.py`).
- `Books.statements()` applies `upgrade()` even when the old folder is still there (conflict case), so it can name a statement
  under `04 Bank statements/` while the file is still in `03 Bank statements/`.
- `GET /books/layout` runs `migrate()`, so a GET can move folders. In practice `get_books` has already done the move, but it is
  still a side effect on a GET.
- Two first requests with the same new token at once may both try to rename. The loser's error is logged and swallowed, and the
  next request re-checks. This has not been tested against Graph.
- In test mode the layout check runs on every request (`cache=False`), so `/health` `folder_layout.checks` counts requests,
  not sign-ins, there.
- The web UI still spells *current* folder names literally in about 15 strings (`UploadToInbox`, `LiveReview`,
  `OutlookIntake`, `LiveBank`, `InvoiceForm`, `LiveInvoices`, `ReadyPanel`, `sample-home`, `sample-ask`). `test_paths.py`
  stops *old* names coming back in web code, but a future rename would have to change these strings by hand.
- The README "Checked 27 Oct 2026" paragraph still quotes older test counts (runtime 607, connectors 34).
- The 4 e2e failures that are already on `main` (above) remain. They are not caused by this branch.

## How to verify by hand

Run the runtime tests from `services/runtime` with this checkout on the path (`pytest -q -o pythonpath="<repo>/services/runtime
<repo>/packages/ledger/src <repo>/packages/connectors/src"`); `tests/test_layout.py` and `tests/test_paths.py` cover the rename
and the single source. Then, on a real OneDrive (personal account first), before signing in to this build:
1. Create `03 Bank statements` with a CSV inside, `04 Payroll`, and both `05 VAT returns` and `06 VAT returns`.
2. Sign in and open Files. Check that `03 Bank statements` is now `04 Bank statements` with the same file and the same
   modified date (moved, not copied), and that `04 Payroll` is now `05 Payroll`.
3. Check that the page shows "Old and new folders side by side" for the VAT pair and that both VAT folders are untouched.
4. Check that `_System/audit/<yyyy-mm>.jsonl` has one `folders_renamed` line and that `/health` shows `folder_layout` counts
   and no folder names.
5. Reload and confirm nothing more changes.
6. Run onboarding on an empty account and confirm that it creates `00 Inbox` … `07 Reports`, `03 Sales/invoices/sent` and a
   README.txt that lists the same eight folders.
