# Honesty: every known gap

A flat list, grouped by area, from the code on `main` and the "What remains" section of every `docs/reviews/*/REVIEW.md`
(duplicates merged). Severity-ordered tables are in `docs/REMAINING.md`; what each feature does and how it is tested is the
README table. We could not reach accnomos.com or api.accnomos.com from this session, so the live sites are unchecked.

Checked 27 Oct 2026 on main (Linux): runtime and packages 1,176 passed, 1 skipped; evals 258; relay 102; Playwright 195; `flutter analyze` clean and `flutter test` 158 passed. On Windows, set `PYTHONUTF8=1` first: four source-scanning test files read UTF-8 with the cp1252 default otherwise.
`pnpm run build` and `npx eslint src` pass in `apps/web`; `pnpm run e2e` passes whole (191 tests) with `E2E_PYTHON` pointed at the
project venv (no `python3` on this machine's PATH). `ruff` has not been run.

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
- **Company and VAT look-ups are built and tested on fakes only.** Companies House (search, profile) and HMRC's Check a UK VAT number v2.0 (through the relay) have never been called for real from this code: the session that built them had no Companies House key and no HMRC sandbox credentials. The VAT check is sandbox-only like everything HMRC (answers say "(HMRC sandbox)"); untested live. HMRC's own sandbox test numbers (e.g. 553557881) fail the mod-97 check, so the checksum is shown as information and never blocks a check. Whether HMRC expects fraud-prevention headers on this application-restricted API was not verified; the relay sends none there. Switching to production is environment-only and written down in `docs/PRODUCTION.md`, not done.
- The browser flow (connect → obligations → declaration → submit → receipt in `06 VAT returns/`) is built and type-checked but has **not been run end to end** against HMRC's sandbox. Relay tests mock HMRC.
- **The runtime holds no HMRC token, so it learns obligations second-hand.** When connected, the web app fetches HMRC's obligations through the relay and posts them to `POST /books/vat/obligations` (stored in `_System/vat/obligations.json`). `/books/vat/periods` and `/books/vat` then mark a period submitted when HMRC says fulfilled (source `hmrc`, with HMRC's period key, due date and received date) or when our own receipt exists (source `accnomos`); a fulfilled period cannot be submitted again from the web. Dates that match none of our periods warn in plain English (our stagger differs from HMRC's). Until the web app has fetched the list, a return filed elsewhere still shows as open — and the whole round trip is **sandbox-only and untested against the live sandbox until the owner signs in** (built and type-checked against a faked relay; relay tests mock HMRC).
- The runtime's own period key (`26A4` style, saved as `calculated_for`) is still a placeholder; HMRC's key is used on `/books/vat` and `/books/vat/periods` when its dates match, and submission uses HMRC's key. For monthly returns all three months of a quarter get the same placeholder.
- `GET /books/vat` accepts `?today=`, so a client can move "current" and with it `can_submit`; the web gate is advisory and HMRC decides what can be filed.
- No flat-rate scheme, no annual accounting scheme, no fuel scale-charge calculation.
- The runtime's "today" is the **London date** (`books.today()`, Europe/London via `zoneinfo` + `tzdata`): `GET /audit` `from`/`to` filter by London day too. Both clients send `today` to the dashboard, so this mostly affects direct API callers and chat actions.

## Receipts, review and the ledger

- **No separate LLM Reviewer.** The card's "why" line is composed by code ("Checker, code"). Models write words only in *Ask*, inbox triage, reminder drafts and the planner rationale, each checked by code. The signed-out mock-up on `/vat` has a "Reviewer's note (Muse Spark)"; it is labelled sample but no such reviewer runs.
- Key-mode extraction (muse-spark-1.3) is unit-tested only.
- **Ledger files are not tamper-evident** (no signatures, no hash chain). An undo is a reversing entry dated like the original — unless that VAT period was already submitted, when the correction is dated today and lands in the current, open period instead (the undo response carries `dated_today`, `reason` and both period labels; `test_undo_submitted.py`).
- `/books/vat` entry counts put a reversal against the box it reverses, and the page header says how many of the period's entries are undone (e.g. "3 entries, 1 undone").
- **No real HEIC from a phone has been read, and no real supplier PDF.** HEIC → JPEG (`pillow-heif` 1.8.1) and PDF
  reading (`pypdfium2` 5.14.0, locked in `uv.lock`) are tested with the real libraries, but only on files the tests make
  (a HEIC written by `pillow-heif`, PDFs written by `fpdf2`). The Docker image has not been built with them.
- A multi-page PDF is read from page 1 only (a total printed only on page 2 is missed); a scanner batch of several
  receipts in one PDF is read as one document and not split.
- Receipts in an email body are found by a code rule tested on six fictional emails, not on real Uber, Amazon or SaaS
  mail, nor on Graph's HTML-to-text conversion of them.
- `POST /books/approve/{id}` is kept as an alias for web builds deployed before the integration review; remove it after the next deploy.
- `POST /reports/export` saves one spreadsheet in `07 Reports/` from the web and from Android More → Reports (a same-day file of the same name gets ` (2)`; it never posts), but only fake storage has been written in tests. The folder names now have one source (`services/runtime/app/paths.py`); existing users' old-named folders are renamed once on first contact (`app/layout.py`), which has only been tested on fake storage, not on a real OneDrive.
- `services/runtime/tests/test_integration.py` holds the runtime to the documented folder layout only for the features its scenario exercises (not invoicing, payroll, planner, to-dos, action audit).

## Models

- **Verifier needs a Baseten key.** Muse Spark Open runs only in key mode and only if the server owner sets `BASETEN_API_KEY`; the demo deployment now sets one. Without one, key mode verifies with the request's model (muse-spark-1.3 by default) and local mode with Glimmer. The server has a Baseten key since 27 Oct 2026, and a real call through `ai/verify.py` read a gold receipt correctly in 7 s; an eval over the 200 gold receipts is in `evals/runs/spark_open_200` once it lands. No real Meta (muse-spark-1.3) verifier call has been made. The Baseten model id `meta-models/muse-spark-open` is the one Baseten's `/v1/models` lists (checked 27 Oct 2026).
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

- **Part payments, overpayments and credit notes are modelled by code** (`app/settlement.py`), tested on fake storage only. *Record payment* / *Mark paid* posts Dr 1200 Bank (or 1210 Cash) / Cr 1100 Debtors; *Remove* reverses it; a paid invoice can be voided only after its payments and credit notes are removed. A credit note (CN-0001…) is posted as a reversal with the invoice's VAT codes on its own date — or, for a stand-alone credit note with its own customer, lines and descriptions, with its lines' VAT codes; with no invoice to reduce, the amount is left as a credit on the customer. *Mark paid* on a part-paid invoice records only the balance (a stale full total never overpays); a paid invoice's PDF carries a PAID stamp with the date, while the emailed copy in `sent/` stays as the customer got it. A credit left on a contact (overpayment, or a credit note over what was owed) can be applied to another of that contact's open documents (an allocation: nothing is posted) or refunded (posted Dr 1100 Debtors / Cr 1200 Bank, or Dr 1200 Bank / Cr 2100 Creditors for a supplier), web only; the payment or credit note behind a used credit cannot be removed until the use is. Credit note PDFs have not been opened in a real viewer or emailed from a real mailbox.
- A bank line matched straight to invoices on the Bank page still posts nothing until *Post as payment* turns it into a recorded payment. A statement line for money already recorded is suggested to that payment (same amount, 5 days before to 14 after) and a match to a settled document is refused, so the same money is not counted twice; outside those rules it is up to you. A supplier credit note is linked to its bill only when its printed "original invoice" number matches exactly one standing bill of that supplier; otherwise it is a credit on the supplier. Payment terms per contact are in the web *Edit*. The extraction eval was not re-run since `credit_note` and `original_invoice_number` were added.
- An invoice made from a job's hours marks only the entries whose hours and rate still match their sent line; voiding the invoice frees its entries again.
- "Invoiced" value and margin use each person's *current* charge rate; changing a rate restates past jobs.
- If saving the sent copy fails after the email has gone, the invoice is saved as sent but the sale is not posted until the user retries (the retry exists). `GraphMailSender` checks the encoded request against 4 MB and refuses larger ones with an error (about 3 MB of attachments); big attachments (draft plus upload session) are not supported. In the send dialogs the tick stays ticked if the user edits the message afterwards.
- Ageing counts what is still owed from the due date: the invoice's own, else the contact's terms, else 30 days from the document date (bills carry no due date from the reader). Customer VAT numbers are only set with *Edit*. Outlook contacts added with "also add" are always customers. Every `contacts.json` is rewritte re-reads and merges on an ETag conflict, so two tabs editing different contacts both win; two saves colliding twice over get a 409 asking for a reload. After *Edit* the side panel reloads the statement in place.
- **Possible duplicates are AI-assisted, not AI-decided.** Code finds the candidates and their evidence; your model (Glimmer local, Muse Spark key) gives `{same, confidence, keep_name, reason}` beside it, and only your tap merges. Judgement has run on the test stub only, never a real model. A merge across different VAT numbers is refused; after a merge the *Undo* button lasts until you reload the page (the record stays for the API). Merging is on the web and only, not Android (the phone is a thin client over the same routes; its sheets are new and have not been run on a real phone).
- Plain timesheet edits do not rebuild Books.xlsx. A timesheet whose date moves month is written to the new file before the old one is cleared; a failure between leaves a duplicate, never a loss. A purchase can be tagged to a closed job through the API (on purpose).
- The web mileage log can add, edit and delete journeys; vehicles can be renamed, deactivated or deleted from the page (deletion is refused, with the reason, while journeys or tagged receipts reference the vehicle). The Review vehicle picker offers *Add a vehicle* when no business vehicle is active. Vehicle pre-fill at scan uses a category plus keyword list.

## Payroll

- **Estimates only. Not payroll, not RTI.** No FPS/EPS, no payment to HMRC; your payroll provider does that.
- The estimate divides annual thresholds by 12 (tax about 20p a month high, NI a few pence off HMRC's tables), monthly pay only, tax code 1257L on a month-1 basis, England/NI rates, NI category A. No student loans, pensions, statutory pay, benefits, salary sacrifice or Employment Allowance; no salaried staff (gross is hours × rate).
- The 2026–27 rates in `payroll_rates.py` were checked against GOV.UK on 27 Oct 2026 by the payrun branch's author (a code comment and commit message, no other record); `tests/test_payroll_rates.py` now pins every constant to the GOV.UK figures (re-read 27 Oct 2026, all matched). Re-check each April.
- Undoing a payroll ledger entry from outside the Payroll page leaves the run "confirmed" until it is reopened.

## Bank statements

- **Bank formats are modelled, not verified.** Barclays, Starling, Tide, Monzo and HSBC/Lloyds layouts follow public formats and have not been checked against real exports; unknown headers fall back to `bank`.
- A re-export that overlaps an earlier one gets a different sha256; if every line was already imported, the CSV is still filed but has no stored lines and does not appear under Statements.
- **Part payments are never suggested**: one entry paid by two bank lines finds no match (20 of 106 gold pairs), and *Confirm* refuses a second line for the same entry. Supplier refunds more than 5 days after the credit note are missed, because the Tide parser drops the `Transaction Type` column. Payments on terms (up to 60 days after the document) are suggested only when the counterparty's name is in the line, and never as `exact`.
- *Confirm all exact matches* skips matches a penny out (fixed in the integration review) but that rule has no web test. `suggested_filename` on bank-line proposals is the date and a filesystem-safe description with no extension; nothing reads it.

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
- **`POST /books/export` has run on fake storage only** (unit tests plus one e2e export of a single posted receipt). The zip carries an *index* of the invoice PDFs, not the PDFs themselves, which stay filed under `03 Sales`; the 2,000-file / 25 MB caps are covered by a monkeypatched unit test, not a full-size export. The CSVs have never been opened in Excel from a real OneDrive. The `account.live.com/myapps` revoke link and the OneDrive-folder *Open* link have not been clicked through on a real account.
- With no business settings saved, Home *Deadlines* assumes stagger 1 and now says so (`assumed: true`); the phone sends its saved stagger (or nothing, when none is saved) and shows the same note, linking to Settings. With annual accounting the tiles show "—" and "Annual VAT returns are not worked out yet". `GET /books/deadlines` returns `start_month` normalised to 1–3.
- A provider-level read failure now marks only its tiles `{"error": ...}` (Graph 401/403 still fails the whole request, so the app signs in again); the Android app does not read that marker (not run). A failed pull-to-refresh on the phone keeps the old figures under a "Could not load your figures" line; the tiles are not marked stale.
- The web sidebar names the saved AI choice (Glimmer on your machine, Muse Spark on your key, or the stub in test mode). Ask uses the period picked on `/vat` but has no picker of its own.

## Android

- `flutter analyze` is clean and `flutter test` passes (27 Oct 2026, incl. the payments sheets and Add from phone at 360 dp, now also the company look-up, VAT check, contact edit, review VAT gate and duplicates sheets at 360 dp); both now run on every Android merge. Nothing on the phone has been run on a real device.
- On the phone there is no *Post as payment* (a Bank-page match still posts nothing until the web turns it into a recorded payment), no credit-note PDF/email/void, and no statement of which bill a supplier credit note will link to. Bank matching stays web/Bank only.
- **Play signing hash → Entra: registered 27 Oct 2026.** Play re-signs with Google's app signing key (SHA-1 `54:C9:BB:EE:…:42:B0`), whose MSAL hash `VMm77tAADe8/UZxWIvqfRmMiQrA=` the owner added in Entra (Android platform, `com.accnomos.app`). Release builds from 0.3.1+4 carry it (`tools/build_release.ps1`; checked inside the 0.3.1+4 bundle). Builds up to 0.3.0+3 carried the debug hash and could not sign in from Play. Sign-in on a Play install has **not yet been tried on a real phone**. `broker_redirect_uri_registered` stays `false` (browser sign-in, no broker).
- The phone sends its saved VAT stagger (or custom start month) on every VAT call — VAT return, periods, dashboard, reports and Ask — and shows the assumed-quarters note on Home when none is saved. Covered by `apps/mobile/test/vat_stagger_test.dart` (mock transport); not yet run against a real runtime with a non-1 stagger.
- The Meta API key is not in secure storage (`flutter_secure_storage` is the TODO in `apps/mobile/lib/services/settings.dart`).
- On the phone, Payroll is read-only and Bank only confirms matches the runtime is sure about. Reports (More → Reports: P&L, aged, VAT, trend, *Save to 07 Reports*) is a thin client over `GET /reports/*` with no offline copy. No HMRC filing on the phone (the VAT check only reads, on a tap).
- Mic on Ask records WAV and calls `/books/ask/voice`; no run on a device is recorded.
- *Add from phone* (0.3.2) opens the system contact picker and reads name, emails, phones and postal address from each returned contact URI only: no `READ_CONTACTS` in the manifest, nothing written back to the phone. Covered by widget tests with a mocked picker and by runtime tests for `POST /contacts/import-phone`; the picker grant, repeated picks and the sheet have not been run on a real phone.

## Security and deployment

- Single-worker limits: the **rate limit is per process** (in-memory buckets, cleared on restart; several replicas would each allow the full rate) and the relay's spent-state set is per process, hence one relay worker (`deploy/Dockerfile.relay`).
- The Graph provider's `_safe_path` raises a plain `ValueError`, so a hand-edited unsafe path in the user's books returns a 500 with a correlation id, not a 400 (nothing can escape the folder either way).
- Deploy files are checked by config tests only: images not built, `docker compose up` and `nginx -t` not run, `.htaccess` not tried on Apache/Plesk, base images pinned by tag not digest, nothing tried against live `api.accnomos.com`. `Permissions-Policy` lists the deprecated `interest-cohort`.
- No authentication of callers beyond holding a valid token; `X-User` is not checked against the token. No script CSP on the web app. The AI key and HMRC tokens live in browser storage, readable by an XSS on the web origin. Prompt injection beyond file names is only mitigated by checks and approval.
- The shared `.venv` on the Spark can hold editable installs from another checkout; run `uv sync --all-packages` in the checkout you serve from.

## Testing and process

- The web has no unit tests; pages are checked by `pnpm run build` and the Playwright suite. The e2e CI job `.github/workflows/e2e.yml` has never run on GitHub; its fake calendar is seeded but no e2e flow uses it. The suite does not prove real MSAL, Graph, HMRC relay or model accuracy.
- The SAM response fixture `services/runtime/tests/fixtures/sam_response.json` is marked ILLUSTRATIVE and must be replaced with a captured real response before turning on `SAM_CROP`.
