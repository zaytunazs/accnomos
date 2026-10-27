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
  timesheets, contacts, vehicles / mileage, invoices, actions, payroll, plan. Test mode (`ACCNOMOS_TEST_MODE=1`) adds `/__test`.
  `apps/web/src/lib/runtime.ts` and `apps/mobile/lib/services/runtime_client.dart` have one call per route.
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
`invoicing.py`, `payroll.py`, `jobs.py`, `mileage.py`, `contacts.py`, `intake.py`, `todos.py`, `plan_apply.py`.
`services/runtime/tests/test_integration.py` holds what the runtime writes during its scenario to a `LAYOUT` list kept by
hand in step with the first table; it does **not** exercise invoicing, payroll, the planner, to-dos or action audit, so those
paths are listed here from the code only.

Documents, filed by code and never deleted:

| Path | Written by | Notes |
|---|---|---|
| `README.txt` | web onboarding (text from `paths.readme_text()`) | once |
| `00 Inbox/<name>` | web and Android upload; Outlook intake as `<yyyy-mm-dd>_<sender-domain>_<name>` | moved out when read |
| `01 Receipts/<yyyy-mm>/<date> <supplier> £<total>.<ext>` | runtime, when a proposal is filed | |
| `02 Needs a look/<name>` | runtime: documents that need a look, and rejected ones | |
| `03 Sales/<name>` | runtime, a scanned document the reader classes as a sales invoice | |
| `03 Sales/invoices/INV-0001.json`, `.pdf`; `03 Sales/invoices/sent/INV-0001.pdf` | runtime, invoicing | `invoices/` and `invoices/sent/` are created at onboarding |
| `04 Bank statements/<last date>_<bank>.csv` | runtime, bank import | |
| `05 Payroll/<yyyy-mm>.csv` | runtime, pay-run export | |
| `06 VAT returns/<periodKey>/return.json`, `receipt.json` | web, after an HMRC sandbox submission | once per key |
| `07 Reports/` | created at onboarding | nothing writes here yet |

**Old folder names.** Until 27 Oct 2026 the tree used other names (`paths.RENAMED`: old name → current name, e.g.
the old name `03 Bank statements` is now `04 Bank statements`). On the first request a sign-in makes, `app/layout.py`
renames each old-named top-level folder to its current name with one move (a Graph PATCH of the folder's name;
everything inside goes with it), writes one `folders_renamed` audit line, and never copies or deletes. If the old and
the new folder both exist it leaves both: `GET /books/layout` lists the pair, the Files page shows a warning, and
`/health` counts it under `folder_layout` (counts only, no names). Paths saved before the rename (a proposal's
`file_path`, a bank line's `source_file`) are read through `paths.upgrade()`.
| `Books.xlsx` | runtime, `rebuild_safely` after each ledger-changing action and on *Rebuild* | rewritten whole; sheets `README`, `Summary`, `Ledger`, `Accounts`, `VAT`, `Customers`, `Suppliers`, `Bank`, `Proposals`, `Jobs`, `Vehicles`, `Payroll` (`projection.SHEETS`). A feature whose file cannot be read leaves its sheet empty; a failed rebuild is audited and never fails the user's action |

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
| `Contacts/contacts.json` | names and details only, never money | rewritten whole (last write wins) |
| `Jobs/jobs.json`, `Staff/staff.json`, `Timesheets/<yyyy-mm>.jsonl` | jobs, staff and rates, timesheet entries | entries edited and deleted |
| `Vehicles/vehicles.json`, `Mileage/<tax-year>.jsonl` | tax year like `2026-27` | entries edited and deleted |
| `Invoicing/profile.json`, `sequence.json`, and the logo file | business profile, invoice numbering, logo (any file under `_System/Invoicing/`) | rewritten |
| `Payroll/runs/<yyyy-mm>.json` | one pay run per month | updated |
| `Planner/applied.json` | which day plans were applied (idempotency) | updated |
| `Todos/todos.json` | to-dos added from triage | updated |

OneDrive paths ignore case, so `_System/audit` and `_System/Audit` are one folder. Money is integer pence in every file except
`Books.xlsx`, which shows pounds.

**Ledger events** (`packages/ledger`): `kind` = purchase · sale · bank · adjustment · reversal, ≥ 2 lines, Σ debit = Σ credit
(enforced on construction), VAT code per line (S 20 %, R 5 %, Z, E, O, N), `evidence` = document hashes, `approved_by` (agents
never approve; Autopilot is recorded as `autopilot`). Nothing is edited; **undo adds a `reversal` event** that references the
original. The nine VAT boxes come from `compute_vat_return`, plain code, boxes 6–9 truncated to whole pounds.

**Audit lines** are one JSON object per line: `{"ts", "actor", "action", "refs"}`. `actor` is `user:<email>` for something a
person did, or `agent:<name>` (`extractor`, `intake`, `autopilot`, `mileage`, `contacts`, `triage`) for something done for them.

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

## Models: where each is called

| Model | Called from | Mode | Status |
|---|---|---|---|
| **Muse Glimmer 30B** (`muse-glimmer:30b`, Ollama `/api/chat`) | `ai/extract.py` (extraction); `ai/verify.py` (verifier); `ai/ask.py` `call_json_model` (Ask, and through it `actions.py` intents, `ai/triage.py`, `ai/remind.py`, `ai/plan.py` rationale) | local | Run by hand on our DGX Spark for extraction and verifier (`evals/`); the other tasks tested with a stub |
| **Muse Spark** (`muse-spark-1.3`, Meta Model API `/chat/completions`, the user's key) | the same call sites in key mode; `ai/verify.py` when no Baseten key is set | key | **Unverified**: unit-tested against stubs; no key in our eval environment |
| **Muse Spark Open** (Baseten, `inference.baseten.co`) | `ai/verify.py`, only in key mode when the **server owner** sets `BASETEN_API_KEY` | key | **Unverified**: unit-tested only; the model slug is unconfirmed; needs a Baseten key we have not set on the demo |
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
