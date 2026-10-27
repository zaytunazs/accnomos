# Architecture

Accnomos has no user database. The user's books are files in a folder they own; the services read and
write that folder with the user's own token on each request and keep nothing.

```
apps/web (Next.js PWA) ─┐                      ┌─> Microsoft Graph: the user's OneDrive folder
apps/mobile (Flutter) ──┼─> services/runtime ──┼─> Meta models (user's key) or Ollama (user's machine)
                        │   (FastAPI, :8780)   └─> Baseten verifier (only if the server owner sets a key)
                        └─> services/hmrc-relay (:8787) ─> HMRC MTD VAT API (sandbox)
```

- **services/runtime** (`app`): the Agent Runtime. Every call carries the user's Graph token and AI settings
  in headers (below). Routes are listed at `/docs` on a running runtime; `apps/web/src/lib/runtime.ts` and
  `apps/mobile/lib/services/runtime_client.dart` have one call per route.
- **services/hmrc-relay** (`relay`): holds the HMRC client secret, does OAuth and adds fraud-prevention
  headers. HMRC tokens stay in the browser tab's `sessionStorage`. See `docs/HMRC.md`.
- **packages/ledger**: ledger events, bank CSV parsing and matching, the VAT 9-box engine. No model code.
- **packages/connectors**: `StorageProvider`, `MailProvider`, `ContactsProvider`; Microsoft Graph and fake
  implementations.

## Settings headers

Read in one place each (`services/runtime/app/routes_books.py`, `app/ai/config.py`):

| Header | Read by | Notes |
|---|---|---|
| `X-Graph-Token`, `X-Account-Kind` | `get_books` | 401 without a token; kind is `personal` or `work` |
| `X-AI-Mode`, `X-AI-Base-Url`, `X-AI-Model`, `X-Meta-Api-Key` | `ai_config_from_request` | `key` or `local` |
| `X-User` | `require_user` / `optional_user` | the signed-in email; required for anything that writes |
| `X-Business-Name` | `business_name` | optional; tells sales invoices from purchases |
| `X-Autopilot` | `POST /books/scan` | `off` stops Autopilot for that scan |

## The books folder

Personal accounts: `Apps/Accnomos` (the OneDrive app folder). Work accounts: `/Accnomos`. Paths below are
relative to that root. `services/runtime/tests/test_integration.py` checks that everything the runtime writes
fits this list.

| Path | Written by | Kind |
|---|---|---|
| `README.txt` | web onboarding | written once |
| `00 Inbox/<name>` | web and Android upload; Outlook intake as `<yyyy-mm-dd>_<sender-domain>_<name>` | moved out when read |
| `01 Receipts/<yyyy-mm>/<date> <supplier> £<total>.<ext>` | runtime, when a proposal is filed | |
| `02 Sales invoices/<name>` | runtime | |
| `03 Bank statements/<last date>_<bank>.csv` | runtime, bank import | |
| `04 Needs a look/<name>` | runtime: documents that need a look, and rejected ones | |
| `05 VAT returns/<periodKey>/return.json`, `receipt.json` | web, after an HMRC submission | written once |
| `06 Reports/` | created at onboarding; nothing writes here yet | |
| `Books.xlsx` | runtime, after every decision and on *Rebuild* | rewritten whole |
| `_System/docs/<sha256>.json` | runtime: one per document read (the hash is the duplicate key) | |
| `_System/proposals/<id>.json` | runtime: proposals and their decisions | updated |
| `_System/Ledger/events/<yyyy-mm>/<ts>-runtime-<id>.json` | runtime, on approve or undo | **append-only** |
| `_System/audit/<yyyy-mm>.jsonl` | runtime: one line per action | **append-only** |
| `_System/audit/autopilot/<yyyy-mm>.jsonl` | runtime: Autopilot's own record | **append-only** |
| `_System/rules.json` | runtime: "file this supplier to that account" rules from Approve | rewritten |
| `_System/Rules/rules.json` | runtime: Autopilot rules ("Always do this") | rewritten |
| `_System/cursors.json` | runtime: last inbox scan | rewritten |
| `_System/bank/<sha256>.json` | runtime: lines from one statement, with their match status | updated |
| `_System/Intake/seen.json`, `_System/Intake/log/<yyyy-mm>.jsonl` | runtime, Outlook intake | |
| `_System/Contacts/contacts.json` | runtime: names and details only, never money | rewritten |
| `_System/Jobs/jobs.json`, `_System/Staff/staff.json` | runtime | rewritten |
| `_System/Timesheets/<yyyy-mm>.jsonl` | runtime | entries edited and deleted |
| `_System/Vehicles/vehicles.json`, `_System/Mileage/<tax-year>.jsonl` | runtime (tax year like `2026-27`) | entries edited and deleted |

OneDrive paths ignore case, so `_System/audit` and `_System/Audit` are one folder.

Ledger events are never edited. Undo posts a reversal event (every line on the other side, same date) and
puts the proposal back in Review. Money is integer pence in every file except Books.xlsx, which shows pounds.

## Audit lines

One JSON object per line, the same in both audit logs:

```json
{"ts": "2026-10-27T14:03:11+00:00", "actor": "user:sam@example.co.uk", "action": "approved", "refs": {"proposal": "…"}}
```

`actor` is `user:<email>` for something a person did, or `agent:<name>` (`agent:extractor`, `agent:intake`,
`agent:autopilot`, `agent:mileage`, `agent:contacts`) for something done for them.

## Books.xlsx

Built by `services/runtime/app/projection.py` from the files above, in this sheet order (`SHEETS`):
`README`, `Summary`, `Ledger`, `Accounts`, `VAT`, `Customers`, `Suppliers`, `Bank`, `Proposals`, `Jobs`,
`Vehicles`. A feature that cannot read its own files (a hand-edited jobs or vehicles file) leaves its sheet
empty and the rest still builds; a failed rebuild is audited and never fails the user's action.
