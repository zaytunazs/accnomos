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
| `apps/web` | Next.js PWA (Home · Review · Ask · VAT · Jobs · Files) |

| `apps/web` | Next.js PWA (Home · Review · Ask · VAT return · Contacts · Files) |
| `apps/mobile` | Flutter Android app, same runtime API |
| `services/runtime` | Stateless Agent Runtime (FastAPI): receives the user's cloud token + AI config per request, keeps nothing |
| `services/hmrc-relay` | Stateless HMRC relay: holds the HMRC client secret, adds fraud-prevention headers |
| `packages/ledger` | Append-only ledger events, projections, deterministic VAT 9-box engine, tests |
| `packages/connectors` | `StorageProvider` / `MailProvider` / `CalendarProvider` interfaces, Microsoft Graph implementations, fake provider + contract tests |
| `evals` | Synthetic gold set and the eval harness that grades Meta model outputs |
| `tools` | Owner-run scripts (keystore, dev helpers) |

## Meta models used (runtime path)

| Model | Role |
|---|---|
| Muse Glimmer 30B (open weights, Ollama, user's own hardware) | Receipt/invoice reading, categorising, tool calls |
| muse-spark-1.3 (Meta Model API, user's key) | Review, anomalies, explanations; cloud-mode extraction |
| sam-3.1 | Crop/split receipts in messy photos |
| muse-voice-transcribe-1.0 | Voice notes and voice questions |
| muse-wonder-1.0 | Plans multi-step commands |
| Muse Spark Open (Baseten) | Independent verifier (optional) |

## What works today (verified live, updated as we go)

| Date | Verified |
|---|---|
| 26 Oct | Microsoft sign-in (MSAL v5 + redirect bridge) on a personal account; `Apps/Accnomos` tree + README created in the user's OneDrive |
| 27 Oct | Upload → `00 Inbox` → scan → **Muse Glimmer 30B on our DGX Spark** reads the receipt (40 s, 9/9 code checks) → proposal in `_System/proposals` → **Approve** → immutable ledger event in `_System/Ledger/events` → **VAT 9 boxes computed by code** from those events (`/books/vat`) |
| 27 Oct | Eval on 60 synthetic messy receipts (Glimmer, local): supplier 100%, VAT total 100%, gross 100%, date 98%, net 97%; proposed/needs-a-look decision 88% — `evals/REPORT_glimmer_messy_60_2026-10-27.md` |
| 27 Oct | HMRC relay: OAuth, fraud-prevention headers v3.3, VAT MTD endpoints — unit-tested against mocks; sandbox call pending credentials |
| 27 Oct | **HMRC (sandbox) in the web app:** on `/vat`, under the live 9-box return, *Connect to HMRC (sandbox)* (OAuth with PKCE through the relay, tokens only in the tab's `sessionStorage`) → open obligations → confirm the boxes and tick the legal declaration → submit → receipt saved to `05 VAT returns/<periodKey>/` in your OneDrive. Built and type-checked; end-to-end browser run pending. See `docs/HMRC.md` |
| 27 Oct | **Outlook intake (F10):** Settings → *Outlook intake* asks for `Mail.Read` only when switched on → *Check my inbox now* (`POST /mail/scan`) copies likely receipts/invoices from the last 14 days into `00 Inbox`, deduplicated, with a log in `_System/Intake/`. Web build passes; runtime tests written against fake mailbox/storage; live mailbox run pending |
| 27 Oct | **Voice ask (Muse Voice Transcribe) — key mode only:** on `/ask`, hold the mic button to speak a question → the browser records webm/opus → `POST /books/ask/voice` converts it with ffmpeg to WAV mono 16 kHz → `muse-voice-transcribe-1.0` with your Meta key → the transcript goes through the same grounded Ask as typed questions and is shown as your message. Audio is not kept. Disabled in local-AI mode. Tests on a generated tone and stubbed HTTP (`services/runtime/tests/test_voice.py`); Muse Voice request format from research notes, not yet checked against dev.meta.ai; live mic run pending |
| 27 Oct | **Autopilot L1:** tick *Always do this for &lt;supplier&gt;* on Approve → rule saved to `_System/Rules/rules.json` in your OneDrive → later scans post matching receipts as `autopilot` **only** when every code check passes, the VAT number and VAT treatment match and the total is ≤ 2× the usual; each one is audited and listed in Review under *Approved by Autopilot* with **Undo** (a reversing ledger entry, never a delete). Rules and an on/off switch in Settings. Fake-storage tests in `services/runtime/tests/test_autopilot.py`; end-to-end run pending. See `docs/AUTOPILOT.md` |
| 27 Oct | **Verifier:** independent second reading compared per field in code; disagreement → *Needs a look* with both values. Glimmer/Glimmer on 20 messy receipts: 17/18 verified agreed on all fields, 1 false alarm (mixed-rate net), 0 extra catches — `evals/REPORT_verifier_glimmer_messy_20_2026-10-27.md`. Baseten path unit-tested only |
| 27 Oct | **Books.xlsx:** rebuilt from the event files after every approve, reject and bank match, and on demand (`POST /books/rebuild`, *Rebuild Books.xlsx* on Files). Sheets `README` (says it is generated; do not edit), `Summary`, `Ledger` (with totals row), `Accounts`, `VAT`, `Customers`, `Suppliers`, `Bank`, `Proposals`; £ and dd/mm/yyyy formats, frozen headers. Runtime tests open the workbook with openpyxl on a synthetic ledger and check the totals on `Ledger`, `Customers`, `Suppliers`, `Summary` and `VAT` against the events (a reversal nets off). There is no *undo approval* yet, so there is no undo path to rebuild after. Not yet opened in Excel from a real OneDrive |
| 27 Oct | **Files page (live):** signed in, lists the real books folder from Graph (00–06 with file counts, sizes, last modified, *Open* links; `_System` collapsed); signed out, the sample tree. Web build passes; not yet checked against a real OneDrive |
| 27 Oct | **VAT deadlines (F12-lite):** `GET /books/deadlines` works out the current VAT period from the stagger (1/2/3, custom start month, or monthly), the return/payment date (1 month + 7 days after period end), days left and Box 5 so far; Home *Deadlines* uses it when signed in, sample otherwise. Stagger is set in onboarding and Settings (this device only). Date maths unit-tested; annual accounting not covered; not yet run against a real account |
| 27 Oct | **Contacts:** `/contacts` lists customers and suppliers built from the ledger (one contact per VAT number, else per normalised name, so "Screwfix Direct Ltd." and "SCREWFIX DIRECT" are one), with open balance and net this tax year; a side panel shows the statement (running balance; card/cash receipts settle on their own line, invoices and bills on account stay open until a bank line is matched) and *Edit* (edited fields survive *Refresh from books*; a rename to another contact's name is refused). *Aged balances* tab: debtors and creditors in 0–30/31–60/61–90/90+ days from the document date. *Import from Outlook* asks for `Contacts.Read` only when tapped and fills blank emails/phones (optionally adds new contacts). Saved: names and details only, in `_System/Contacts/contacts.json`; money is always worked out from the event files. Books.xlsx gains `Customers` and `Suppliers` (name, VAT number, net and VAT this tax year, unpaid), and `Summary` counts both. Web build passes; runtime tests pass against fake storage and a fake address book (`services/runtime/tests/test_contacts.py`); not yet run against a real OneDrive or Outlook |

| 27 Oct | **Books.xlsx:** rebuilt from the event files after every approve, reject and bank match, and on demand (`POST /books/rebuild`, *Rebuild Books.xlsx* on Files). Sheets `README` (says it is generated; do not edit), `Summary`, `Ledger` (with totals row), `Accounts`, `VAT`, `Suppliers`, `Bank`, `Proposals`; £ and dd/mm/yyyy formats, frozen headers. Runtime tests open the workbook with openpyxl on a synthetic ledger and check the totals on `Ledger`, `Suppliers`, `Summary` and `VAT` against the events (a reversal nets off on all four). There is no *undo approval* yet, so there is no undo path to rebuild after. Not yet opened in Excel from a real OneDrive |
| 27 Oct | **Files page (live):** signed in, lists the real books folder from Graph (00–06 with file counts, sizes, last modified, *Open* links; `_System` collapsed); signed out, the sample tree. Web build passes; not yet checked against a real OneDrive |
| 27 Oct | **VAT deadlines (F12-lite):** `GET /books/deadlines` works out the current VAT period from the stagger (1/2/3, custom start month, or monthly), the return/payment date (1 month + 7 days after period end), days left and Box 5 so far; Home *Deadlines* uses it when signed in, sample otherwise. Stagger is set in onboarding and Settings (this device only). Date maths unit-tested; annual accounting not covered; not yet run against a real account |
| 27 Oct | **Jobs, staff and timesheets:** `/jobs` (summary tiles, jobs table, *Add job*) and the job page (timesheet with a quick-add row: staff, date, hours in 0.25 steps, note, billable; labour cost, materials, billable value and margin). Staff and their cost/charge rates in Settings › *Staff* (names and roles only). Review can tag a purchase to a job on Approve; its ex-VAT net counts as job materials until undone. *Create invoice from unbilled hours* proposes one line per person (hours × charge rate, at cost if none is set) and marks nothing; until sales invoicing lands, *Invoice sent: mark these hours invoiced* records the invoice number (`POST /jobs/{id}/mark-invoiced`). Files in `_System/Jobs`, `_System/Staff`, `_System/Timesheets/<yyyy-mm>.jsonl`; Books.xlsx gets a `Jobs` sheet. "Invoiced" and margin value hours at each person's *current* charge rate (not read back from an invoice), so changing a rate changes past figures. Rounding, pence maths, grouping, summaries and routes tested on fake storage (`services/runtime/tests/test_jobs.py`); web build passes; not yet run against a real OneDrive |

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
