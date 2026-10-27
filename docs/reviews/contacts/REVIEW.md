# Review: `claude/contacts`

Task: customers and suppliers contact book from the ledger, statements, aged balances, Outlook import, Books.xlsx
`Customers`/`Suppliers` sheets, `/contacts` web page (brief: `TASK_BRIEF.md`).

## What was checked

- **Tests.** `packages/connectors` 19 passed, `packages/ledger` 15 passed, `services/runtime` 141 passed (was 140; one added),
  `services/hmrc-relay` 39 passed. `apps/web`: `pnpm run build` passes; `/contacts` is prerendered.
  - Environment note: in this shared environment the editable installs of `accnomos_connectors` and the runtime `app`
    package point at the sibling checkout `repo-lane-f`, so a plain `pytest -q` fails at collection in `packages/connectors`
    and `services/runtime` (ImportError for `GraphContactsProvider` / `AddressBookContact`). That comes from the environment,
    not the code. The suites were run with this lane's sources first, e.g. from `services/runtime`:
    `python -m pytest -q -o pythonpath="$PWD $PWD/../../packages/connectors/src $PWD/../../packages/ledger/src"`.
- **Diff read** (connectors, `app/contacts.py`, `routes_contacts.py`, `projection.py`, `books.py`, web page, `runtime.ts`, `msal.ts`, sample data):
  - Money is pence (integers) throughout. The Books.xlsx and web layers only turn it into pounds for display. `contacts.json` stores no amounts
    (a route test checks this). GET routes write nothing.
  - Graph access is read-only (GET `/me/contacts` with the brief's `$select`, paging via `@odata.nextLink`). `Contacts.Read` is requested only
    from *Import from Outlook* (`contactsScopesFor`). A 403 from Graph comes back as 401 through the existing global `GraphError` handler.
  - No secrets and nothing stored server-side. Contacts live in the user's `_System/Contacts/contacts.json`, and edits and imports are audited there.
  - Signed-out and error views show the sample, labelled "SAMPLE — FICTIONAL COMPANY". Wording is UK English.
  - Input validation is at the API boundary: contact ids must be 16 hex characters, VAT numbers must look like UK ones, emails
    and categories are checked, VAT codes must be valid, a VAT number cannot be on two contacts, and `from` must not be after `to`.

## What I fixed

| Commit | Fix |
|---|---|
| `3696f1a` | `apply_edit` now refuses a rename to a name that another contact already has (as its name or an alias). Before, both contacts shared a key and later documents went to whichever came first. Test added. |
| `3ab1502` | Books.xlsx `Summary` counted suppliers with the old per-name `supplier_totals`, so "Screwfix" and "SCREWFIX DIRECT" counted as 2 while the deduplicated `Suppliers` sheet showed 1 row. `Summary` now counts `Customers` and `Suppliers` from the same rows as the sheets. Removed the now-unused `supplier_totals`; test updated. |
| `2c6b7de` | New route test: *Import from Outlook* without `Contacts.Read` consent (Graph 403) returns 401 and writes no `contacts.json` and no audit line. |
| `14a3dfe` | README: removed the blank line that split the "What works today" table, which stopped the Books.xlsx/Files/Deadlines/Contacts rows rendering as rows (the blank line was already on main). The Contacts and Books.xlsx rows now match the code. |

## What remains

- Not run live: nothing has been tried against a real OneDrive or Outlook address book. On work or school accounts, `Contacts.Read` consent may need an admin; this is untested.
- A matched bank line counts as full payment, whatever its amount. Partial payments, overpayments and credit notes are not modelled, so a part-paid invoice drops out of *Aged balances* completely.
- Ageing uses the document date, because no due dates or payment terms are recorded.
- Customer VAT numbers are never taken from documents (on a sales invoice the VAT number is the user's own). They can only be set with *Edit*.
- Contacts added from Outlook with "also add" are always created as `customer`.
- `save_contacts` rewrites the whole file: two tabs editing at once means the last write wins (no merge on conflict).
- After *Edit*, the side panel reloads the list but not the statement. Only details change, so the figures stay correct.
- No web unit tests exist for the page (only the build check). `ruff` was not run in this session.
- Shared-environment editable installs point at `repo-lane-f` (see above); CI or a fresh venv should run plain `pytest -q`.

## How to verify by hand

Start the runtime and web app, sign in with a Microsoft account whose books folder has a few approved receipts and one sales
invoice, and open **Contacts**. Check that spelling variants of one supplier ("Screwfix Direct Ltd." / "SCREWFIX DIRECT") appear as one row
with the right open balance and net this tax year. Click it and check that the statement's running balance ends at the open balance.
Press **Refresh from books** and confirm `Apps/Accnomos/_System/Contacts/contacts.json` appears in OneDrive with names and details but no amounts.
**Edit** a contact's phone and category, refresh again, and check the edits are kept; renaming it to another contact's name should be refused.
On **Aged balances**, check an unpaid sales invoice sits in the right 0–30/31–60/61–90/90+ column and disappears once a bank line is matched to it.
**Import from Outlook** should ask only for read access to contacts and then fill blank emails and phones. Finally, run **Rebuild Books.xlsx** on Files and open the `Customers`,
`Suppliers` and `Summary` sheets in Excel.
