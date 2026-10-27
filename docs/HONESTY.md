# Honesty: every known gap

A flat list, grouped by area, from the code on `main` and the "What remains" section of every `docs/reviews/*/REVIEW.md`
(duplicates merged). Severity-ordered tables are in `docs/REMAINING.md`; what each feature does and how it is tested is the
README table. We could not reach accnomos.com or api.accnomos.com from this session, so the live sites are unchecked.

Checked 27 Oct 2026 on this checkout: `pytest -q` passes in `services/runtime` (600), `packages/ledger` (32),
`packages/connectors` (34) and `services/hmrc-relay` (100). The Flutter app was **not** built, analysed or tested. The web
build and the Playwright suite were not re-run for this pass. `ruff` has not been run on `main`.

## What is real, and what is not

- **Real runs** are the maintainers' own, on 26–27 Oct: Microsoft sign-in on a personal account, folder creation, upload → scan →
  Glimmer on our DGX Spark → approve → ledger event → VAT boxes. No log is committed. The committed evidence is the eval reports in `evals/`.
- Everything else is **tested on fakes** (in-memory OneDrive, mailbox, calendar and address book; stubbed model; mocked HMRC and Meta).
- **Demo data is synthetic**: Bramblewood Joinery Ltd, the receipts, bank CSVs and the gold set are generated. The grey "SAMPLE — FICTIONAL COMPANY" banner shows on every app page except `/privacy`, **including when signed in**. Signed-out pages show static mock-ups.
- **Evals are synthetic renderings**, so real phone photos will score lower. Extraction: 60 documents, Glimmer local, every field right on 73 %. Verifier: 20 documents, 0 extra catches, 1 false alarm.
- Everything was written during the build period with coding assistants (Claude, Muse Code, a local Qwen); every merge was reviewed (`docs/reviews/`). The DGX Spark and Ollama setup predates the event.

## HMRC

- **Sandbox only.** The relay defaults to `test-api.service.hmrc.gov.uk`; no production credentials, no real filing.
- The browser flow (connect → obligations → declaration → submit → receipt in `05 VAT returns/`) is built and type-checked but has **not been run end to end** against HMRC's sandbox. Relay tests mock HMRC.
- **The runtime makes no call to HMRC's obligations endpoint.** The relay has one and *Connect to HMRC* uses it, but `/books/vat/periods` cannot, because the runtime holds no HMRC token. So "submitted" means "a receipt our own submission saved in `05 VAT returns/`": a return filed elsewhere, or a deleted receipt, shows as open.
- The runtime's own period key (`26A4` style, saved as `calculated_for`) is a placeholder; submission uses HMRC's key. For monthly returns all three months of a quarter get the same placeholder.
- `GET /books/vat` accepts `?today=`, so a client can move "current" and with it `can_submit`; the web gate is advisory and HMRC decides what can be filed.
- No flat-rate scheme, no annual accounting scheme, no fuel scale-charge calculation.
- The runtime's "today" is the **UTC date** (`books.now()`): between midnight and 1 am in BST an invoice date, a "yesterday" or a due date can be a day behind the UK date. Both clients send `today` to the dashboard, so this mostly affects direct API callers and chat actions.

## Receipts, review and the ledger

- **No separate LLM Reviewer.** The card's "why" line is composed by code ("Checker, code"); Muse Spark writes answers only in *Ask*.
- Key-mode extraction (muse-spark-1.3) is unit-tested only.
- **Ledger files are not tamper-evident** (no signatures, no hash chain). An undo is a reversing entry dated like the original; if that VAT period was already submitted, the correction belongs in the current period.
- `/books/vat` entry counts include sales and purchases only; a reversal changes the amounts but not the count next to boxes 1–4 and 6–7.
- HEIC photos are copied by Outlook intake but not read yet.
- `POST /books/approve/{id}` is kept as an alias for web builds deployed before the integration review; remove it after the next deploy.
- The 6 April tax-year rule is written twice (`contacts.uk_tax_year_start`, `mileage.tax_year_of`); both are tested.
- `06 Reports/` is created at onboarding and nothing writes to it. `03 Sales/invoices` and `04 Payroll` share their numbers with `03 Bank statements` and `04 Needs a look`.
- `services/runtime/tests/test_integration.py` holds the runtime to the documented folder layout only for the features its scenario exercises (not invoicing, payroll, planner, to-dos, action audit).

## Models

- **Verifier needs a Baseten key.** Muse Spark Open runs only in key mode and only if the server owner sets `BASETEN_API_KEY`; the demo deployment sets none. Without one, key mode verifies with muse-spark-1.3 and local mode with Glimmer. No real Baseten or Meta verifier call has ever been made, and the Baseten model slug `meta-models/muse-spark-open` is unconfirmed.
- The verifier's catch rate is unmeasured (Glimmer checking Glimmer, 20 documents, 0 extra catches). Mixed-rate receipts give false alarms (it reads the standard-rated subtotal as net); the prompt needs a mixed-rate hint. All six fields are decisive, which is stricter than the original brief.
- The card cannot adopt the second reading: on a disagreement the user can approve the first reading or reject.
- **SAM 3.1 crop is off by default** (`SAM_CROP=1`); its wire format is unverified and has never run live; the default crop is plain code, measured on synthetic scenes only (mean IoU 0.88). No crop chip in the UI.
- **Muse Voice Transcribe:** the request (`/asr/transcribe`, multipart parts, response field) comes from research notes and has not been checked against dev.meta.ai. No live mic run in Chrome/Edge, Firefox, Safari/iOS or on Android. Key mode only. Meta has no text-to-speech model and Accnomos does not read answers aloud.
- In key mode with no `X-Meta-Api-Key` header, `AiConfig` falls back to the server's `META_API_KEY`, so typed and voice Ask would run on the operator's key.
- **"On my own machine" means the machine running the runtime.** Our demo runtime and Ollama are on our DGX Spark; a user's laptop is not reachable from `api.accnomos.com`.
- Harness gold issues: `015_zero` (VAT number not printed) and `016_no_vat_number` (£0 VAT expected to need a look).
- A bad `X-AI-*` configuration makes inbox triage silently run without a model ("No AI is set up") instead of naming the setting.
- The planner's rationale model sees calendar event subjects as well as job names (only the user's own AI).

## Chat and voice actions, Autopilot

- Without `ACTIONS_SIGNING_KEY` (the deploy file passes it through, empty by default), each runtime process makes a random key: after a restart, or with several workers, a card can fail with 403.
- If the runtime dies between the `approving` and `executed` audit lines, that action stays blocked (409) on purpose; there is no UI to clear it.
- Invoice drafts for chat actions can end as drafts when `Mail.Send` has not been granted; the card cannot request consent.
- The Autopilot switch (level L1/L2) lives in the browser's `localStorage`. **The Android app never sends `X-Autopilot`**, so scans from the phone always run Autopilot when a rule exists, even if it is off on the web.
- Autopilot only handles purchases that match a rule; it never makes rules itself.

## Invoicing, jobs, contacts

- No credit notes; *Mark paid* posts nothing (the receipt is not posted to 1200 Bank); a paid invoice cannot be voided.
- **Hours are not linked to invoices:** nothing records which timesheet entries an invoice billed, so the user marks hours invoiced by typing the invoice number (`routes_jobs.py`, `JobDetail.tsx` TODOs). That route checks entry ids but not that hours or rates still match what the user saw.
- "Invoiced" value and margin use each person's *current* charge rate; changing a rate restates past jobs.
- If saving the sent copy fails after the email has gone, the invoice is saved as sent but the sale is not posted until the user retries (the retry exists). `GraphMailSender.MAX_INLINE` checks raw bytes, not base64, against Graph's 4 MB cap. In the send dialogs the tick stays ticked if the user edits the message afterwards.
- A matched bank line counts as full payment: part payments, overpayments and credit notes are not modelled, so a part-paid invoice drops out of *Aged balances*. Ageing uses the document date (no payment terms). Customer VAT numbers are only set with *Edit*. Outlook contacts added with "also add" are always customers. `contacts.json` is rewritten whole, so two tabs editing at once means last write wins.
- Plain timesheet edits do not rebuild Books.xlsx. A timesheet whose date moves month is written to the new file before the old one is cleared; a failure between leaves a duplicate, never a loss. A purchase can be tagged to a closed job through the API (on purpose).
- The web mileage log can add and delete journeys but has no edit control (`PATCH /mileage/{id}` exists). The Review vehicle picker shows only when there is an active business vehicle. Vehicle pre-fill at scan uses a category plus keyword list.
- `MarkInvoicedBody.entry_ids` has no item limit beyond the 256 KB body cap.

## Payroll

- **Estimates only. Not payroll, not RTI.** No FPS/EPS, no payment to HMRC; your payroll provider does that.
- The estimate divides annual thresholds by 12 (tax about 20p a month high, NI a few pence off HMRC's tables), monthly pay only, tax code 1257L on a month-1 basis, England/NI rates, NI category A. No student loans, pensions, statutory pay, benefits, salary sacrifice or Employment Allowance; no salaried staff (gross is hours × rate).
- The 2026–27 rates in `payroll_rates.py` have not been re-checked against GOV.UK from this environment.
- Undoing a payroll ledger entry from outside the Payroll page leaves the run "confirmed" until it is reopened.

## Bank statements

- **Bank formats are modelled, not verified.** Barclays, Starling, Tide, Monzo and HSBC/Lloyds layouts follow public formats and have not been checked against real exports; unknown headers fall back to `bank`.
- A re-export that overlaps an earlier one gets a different sha256; if every line was already imported, the CSV is still filed but has no stored lines and does not appear under Statements.
- *Confirm all exact matches* skips matches a penny out (fixed in the integration review) but that rule has no web test. `suggested_filename` on bank-line proposals ends in `.csv` and uses the raw description; nothing reads it.

## Inbox, calendar, planner

- Not run against a real mailbox, calendar or address book. Admin consent for `Contacts.Read` on work accounts is untested.
- A triage draft is two Graph calls; if the second fails an empty reply stays in Drafts (we do not delete mail). Sent Items are not read, so an answered thread can still show *Reply*.
- **First-time calendar consent loses the plan:** MSAL redirects to Microsoft and on return the plan card is gone; plan again and tap Apply again.
- Two Applies at the same moment can both create events (no lock in a stateless runtime). Planner: Europe/London only, travel times are rules of thumb by postcode district, only VAT returns count as "due", the *Visit length* input caps at 12 h in the web (runtime 24 h), *Plan a day with these jobs* sends every open job.
- Mileage proposals from the planner appear only when active vehicles exist, use the first active vehicle, and write nothing.

## Files, Books.xlsx, dashboard

- Books.xlsx has never been opened in Excel from a real OneDrive. openpyxl writes any cell text starting with `=` as a formula, on every sheet (one fix in `projection._table`).
- Home *Deadlines* assumes stagger 1 when no business settings are saved, without saying so; annual accounting shows the sample tiles. `GET /books/deadlines` returns `start_month` normalised to 1–3.
- On Files a top-level folder's "N files" adds its sub-folders' `childCount`.
- The dashboard returns 500 if an audit or storage read fails at the provider level (only parse errors are isolated per tile). A failed pull-to-refresh on the phone keeps the old figures without a "stale" marker.
- The web sidebar always says "AI: local Meta agent (Glimmer 30B)", whatever AI is set in Settings. Ask uses the period picked on `/vat` but has no picker of its own.

## Android

- `flutter analyze` and `flutter test` have **never been run** on the current `apps/mobile`, including the large `runtime_client.dart` additions. Nothing on the phone has been run for this pass.
- **Play signing hash → Entra is pending** (maintainers' status; nothing in the repo records it). The MSAL redirect URI contains the APK signing hash. The app defaults to the **debug** key's hash; `assets/msal_config.json` has `broker_redirect_uri_registered: false`. The Google Play (App Signing) release hash has not been registered as a redirect URI in Entra, so a release or Play build may not be able to sign in (the app then says so and stays on sample data). Not confirmed either way.
- **The phone has no working VAT stagger.** Settings saves a stagger and custom start month, but no request sends them, so Home deadlines, the VAT picker and the dashboard use calendar quarters.
- The Meta API key is not in secure storage (`flutter_secure_storage` is the TODO in `apps/mobile/lib/services/settings.dart`).
- On the phone, Payroll is read-only and Bank only confirms matches the runtime is sure about. No HMRC filing on the phone.
- Mic on Ask records WAV and calls `/books/ask/voice`; no run on a device is recorded.

## Security and deployment

- Single-worker limits: the **rate limit is per process** (in-memory buckets, cleared on restart; several replicas would each allow the full rate) and the relay's spent-state set is per process, hence one relay worker (`deploy/Dockerfile.relay`).
- `CF-Connecting-IP` is trusted whenever present in `deploy/nginx.conf`; on a Plesk path a client could pick its own address for the rate limit and the HMRC `Gov-Client-Public-IP`. The fix is a manual front-proxy step.
- The Graph provider's `_safe_path` raises a plain `ValueError`, so a hand-edited unsafe path in the user's books returns a 500 with a correlation id, not a 400 (nothing can escape the folder either way).
- Deploy files are checked by config tests only: images not built, `docker compose up` and `nginx -t` not run, `.htaccess` not tried on Apache/Plesk, base images pinned by tag not digest, nothing tried against live `api.accnomos.com`. `Permissions-Policy` lists the deprecated `interest-cohort`.
- No authentication of callers beyond holding a valid token; `X-User` is not checked against the token. No script CSP on the web app. The AI key and HMRC tokens live in browser storage, readable by an XSS on the web origin. Prompt injection beyond file names is only mitigated by checks and approval.
- `uv.lock` is stale: `accnomos-runtime` lists `pillow` but has no entry for `numpy` or `fpdf2`, so `uv sync --frozen` would leave them out. Docker installs with `pip`.
- The shared `.venv` on the Spark can hold editable installs from another checkout; run `uv sync --all-packages` in the checkout you serve from.

## Testing and process

- The web has no unit tests; pages are checked by `pnpm run build` and the Playwright suite. The e2e CI job `.github/workflows/e2e.yml` has never run on GitHub; its fake calendar is seeded but no e2e flow uses it. The suite does not prove real MSAL, Graph, HMRC relay or model accuracy.
- `docs/DEV.md`: the SAM request/response fixture is marked ILLUSTRATIVE and must be replaced with a captured real response before turning SAM on.
