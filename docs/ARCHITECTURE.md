# Architecture

Accnomos has no user database. The user's books are files in a folder they own; two stateless services read and write that
folder with the user's own token on each request and keep nothing. Checked against `services/runtime/app/*.py` on `main`
(27 Oct 2026); "unverified" below means we have not run it against the real service.

```
apps/web (Next.js PWA) ─┐                      ┌─> Microsoft Graph: the user's OneDrive folder
apps/mobile (Flutter) ──┼─> services/runtime ──┼─> Meta models (user's key) or Ollama (local mode)
                        │   (FastAPI, :8780)   └─> Baseten verifier (only if the server owner sets a key)
                        └─> services/hmrc-relay (:8787) ─> HMRC MTD VAT API (sandbox)
```

- **`services/runtime`** (`app`): the Agent Runtime. Every call carries the user's Graph token and AI settings in headers
  (below). Routers are the `include_router` lines in `app/main.py`: extract, books (scan, proposals, approve, undo, rules,
  rebuild), VAT and deadlines, dashboard, bank, ask (typed and voice), mail (intake, triage, draft reply), todos, jobs / staff /
  timesheets, contacts, vehicles / mileage, invoices, actions, payroll, plan, reports, audit, close (the month-end close
  agent, `app/routes_close.py`). Test mode (`ACCNOMOS_TEST_MODE=1`) adds
  `/__test`. `apps/web/src/lib/runtime.ts` and `apps/mobile/lib/services/runtime_client.dart` have one call per route, except
  that the phone does not call `/reports/*` yet.
- **`services/hmrc-relay`** (`relay`): exists only because HMRC needs the OAuth **client secret** at code exchange and
  refresh. It holds that secret, adds the v3.3 fraud-prevention headers, validates the return (box 3 = 1 + 2, box 5 = |3 − 4|,
  whole pounds where HMRC requires) and forwards. PKCE: only the browser holds the verifier; HMRC tokens sit in the tab's
  `sessionStorage` and travel in `X-HMRC-Access-Token`. Runs one worker. `docs/HMRC.md`, `services/hmrc-relay/README.md`.
- **`packages/ledger`**: ledger events, bank CSV parsing and matching, the VAT 9-box engine. No model code.
- **`packages/connectors`**: `StorageProvider`, `MailProvider`, `ContactsProvider`, `CalendarProvider`; Microsoft Graph and fake implementations.
- **Runtime state:** none, except voice audio in a temporary directory deleted after conversion, and the in-memory rate limiter
  and (without `ACTIONS_SIGNING_KEY`) a random per-process signing key for action cards. Browsers call the runtime directly; CORS
  (`CORS_ORIGINS`) is its gate, because every call is useless without the caller's own Graph token. Demo deployment (`deploy/`):
  Docker on a DGX Spark behind a tunnel as `api.accnomos.com`, Ollama on the same host (not checked from this review).

## Settings headers

Read in one place each (`services/runtime/app/routes_books.py`, `app/ai/config.py`):

| Header | Read by | Notes |
|---|---|---|
| `X-Graph-Token`, `X-Account-Kind` | `get_books` | 401 without a token; kind is `personal` (default) or `work` |
| `X-AI-Mode`, `X-AI-Base-Url`, `X-AI-Model`, `X-Meta-Api-Key` | `ai_config_from_request` | mode `key` or `local`; the base URL must be on the server's allow-list. In key mode with no key header the server's `META_API_KEY` is used |
| `X-User` | `require_user` / `optional_user` | the signed-in email; required for anything that writes; an audit label, not checked against the token |
| `X-Business-Name` | `business_name` | optional; tells sales invoices from purchases |
| `X-Autopilot` | `POST /books/scan` | `off` stops Autopilot for that scan. The web sends it at level L1/L0; the phone never sends it |
| `X-HMRC-Access-Token` | relay | scrubbed from logs by the runtime's middleware too |
| `X-Correlation-Id` | every response | also in the body of a 500 |

VAT settings are query parameters, not headers (`app/vat_cycle.py`): `stagger` (1–3) or `start_month`, `months` (3 or 1),
and `today`. With none sent, the runtime uses calendar quarters. **"Today" on the runtime is the UTC date** (`books.now()`; the VAT routes use `books.today()`, the server's local date, UTC in the container).

## The books folder

Personal accounts: `Apps/Accnomos` (the OneDrive app folder, `Files.ReadWrite.AppFolder`). Work accounts: `/Accnomos`
(`Files.ReadWrite`, a broader scope). Paths are relative to that root. **The numbered folder names live only in
`services/runtime/app/paths.py`**; `tools/gen_folders.py` copies them (and the README.txt text) into
`packages/connectors/folders.json`, `apps/web/src/lib/folders.ts` and a marked block in
`apps/mobile/lib/services/graph.dart`, and `tests/test_paths.py` fails if any copy differs or if a numbered name is
spelt as a literal anywhere else in Python. The `_System/` paths come from the constants in `app/books.py`,
`invoicing.py`, `payroll.py`, `payrun.py`, `jobs.py`, `mileage.py`, `contacts.py`, `intake.py`, `todos.py`, `plan_apply.py`.
`services/runtime/tests/test_integration.py` holds what the runtime writes during its scenario to a `LAYOUT` list kept by
hand in step with the first table; it does **not** exercise invoicing, payroll, the planner, to-dos or action audit, so those
paths are listed here from the code only.

Documents, filed by code and never deleted:

| Path | Written by | Notes |
|---|---|---|
| `README.txt` | web onboarding (text from `paths.readme_text()`) | once |
| `00 Inbox/<name>` | web and Android upload; Outlook intake as `<yyyy-mm-dd>_<sender-domain>_<name>`, an email receipt as `…_<subject>.eml.txt` (`docs/INBOX.md`) | moved out when read |
| `01 Receipts/<yyyy-mm>/<date> <supplier> £<total>.<ext>` | runtime, when a proposal is filed | |
| `02 Needs a look/<name>` | runtime: documents that need a look, and rejected ones | |
| `03 Sales/<name>` | runtime, a scanned document the reader classes as a sales invoice | |
| `03 Sales/invoices/INV-0001.json`, `.pdf`; `03 Sales/invoices/sent/INV-0001.pdf` | runtime, invoicing | `invoices/` and `invoices/sent/` are created at onboarding |
| `03 Sales/credit-notes/CN-0001.json`, `.pdf`; `03 Sales/credit-notes/sent/CN-0001.pdf` | runtime, credit notes (`credit_notes.py`) | created with the first credit note |
| `03 Sales/quotes/Q-<yyyymmdd>-<xxxx>.pdf` | runtime, `POST /cis/quote` (`routes_cis.py`) | a quote priced like an invoice (CIS deduction, reverse charge wording); posts nothing, takes no invoice number |
| `04 Bank statements/<last date>_<bank>.csv` | runtime, bank import | |
| `05 Payroll/<yyyy-mm>.csv` | runtime, pay-run export | |
| `05 Payroll/<tax year>/RTI/FPS-<run>.xml`, `EPS-<tax year>-month-<nn>.xml` | runtime, PAYE payroll (`routes_payrun.py`) on download | generated for checking, never submitted |
| `05 Payroll/<tax year>/payslips/payslip-<run>-<payroll id>.pdf`, `Pension/pension-<provider>-<run>.csv` | runtime, on download of an approved run | |
| `06 VAT returns/<periodKey>/return.json`, `receipt.json` | web, after an HMRC sandbox submission | once per key |
| `07 Reports/<yyyy-mm>-month-end-draft.xlsx`, `07 Reports/<yyyy-mm>-month-end.xlsx` | runtime, the month-end close (`app/month_end.py`): the draft (About, P&L, Balance sheet) is rewritten by each run once nothing blocks the close; the closed one is written on Approve and never overwritten (a re-close saves ` (2)`) | Posts nothing |
| `07 Reports/<yyyy-mm-dd>-uk-property-<tax year>-to-<period end>.json` | runtime, `POST /property/mtd/{taxYear}/export` | the Property Business API 6.0 bodies, ready to submit with other software; posts nothing |
| `07 Reports/<yyyy-mm-dd>-<name>.xlsx` | runtime, `POST /reports/export` (*Export to OneDrive* on Reports) | `name` is `profit-and-loss`, `aged-balances`, `vat-summary`, `monthly-trend` or `reports` (all of them); a second export the same day gets ` (2)`, nothing is overwritten. Starts with `SAMPLE — FICTIONAL COMPANY` when the books are the demo seed's. Posts nothing |
| `07 Reports/CIS/CIS300 <yyyy-mm-dd>.csv`, `.json` | runtime, `POST /cis/returns/{tax month end}/export` (`cis.py`) | the CIS300 figures for filing elsewhere; a second save for the same month replaces them; never submitted. Starts with `SAMPLE — FICTIONAL COMPANY` on the demo books |
| `Archive/<year>/<original path>`, `Archive/<year>.zip` | runtime, `POST /files/archive` (`archive.py`) | made when first used; the zip is an extra copy with `manifest.json`, the folder stays. See *Files, archive and backups* |
| `Backups/accnomos-backup-<yyyy-mm-dd>.zip`, `….zip.sha256` | runtime, `POST /backups` (`backups.py`) | made when first used; a second backup the same day gets ` (2)` |
| `_Trash/<yyyy-mm-dd>/<original path>` | runtime: Clean up, backup retention, an undone archive's zip, files a restore replaced | made when first used; **never emptied by the app**, the user empties it in OneDrive |
| `Books.xlsx` | runtime, `rebuild_safely` after each ledger-changing action and on *Rebuild* | rewritten whole; sheets `README`, `Summary`, `Ledger`, `Accounts`, `VAT`, `P&L`, `Customers`, `Suppliers`, `Bank`, `Proposals`, `Jobs`, `Vehicles`, `Payroll` (`projection.SHEETS`). A feature whose file cannot be read leaves its sheet empty; a failed rebuild is audited and never fails the user's action |

**Old folder names.** Until 27 Oct 2026 the tree used other names (`paths.RENAMED`: old name → current name, e.g.
the old name `03 Bank statements` is now `04 Bank statements`). On the first request a sign-in makes, `app/layout.py`
renames each old-named top-level folder to its current name with one move (a Graph PATCH of the folder's name;
everything inside goes with it), writes one `folders_renamed` audit line, and never copies or deletes. If the old and
the new folder both exist it leaves both: `GET /books/layout` lists the pair, the Files page shows a warning, and
`/health` counts it under `folder_layout` (counts only, no names). Expect this for anyone who raised an invoice before:
invoicing already wrote `03 Sales/invoices`, so the folder with the old name `02 Sales invoices` (usually empty) stays beside it until the user
deletes it. Paths saved before the rename (a proposal's `file_path`, a bank line's `source_file`) are not rewritten; they
go through `paths.upgrade()` when a document is filed and when statements are listed (Bank page, Home). The `Bank` and `Proposals` sheets of
Books.xlsx still show the path as it was saved.

`_System/` (settings and working data; money is always recomputed from the events):

| Path | Holds | Kind |
|---|---|---|
| `Ledger/events/<yyyy-mm>/<ts>-runtime-<id>.json` | **The books.** One immutable, balanced journal per file, integer pence | append-only |
| `docs/<sha256>.json` | one record per document read (the hash is the duplicate key) | written once |
| `proposals/<id>.json` | proposals and their decisions | updated |
| `audit/<yyyy-mm>.jsonl` | one line per action | append-only |
| `audit/autopilot/<yyyy-mm>.jsonl`, `audit/actions/<yyyy-mm>.jsonl` | Autopilot's own record; chat-action approvals and rejections | append-only |
| `rules.json` | "file this supplier to that account" from Approve | rewritten |
| `Rules/rules.json` | Autopilot rules ("Always do this") | rewritten |
| `cursors.json` | last inbox scan | rewritten |
| `bank/<sha256>.json` | lines of one statement with their match status | updated |
| `Intake/seen.json`, `Intake/log/<yyyy-mm>.jsonl` | Outlook intake | |
| `Originals/<name>.heic` | a HEIC photo from `00 Inbox`, once its JPEG has taken its place (`inbox.py`) | never deleted |
| `Contacts/contacts.json` | names and details only, never money | rewritten whole (last write wins) |
| `Jobs/jobs.json`, `Staff/staff.json`, `Timesheets/<yyyy-mm>.jsonl` | jobs, staff and rates, timesheet entries | entries edited and deleted |
| `Vehicles/vehicles.json`, `Mileage/<tax-year>.jsonl` | tax year like `2026-27` | entries edited and deleted |
| `Invoicing/profile.json`, `sequence.json`, `credit_sequence.json`, and the logo file | business profile, invoice and credit note numbering, logo (any file under `_System/Invoicing/`) | rewritten |
| `Payments/providers.json` | the user's own Stripe account id / PayPal merchant id / PayPal.me name for payment links, when linked (`online_payments.py`); never a key or token | rewritten |
| `Payments/payments.json` | recorded payments: amount, date, account, the split across invoices or bills, the posted event (`payments.py`) | rewritten whole; a removed payment is kept, marked removed |
| `Payroll/runs/<yyyy-mm>.json` | one pay run per month | updated |
| `CIS/settings.json`, `CIS/statements.json`, `CIS/subcontractors.json`, `CIS/payments.json` | CIS registration; contractors' payment and deduction statements (approved); the contractor's subcontractors and payments to them (`cis.py`) | rewritten; a removed payment is kept, marked removed |
| `CIS/readings/<id>.json` | a CIS statement or reverse-charge bill your AI read, waiting for Approve or Reject (`cis_readings.py`) | updated once by the decision |
| `Payroll/employer.json`, `Payroll/employees.json` | PAYE references, Employment Allowance, pension scheme; employees' payroll records (NI number, date of birth, address) | rewritten whole |
| `Payroll/payruns/<tax year>-<frequency>-<nn>.json`, `payruns/discarded/` | one PAYE pay run: inputs, every calculated figure and year to date (`payrun.py`) | updated until posted; a discarded draft is moved, not deleted |
| `Planner/applied.json` | which day plans were applied (idempotency) | updated |
| `Todos/todos.json` | to-dos added from triage | updated |
| `archive/map.json` | old path → new path for every document the app moved (archive, Files page move and rename) | updated; applied when proposals and bank lines are read |
| `archive/runs/<id>.json` | one archive run: every move, its zips, and when it was undone | written, then updated once by Undo |
| `Property/properties.json`, `tags.json`, `settings.json`, `submissions.json` | let properties and owners' shares; event id → property (and category); landlord mode, quarters, finance costs brought forward, HMRC business id; UK property updates sent to the sandbox (`app/property.py`, `app/routes_property.py`) | rewritten (tags updated per entry; submissions keep the last 200) |
| `Settings/files.json` | `backup_keep` (default 12), `monthly_backup` (default off) | rewritten |
| `profile.json` | what these books are: name, kind (`company`, `sole_trader`, `personal`), kind settings, other linked accounts by sign-in name (`app/profile.py`, `PUT /profile`) | rewritten whole |

| `close/<yyyy-mm>.json` | the month-end close: the last 10 runs (steps, findings, card summaries; never the signed cards) and every close record (who, when, the snapshot and its SHA-256) | updated; close records are only appended |

OneDrive paths ignore case, so `_System/audit` and `_System/Audit` are one folder. Money is integer pence in every file except
`Books.xlsx`, which shows pounds.

**Ledger events** (`packages/ledger`): `kind` = purchase · sale · bank · adjustment · reversal, ≥ 2 lines, Σ debit = Σ credit
(enforced on construction), VAT code per line (S 20 %, R 5 %, Z, E, O, N), `evidence` = document hashes, `approved_by` (agents
never approve; Autopilot is recorded as `autopilot`), `reverse_charge_vat` (VAT Act 1994 s55A: on a purchase, VAT in box 1 and box 4; on a sale, the customer's, kept off this return). Nothing is edited; **undo adds a `reversal` event** that references the
original. The nine VAT boxes come from `compute_vat_return`, plain code, boxes 6–9 truncated to whole pounds.

**Audit lines** are one JSON object per line: `{"ts", "actor", "action", "refs"}`. `actor` is `user:<email>` for something a
person did, or `agent:<name>` (`extractor`, `intake`, `autopilot`, `mileage`, `contacts`, `triage`, `folder-layout`, `backup`, `close`)
for something done for them. Applying a day plan is the user's action (`plan_applied`); there is no `agent:planner` writer yet.
Chat and voice actions write their own lines to `audit/actions/` (`{"ts", "action_id", "kind", "event", "user", …}`, `event`
= approving · executed · failed · rejected), and Autopilot's postings are repeated with its reasons in `audit/autopilot/`.

**Reading it back:** `GET /audit?from=&to=&actor=&kind=&limit=` (`app/audit_view.py`, read-only) reads the month files of
`audit/` and `audit/actions/` for the range (one extra month of `actions/`, which files by the month an action was proposed),
newest first, at most 500 lines and at most 366 days per request. `audit/autopilot/` is not read, because every line in it is already in `audit/`. Each line becomes
`{ts, actor, actor_kind: user|agent, actor_label, event, summary, refs: {proposal, event, invoice, action, file}}`; the
summary comes from one table, `SUMMARIES` (a kind not in it shows as its own name), and `approving` rows are skipped (the
`executed`, `failed` or `rejected` row that follows is the outcome). `actor` matches `user`, `agent`, an agent name or a full
actor; `kind` matches an event or a prefix family (`invoice` is every `invoice_*`). Days are UTC. A test fails if a
`Books.audit` call in `app/` writes a kind with no sentence. The web `/audit` page and the Android *Audit trail* screen read it
through this route; the Home dashboard reads `audit/` for recent activity, and `app/actions.py` reads its own log so an
action never runs twice.

## Files, archive and backups

The Files page's tools (web; Android shows the storage totals and *Back up now*) all go through the runtime, so they are
audited and run on `FakeStorageProvider` in tests: `services/runtime/app/routes_files.py` over `files.py`, `archive.py`
and `backups.py`. Every write needs `X-User`; previews write nothing.

* **Nothing is deleted.** What the app would otherwise delete goes to `_Trash/<date>/<original path>`: Clean up of
  duplicates, backups beyond the kept number, the zip of an undone archive run, and the current copy of a file a
  restore replaces. The user empties `_Trash` in OneDrive.
* **What never moves.** `_System/` (ledger events above all), `Backups/`, and the files other modules read at a fixed
  path: `03 Sales/invoices/**`, `03 Sales/credit-notes/**` (invoice and credit note records and PDFs),
  `06 VAT returns/**` (read for the submitted-period lock), `Books.xlsx` and `README.txt`. Move, rename and Clean up
  refuse them; archiving skips them.
* **Links keep working.** Every move the app makes is written to `_System/archive/map.json` (`Books.record_moves`:
  old → new, chains collapsed to one hop, moving back removes the entry so there is never a cycle).
  `Books.get_proposal`, `list_proposals` and `stored_bank_lines` apply it, so a proposal's `file_path` and a bank line's
  `source_file` lead to where the document is now without rewriting either file. Ledger events point at documents by
  hash (`evidence`), never by path. A move made by hand in OneDrive is not in the map (as before).
* **Overview** (`GET /files/overview`): files and bytes per top folder and per tax year, the 10 largest documents, and
  duplicate sets. Each folder is listed once per request (the request memo); duplicates are grouped by the hash Graph
  lists (`FileRef.content_hash`: `sha256Hash`, else `quickXorHash`, else `sha1Hash`), and only same-size files without
  one are read and hashed (at most 200 files of 20 MB each). The copy suggested to keep is the one the books link to,
  else a filed one over an Inbox or archived copy. **Index** (`GET /files/index`) is the same walk as a list for search:
  each document's date (the linked document's date, else a date in its name, else in its folder, else last modified),
  tax year, type, and, when a posted proposal links to it, the ledger entry's net + VAT from the event. A walk stops at
  20,000 files and says so.
* **Archive by year** (`POST /files/archive/preview`, `/files/archive`, `/files/archive/runs/<id>/undo`): years are UK tax
  years (6 April) or financial years ending on a chosen month end; the label is `2025-26` (or `2026` when a year sits
  inside one calendar year). Documents in `01 Receipts`, `03 Sales` (not the protected parts), `04 Bank statements`,
  `05 Payroll` and `07 Reports` dated in a year that ends on or before the chosen one move to
  `Archive/<year>/<same path>`; the year we are in is refused. With `zip`, `Archive/<year>.zip` holds that year's folder
  plus `manifest.json` (path, size, sha256 per file); over 50 MB the zip is skipped with a note. Undo moves each file
  back (a taken name gets ` (2)`), reports files the user moved since instead of hunting for them, and puts the run's
  zips in `_Trash`.
* **Backups** (`POST /backups`, `GET /backups`, `PUT /backups/settings`, `POST /backups/verify`,
  `/backups/restore/preview`, `/backups/restore`, `/backups/auto`): the zip holds every file under `_System` at its
  own path plus `manifest.json` (`format`, `created_at`, each file's path, size and sha256, and `files_sha256` over the
  sorted list); the `.sha256` beside it is the zip's own sha256 in `sha256sum` format. At most 20,000 files and
  100 MB (413 beyond). Retention keeps the newest `backup_keep`. Verify checks the zip against its `.sha256`, every file
  against the manifest, and refuses any path outside `_System` or with an unsafe segment. Restore is preview first:
  each file is *new*, *same*, *changed* or *kept* (a ledger event or audit file that differs: append-only, never
  replaced). It writes new files, moves the current copy of each changed file to `_Trash/<date>/restore-<hhmmss>/`
  before writing the backup's copy, never deletes a file the backup lacks, and needs `confirm: "RESTORE"` unless the
  books are empty (no ledger events and no proposals). Then Books.xlsx is rebuilt.
* **Monthly backup** is optional and off by default. There is no server per user, so nothing can run on a schedule:
  `components/files/MonthlyBackup.tsx` in the web app shell calls `POST /backups/auto` once a month per device, only on
  a device where the user switched it on (the Files page mirrors the OneDrive setting into `localStorage`), and the
  runtime backs up only when the setting is on and no backup is dated this month. A month in which nobody opens the
  app gets no backup. Android does not run it.
* **Audit kinds:** `files_moved`, `file_renamed`, `files_trashed`, `files_archived`, `archive_undone`,
  `backup_created` (actor `agent:backup` for the monthly one), `backup_verified`, `backup_restored`,
  `file_settings_saved`, each with a sentence in `audit_view.SUMMARIES`.

## Round trips and caching

Every read of the books is a Graph call, so the runtime avoids repeating them (`services/runtime/app/cache.py`):

* Per request: a `Books` built with a `cache_key` memoises repeated `list`/`read` calls (each folder is listed
  once) and reads independent files together with `asyncio.gather` (at most 8 round trips in flight). A miss is
  memoised too, so a file that is not there costs one round trip per request, not one per look; concurrent looks at
  one path share a single round trip. A write or move forgets exactly the paths it changed (and every remembered
  miss), so a request always reads its own writes; a read still in flight when the request writes is not memoised.
  `Books._update` forgets the file and its folder listing before a read-modify-write, so the If-Match retry reads
  storage, not the memo.
* Across requests: only posted ledger events (`_System/Ledger/events/…`, immutable once written) are kept, in a
  small in-process LRU (1,000 files / 8 MB) keyed by a hash of the caller's token (plus the test tenant in test
  mode). Never cached across users; never cached mutable files beyond one request. The key holds a hash, not the token.

Speed on a real-sized seeded book, measured on fakes with simulated latency: `evals/runs/bench_runtime/report.md`.

**Linked accounts never share a cache entry.** Each profile is its own Microsoft account (next section), so every
request carries that account's own token, and both cache layers are keyed by a hash of it
(`services/runtime/tests/test_profile.py` checks that two tokens get two keys and that one account's cached event is
never served to the other).

## Profiles (linked accounts)

One Microsoft account is one profile: a company, a sole-trader business or personal finances, with its books in that
account's own OneDrive. A user with several links several accounts; there is still no user database.

* **Which accounts are linked** lives in the browser. The web keeps every account signed in with MSAL's multi-account
  cache (`getAllAccounts()`, `setActiveAccount`, `loginRedirect` with `prompt: "select_account"` to add one) and
  `localStorage` `accnomos.profiles` (`apps/web/src/lib/profiles.ts`): the account whose settings are live, and each
  account's last-read name, kind and features for the menu. Switching sets MSAL's active account, so `getToken` (and
  every runtime and Graph call after it) uses the other account's token, then reloads.
* **Per-business settings this browser keeps** (`accnomos.business`, VAT period, Autopilot level, Ask history, intake
  and triage state, setup checklist, invoice draft: `PROFILE_KEYS`) are stashed under the old account and the new
  account's copy restored on every switch. The HMRC connection (sessionStorage) is dropped on a switch, never carried:
  the user connects HMRC again for that business. The AI settings and device id are the person's and stay.
* **What the books are** is in each account's `_System/profile.json` (`GET`/`PUT /profile`, `app/profile.py`). Without
  the file the books are a VAT-registered company, so nothing changed for existing users. `linked` may list the other
  accounts by sign-in name (never a token or an id the app could sign in with) so a new browser can offer to add them
  (Settings › Business › Profile).
* **Kind gates features.** `features` in `GET /profile`: personal books have no `vat`, `invoices` or `payroll`; `vat`
  needs `vat_registered`; `self_employment` is for sole traders. The runtime answers 404 with a sentence on the gated
  routes (`routes_books.require_feature`: `/books/vat*`, `/books/deadlines`, `/reports/vat`, `/invoices/*`,
  `/credit-notes*`, `/payroll/*`), costing one read of `profile.json` on those routes only. The web hides what the kind
  lacks.
* **Menu bar** (`apps/web/src/components/TopBar.tsx`, `apps/web/src/lib/nav.ts`), signed in only: the profile switcher
  at the far left, the groups Home, Sales, Purchases, Reporting, Accounting, Tax, Payroll, Contacts and (personal books)
  Personal as disclosure dropdowns, then Search (find a page), Ask, Help, Notifications (the Review count) and the
  account menu (email, *Sign out of this one*). Under 900 px the groups are in a modal drawer. A link shows only when its
  page is in the build (`apps/web/src/lib/routes.server.ts` lists `src/app` when the static export is made) and the
  profile has its feature, so the menu never links to a 404. Signed out, the old sidebar and phone header stay.
* **Android** is single-account (`msal_config.json` `account_mode: SINGLE`): Settings shows the profile's name and
  kind and *Switch account* signs out, forgets the phone's business details, and signs in again.
* **Test mode:** a token `test-token.<account>` is another account with fakes of its own (`app/testmode.py`
  `TEST_ACCOUNT_TOKEN`); the web's test sign-in adds Jo (`test-token.jo`) when you sign in while signed in.

## The agent pipeline

`app/pipeline.py` (scan) and `app/inbox.py` (posting during a scan):

| # | Stage | Done by | Today |
|---|---|---|---|
| 1 | Intake | Code | Upload to `00 Inbox`, scan, optional Outlook copy (`Mail.Read`, plain-code filters, no AI) |
| 2 | Crop | **Code** by default (Pillow + Otsu); SAM 3.1 only with `SAM_CROP=1` in key mode; `CROP_MODE=off` disables | Code crop tested; SAM never run |
| 3 | Extractor | **Muse Glimmer 30B** (local) or **Muse Spark** (key mode), strict-JSON schema | Glimmer run by hand; Spark unit-tested only |
| 4 | Checker | **Code**: line and total arithmetic, VAT maths and rates, VAT-number format, duplicate hash, currency, valid date, confidence, and the document's date against the current VAT period (a **warning**, never a fail) | Tested; any failure → *Needs a look* |
| 5 | Reviewer | **Code** composes the "why" line on each card ("Checker, code"). Models write words only in *Ask*, triage, reminders and the planner rationale | **No separate LLM reviewer exists** |
| 6 | Verifier | A second reading with a different prompt that never sees the first answer, run only if the checks pass; **code** compares six fields (supplier, VAT number, date, net, VAT, total) | Glimmer/Glimmer run on 20 documents; Baseten and Meta paths unit-tested only; `VERIFIER=off` disables it |
| 7 | Human | The user taps Approve (or Reject) | Always, unless an Autopilot rule applies |
| 8 | Poster | Code writes the ledger event | Tested |
| 9 | Filer | Code renames and files the document; HMRC submission is a separate, explicit web step with a legal declaration | Tested; HMRC sandbox only, never run end to end |

Autopilot is off by default (level L1, propose only). At L2 a receipt posts without a tap only if a rule you saved matches
(same supplier, VAT number and treatment, total ≤ 2× the usual) **and** every code check passes with no warnings, which includes
the verifier agreeing. Each post is audited and has **Undo**. `docs/AUTOPILOT.md`.

## Money invariants (property tests)

The money maths is checked by property-based tests (Hypothesis) as well as by examples. The inputs are generated
from the real models, and the checks go through the real functions:

- `packages/ledger/tests/test_properties.py`: every event balances in integer pence; the 9-box identities hold (box 3
  = box 1 + box 2, box 5 = |box 3 − box 4|, boxes 6–9 whole pounds) and agree with the events in the period; bank
  amounts round-trip; the matcher never uses a bank line or an event twice.
- `services/runtime/tests/test_properties_money.py`: mixed-rate invoices sum line VAT exactly; every draft journal
  balances and its undo zeroes every account and box; repairs round-trip within 1p; settlement never pays a document
  beyond its total; aged debtors add up; VAT periods for all three staggers and monthly tile the calendar across leap
  years and BST/GMT.
- `services/runtime/tests/test_properties_books.py`: a state machine runs random sequences of approvals, payments,
  credit notes, bank matches, refunds and undos through the real actions. After every step the trial balance
  balances, 1100 Debtors and 2100 Creditors equal the aged balances less unused credits, 2200 VAT control equals box
  1 less box 4, and each invoice file agrees with the ledger.

They add about 13 s to the suites. `HYPOTHESIS_PROFILE=deep` and `-m slow` run deeper. The bugs these tests found
are in `docs/reviews/property-tests/REVIEW.md`, and each has a plain example in
`services/runtime/tests/test_property_regressions.py`.

## The month-end close

`app/month_end.py`, `app/routes_close.py`, web `/month-end` (`apps/web/src/components/month-end/MonthEnd.tsx`) and the
Home card, Android *More › Month-end* and its Home card (read only). One button, **Close October**, runs an agent loop
that is plain code: nine steps in order, each reported as it finishes (`POST /close/{yyyy-mm}/run?stream=1`, server-sent
events `start`, `step` ×9, `summary`, `run`), each ending `ok`, `needs_you` or `blocked` with one plain-English reason, a
link, what it checked and what it found. A finding is `blocking` (the month's figures are incomplete or wrong until it is
dealt with), `needs_you` (worth doing, does not stop the close) or `note`.

| # | Step | What code checks | What it proposes |
|---|---|---|---|
| 1 | Inbox | files in `00 Inbox` (blocking: they may be dated in the month); proposals waiting on Review dated in the month (blocking) or with no readable date; Outlook, only when the app says intake is on, as a **dry run** of `scan_mail` (nothing copied) | links to Review and Settings › Outlook |
| 2 | Bank | per bank (from the statement file name): days of the month no imported statement covers, longer than 3 days (`GAP_DAYS`): "Bank statement missing for 12–31 Oct (starling)"; consecutive statements whose balances do not join up; lines in the month not reconciled | each suggested match (`Books.bank_suggestions`, code) as a `match_bank_line` card, at most 10 |
| 3 | Sales | draft invoices dated in the month (blocking: not in sales); sent invoices past due with money outstanding | a `chase_invoice` card per overdue invoice (at most 5), words by the user's AI checked by code (`app/ai/remind.py`), or by code with no AI |
| 4 | Purchases | bills on account due within 7 days or overdue (aged creditors); supplier credits not applied | links to Contacts |
| 5 | Payroll | only if staff or pay runs exist: no pay run for the month (blocking if hours were logged), or a draft one (blocking) | link to Payroll |
| 6 | VAT | if the month ends a VAT period (the usual `stagger` / `start_month` / `months`): the 9 boxes (`compute_vat_return`), the deadline (HMRC's obligation if posted, else 1 month 7 days), submitted or not, and the digital-links trail (each event on the return with its evidence hashes, up to 200) | link to `/vat?period=…`; **never submits** |
| 7 | Checks | a balance on `7999 Sundry expenses` (the chart has no suspense account; Sundry is where uncategorised costs go) and accounts with no code (blocking); live sales or purchases with the same counterparty, amount and day (blocking); bank balances below zero; a purchase over 3× the supplier's median (and £100 over it); manual adjustments | links |
| 8 | Reports | blocked while anything blocks or the month has not ended; otherwise the P&L and balance sheet (`reports.balance_sheet`) saved as `07 Reports/<yyyy-mm>-month-end-draft.xlsx` | |
| 9 | Lock | blocked while anything blocks or the month has not ended; already closed with the same snapshot → ok | a `close_month` card |

**Safety.** The agent posts nothing and sends nothing. A run writes its record (`_System/close/<yyyy-mm>.json`), one
`close_run` audit line (`agent:close`) and, at step 8, the draft report. Everything else is a card approved through
`POST /actions/approve` (`docs/ACTIONS.md`: signed, 15-minute expiry, executed once). A step that raises is shown as
`blocked` with its error, never skipped; a missing input says what to upload or do. The summary is the only model
output: `app/ai/close_summary.py` gives the model the steps' titles, statuses and reasons and the counts, and checks the
reply with Ask's number check (`KnownNumbers`): every figure must be in the facts, no links, and a month that cannot be
closed may not be called ready. Otherwise, or with no AI, code writes it (`fallback_reason`).

**Close and after.** Approving `close_month` recomputes the month's snapshot (every ledger event and bank line dated in
the month, the P&L by account and the month's own VAT boxes; SHA-256 over its canonical JSON) and refuses with 409 if
it differs from the one on the card; otherwise it saves `07 Reports/<yyyy-mm>-month-end.xlsx`, appends a close record
and audits `month_closed` (or `month_reclosed`). Closing does not stop anyone posting into the month: `GET /close`
(Home) and `GET /close/{month}` compare the last close's snapshot with the books now and, when they differ, list each
change in a sentence ("A purchase from Wickes for £24.00 dated 20 Oct was approved on 5 Nov") with the before/after
P&L lines and VAT boxes, and the next run offers a re-close. When the month's VAT period was already submitted, the
note says the changes are not on that return; Undo keeps dating corrections today (`app/approve.py`).

## Models: where each is called

| Model | Called from | Mode | Status |
|---|---|---|---|
| **Muse Glimmer 30B** (`muse-glimmer:30b`, Ollama `/api/chat`) | `ai/extract.py` (extraction); `ai/verify.py` (verifier); `ai/ask.py` `call_json_model` (Ask, and through it `actions.py` intents, `ai/triage.py`, `ai/remind.py`, `ai/plan.py` rationale) | local | Run by hand on our DGX Spark for extraction and verifier (`evals/`); the other tasks tested with a stub |
| **Muse Spark** (`muse-spark-1.3`, Meta Model API `/chat/completions`, the user's key) | the same call sites in key mode; `ai/verify.py` when no Baseten key is set | key | **Unverified**: unit-tested against stubs; no key in our eval environment |
| **Muse Spark Open** (Baseten, `inference.baseten.co`) | `ai/verify.py`, only in key mode when the **server owner** sets `BASETEN_API_KEY` | key | Wired on the demo server (key set 27 Oct 2026); id `meta-models/muse-spark-open` as Baseten lists it; one real call checked; eval on 200 gold documents: all fields 91 % clean, 93 % messy (`evals/runs/spark_open_200`, `spark_open_messy_200`) |
| **Muse Voice Transcribe** (`muse-voice-transcribe-1.0`) | `ai/voice.py` `transcribe()`, from `POST /books/ask/voice` (web and Android mic) after ffmpeg converts to WAV 16 kHz mono | key only | **Unverified**: request format from research notes, never checked against dev.meta.ai; no live mic run |
| **SAM 3.1** (`sam-3.1`) | `ai/crop.py` `_call_sam`, only with `SAM_CROP=1` | key | **Unverified and off by default**: wire format is a guess; the default crop is code |
| **Muse Image** (`muse-image-1.0`) | `tools/brand_muse.py`, build time, for the brand artwork | n/a | Run once; **not part of the runtime** |

`muse-wonder-1.0` is not called anywhere: chat actions use the user's configured Glimmer or Spark. Details and eval numbers:
`docs/META_MODELS.md`. In local mode documents go only to Ollama, never to Meta or Baseten. Caveat: in our demo the runtime and
Ollama are on our DGX Spark, so the image passes through that machine's memory; "on your machine" needs you to run the runtime yourself.

## What never leaves the device

- Meta API key: browser `localStorage`, sent per request to the runtime in a header (Android: app settings, **not** in secure storage yet).
- HMRC tokens: tab `sessionStorage`. Microsoft tokens: MSAL's cache in the browser or app.
- Voice audio is not kept; voice needs a Meta key.

## Threat model

1. **Runtime sees tokens and documents in memory.** Mitigation: stateless by design, no database, tokens scrubbed from logs; self-hostable.
2. **Prompt injection or a wrong reading from a document.** Model output is untrusted: code checks, an independent second reading, and a human approval stand between it and the ledger. *Ask* answers are checked against a facts pack; an invented figure is replaced by the quoted facts. Extraction itself is not adversarially robust (`docs/SECURITY.md`).
3. **HMRC credentials and filing.** Client secret only in the relay; PKCE, signed one-time `state`, redirect allow-list; no filing without the ticked legal declaration. Sandbox only.
4. **Tampering.** Events are append-only by convention and by code, but the files are the user's: they are **not signed or hash-chained**, so edits made directly in OneDrive would not be detected. `Books.xlsx` is generated and labelled do-not-edit.
5. **Availability.** One host behind a tunnel runs the demo. Fallbacks: key mode needs no Ollama; `VERIFIER=off`; the books stay readable in OneDrive whether or not we are up.
