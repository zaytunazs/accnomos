# Review: `claude/demo-seed`

Second-agent review of the demo seed (`TASK_BRIEF.md`): `tools/seed_demo.py`, `tools/seed_demo.md`,
`services/runtime/tests/test_seed_demo.py`.

## What was checked

- `services/runtime`: `pytest -q` with this checkout's `services/runtime`, `packages/ledger/src` and `packages/connectors/src`
  on the path (the shared venv's editable installs point at another lane): **625 passed, 1 skipped** (the Graph test, no token).
  `packages/*`, `services/hmrc-relay` and `apps/web` are not touched by this branch, so they were not re-run.
- Read the whole diff against the brief. It covers all of it: folder tree, 25 Inbox documents (two meant for *Needs a look*),
  40 approved events over the last two complete VAT periods, two bank CSVs, contacts, two jobs with timesheets, a vehicle with
  mileage, three invoices (one overdue), Books.xlsx rebuilt, `--wipe` with y/N, `--dry-run`. Everything is written through the
  runtime's own functions (`approve`, `invoicing`, `jobs`, `mileage`, `contacts`, `Books`), and every document, statement and
  invoice note carries *SAMPLE — FICTIONAL COMPANY*.
- Product rules: no server-side data. The token comes from a hidden prompt or an env var, is kept only in memory and is
  never printed. Approvals are recorded as user `demo-seed` and proposals as model `seed:gold-reading`, so nothing pretends a
  model read the documents. Money is in integer pence throughout. No email is sent (`NotEmailed`).
- Ran the seed on the fake OneDrive and compared it with every figure in `tools/seed_demo.md` (VAT boxes for both periods,
  invoice totals, 18 matched / 2 open older bank lines, 14 suggestions, 4 customers + 13 suppliers, 13 journeys / 181.7 miles).
  They all match.
- `--wipe` path against `GraphStorageProvider` internals (`_root_drive_path`, `_request`, `_folders`). Clearing `_folders`
  is safe because `_folder("")` calls `ensure_root` again.

## Fixed

- `260b737`: a missing token, or a 401/403 from Graph (wrong or expired token), now gives a plain message and exit 1
  instead of a traceback. Any Graph error says the folder may be part-filled and to rerun with `--wipe`. The token is never echoed.
- `4053d51`: the full fake run was dated `date.today()`, so it changed from day to day and nothing tied it to the walkthrough.
  It is now pinned to 27 Oct 2026 and checks the walkthrough's figures: VAT boxes 1/4/5/6/7 for both periods, invoice totals,
  bank match counts, contact counts and miles. Added tests for `--wipe` answered `y` (deletes exactly the folder's top-level
  items and clears the folder cache), an empty token, and an expired token (message without the token in it).
- `1cf585e`: README *What works today* row (marked fake storage only, not yet run against a real OneDrive), a pointer in
  `docs/DEMO.md` to seed a separate account, and a note in `tools/seed_demo.md` on a token expiring part-way.

## What remains

- **Never run against a real OneDrive.** Some things only a live run will show: the Graph call count and time ("a few minutes"
  is a guess), throttling, the app-folder name check on a real personal account, and whether the Accnomos web app really
  sends `X-Graph-Token` with a token that has `Files.ReadWrite` on the app folder.
- The *Needs a look* and "23 proposals" claims for the 25 Inbox documents depend on a real model's reading when someone
  presses *Scan*. The plan only knows that the gold fields fail the checks for those two.
- The walkthrough's figures hold only for a run in Oct–Dec 2026 on stagger 1. Other dates give other figures (`--dry-run`
  prints them), and the test pins only 27 Oct 2026.
- `_wipe` uses private members of `GraphStorageProvider`. A public `delete`/`clear` on the provider would be cleaner, but it
  is out of scope for this branch.
- `ruff check` was not run (it needs approval in this environment).
- `TASK_BRIEF.md` was committed in `2fb02c9` ("wip: checkpoint"). Drop it or squash it before merging if briefs shouldn't live on `main`.

## How to verify by hand

From the repo root, with the runtime venv active, run `python tools/seed_demo.py --business "Bramblewood Joinery Ltd" --dry-run`.
Check it lists 40 approved ledger events in Apr–Jun and Jul–Sep 2026, one OVERDUE invoice and 25 Inbox documents, two marked
"Needs a look". Then use a **throwaway** personal Microsoft account. Sign in at accnomos.com and complete *Connect*, copy
`X-Graph-Token` from a runtime request in DevTools, and run the command without `--dry-run`, pasting the token at the hidden prompt.
Then, in the app, set Business details to *Bramblewood Joinery Ltd* and check:
- *VAT return* for Jul–Sep 2026 shows Box 1 £2,944.63, Box 4 £141.30 and Box 5 £2,803.33.
- *Invoices* shows INV-0001 paid, INV-0002 overdue and INV-0003 sent.
- *Bank* shows Apr–Jun reconciled, with 14 suggestions waiting for Jul–Sep.
- *Files* shows Books.xlsx and the README.

Run it again to check it refuses a folder that already has entries, then try `--wipe` and answer `n` to check nothing changes.
