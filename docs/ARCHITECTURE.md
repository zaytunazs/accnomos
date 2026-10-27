# Architecture

Accnomos has no user database. Three pieces cooperate, and two of them are stateless.

```
 Browser PWA / Android app ──(Graph token + AI settings in headers, every request)──► Agent Runtime (FastAPI, stateless)
        │  │                                                                             │        │
        │  └─ HMRC calls ──► HMRC relay (stateless; holds only the HMRC client secret) ──┼──► HMRC (sandbox)
        ▼                                                                                ▼        ▼
   Microsoft Graph ◄────────── reads and writes the user's own OneDrive folder ◄─────────┘   Meta models
```

## The stateless runtime

`services/runtime` receives the user's storage token and AI configuration (`X-AI-Mode`, `X-Meta-Api-Key`, …) with each request,
works against the user's own folder, answers and keeps nothing. Voice audio is the only thing written locally, in a temporary
directory that is deleted after conversion. Browsers call it directly; CORS is its only gate (`CORS_ORIGINS`), because every call
is useless without the caller's own Graph token. Demo deployment (`deploy/`): Docker on a DGX Spark, published as
`api.accnomos.com` through a tunnel, with Ollama on the same host.

## The HMRC relay

`services/hmrc-relay` exists only because HMRC needs the OAuth **client secret** at code exchange and refresh. It holds that
secret, adds the spec v3.3 fraud-prevention headers (client facts from the browser plus facts it saw itself), validates the
return (box 3 = 1 + 2, box 5 = |3 − 4|, whole pounds where HMRC requires) and forwards. PKCE: only the browser holds the
verifier. User tokens sit in the tab's `sessionStorage` and travel in `X-HMRC-Access-Token`. Details: `services/hmrc-relay/README.md`, `docs/HMRC.md`.

## OneDrive as the database

Personal accounts use the app folder (`Files.ReadWrite.AppFolder`, → *OneDrive › Apps › Accnomos*); work accounts use `/Accnomos`.

| Path | Holds |
|---|---|
| `00 Inbox` · `01 Receipts` · `02 Sales invoices` · `03 Bank statements` · `04 Needs a look` · `05 VAT returns/<periodKey>/` · `06 Reports` | The user's documents; filed by code, never deleted. `05` gets `return.json` and `receipt.json` (HMRC's response and the fraud headers sent) |
| `_System/Ledger/events/<yyyy-mm>/<ts>-<device>-<id>.json` | **The books.** One immutable, balanced journal per file (integer pence) |
| `_System/proposals/`, `_System/docs/<sha256>.json` | Proposals and their decisions; one record per processed document (hash = duplicate key) |
| `_System/audit/<yyyy-mm>.jsonl`, `_System/audit/autopilot/` | Append-only audit trail |
| `_System/Rules`, `Contacts`, `Jobs`, `Staff`, `Timesheets`, `Vehicles`, `Mileage`, `bank`, `Intake` | Settings and working data. Money is always recomputed from the events |
| `Books.xlsx` | Read-only projection, rebuilt from the event files after every approve, reject and bank match (sheets: README, Summary, Ledger, Accounts, VAT, Customers, Suppliers, Bank, Jobs, Vehicles, Proposals) |

**Ledger events** (`packages/ledger`): `kind` = purchase · sale · bank · adjustment · reversal, ≥ 2 lines, Σ debit = Σ credit
(enforced on construction), VAT code per line (S, R, Z, E, O, N), `evidence` = document hashes, `approved_by` (agents never
approve; Autopilot is recorded as `autopilot`). Nothing is edited; **undo adds a `reversal` event** that references the original.
The 9 VAT boxes come from `compute_vat_return`, plain code.

## The agent pipeline

| # | Stage | Done by | Today |
|---|---|---|---|
| 1 | Intake | Code | Upload to `00 Inbox`, scan, optional Outlook copy (`Mail.Read`, plain-code filters, no AI) |
| 2 | Extractor | **Muse Glimmer 30B** (local) or **Muse Spark** (key mode), strict-JSON schema; optional crop first (code by default, SAM 3.1 behind a flag) | Live |
| 3 | Checker | **Code**: line and total arithmetic, VAT maths and rates, VAT-number format, duplicate hash, currency, valid date, confidence (a date-in-period check exists in `checks.py` but the scan does not pass a period yet, so it never runs) | Live; any failure → *Needs a look* |
| 4 | Reviewer | **Code** composes the "why" line on each card (labelled "Checker, code"). Muse Spark explains only in *Ask* | **No separate LLM reviewer is wired into the pipeline** |
| 5 | Verifier | A second model reads the image again with a different prompt and never sees the first answer; **code** compares six fields | Live; disagreement → *Needs a look* with both values |
| 6 | Human | The user taps Approve (or Reject) | Always, unless an Autopilot rule applies (below) |
| 7 | Poster | Code writes the ledger event | Live |
| 8 | Filer | Code renames and files the document; HMRC submission is a separate, explicit step with a legal declaration | Live; HMRC sandbox only |

Autopilot is off by default (level L1, propose only). At L2 a receipt posts without a tap only if a rule you saved matches
(same supplier, VAT number and treatment, total ≤ 2× the usual) **and** every code check passes with no warnings (which includes the verifier agreeing). Each post is audited and has **Undo**. See `docs/AUTOPILOT.md`.

## Where each Meta model is used

See `docs/META_MODELS.md` for the full table. In short: Glimmer or Spark read and answer; Spark Open (Baseten, optional) or
Glimmer verify; Voice Transcribe turns a spoken question into text; SAM 3.1 crops photos only when switched on; Muse Image was used for
brand artwork, not in the product runtime.

## What never leaves the device

- Meta API key: browser `localStorage`, sent per request to the runtime in a header (Android: app settings; TODO: secure storage).
- HMRC tokens: tab `sessionStorage`. Microsoft tokens: MSAL's cache in the browser or app.
- In **local** mode, document images go only to Ollama, never to Meta or Baseten. Caveat: in our demo the runtime and Ollama are on
  our DGX Spark, so the image passes through that machine's memory. Truly on-device needs you to run the runtime yourself.
- Voice audio is not kept; voice is key mode only.

## Threat model

1. **Runtime sees tokens and documents in memory.** Mitigation: stateless by design, no database, tokens never logged or stored; self-hostable. Work accounts grant a broader scope (`Files.ReadWrite`) than personal ones.
2. **Prompt injection or a wrong reading from a document.** Model output is untrusted: code checks, an independent second reading, and a human approval stand between it and the ledger. *Ask* answers are checked against a facts pack; an invented figure is replaced by the quoted facts.
3. **HMRC credentials and filing.** Client secret only in the relay; PKCE, signed `state`, redirect allow-list; no filing without the ticked legal declaration. Sandbox only.
4. **Tampering.** Events are append-only by convention and by code, but the files are the user's: they are **not signed or hash-chained**, so edits made directly in OneDrive would not be detected. Books.xlsx is generated and labelled do-not-edit.
5. **Availability.** One host behind a tunnel runs the demo. Fallbacks: key mode needs no Ollama; `VERIFIER=off`; the books stay readable in OneDrive whether or not we are up.
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
