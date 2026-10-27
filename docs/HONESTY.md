# Honesty: every known gap

A flat list, grouped by area, from the code on `main` and the "What remains" section of every `docs/reviews/*/REVIEW.md`
(duplicates merged). Severity-ordered tables are in `docs/REMAINING.md`; what each feature does and how it is tested is the
README table. We could not reach accnomos.com or api.accnomos.com from this session, so the live sites are unchecked.

Checked 27 Oct 2026 on this checkout: `pytest -q` passes in `services/runtime` (811 passed, 1 skipped), `packages/ledger` (35),
`packages/connectors` (43), `services/hmrc-relay` (102) and `evals` (158). The Flutter app was **not** built, analysed or tested. `pnpm run build`
in `apps/web` passes; of the Playwright suite only `review.spec.ts`, `contacts.spec.ts` and `settings.spec.ts` were re-run (all pass). `ruff` has not been run on `main`.

## What is real, and what is not

- **Real runs** are the maintainers' own, on 26–27 Oct: Microsoft sign-in on a personal account, folder creation, upload → scan →
  Glimmer on our DGX Spark → approve → ledger event → VAT boxes. No log is committed. The committed evidence is the eval reports in `evals/`.
- Everything else is **tested on fakes** (in-memory OneDrive, mailbox, calendar and address book; stubbed model; mocked HMRC and Meta).
- **Demo data is synthetic**: Bramblewood Joinery Ltd, the receipts, bank CSVs and the gold set are generated. Signed out, Home, Review, Ask, VAT return and Files show static mock-ups under a "SAMPLE — FICTIONAL COMPANY" banner (`DemoBanner.tsx`); other pages label their own sample fallbacks. Once signed in the banner is hidden.
- **Evals are synthetic renderings**, so real phone photos will score lower. Extraction: 200 documents, Glimmer local, every field right on 88 % (60 documents: 73 %). Verifier: 20 documents, 0 extra catches, 1 false alarm. The Claude judge agrees with the code score on only 79/200 documents (it grades line wording and category, which the code does not); the code score is the headline.
- **Repairs and the re-read are not yet measured live.** Code now repairs VAT-inclusive totals and doubled quantities before the checks (the card says "Figures repaired by code from the receipt's own arithmetic") and re-reads unsure or non-adding documents once at higher resolution. Neither has had a live 200-document run. A replay of the stored readings through the repairs (`evals/harness/replay.py`, no model, so it cannot measure the re-read) gives all fields 88 % → 91 % and net 93 % → 97 %, but false passes 9 → 11: two receipts with no VAT number and no VAT, which the eval expects in *Needs a look*, used to fail only on bad arithmetic and now pass.
- **A missing VAT number with no VAT is now flagged only for suppliers the books don't know (owner's rule, 27 Oct).** Over £250, no VAT, no VAT number, unknown supplier: *Needs a look* with "Is &lt;supplier&gt; VAT-registered?"; ticking "isn't VAT-registered" on Approve records it in `contacts.json`, and a VAT number seen on an approved receipt records "registered", so later receipts are decided without asking. On perfect readings of the 200 gold documents false passes go 6 → 2 (`evals/runs/supplier_vat_replay/report.md`). **The replay of the stored Glimmer readings was not re-run** (the records were not in that checkout): the check only adds fails when the books are empty, so the 11 cannot rise except through gold 176/184, whose expectation moved to *Needs a look* (overseas SaaS suppliers over £250; the reading has no address, so code can't tell they are overseas, and the user is asked once per supplier). The two remaining false passes, 038 and 060, are under £250 with no VAT, which the rule passes and the older gold rule does not. Supplier lookup at scan time reads the saved `contacts.json` only: a supplier whose VAT number is in the ledger but who was never saved (approved before this change, Contacts never refreshed) counts as unknown until *Refresh from books*. Whether the business is VAT-registered is a new setting in the invoice profile (default yes; a VAT number always means yes).
- **Feature evals use the same synthetic data**, built from the gold documents rather than real exports or mailboxes: bank matching precision 83/83, recall 83/106; Outlook intake 12/17 documents kept, 11/11 decoys dropped; Ask numbers exact 28/32 (Glimmer) and 31/32 (Qwen). Each has its report under `evals/runs/` and one command to reproduce it. The triage expectation was written for the run, not taken from the fixtures.
- Everything was written during the build period with coding assistants (Claude, Muse Code, a local Qwen); every merge was reviewed (`docs/reviews/`). The DGX Spark and Ollama setup predates the event.

## HMRC

- **Sandbox only.** The relay defaults to `test-api.service.hmrc.gov.uk`; no production credentials, no real filing.
- The browser flow (connect → obligations → declaration → submit → receipt in `06 VAT returns/`) is built and type-checked but has **not been run end to end** against HMRC's sandbox. Relay tests mock HMRC.
- **The runtime makes no call to HMRC's obligations endpoint.** The relay has one and *Connect to HMRC* uses it, but `/books/vat/periods` cannot, because the runtime holds no HMRC token. So "submitted" means "a receipt our own submission saved in `06 VAT returns/`": a return filed elsewhere, or a deleted receipt, shows as open.
- The runtime's own period key (`26A4` style, saved as `calculated_for`) is a placeholder; submission uses HMRC's key. For monthly returns all three months of a quarter get the same placeholder.
- `GET /books/vat` accepts `?today=`, so a client can move "current" and with it `can_submit`; the web gate is advisory and HMRC decides what can be filed.
- No flat-rate scheme, no annual accounting scheme, no fuel scale-charge calculation.
- The runtime's "today" is the **London date** (`books.today()`, Europe/London via `zoneinfo` + `tzdata`): `GET /audit` `from`/`to` filter by London day too. Both clients send `today` to the dashboard, so this mostly affects direct API callers and chat actions.

## Receipts, review and the ledger

- **No separate LLM Reviewer.** The card's "why" line is composed by code ("Checker, code"). Models write words only in *Ask*, inbox triage, reminder drafts and the planner rationale, each checked by code. The signed-out mock-up on `/vat` has a "Reviewer's note (Muse Spark)"; it is labelled sample but no such reviewer runs.
- Key-mode extraction (muse-spark-1.3) is unit-tested only.
- **Ledger files are not tamper-evident** (no signatures, no hash chain). An undo is a reversing entry dated like the original; if that VAT period was already submitted, the correction belongs in the current period.
- `/books/vat` entry counts put a reversal against the box it reverses, and the page header says how many of the period's entries are undone (e.g. "3 entries, 1 undone").
- **No real HEIC from a phone has been read, and no real supplier PDF.** HEIC → JPEG (`pillow-heif` 1.8.1) and PDF
  reading (`pypdfium2` 5.14.0, locked in `uv.lock`) are tested with the real libraries, but only on files the tests make
  (a HEIC written by `pillow-heif`, PDFs written by `fpdf2`). The Docker image has not been built with them.
- A multi-page PDF is read from page 1 only (a total printed only on page 2 is missed); a scanner batch of several
  receipts in one PDF is read as one document and not split.
- Receipts in an email body are found by a code rule tested on six fictional emails, not on real Uber, Amazon or SaaS
  mail, nor on Graph's HTML-to-text conversion of them.
- `POST /books/approve/{id}` is kept as an alias for web builds deployed before the integration review; remove it after the next deploy.
- `07 Reports/` is created at onboarding and nothing writes to it. The folder names now have one source (`services/runtime/app/paths.py`); existing users' old-named folders are renamed once on first contact (`app/layout.py`), which has only been tested on fake storage, not on a real OneDrive.
- `services/runtime/tests/test_integration.py` holds the runtime to the documented folder layout only for the features its scenario exercises (not invoicing, payroll, planner, to-dos, action audit).

## Models

- **Verifier needs a Baseten key.** Muse Spark Open runs only in key mode and only if the server owner sets `BASETEN_API_KEY`; the demo deployment sets none. Without one, key mode verifies with the request's model (muse-spark-1.3 by default) and local mode with Glimmer. No real Baseten or Meta verifier call has ever been made, and the Baseten model slug `meta-models/muse-spark-open` is unconfirmed.
- The verifier's catch rate is unmeasured (Glimmer checking Glimmer, 20 documents, 0 extra catches). Mixed-rate receipts give false alarms (it reads the standard-rated subtotal as net); the prompt needs a mixed-rate hint. All six fields are decisive, which is stricter than the original brief.
- The card cannot adopt the second reading: on a disagreement the user can approve the first reading or reject.
- **SAM 3.1 crop is off by default** (`SAM_CROP=1`); its wire format is unverified and has never run live; the default crop is plain code, measured on synthetic scenes only (mean IoU 0.88). No separate crop chip: the crop note is appended to the card's verifier line.
- **Muse Voice Transcribe:** the request (`/asr/transcribe`, multipart parts, response field) comes from research notes and has not been checked against dev.meta.ai. No live mic run in Chrome/Edge, Firefox, Safari/iOS or on Android. Key mode only. Meta has no text-to-speech model and Accnomos does not read answers aloud.
- In key mode with no `X-Meta-Api-Key` header, `AiConfig` falls back to the server's `META_API_KEY`, so typed and voice Ask would run on the operator's key.
- **"On my own machine" means the machine running the runtime.** Our demo runtime and Ollama are on our DGX Spark; a user's laptop is not reachable from `api.accnomos.com`.
- Harness gold issues: `015_zero` (VAT number not printed); `038` and `060` (`no_vat_number`, under £250, £0 VAT) still expected to need a look, which the owner's rule does not do.
- A bad `X-AI-*` configuration makes inbox triage silently run without a model ("No AI is set up") instead of naming the setting.
- The planner's rationale model sees calendar event subjects as well as job names, and with no `X-AI-*` headers `/plan/day` falls back to the server's default model (`AI_MODE`, or `META_API_KEY` in key mode), not only the user's own (`routes_plan.optional_ai`).

## Chat and voice actions, Autopilot

- Without `ACTIONS_SIGNING_KEY` (the deploy file passes it through, empty by default), each runtime process makes a random key: after a restart, or with several workers, a card can fail with 403.
- If the runtime dies between the `approving` and `executed` audit lines, that action is never re-run on its own (409). After 10 minutes, rejecting the card clears it; the user checks whether it happened and asks again.
- Invoice drafts for chat actions can end as drafts when `Mail.Send` has not been granted; the card cannot request consent.
- The Autopilot level lives in the browser's `localStorage` (`accnomos.autopilot`; only L2 turns posting on). The Android app stores its own level the same way and sends `X-Autopilot: off` on every runtime call below L2, so phone scans post nothing without the user.
- Autopilot only handles purchases that match a rule; it never makes rules itself.

## Invoicing, jobs, contacts

- No credit notes; *Mark paid* posts nothing (the receipt is not posted to 1200 Bank); a paid invoice cannot be voided.
- An invoice made from a job's hours marks only the entries whose hours and rate still match their sent line; voiding the invoice frees its entries again.
- "Invoiced" value and margin use each person's *current* charge rate; changing a rate restates past jobs.
- If saving the sent copy fails after the email has gone, the invoice is saved as sent but the sale is not posted until the user retries (the retry exists). `GraphMailSender` checks the encoded request against 4 MB and refuses larger ones with an error (about 3 MB of attachments); big attachments (draft plus upload session) are not supported. In the send dialogs the tick stays ticked if the user edits the message afterwards.
- A matched bank line counts as full payment: part payments, overpayments and credit notes are not modelled, so a part-paid invoice drops out of *Aged balances*. Ageing counts from the document date and ignores the invoice's due date and payment terms. Customer VAT numbers are only set with *Edit*. Outlook contacts added with "also add" are always customers. `contacts.json` is rewritten whole, so two tabs editing at once means last write wins.
- Plain timesheet edits do not rebuild Books.xlsx. A timesheet whose date moves month is written to the new file before the old one is cleared; a failure between leaves a duplicate, never a loss. A purchase can be tagged to a closed job through the API (on purpose).
- The web mileage log can add and delete journeys but has no edit control (`PATCH /mileage/{id}` exists). The Review vehicle picker shows only when there is an active business vehicle or the proposal already has one. Vehicle pre-fill at scan uses a category plus keyword list.

## Payroll

- **Estimates only. Not payroll, not RTI.** No FPS/EPS, no payment to HMRC; your payroll provider does that.
- The estimate divides annual thresholds by 12 (tax about 20p a month high, NI a few pence off HMRC's tables), monthly pay only, tax code 1257L on a month-1 basis, England/NI rates, NI category A. No student loans, pensions, statutory pay, benefits, salary sacrifice or Employment Allowance; no salaried staff (gross is hours × rate).
- The 2026–27 rates in `payroll_rates.py` were checked against GOV.UK on 27 Oct 2026 by the payrun branch's author (a code comment and commit message, no other record); `tests/test_payroll_rates.py` now pins every constant to the GOV.UK figures (re-read 27 Oct 2026, all matched). Re-check each April.
- Undoing a payroll ledger entry from outside the Payroll page leaves the run "confirmed" until it is reopened.

## Bank statements

- **Bank formats are modelled, not verified.** Barclays, Starling, Tide, Monzo and HSBC/Lloyds layouts follow public formats and have not been checked against real exports; unknown headers fall back to `bank`.
- A re-export that overlaps an earlier one gets a different sha256; if every line was already imported, the CSV is still filed but has no stored lines and does not appear under Statements.
- **Part payments are never suggested**: one entry paid by two bank lines finds no match (20 of 106 gold pairs), and *Confirm* refuses a second line for the same entry. Supplier refunds more than 5 days after the credit note are missed, because the Tide parser drops the `Transaction Type` column. Payments on terms (up to 60 days after the document) are suggested only when the counterparty's name is in the line, and never as `exact`.
- *Confirm all exact matches* skips matches a penny out (fixed in the integration review) but that rule has no web test. `suggested_filename` on bank-line proposals ends in `.csv` and uses the raw description; nothing reads it.

## Inbox, calendar, planner

- Not run against a real mailbox, calendar or address book. Admin consent for `Contacts.Read` on work accounts is untested.
- Outlook intake drops photos forwarded by a colleague on the user's own domain: they get no sender point and score 0.3 against the 0.4 threshold (5 of 17 documents in the fixtures). Triage keeps mail from the user's own address on another domain (a phone, say) and from a second company domain.
- Ask on Glimmer takes about 16 s (median, slowest 50 s) with 0 timeouts in the 40-prompt eval (`evals/runs/ask_40/report.md`). On Glimmer the streamed words arrive in one piece (Ollama holds back a schema-constrained reply), so in practice the 90 s first-chunk wait is a whole-reply timeout there. Wrong-period grounding is a phrase and label match per sentence: a sentence that names the other period ("last quarter", "Apr–Jun 2026", "26A2") may quote its figures; a figure that exists in both periods cannot be told apart. The router is keywords only; a follow-up like "why?" is routed on its own words and treated as being about the current period.
- A triage draft is two Graph calls; if the second fails an empty reply stays in Drafts (we do not delete mail). Sent Items are not read, so an answered thread can still show *Reply*.
- **First-time calendar consent loses the plan:** MSAL redirects to Microsoft and on return the plan card is gone; plan again and tap Apply again.
- Two Applies at the same moment can both create events (no lock in a stateless runtime). Planner: Europe/London only, travel times are rules of thumb by postcode district, only VAT returns count as "due", the *Visit length* input caps at 12 h in the web (runtime 24 h), *Plan a day with these jobs* sends every open job.
- Mileage proposals from the planner appear only when active vehicles exist, use the first active vehicle, and write nothing.

## Files, Books.xlsx, dashboard

- Books.xlsx has never been opened in Excel from a real OneDrive.
- With no business settings saved, Home *Deadlines* assumes stagger 1 and now says so (`assumed: true`; the phone sends no stagger and does not show the note); with annual accounting the tiles show "—" and "Annual VAT returns are not worked out yet". `GET /books/deadlines` returns `start_month` normalised to 1–3.
- A provider-level read failure now marks only its tiles `{"error": ...}` (Graph 401/403 still fails the whole request, so the app signs in again); the Android app does not read that marker (not run). A failed pull-to-refresh on the phone keeps the old figures under a "Could not load your figures" line; the tiles are not marked stale.
- The web sidebar names the saved AI choice (Glimmer on your machine, Muse Spark on your key, or the stub in test mode). Ask uses the period picked on `/vat` but has no picker of its own.

## Android

- `flutter analyze` and `flutter test` have **never been run** on the current `apps/mobile`, including the large `runtime_client.dart` additions. Nothing on the phone has been run for this pass.
- **Play signing hash → Entra is pending** (maintainers' status; nothing in the repo records it). The MSAL redirect URI contains the APK signing hash. The app defaults to the **debug** key's hash; `assets/msal_config.json` has `broker_redirect_uri_registered: false`. The Google Play (App Signing) release hash has not been registered as a redirect URI in Entra, so a release or Play build may not be able to sign in (the app then says so and stays on sample data). Not confirmed either way.
- **The phone has no working VAT stagger.** Settings saves a stagger and custom start month, but no request sends them, so Home deadlines, the VAT picker and the dashboard use calendar quarters.
- The Meta API key is not in secure storage (`flutter_secure_storage` is the TODO in `apps/mobile/lib/services/settings.dart`).
- On the phone, Payroll is read-only and Bank only confirms matches the runtime is sure about. No HMRC filing on the phone.
- Mic on Ask records WAV and calls `/books/ask/voice`; no run on a device is recorded.

## Security and deployment

- Single-worker limits: the **rate limit is per process** (in-memory buckets, cleared on restart; several replicas would each allow the full rate) and the relay's spent-state set is per process, hence one relay worker (`deploy/Dockerfile.relay`).
- The Graph provider's `_safe_path` raises a plain `ValueError`, so a hand-edited unsafe path in the user's books returns a 500 with a correlation id, not a 400 (nothing can escape the folder either way).
- Deploy files are checked by config tests only: images not built, `docker compose up` and `nginx -t` not run, `.htaccess` not tried on Apache/Plesk, base images pinned by tag not digest, nothing tried against live `api.accnomos.com`. `Permissions-Policy` lists the deprecated `interest-cohort`.
- No authentication of callers beyond holding a valid token; `X-User` is not checked against the token. No script CSP on the web app. The AI key and HMRC tokens live in browser storage, readable by an XSS on the web origin. Prompt injection beyond file names is only mitigated by checks and approval.
- The shared `.venv` on the Spark can hold editable installs from another checkout; run `uv sync --all-packages` in the checkout you serve from.

## Testing and process

- The web has no unit tests; pages are checked by `pnpm run build` and the Playwright suite. The e2e CI job `.github/workflows/e2e.yml` has never run on GitHub; its fake calendar is seeded but no e2e flow uses it. The suite does not prove real MSAL, Graph, HMRC relay or model accuracy.
- The SAM response fixture `services/runtime/tests/fixtures/sam_response.json` is marked ILLUSTRATIVE and must be replaced with a captured real response before turning on `SAM_CROP`.
