# Accnomos

**Accounting, intelligently done.** Bookkeeping and MTD VAT for UK small businesses, built for the Meta Global AI Developer Hackathon (Indie track).
Your books are files in your own OneDrive (no Accnomos database); Meta models read and check the paperwork; you approve; code calculates the VAT.

- **Works today (tested, mostly on fakes):** upload a receipt → Muse Glimmer 30B (or Muse Spark) reads it → code checks + an independent second reading → you approve → immutable ledger event → VAT nine boxes by code → HMRC **sandbox** submission (web) → `Books.xlsx`; plus Ask, bank statements, invoicing, jobs, mileage, pay-run estimates, a day planner and an Android app. One row each in the table below.
- **Not yet:** production HMRC filing, Google Drive, and any run of most features against a real OneDrive, a real model key or a real phone. `docs/HONESTY.md` lists every known gap.
- **Run it:** `uv sync --all-packages --all-extras && uv run pytest -q`; `cd apps/web && pnpm install && pnpm run build`; services and web dev servers in `docs/DEV.md`.
- **Docs:** [Architecture](docs/ARCHITECTURE.md) · [Meta models and evals](docs/META_MODELS.md) · [4-minute demo](docs/DEMO.md) · [Honesty](docs/HONESTY.md) · [What remains](docs/REMAINING.md)

## Layout

| Path | What |
|---|---|
| `apps/web` | Next.js PWA (Home · Review · Ask · Invoices · Bank · VAT return · Jobs · Payroll · Contacts · Vehicles · Files · Settings) |
| `apps/mobile` | Flutter Android app (Home · Review · Ask · VAT · More: Files, Contacts, Invoices, Jobs, Vehicles, Bank, Payroll; Settings), same runtime API |
| `services/runtime` | Stateless Agent Runtime (FastAPI): receives the user's cloud token + AI config per request, keeps nothing |
| `services/hmrc-relay` | Stateless HMRC relay: holds the HMRC client secret, adds fraud-prevention headers |
| `packages/ledger` | Append-only ledger events, projections, deterministic VAT 9-box engine, bank CSV parsing and matching, tests |
| `packages/connectors` | `StorageProvider` / `MailProvider` / `ContactsProvider` / `CalendarProvider` interfaces, Microsoft Graph implementations, fake provider + contract tests |
| `evals` | Synthetic gold set and the eval harness that grades Meta model outputs |
| `tools` | Owner-run scripts (keystore, brand art, sample receipt, dev helpers) |
| `docs` | `ARCHITECTURE.md` (folder layout, headers, models, audit format), `DEV.md`, `HMRC.md`, `AUTOPILOT.md`, `ACTIONS.md`, `INBOX.md`, `PLANNER.md`, `SECURITY.md`, `HONESTY.md`, `REMAINING.md`, `reviews/` |

## Meta models used (runtime path)

| Model | Role |
|---|---|
| Muse Glimmer 30B (open weights, Ollama) | Receipt/invoice reading, categorising, local-mode Ask, Verifier and the other text tasks |
| muse-spark-1.3 (Meta Model API, user's key) | Key-mode extraction, Ask and the other text tasks |
| Muse Spark Open (Baseten, optional) | Independent verifier (key mode; needs the server owner's Baseten key; unit-tested only) |
| muse-voice-transcribe-1.0 | Spoken questions on Ask (key mode; not yet run live) |
| sam-3.1 | Crop receipts in messy photos, **off by default** (code crop is the default; never run live) |

Muse Image made the brand artwork at build time (`tools/brand_muse.py`; not in the runtime). Costs, fallbacks and eval numbers: `docs/META_MODELS.md`.

## What works today

Checked 27 Oct 2026 on this checkout: `pytest -q` passes in `services/runtime` (600 tests), `packages/ledger` (32),
`packages/connectors` (34) and `services/hmrc-relay` (100). `cd apps/web && pnpm run e2e` is set up to run 23
Playwright tests; this check did not re-run it. Nothing in the Flutter app was built, analysed or tested (no Flutter SDK here).
**"Tested" means automated tests on fakes:** an in-memory OneDrive, mailbox, calendar and address book
(`packages/connectors`), a stubbed model, HMRC and Meta mocked over HTTP. That proves our logic, not Microsoft, Meta or HMRC.
**Runs against real services** were done by hand by the maintainers on 26–27 Oct (a personal Microsoft account, Muse Glimmer 30B
on our DGX Spark: sign-in, folder setup, read → approve → ledger → VAT boxes). No log is committed, so that is our word, not
evidence. The committed artefacts are the eval reports in `evals/`. All demo companies, receipts and CSVs are synthetic.
Gaps and limits: `docs/HONESTY.md` (flat list) and `docs/REMAINING.md` (by severity).

| Feature | What it does | How it is tested | NOT verified |
|---|---|---|---|
| Microsoft sign-in, books folder | MSAL sign-in; creates `00 Inbox` … `06 Reports` + `_System` and a `README.txt` in the user's OneDrive (app folder for personal accounts, `/Accnomos` for work) | e2e `connect.spec.ts` with a **fake** account; `packages/connectors/tests/test_msgraph.py` (mock transport) | Real sign-in run by hand on a personal account only; work accounts never tried |
| Receipts → review → ledger | Upload (or phone capture) → `00 Inbox` → scan → optional code crop → model reads → code checks → Verifier second reading → proposal → **Approve** → balanced ledger event in `_System/Ledger/events` → filed. *Undo* adds a reversal event. Code: `pipeline.py`, `checks.py`, `approve.py` | `test_books.py`, `test_checks_journal.py`, `test_verify.py`, `test_crop.py`, `test_integration.py`, `packages/ledger/tests`; e2e `review-vat.spec.ts` (stub AI) | Key mode (muse-spark-1.3), Baseten verifier and SAM 3.1 never called for real; real phone photos. Eval, 60 synthetic messy receipts, Glimmer local: supplier, VAT and gross 100 %, date 98 %, net 97 %, status 80 % (`evals/REPORT_glimmer_messy_60_2026-10-27.md`). Verifier, 20 docs, Glimmer checking Glimmer: 17/18 agreed, 0 extra catches, 1 false alarm (`evals/REPORT_verifier_glimmer_messy_20_2026-10-27.md`) |
| Books.xlsx | Rebuilt from the event files after approve, reject, undo, bank, invoice, payroll, mileage and job actions, and on demand (`POST /books/rebuild`). 12 sheets (`SHEETS` in `projection.py`); a generated, do-not-edit copy | `test_bank_projection.py`, `test_integration.py`, `test_contacts.py`, `test_jobs.py`, `test_mileage.py`, `test_payroll.py` open it with openpyxl and check sheets and totals | Never opened in Excel from a real OneDrive. openpyxl turns any cell text starting with `=` into a formula (every sheet) |
| VAT return, periods, deadlines | Nine boxes by code (`compute_vat_return`), boxes 6–9 whole pounds; period picker (current + 8 before) by saved stagger; a scan warns when a document's date is outside the period; `GET /books/deadlines` | `test_vat_route.py`, `test_vat_periods.py`, `test_deadlines.py`, `packages/ledger/tests/test_vat.py`; e2e `review-vat.spec.ts` | Real account. Annual accounting and flat-rate schemes not covered. "Submitted" means a receipt our own submission saved, so a return filed elsewhere shows as open |
| HMRC sandbox submission (web) | `/vat` → *Connect to HMRC (sandbox)* (OAuth + PKCE through the relay) → obligations (relay `/vat/{vrn}/obligations`) → declaration → submit → receipt in `05 VAT returns/<periodKey>/`. `docs/HMRC.md` | `services/hmrc-relay/tests` (HMRC mocked); e2e `hmrc.spec.ts` with Playwright standing in for the relay | No end-to-end call to HMRC's sandbox from the app. Never production. The runtime does not call HMRC's obligations endpoint |
| Ask (typed and voice) | Facts pack by code; every figure in the answer is checked and an invented one replaced by the facts; web and Android mic → ffmpeg → `muse-voice-transcribe-1.0` (key mode only) | `test_ask.py`, `test_voice.py` (generated tone, stubbed HTTP); e2e `ask.spec.ts` (stub AI) | Muse Voice request format is from research notes, not dev.meta.ai; no live mic run on any browser or phone; real model answers |
| Chat/voice actions | "Send a £100 invoice to JM Trading", "log 7.5 hours for Sam on Elm Road": the model returns an intent, code finds names and prices lines, a signed card waits for **Approve** (`POST /actions/approve`); audited. `docs/ACTIONS.md` | `test_actions.py` (stubbed model, fake storage and mailbox) | Real model and mailbox. Without `ACTIONS_SIGNING_KEY`, a restart or several workers make a card fail with 403 |
| Autopilot L1/L2 + Verifier | L1 (default) proposes only. At L2 a receipt posts without a tap only if a saved rule matches (same supplier, VAT number and treatment, total ≤ 2× usual) and every check passes with no warning, the verifier agreeing included; audited; *Undo*. `docs/AUTOPILOT.md` | `test_autopilot.py`, `test_verify.py`; Dart `autopilot_undo_test.dart` (not run) | End to end on real data. The Spark Open path needs a Baseten key; otherwise the verifier is Glimmer or muse-spark. The phone never sends `X-Autopilot: off` |
| Outlook intake | Settings → *Check my inbox now*: `Mail.Read` only; keeps PDF/JPEG/PNG/HEIC of 10 KB–15 MB from the last 14 days that look like receipts (plain code, no AI), deduplicated, copied to `00 Inbox`; never sends, moves or deletes mail | `test_mail_intake.py` (fake mailbox); e2e `outlook.spec.ts` | Real mailbox. HEIC is copied but not read yet |
| Inbox triage and to-dos | Home *Inbox* card: last 7 days, previews only, newsletters and no-reply senders dropped; your AI gives category, summary, suggested reply and to-dos, each checked by code; *Draft in Outlook* (`Mail.ReadWrite`) never sends; to-dos in `_System/Todos`. `docs/INBOX.md` | `test_triage.py` (fake mailbox, stubbed model, Graph request shapes on a mock transport) | Real mailbox and model. A failed second Graph call can leave an empty draft in Drafts |
| Bank statements | `/bank`: CSV import (Barclays, Starling, Tide, Monzo, HSBC/Lloyds layouts), suggested matches, transfer/ignore, expense proposals, *Reconciled to date*; on the phone, view and confirm a match | `packages/ledger/tests/test_bank.py`, `test_bank_gold.py` and `services/runtime/tests/test_bank_gold.py` on `evals/gold/bank/`; `test_bank_projection.py` | Layouts follow public formats, **not** checked against real exports |
| Contacts | Customers and suppliers built from the ledger, statements, aged balances, edit, *Import from Outlook* (`Contacts.Read`) | `test_contacts.py`, `packages/connectors/tests/test_contacts.py` | Real OneDrive and Outlook; admin consent on work accounts untested. A matched bank line counts as full payment |
| Sales invoicing | Draft → A4 PDF → send via Outlook (`Mail.Send`, after a tick) → sale posted once → reminder draft → mark paid / void (a reversal). Money by code, per line | `test_invoicing.py` (fake storage and mailbox), `packages/connectors/tests/test_send_mail.py` | Sending from a real mailbox; the PDF in a real viewer. No credit notes; *Mark paid* does not post to 1200 Bank |
| Jobs and timesheets | `/jobs`, staff rates in Settings, timesheets in 0.25 h steps, purchases tagged to a job on Approve, margin; invoice lines from unbilled hours | `test_jobs.py` | Real OneDrive. Invoices carry no link to hours: you mark them invoiced by typing the invoice number. "Invoiced" and margin use each person's *current* charge rate |
| Vehicles and mileage | Vehicles, mileage log, HMRC approved rates (45p/25p, 24p, 20p) from one table in `mileage.py`, a quarter's claim as an expense proposal owed to the owner, locking after a claim | `test_mileage.py` | Real OneDrive. The fuel scale charge is text only, not calculated |
| Pay runs (estimates) | `/payroll`: monthly estimate of PAYE, employee and employer NI from timesheet hours, CSV to `04 Payroll/`; *Confirm* posts the provider's **actual** gross and employer NI. Not payroll, not RTI | `test_payroll.py` | 2026–27 rates not re-checked against GOV.UK; no RTI (FPS/EPS); tax code 1257L, NI category A, month 1 only |
| Day planner | *Plan today*, or "Plan my Thursday" in Ask: code orders visits by postcode district around Outlook events, the model only writes the rationale; *Apply* creates `[Accnomos]` events once per plan. `docs/PLANNER.md` | `test_planner.py` (fake calendar; Graph request shapes on a mock transport) | Real Outlook calendar. Europe/London only; travel times are rules of thumb |
| Home dashboard | Cash, owed to you / by you, VAT Box 5 and deadline, needs attention and recent activity from one `GET /books/dashboard`, no model call; labelled sample when signed out | `test_dashboard.py`; e2e phone-width smoke loads the page | Real account. The "SAMPLE — FICTIONAL COMPANY" banner still shows when signed in |
| Files page | Lists the real books folder from Graph (`_System` collapsed) with *Open* links; *Rebuild Books.xlsx* | e2e `files.spec.ts` (look-alike Graph) | Real OneDrive. A folder's "N files" can count nested folders |
| Android app (0.2.0+2) | Sign-in, capture, Review (approve/edit/reject, Autopilot undo), Ask with mic and action cards, Home dashboard, VAT with period picker; More: Files, Contacts, Invoices, Jobs, Vehicles, Bank, Payroll (read-only) | 8 Dart tests in `apps/mobile/test`, **not run** | `flutter analyze` and `flutter test` never run; no phone run recorded. No HMRC filing. A VAT stagger is saved in Settings but no request sends it, so VAT and deadlines use calendar quarters. Release signing hash not registered with Microsoft |
| End-to-end suite | `pnpm run e2e`: Playwright (Chromium), test-mode web export + runtime, 23 tests including every page at phone width. `docs/DEV.md` | Itself (counted from `apps/web/e2e/*.spec.ts`; not re-run in this check) | Real MSAL, Graph, HMRC and model accuracy. `.github/workflows/e2e.yml` has never run on GitHub |
| Security | Log scrubbing, size caps, per-IP rate limit, safe 500s, exact-origin CORS, safe file names, one-time OAuth state, hardened containers. `docs/SECURITY.md` | `test_security.py`, `test_validation.py`, `test_deploy_hardening.py`, relay `test_hardening.py`, `test_state_and_redirects.py` | Not deployed or load-tested; images never built; rate limit is per process |

Not built: Google Drive (OneDrive only), production HMRC filing, `muse-wonder` multi-step planning, credit notes, RTI.

## Honesty notes

- Everything in this repository was written during the hackathon building period. Pre-existing items: none in the code; the
  DGX Spark/Ollama host setup predates the event and is infrastructure, not product code.
- Demo data is synthetic and labelled "SAMPLE — FICTIONAL COMPANY". HMRC is sandbox only.
- Coding assistants (Claude, Muse Code, local Qwen) were used to write code; Meta models are the ones doing the work at runtime.
- Meta has no text-to-speech model, and Accnomos does not read answers aloud: voice is input only.

## Running locally

See `docs/DEV.md`. Secrets go in `.env` (copy `.env.example`); never commit it.

## Licence

MIT — see `LICENSE`.
