# Accnomos

**Accounting, intelligently done.** Your books stay in your own cloud. Meta AI does the work.

Bookkeeping and MTD VAT for UK small businesses, built for the Meta Global AI Developer Hackathon
(26 Oct – 4 Nov 2026, Indie track, problem statement "Build for Your World").

- **No user database.** Your books live in a folder you own (OneDrive first; Google Drive next).
  Disconnect the app and every file is still there, readable without us.
- **Meta AI on your terms.** Bring your own Meta Model API key, or run Muse Glimmer 30B on your own machine.
- **AI proposes, you approve, code calculates.** VAT boxes are computed by deterministic code from
  entries you approved; filing to HMRC needs an explicit tap.
- Multi-agent with verification: Intake → Extractor → Checker (code) → Reviewer → Verifier → Human → Poster → Filer.

## Layout

| Path | What |
|---|---|
| `apps/web` | Next.js PWA (Home · Review · Ask · Bank · VAT return · Jobs · Contacts · Vehicles · Files · Settings) |
| `apps/mobile` | Flutter Android app (Home · Review · Ask · VAT return · Settings), same runtime API |
| `services/runtime` | Stateless Agent Runtime (FastAPI): receives the user's cloud token + AI config per request, keeps nothing |
| `services/hmrc-relay` | Stateless HMRC relay: holds the HMRC client secret, adds fraud-prevention headers |
| `packages/ledger` | Append-only ledger events, projections, deterministic VAT 9-box engine, tests |
| `packages/connectors` | `StorageProvider` / `MailProvider` / `ContactsProvider` / `CalendarProvider` interfaces, Microsoft Graph implementations, fake provider + contract tests |
| `evals` | Synthetic gold set and the eval harness that grades Meta model outputs |
| `tools` | Owner-run scripts (keystore, dev helpers) |
| `docs` | `ARCHITECTURE.md` (folder layout, headers, audit format), `DEV.md`, `HMRC.md`, `AUTOPILOT.md`, `REMAINING.md`, `reviews/` |

## Meta models used (runtime path)

| Model | Role |
|---|---|
| Muse Glimmer 30B (open weights, Ollama, user's own hardware) | Receipt/invoice reading, categorising, tool calls |
| muse-spark-1.3 (Meta Model API, user's key) | Review, anomalies, explanations; cloud-mode extraction |
| sam-3.1 | Crop/split receipts in messy photos |
| muse-voice-transcribe-1.0 | Voice notes and voice questions |
| muse-wonder-1.0 | Plans multi-step commands |
| Muse Spark Open (Baseten) | Independent verifier (optional) |

## What works today

Status words: **works end-to-end** (run live against a real OneDrive / model), **works with fakes / needs a live
run** (tests pass against fake storage, mailbox or model; not yet run live), **UI only** (screens with sample
data, no backend), **not started**. Last checked 27 Oct 2026 against `main`: runtime 270 tests, ledger and
connectors 50, relay 39, web build passes. The Android app was not analysed (no Flutter on the review machine).
What is still open is in `docs/REMAINING.md`.

| Feature | Status | Evidence and gaps |
|---|---|---|
| Microsoft sign-in and books folder setup | **works end-to-end** | 26 Oct: MSAL v5 on a personal account; `Apps/Accnomos` tree and `README.txt` created in OneDrive. Work accounts not tried |
| Read a receipt → proposal → Approve → ledger event | **works end-to-end** | 27 Oct: upload to `00 Inbox` → Muse Glimmer 30B on our DGX Spark (40 s, 9/9 code checks) → Approve → event in `_System/Ledger/events`. Key mode (muse-spark-1.3) unit-tested only |
| VAT return: 9 boxes by code | **works end-to-end** | 27 Oct: `/books/vat` from the approved events above. Undone sales and purchases net off on the right side (fixed in this review) |
| Extraction quality (eval) | **works end-to-end** | 60 synthetic messy receipts, Glimmer local: supplier, VAT and gross 100 %, date 98 %, net 97 %, decision 88 % — `evals/REPORT_glimmer_messy_60_2026-10-27.md` |
| Undo an approval | **works with fakes / needs a live run** | Posts a reversal event, puts the proposal back in Review, rebuilds Books.xlsx; refused while a bank line is matched |
| HMRC VAT submission (sandbox) | **works with fakes / needs a live run** | Relay OAuth, fraud headers v3.3 and MTD endpoints tested against mocks; `/vat` *Connect to HMRC* → obligations → declaration → submit → `05 VAT returns/<periodKey>/` built and type-checked. No sandbox call yet. `docs/HMRC.md` |
| Verifier (second reading) | **works with fakes / needs a live run** | Glimmer/Glimmer eval on 20 messy receipts: 17/18 verified agreed, 1 false alarm, 0 extra catches (`evals/REPORT_verifier_glimmer_messy_20_2026-10-27.md`). Not run in the app; Baseten and key paths unit-tested only |
| Document crop | **works with fakes / needs a live run** | Code method on 20 synthetic scenes: mean IoU 0.88. SAM 3.1 path off by default (wire format unverified) |
| Autopilot L1 | **works with fakes / needs a live run** | Rules from *Always do this*; posts only when every check passes and the total is ≤ 2× usual; *Approved by Autopilot* list with Undo. `docs/AUTOPILOT.md` |
| Ask your books (typed) | **works with fakes / needs a live run** | Facts pack by code, every figure in the answer checked; tests use a stubbed model |
| Ask by voice | **works with fakes / needs a live run** | ffmpeg → `muse-voice-transcribe-1.0` (key mode only); tested on a generated tone and stubbed HTTP. Request format not checked against dev.meta.ai |
| Outlook intake | **works with fakes / needs a live run** | `Mail.Read` only; copies likely receipts to `00 Inbox`, deduplicated. Fake mailbox tests. See below |
| Books.xlsx | **works with fakes / needs a live run** | 11 sheets rebuilt after every approve, reject, undo, bank action and on demand; one integration test builds it from every feature at once. Not yet opened in Excel from a real OneDrive |
| Files page | **works with fakes / needs a live run** | Lists the real folder from Graph when signed in; build-checked only |
| VAT deadlines | **works with fakes / needs a live run** | Current period, due date (1 month + 7 days), days left and Box 5 so far; date maths unit-tested. Annual accounting not covered |
| Bank statements | **works with fakes / needs a live run** | CSV import (Barclays, Starling, Tide, Monzo, HSBC/Lloyds layouts modelled, not checked against real exports), suggested matches, transfer/ignore, expense proposals, *Reconciled to date*. Gold CSVs in `evals/gold/bank/` |
| Contacts | **works with fakes / needs a live run** | Customers and suppliers from the ledger, statements, aged balances, *Import from Outlook* (`Contacts.Read`) |
| Jobs, staff and timesheets | **works with fakes / needs a live run** | Jobs, timesheets in 0.25 h steps, labour/materials/margin, invoice lines from unbilled hours. Values use each person's *current* charge rate |
| Vehicles and mileage | **works with fakes / needs a live run** | HMRC approved mileage rates (45p/25p, 24p, 20p), claims as proposals owed to the owner, locking after a claim, vehicle costs tagged at scan |
| Android app | **works with fakes / needs a live run** | Sign-in, capture to `00 Inbox`, Review (approve/edit/reject), Ask, VAT return; built for the emulator. Home tiles are sample data. Bank, Jobs, Contacts, Vehicles and Files are web only |
| Home tiles and activity (web) | **UI only** | Cash in bank, owed to you, VAT estimate and the activity feed are sample data; only *Deadlines* is live |
| Sales invoicing | **not started** | Jobs propose invoice lines; nothing creates or sends an invoice |
| Google Drive | **not started** | OneDrive only |
| Multi-step commands (muse-wonder) | **not started** | |

## Outlook intake

Turn it on in Settings and Accnomos asks Microsoft for one extra permission, `Mail.Read` (read-only). *Check my inbox
now* looks at emails with attachments from the last 14 days and, with plain code (no AI), keeps PDF/JPEG/PNG/HEIC files
between 10 KB and 15 MB that look like receipts or invoices (sender outside your own domain; words such as receipt,
invoice, bill, order, payment, VAT or remittance in the subject or file name). **Read:** message date, sender, subject
and those attachments. **Written, all in your own folder:** the file as `00 Inbox/<date>_<sender-domain>_<name>`,
`_System/Intake/seen.json` (so nothing is copied twice) and `_System/Intake/log/<yyyy-mm>.jsonl`. **Never:** sending,
moving, flagging, marking as read or deleting mail, reading message bodies, or keeping anything on our server. The
last check time is kept only in this browser. HEIC photos are copied but wait in `00 Inbox` until the reader supports them.

## Verifier (second opinion)

When the first reading passes every code check, a Verifier model reads the same image again with a different prompt
(one question per field) and never sees the first answer. Code then compares supplier, VAT number, date, net, VAT
and total: names ignoring case, punctuation and Ltd/Limited, dates by value, money to the penny (±1p), VAT numbers
by digits. If all six agree, the Review card says *Verifier agrees · all 6 fields match*. Any disagreement sends the
proposal to *Needs a look* with both readings side by side; check the document, then approve or reject. Neither the
model nor the code picks or merges values (choosing the second reading in the card is not built yet). **Which
model:** in local mode it is Glimmer on your machine, so the document stays there. With your own key it is Muse Spark
Open on Baseten if the server owner has set `BASETEN_API_KEY`, otherwise muse-spark-1.3 with your key.
`VERIFIER=off` disables it. First numbers (20 messy receipts, Glimmer/Glimmer): 94% full agreement, 0 errors caught
beyond what the code checks already caught, 1 false alarm. See `evals/REPORT_verifier_glimmer_messy_20_2026-10-27.md`.

## Honesty notes

- Everything in this repository was written during the hackathon building period. Pre-existing items: none in the code; the
  DGX Spark/Ollama host setup predates the event and is infrastructure, not product code.
- Demo data is synthetic and labelled "SAMPLE — FICTIONAL COMPANY". HMRC is sandbox only.
- Coding assistants (Claude, Muse Code, local Qwen) were used to write code; Meta models are the ones doing the work at runtime.
- Meta has no text-to-speech model; spoken answers use the device's own TTS.

## Running locally

See `docs/DEV.md` (written as the pieces land). Secrets go in `.env` (copy `.env.example`); never commit it.

## Licence

MIT — see `LICENSE`.
